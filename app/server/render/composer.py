"""Video composer — port of daihuo-jianshou/src/lib/video-composer/composer.ts.

Orchestrates the final video assembly step (pipeline step 12):
    scene clips + TTS audio + BGM + subtitle burn-in → final.mp4

Key responsibilities:
    1. Mix TTS narration audio with optional BGM track (FFmpeg amix)
    2. Burn subtitles into video (FFmpeg drawtext from SRT segments)
    3. Reconcile scene durations to match audio-driven timing
    4. Concatenate scene clips with optional fade transitions
    5. Write final.mp4 to storage/output/{project_id}/

FFmpeg binary: vendor/ffmpeg.exe (Windows-native, via find_ffmpeg() from
server.audio.ffmpeg_utils — vendor/ first, then PATH fallback).

Phase 3.3 — Task 3.3.2
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from loguru import logger

from server.audio.ffmpeg_utils import find_ffmpeg, probe_duration

# ─── Types ────────────────────────────────────────────────────────────────────

AspectRatio = Literal["9:16", "16:9", "1:1"]
Resolution = Literal["720p", "1080p"]
TransitionMode = Literal["ffmpeg_fade", "direct_concat"]

# Resolution lookup: aspect_ratio → resolution → (width, height)
_RESOLUTIONS: dict[str, dict[str, tuple[int, int]]] = {
    "9:16": {"720p": (720, 1280), "1080p": (1080, 1920)},
    "16:9": {"720p": (1280, 720), "1080p": (1920, 1080)},
    "1:1":  {"720p": (720, 720),  "1080p": (1080, 1080)},
}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SubtitleSegment:
    """A single subtitle entry (maps to one SRT block).

    Attributes:
        text:       Display text.
        start_sec:  Start time in seconds (float).
        end_sec:    End time in seconds (float).
    """
    text: str
    start_sec: float
    end_sec: float


@dataclass
class SubtitleConfig:
    """Subtitle rendering options for FFmpeg drawtext.

    Attributes:
        segments:     List of timed subtitle segments.
        font_size:    Font size in pixels (default 36).
        color:        Font colour string (default "white").
        stroke_color: Outline colour (default "black").
        stroke_width: Outline width in pixels (default 2).
        position:     Vertical position hint ("bottom" | "center" | "top").
    """
    segments: list[SubtitleSegment] = field(default_factory=list)
    font_size: int = 36
    color: str = "white"
    stroke_color: str = "black"
    stroke_width: int = 2
    position: Literal["bottom", "center", "top"] = "bottom"


@dataclass
class ClipInput:
    """One scene clip to include in the composition.

    Attributes:
        file_path:   Absolute path to the video file.
        duration:    Desired duration in seconds (used for reconciliation).
        transition:  Transition mode to the *next* clip.
        has_audio:   Whether the clip carries its own audio track.
    """
    file_path: Path
    duration: float
    transition: TransitionMode = "direct_concat"
    has_audio: bool = False


@dataclass
class ComposeConfig:
    """Full configuration for a single compose run.

    Attributes:
        project_id:   Project identifier (used to name the output directory).
        clips:        Ordered list of scene clips.
        tts_path:     Path to the TTS narration audio file (.mp3/.wav).
        output_dir:   Directory where final.mp4 will be written.
        aspect_ratio: Output aspect ratio (default "9:16").
        resolution:   Output resolution (default "720p").
        bgm_path:     Optional background music file.
        bgm_volume:   BGM volume 0.0–1.0 (default 0.3).
        subtitle:     Optional subtitle configuration.
        tts_volume:   TTS narration volume 0.0–1.0 (default 1.0).
    """
    project_id: str
    clips: list[ClipInput]
    tts_path: Optional[Path] = None
    output_dir: Optional[Path] = None
    aspect_ratio: AspectRatio = "9:16"
    resolution: Resolution = "720p"
    bgm_path: Optional[Path] = None
    bgm_volume: float = 0.3
    subtitle: Optional[SubtitleConfig] = None
    tts_volume: float = 1.0


@dataclass
class ComposeResult:
    """Result of a compose operation.

    Attributes:
        output_path:       Path to the written final.mp4.
        total_duration:    Total video duration in seconds.
        reconciled_clips:  Clips after audio-driven duration reconciliation.
    """
    output_path: Path
    total_duration: float
    reconciled_clips: list[ClipInput]


# ─── Escape helpers ───────────────────────────────────────────────────────────

def _escape_drawtext(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter.

    drawtext uses ':' as a parameter separator; several characters need
    escaping to avoid filter parse errors.  Mirrors the TypeScript
    ``escapeDrawText()`` in daihuo composer.ts.

    Args:
        text: Raw subtitle text.

    Returns:
        Escaped string safe for use inside a drawtext= expression.
    """
    # Order matters: backslash must be first
    text = text.replace("\\", "\\\\\\\\")
    # Replace straight single-quote with right single quotation mark to avoid
    # shell nesting issues (same strategy as the TS original)
    text = text.replace("'", "\u2019")
    text = text.replace(":", "\\\\:")
    text = text.replace("%", "\\\\%")
    text = text.replace("[", "\\\\[")
    text = text.replace("]", "\\\\]")
    return text


def _escape_path(file_path: Path) -> str:
    """Return a path string safe for use inside FFmpeg filter_complex.

    On Windows, backslashes in paths must be doubled inside filter_complex
    strings.  Forward slashes are also accepted by FFmpeg on Windows and
    avoid the escaping issue entirely.

    Args:
        file_path: Path to escape.

    Returns:
        Forward-slash path string.
    """
    return str(file_path).replace("\\", "/")


# ─── Duration reconciliation ──────────────────────────────────────────────────

def reconcile_durations(
    clips: list[ClipInput],
    tts_duration: float,
) -> list[ClipInput]:
    """Redistribute scene clip durations to match the TTS audio length.

    Audio-driven timing: the total video duration is anchored to the TTS
    narration.  Each clip's duration is scaled proportionally so the sum
    equals *tts_duration*.

    If *clips* is empty or *tts_duration* <= 0, the original list is
    returned unchanged.

    Args:
        clips:        Original clip list with designer-specified durations.
        tts_duration: Target total duration in seconds (from TTS audio).

    Returns:
        New list of ClipInput objects with adjusted durations.
    """
    if not clips or tts_duration <= 0:
        return list(clips)

    original_total = sum(c.duration for c in clips)
    if original_total <= 0:
        # Distribute evenly
        per_clip = tts_duration / len(clips)
        return [
            ClipInput(
                file_path=c.file_path,
                duration=per_clip,
                transition=c.transition,
                has_audio=c.has_audio,
            )
            for c in clips
        ]

    scale = tts_duration / original_total
    reconciled = [
        ClipInput(
            file_path=c.file_path,
            duration=round(c.duration * scale, 3),
            transition=c.transition,
            has_audio=c.has_audio,
        )
        for c in clips
    ]

    logger.debug(
        "[composer] reconcile_durations: original_total={:.2f}s tts={:.2f}s scale={:.4f}",
        original_total,
        tts_duration,
        scale,
    )
    return reconciled


# ─── FFmpeg command builder ───────────────────────────────────────────────────

def build_compose_command(
    config: ComposeConfig,
    output_path: Path,
    ffmpeg_bin: Path,
) -> list[str]:
    """Build the FFmpeg argument list for the full compose operation.

    Ported from daihuo ``buildComposeCommand()`` (TypeScript → Python).
    Produces a single-pass FFmpeg command that:
        - Scales + pads each clip to the target resolution
        - Concatenates clips with optional xfade transitions
        - Mixes TTS narration audio (primary) with optional BGM (secondary)
        - Burns subtitle drawtext overlays
        - Encodes to H.264 + AAC MP4

    Args:
        config:      Compose configuration.
        output_path: Destination file path for final.mp4.
        ffmpeg_bin:  Absolute path to the ffmpeg binary.

    Returns:
        List of strings suitable for ``subprocess.run()``.

    Raises:
        ValueError: If *config.clips* is empty.
    """
    if not config.clips:
        raise ValueError("ComposeConfig.clips must not be empty.")

    width, height = _RESOLUTIONS[config.aspect_ratio][config.resolution]

    # ── Build input list ──────────────────────────────────────────────────────
    # Inputs: clips first, then TTS audio (if any), then BGM (if any)
    cmd: list[str] = [str(ffmpeg_bin), "-y"]

    for clip in config.clips:
        cmd += ["-i", str(clip.file_path)]

    tts_index: Optional[int] = None
    if config.tts_path is not None:
        tts_index = len(config.clips)
        cmd += ["-i", str(config.tts_path)]

    bgm_index: Optional[int] = None
    if config.bgm_path is not None:
        bgm_index = len(config.clips) + (1 if tts_index is not None else 0)
        cmd += ["-i", str(config.bgm_path)]

    # ── Build filter_complex ──────────────────────────────────────────────────
    filter_parts: list[str] = []

    # Scale + pad each clip to target resolution
    for i, clip in enumerate(config.clips):
        filter_parts.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"setpts=PTS-STARTPTS[v{i}]"
        )

    # Concatenate video streams with optional xfade
    current_video = "v0"
    for i in range(1, len(config.clips)):
        next_stream = f"xfade{i}" if config.clips[i].transition == "ffmpeg_fade" else f"concat{i}"
        if config.clips[i].transition == "ffmpeg_fade":
            fade_dur = 0.5
            offset = max(0.0, config.clips[i - 1].duration - fade_dur)
            filter_parts.append(
                f"[{current_video}][v{i}]xfade=transition=fade:"
                f"duration={fade_dur}:offset={offset:.3f}[{next_stream}]"
            )
        else:
            # direct_concat
            filter_parts.append(
                f"[{current_video}][v{i}]concat=n=2:v=1:a=0[{next_stream}]"
            )
        current_video = next_stream

    # ── Audio: TTS + BGM mix ──────────────────────────────────────────────────
    current_audio: Optional[str] = None

    if tts_index is not None:
        vol = config.tts_volume
        filter_parts.append(f"[{tts_index}:a]volume={vol:.3f}[tts_vol]")
        current_audio = "tts_vol"

    if bgm_index is not None:
        bgm_vol = config.bgm_volume
        filter_parts.append(f"[{bgm_index}:a]volume={bgm_vol:.3f}[bgm_vol]")
        if current_audio:
            # Mix TTS (primary) + BGM (secondary); duration follows TTS
            filter_parts.append(
                f"[{current_audio}][bgm_vol]amix=inputs=2:"
                f"duration=first:dropout_transition=2[audio_final]"
            )
            current_audio = "audio_final"
        else:
            current_audio = "bgm_vol"

    # ── Subtitle burn-in ──────────────────────────────────────────────────────
    if config.subtitle and config.subtitle.segments:
        sub = config.subtitle
        y_expr = {
            "top": "h*0.1",
            "center": "(h-text_h)/2",
            "bottom": "h*0.85",
        }[sub.position]

        draw_parts = []
        for seg in sub.segments:
            escaped = _escape_drawtext(seg.text)
            draw_parts.append(
                f"drawtext=text='{escaped}':"
                f"fontsize={sub.font_size}:"
                f"fontcolor={sub.color}:"
                f"bordercolor={sub.stroke_color}:"
                f"borderw={sub.stroke_width}:"
                f"x=(w-text_w)/2:y={y_expr}:"
                f"enable='between(t,{seg.start_sec:.3f},{seg.end_sec:.3f})'"
            )

        sub_filter = ",".join(draw_parts)
        sub_out = "sub_out"
        filter_parts.append(f"[{current_video}]{sub_filter}[{sub_out}]")
        current_video = sub_out

    # ── Assemble command ──────────────────────────────────────────────────────
    filter_complex = ";\n".join(filter_parts)
    cmd += ["-filter_complex", filter_complex]
    cmd += ["-map", f"[{current_video}]"]

    if current_audio:
        cmd += ["-map", f"[{current_audio}]"]

    # Encoding: H.264 + AAC, faststart for streaming
    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-profile:v", "high",
        "-level:v", "4.2",
        "-pix_fmt", "yuv420p",
    ]
    if current_audio:
        cmd += ["-c:a", "aac", "-b:a", "256k"]
    else:
        cmd += ["-an"]

    cmd += ["-movflags", "+faststart", str(output_path)]
    return cmd


# ─── Public API ───────────────────────────────────────────────────────────────

class VideoComposer:
    """Orchestrates the final video assembly step.

    Usage::

        composer = VideoComposer()
        result = composer.compose(config)
        print(result.output_path)  # storage/output/{project_id}/final.mp4

    The composer is stateless — each ``compose()`` call is independent.
    """

    def __init__(self) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise FileNotFoundError(
                "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
            )
        self._ffmpeg = ffmpeg
        logger.debug("[composer] ffmpeg binary: {}", self._ffmpeg)

    # ── Public API ────────────────────────────────────────────────────────────

    def compose(self, config: ComposeConfig) -> ComposeResult:
        """Run the full compose pipeline for *config*.

        Steps:
            1. Probe TTS audio duration (if provided)
            2. Reconcile clip durations to match TTS length
            3. Build FFmpeg filter_complex command
            4. Execute FFmpeg
            5. Return ComposeResult

        Args:
            config: Full compose configuration.

        Returns:
            ComposeResult with output_path and reconciled clip list.

        Raises:
            FileNotFoundError: If ffmpeg/ffprobe is not available.
            ValueError: If clips list is empty.
            subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
        """
        if not config.clips:
            raise ValueError("ComposeConfig.clips must not be empty.")

        # ── Step 1: Probe TTS duration ────────────────────────────────────────
        tts_duration: Optional[float] = None
        if config.tts_path is not None and config.tts_path.is_file():
            try:
                tts_duration = probe_duration(config.tts_path)
                logger.info(
                    "[composer] TTS duration probed: {:.2f}s ({})",
                    tts_duration,
                    config.tts_path.name,
                )
            except Exception as exc:
                logger.warning(
                    "[composer] Could not probe TTS duration ({}): {} — using clip durations",
                    config.tts_path,
                    exc,
                )

        # ── Step 2: Reconcile durations ───────────────────────────────────────
        if tts_duration is not None and tts_duration > 0:
            reconciled = reconcile_durations(config.clips, tts_duration)
        else:
            reconciled = list(config.clips)

        total_duration = tts_duration or sum(c.duration for c in reconciled)

        # ── Step 3: Prepare output path ───────────────────────────────────────
        out_dir = config.output_dir
        if out_dir is None:
            out_dir = Path("storage") / "output" / config.project_id
        out_dir.mkdir(parents=True, exist_ok=True)

        output_path = out_dir / "final.mp4"

        # ── Step 4: Build + run FFmpeg ────────────────────────────────────────
        # Use reconciled durations in a copy of config
        reconciled_config = ComposeConfig(
            project_id=config.project_id,
            clips=reconciled,
            tts_path=config.tts_path,
            output_dir=out_dir,
            aspect_ratio=config.aspect_ratio,
            resolution=config.resolution,
            bgm_path=config.bgm_path,
            bgm_volume=config.bgm_volume,
            subtitle=config.subtitle,
            tts_volume=config.tts_volume,
        )

        cmd = build_compose_command(reconciled_config, output_path, self._ffmpeg)

        logger.info(
            "[composer] running FFmpeg: {} clips, tts={}, bgm={}, subtitle={}",
            len(reconciled),
            config.tts_path is not None,
            config.bgm_path is not None,
            config.subtitle is not None and bool(config.subtitle.segments),
        )
        logger.debug("[composer] FFmpeg cmd: {}", " ".join(cmd))

        _run_ffmpeg_cmd(cmd)

        logger.info("[composer] compose done → {}", output_path)
        return ComposeResult(
            output_path=output_path,
            total_duration=total_duration,
            reconciled_clips=reconciled,
        )


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _run_ffmpeg_cmd(cmd: list[str], timeout: int = 600) -> None:
    """Execute an FFmpeg command list and raise on failure.

    Args:
        cmd:     Full command list (binary + args).
        timeout: Maximum seconds to wait (default 600 = 10 min for long videos).

    Raises:
        subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
        subprocess.TimeoutExpired:     If the process exceeds *timeout*.
    """
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        logger.error("[composer] FFmpeg failed (rc={}): {}", result.returncode, stderr[-2000:])
        raise subprocess.CalledProcessError(
            returncode=result.returncode,
            cmd=cmd,
            stderr=result.stderr,
        )


# ─── Convenience function ─────────────────────────────────────────────────────

def compose_video(config: ComposeConfig) -> ComposeResult:
    """Convenience wrapper — create a VideoComposer and run compose().

    Args:
        config: Full compose configuration.

    Returns:
        ComposeResult with output_path and reconciled clip list.

    Raises:
        FileNotFoundError: If ffmpeg is not available.
        ValueError: If clips list is empty.
        subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
    """
    return VideoComposer().compose(config)
