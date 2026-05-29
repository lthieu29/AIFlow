"""Translator + remaster pipeline for crawled videos.

Translates SRT subtitles (Chinese → Vietnamese via Gemini) and re-cuts
the video with the new subtitle track.  Three presets control how much
processing is applied:

- ``LIGHT``          — burn translated subtitles onto the video (FFmpeg drawtext)
- ``AGGRESSIVE``     — replace audio with TTS of translated text + burn subtitles
- ``TRANSLATE_ONLY`` — translate SRT only, no video modification

Phase 4.5 / Task 4.5.6
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from server.audio.ffmpeg_utils import find_ffmpeg
from server.content.crawlers.stream_merger import StreamMerger
from server.content.srt_utils import SrtSegment, format_srt, parse_srt

logger = logging.getLogger(__name__)


# ─── Enums & config ───────────────────────────────────────────────────────────


class RemasterPreset(str, Enum):
    """Processing preset for the remaster pipeline.

    Attributes:
        LIGHT:          Burn translated subtitles onto video (FFmpeg drawtext).
        AGGRESSIVE:     Replace audio with TTS of translated text + burn subs.
        TRANSLATE_ONLY: Translate SRT only — no video modification.
    """

    LIGHT = "light"
    AGGRESSIVE = "aggressive"
    TRANSLATE_ONLY = "translate_only"


@dataclass
class RemasterConfig:
    """Configuration for the remaster pipeline.

    Attributes:
        preset:          Processing preset (default: LIGHT).
        source_language: Source language code for transcription (default: "zh").
        target_language: Target language code for translation (default: "vi").
        gemini_client:   Optional :class:`server.ai.gemini.GeminiClient` instance.
                         If ``None``, translation falls back to returning the
                         original SRT unchanged.
    """

    preset: RemasterPreset = RemasterPreset.LIGHT
    source_language: str = "zh"
    target_language: str = "vi"
    gemini_client: Optional[object] = field(default=None, repr=False)


# ─── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class RemasterResult:
    """Result of a remaster operation.

    Attributes:
        output_path:    Path to the remastered video (or original if
                        ``TRANSLATE_ONLY``).
        translated_srt: Path to the translated SRT file.
        original_srt:   Path to the original (source-language) SRT, if kept.
        preset:         The preset that was applied.
    """

    output_path: Path
    translated_srt: Path
    original_srt: Optional[Path]
    preset: RemasterPreset


# ─── Translation ──────────────────────────────────────────────────────────────

_TRANSLATE_PROMPT_TEMPLATE = (
    "Translate the following subtitle text from {source} to {target}. "
    "Return ONLY the translated text, no explanations, no quotes.\n\n"
    "{text}"
)


def translate_srt(srt_path: Path, config: RemasterConfig) -> Path:
    """Translate an SRT file using Gemini and write the result to disk.

    The translated file is written to the same directory as *srt_path* with
    a ``_{target_language}.srt`` suffix (e.g. ``video_vi.srt``).

    If ``config.gemini_client`` is ``None`` or translation fails, the
    original SRT path is returned unchanged (graceful fallback).

    Args:
        srt_path: Path to the source SRT file.
        config:   Remaster configuration (provides Gemini client + languages).

    Returns:
        Path to the translated SRT file, or *srt_path* on fallback.
    """
    if not srt_path.exists():
        logger.warning("SRT file not found: %s — skipping translation", srt_path)
        return srt_path

    if config.gemini_client is None:
        logger.info(
            "No Gemini client configured — returning original SRT unchanged: %s",
            srt_path,
        )
        return srt_path

    content = srt_path.read_text(encoding="utf-8")
    segments = parse_srt(content)

    if not segments:
        logger.warning("No segments found in %s — returning original", srt_path)
        return srt_path

    translated_segments: list[SrtSegment] = []
    for seg in segments:
        try:
            prompt = _TRANSLATE_PROMPT_TEMPLATE.format(
                source=config.source_language,
                target=config.target_language,
                text=seg.text,
            )
            translated_text = config.gemini_client.generate_text(prompt).strip()
            translated_segments.append(
                SrtSegment(
                    index=seg.index,
                    start_sec=seg.start_sec,
                    end_sec=seg.end_sec,
                    text=translated_text,
                )
            )
            logger.debug(
                "Translated segment %d: %r → %r",
                seg.index,
                seg.text[:40],
                translated_text[:40],
            )
        except Exception as exc:
            logger.warning(
                "Translation failed for segment %d (%r): %s — keeping original",
                seg.index,
                seg.text[:40],
                exc,
            )
            translated_segments.append(seg)

    # Write translated SRT next to the original
    stem = srt_path.stem
    # Strip existing language suffix if present (e.g. video_zh → video)
    if stem.endswith(f"_{config.source_language}"):
        stem = stem[: -len(f"_{config.source_language}")]

    out_path = srt_path.parent / f"{stem}_{config.target_language}.srt"
    out_path.write_text(format_srt(translated_segments), encoding="utf-8")
    logger.info("Translated SRT written to %s", out_path)
    return out_path


# ─── Video remaster ───────────────────────────────────────────────────────────


def _escape_srt_path_for_ffmpeg(srt_path: Path) -> str:
    """Return an SRT path string safe for FFmpeg ``subtitles=`` filter.

    On Windows, backslashes must be escaped as ``\\\\`` inside the filter
    string, and colons in drive letters (``C:``) must be escaped as ``\\:``.

    Args:
        srt_path: Path to the SRT file.

    Returns:
        Escaped path string for use in ``subtitles=<path>`` filter.
    """
    p = str(srt_path).replace("\\", "/")
    # Escape colon in Windows drive letter (C:/ → C\\:/)
    if len(p) >= 2 and p[1] == ":":
        p = p[0] + "\\:" + p[2:]
    return p


def _build_subtitle_burn_cmd(
    ffmpeg: Path,
    video_path: Path,
    srt_path: Path,
    output_path: Path,
) -> list[str]:
    """Build an FFmpeg command that burns subtitles using the ``subtitles`` filter.

    Uses the ``subtitles`` filter (ASS/SRT rendering via libass) which
    handles multi-line text and Unicode better than ``drawtext``.

    Args:
        ffmpeg:      Path to the ffmpeg binary.
        video_path:  Input video path.
        srt_path:    Path to the SRT subtitle file.
        output_path: Destination path for the output video.

    Returns:
        List of strings suitable for ``subprocess.run()``.
    """
    escaped_srt = _escape_srt_path_for_ffmpeg(srt_path)
    return [
        str(ffmpeg),
        "-y",
        "-i", str(video_path),
        "-vf", f"subtitles={escaped_srt}:force_style='FontSize=24,PrimaryColour=&H00FFFFFF'",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]


def remaster_video(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    config: RemasterConfig,
) -> RemasterResult:
    """Apply the remaster preset to a video file.

    Preset behaviour:

    - ``LIGHT``          — burn translated subtitles onto video (FFmpeg subtitles filter).
    - ``AGGRESSIVE``     — burn subtitles + log a warning that TTS replacement is not
                           yet implemented (falls back to LIGHT behaviour).
    - ``TRANSLATE_ONLY`` — skip video modification; return original video path.

    Args:
        video_path:  Path to the input video file.
        srt_path:    Path to the (already translated) SRT file.
        output_path: Destination path for the remastered video.
        config:      Remaster configuration.

    Returns:
        :class:`RemasterResult` describing the operation outcome.

    Raises:
        FileNotFoundError: If FFmpeg cannot be located (LIGHT / AGGRESSIVE only).
        FileNotFoundError: If *video_path* does not exist.
        subprocess.CalledProcessError: If FFmpeg exits with a non-zero code.
    """
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # TRANSLATE_ONLY — no video modification
    if config.preset == RemasterPreset.TRANSLATE_ONLY:
        logger.info(
            "TRANSLATE_ONLY preset — skipping video modification for %s", video_path
        )
        return RemasterResult(
            output_path=video_path,
            translated_srt=srt_path,
            original_srt=None,
            preset=config.preset,
        )

    # LIGHT / AGGRESSIVE — burn subtitles
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise FileNotFoundError(
            "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
        )

    if config.preset == RemasterPreset.AGGRESSIVE:
        logger.warning(
            "AGGRESSIVE preset: TTS audio replacement is not yet implemented — "
            "falling back to subtitle burn-in (LIGHT behaviour)."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = _build_subtitle_burn_cmd(ffmpeg, video_path, srt_path, output_path)

    logger.info(
        "Burning subtitles (%s preset): %s → %s",
        config.preset.value,
        video_path.name,
        output_path.name,
    )
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))

    subprocess.run(cmd, check=True, capture_output=True, timeout=600)

    logger.info("Remaster complete → %s", output_path)
    return RemasterResult(
        output_path=output_path,
        translated_srt=srt_path,
        original_srt=None,
        preset=config.preset,
    )


# ─── VideoRemaster class ──────────────────────────────────────────────────────


class VideoRemaster:
    """High-level async interface for the full translate + remaster pipeline.

    Validates configuration at construction time so callers get an immediate
    error if the setup is invalid, rather than a delayed failure mid-pipeline.

    Example::

        from server.ai.gemini import GeminiClient
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, VideoRemaster,
        )

        client = GeminiClient(api_key="AIzaSy...")
        config = RemasterConfig(
            preset=RemasterPreset.LIGHT,
            source_language="zh",
            target_language="vi",
            gemini_client=client,
        )
        remaster = VideoRemaster(config)
        result = await remaster.remaster(video_path, output_dir)
    """

    def __init__(self, config: RemasterConfig) -> None:
        """Initialise and validate the remaster configuration.

        Args:
            config: Remaster configuration.

        Raises:
            ValueError: If *config* is not a :class:`RemasterConfig` instance.
        """
        if not isinstance(config, RemasterConfig):
            raise ValueError(
                f"config must be a RemasterConfig instance, got {type(config).__name__}"
            )
        self._config = config
        logger.debug(
            "VideoRemaster initialised: preset=%s src=%s tgt=%s gemini=%s",
            config.preset.value,
            config.source_language,
            config.target_language,
            "yes" if config.gemini_client is not None else "no",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def remaster(
        self,
        video_path: Path,
        output_dir: Path,
    ) -> RemasterResult:
        """Run the full translate + remaster pipeline.

        Pipeline steps:

        1. Extract / transcribe subtitles from *video_path* (via
           :class:`~server.content.crawlers.stream_merger.StreamMerger`).
        2. Translate the SRT using Gemini (or fall back to original).
        3. Apply the configured preset (burn subs / translate-only).
        4. Return :class:`RemasterResult`.

        Args:
            video_path: Path to the input video file.
            output_dir: Directory where output files will be written.

        Returns:
            :class:`RemasterResult` describing the operation outcome.

        Raises:
            FileNotFoundError: If *video_path* does not exist.
            FileNotFoundError: If FFmpeg is required but not found.
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 1: Get subtitles ─────────────────────────────────────────────
        original_srt = await self._get_subtitles(video_path, output_dir)

        # ── Step 2: Translate SRT ─────────────────────────────────────────────
        # Run blocking I/O in a thread pool to keep the event loop free
        loop = asyncio.get_running_loop()
        translated_srt = await loop.run_in_executor(
            None, translate_srt, original_srt, self._config
        )

        # ── Step 3: Apply preset ──────────────────────────────────────────────
        output_path = output_dir / f"{video_path.stem}_remastered.mp4"

        result = await loop.run_in_executor(
            None,
            remaster_video,
            video_path,
            translated_srt,
            output_path,
            self._config,
        )

        # Attach original SRT reference
        if original_srt != translated_srt:
            return RemasterResult(
                output_path=result.output_path,
                translated_srt=result.translated_srt,
                original_srt=original_srt,
                preset=result.preset,
            )
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_subtitles(self, video_path: Path, output_dir: Path) -> Path:
        """Extract embedded subtitles or transcribe audio to get an SRT.

        Tries embedded subtitle extraction first; falls back to Whisper
        transcription.  If both fail, writes an empty SRT so the pipeline
        can continue gracefully.

        Args:
            video_path: Path to the video file.
            output_dir: Directory for output SRT files.

        Returns:
            Path to the SRT file (may be empty if extraction/transcription failed).
        """
        srt_path = output_dir / f"{video_path.stem}_{self._config.source_language}.srt"

        loop = asyncio.get_running_loop()

        try:
            merger = StreamMerger()
        except FileNotFoundError:
            logger.warning(
                "FFmpeg not available — cannot extract/transcribe subtitles. "
                "Writing empty SRT."
            )
            srt_path.write_text("", encoding="utf-8")
            return srt_path

        # Try embedded subtitle extraction first
        extracted = await loop.run_in_executor(
            None,
            merger.extract_subs,
            video_path,
            srt_path,
            self._config.source_language,
        )
        if extracted is not None:
            logger.info("Embedded subtitles extracted: %s", extracted)
            return extracted

        # Fall back to Whisper transcription
        logger.info(
            "No embedded subtitles — attempting Whisper transcription (%s) …",
            self._config.source_language,
        )
        transcribed = await loop.run_in_executor(
            None,
            merger.transcribe,
            video_path,
            output_dir,
            self._config.source_language,
        )
        if transcribed is not None:
            logger.info("Transcription complete: %s", transcribed)
            return transcribed

        # Both failed — write empty SRT so pipeline can continue
        logger.warning(
            "Could not extract or transcribe subtitles for %s — writing empty SRT",
            video_path,
        )
        srt_path.write_text("", encoding="utf-8")
        return srt_path
