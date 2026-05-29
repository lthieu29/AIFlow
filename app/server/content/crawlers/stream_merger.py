"""DASH stream merger and subtitle extractor.

Provides utilities for:
- Merging separate DASH video + audio streams into a single MP4 (FFmpeg mux).
- Extracting embedded subtitles from a video file.
- Transcribing video audio via Whisper to produce an SRT file.

All FFmpeg operations use ``find_ffmpeg()`` from ``server.audio.ffmpeg_utils``
(vendor/ first, then PATH) — consistent with the rest of the project.

Phase 4.5 / Task 4.5.5
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from server.audio.ffmpeg_utils import find_ffmpeg, find_ffprobe
from server.audio.transcribe import transcribe_audio

logger = logging.getLogger(__name__)


# ─── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class MergeResult:
    """Metadata for a successfully merged video file.

    Attributes:
        output_path: Absolute path to the merged MP4 file.
        duration:    Video duration in seconds (0.0 if probe failed).
        has_audio:   Whether the merged file contains an audio stream.
    """

    output_path: Path
    duration: float
    has_audio: bool


# ─── Module-level functions ───────────────────────────────────────────────────


def merge_dash_streams(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> MergeResult:
    """Merge separate DASH video and audio streams into a single MP4.

    Uses ``-c copy`` for a fast mux — no re-encoding.

    Args:
        video_path:  Path to the DASH video-only stream (e.g. .mp4 / .m4v).
        audio_path:  Path to the DASH audio-only stream (e.g. .m4a / .mp4).
        output_path: Destination path for the merged MP4.

    Returns:
        :class:`MergeResult` with output path, duration, and audio flag.

    Raises:
        FileNotFoundError: If FFmpeg cannot be located.
        FileNotFoundError: If *video_path* or *audio_path* do not exist.
        subprocess.CalledProcessError: If FFmpeg exits with a non-zero code.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise FileNotFoundError(
            "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
        )

    if not video_path.exists():
        raise FileNotFoundError(f"Video stream not found: {video_path}")
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio stream not found: {audio_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(ffmpeg),
        "-y",                        # overwrite output without asking
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c", "copy",                # fast mux — no re-encoding
        "-movflags", "+faststart",   # web-friendly MP4 atom ordering
        str(output_path),
    ]

    logger.info("Merging DASH streams → %s", output_path)
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))

    subprocess.run(cmd, check=True, capture_output=True, timeout=300)

    # Probe duration and audio presence
    duration, has_audio = _probe_video(output_path)

    logger.info(
        "Merge complete: %s (duration=%.1fs, has_audio=%s)",
        output_path,
        duration,
        has_audio,
    )
    return MergeResult(output_path=output_path, duration=duration, has_audio=has_audio)


def extract_subtitles(
    video_path: Path,
    output_srt: Path,
    language: str = "vi",
) -> Optional[Path]:
    """Extract embedded subtitles from a video file using FFmpeg.

    Tries to find a subtitle stream matching *language* first; falls back to
    the first available subtitle stream if no language match is found.

    Args:
        video_path:  Path to the video file.
        output_srt:  Destination path for the extracted SRT file.
        language:    Preferred subtitle language code (e.g. "vi", "en").

    Returns:
        Path to the written SRT file if subtitles were found, ``None`` otherwise.

    Raises:
        FileNotFoundError: If FFmpeg cannot be located.
        FileNotFoundError: If *video_path* does not exist.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise FileNotFoundError(
            "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
        )

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    output_srt.parent.mkdir(parents=True, exist_ok=True)

    # Try language-specific stream first, then fall back to first subtitle stream
    for stream_selector in (f"s:m:language:{language}", "s:0"):
        cmd = [
            str(ffmpeg),
            "-y",
            "-i", str(video_path),
            "-map", stream_selector,
            "-c:s", "srt",
            str(output_srt),
        ]

        logger.debug("Trying subtitle extraction with selector '%s'", stream_selector)

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=60,
        )

        if result.returncode == 0 and output_srt.exists() and output_srt.stat().st_size > 0:
            logger.info("Subtitles extracted to %s", output_srt)
            return output_srt

        # Clean up empty/failed output before retrying
        if output_srt.exists():
            output_srt.unlink(missing_ok=True)

    logger.info("No embedded subtitles found in %s", video_path)
    return None


def transcribe_video(
    video_path: Path,
    output_dir: Path,
    language: str = "vi",
) -> Optional[Path]:
    """Extract audio from a video and transcribe it with Whisper.

    Extracts a temporary WAV file from *video_path*, then calls
    :func:`server.audio.transcribe.transcribe_audio` to produce an SRT.

    Args:
        video_path:  Path to the video file.
        output_dir:  Directory where the SRT file will be written.
        language:    Language code for Whisper transcription (e.g. "vi", "en").

    Returns:
        Path to the SRT file if transcription succeeded, ``None`` on failure.

    Raises:
        FileNotFoundError: If FFmpeg cannot be located.
        FileNotFoundError: If *video_path* does not exist.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise FileNotFoundError(
            "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
        )

    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_srt = output_dir / (video_path.stem + ".srt")

    # Extract audio to a temporary WAV file
    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = Path(tmp_dir) / "audio.wav"

        extract_cmd = [
            str(ffmpeg),
            "-y",
            "-i", str(video_path),
            "-vn",                   # drop video
            "-acodec", "pcm_s16le",  # PCM WAV — Whisper-friendly
            "-ar", "16000",          # 16 kHz sample rate
            "-ac", "1",              # mono
            str(audio_path),
        ]

        logger.info("Extracting audio from %s for transcription …", video_path)
        result = subprocess.run(extract_cmd, capture_output=True, timeout=300)

        if result.returncode != 0 or not audio_path.exists():
            logger.warning(
                "Audio extraction failed for %s: %s",
                video_path,
                result.stderr.decode(errors="replace"),
            )
            return None

        # Transcribe with Whisper
        try:
            srt_path = transcribe_audio(
                audio_path=audio_path,
                output_srt=output_srt,
                language=language,
            )
            return srt_path
        except ImportError:
            logger.error(
                "faster-whisper not installed — cannot transcribe %s. "
                "Install with: pip install faster-whisper",
                video_path,
            )
            return None
        except Exception as exc:
            logger.error("Transcription failed for %s: %s", video_path, exc)
            return None


# ─── StreamMerger class ───────────────────────────────────────────────────────


class StreamMerger:
    """High-level interface for DASH stream merging and subtitle extraction.

    Locates FFmpeg at construction time so callers get an immediate
    ``FileNotFoundError`` if the binary is missing, rather than a delayed
    failure at merge time.

    Example::

        merger = StreamMerger()
        result = merger.merge(video_path, audio_path, output_path)
        srt = merger.transcribe(output_path, output_dir, language="vi")
    """

    def __init__(self) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise FileNotFoundError(
                "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
            )
        self._ffmpeg = ffmpeg
        logger.debug("StreamMerger initialised with ffmpeg=%s", ffmpeg)

    # ── Public API ────────────────────────────────────────────────────────────

    def merge(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> MergeResult:
        """Merge DASH video + audio streams into a single MP4.

        Delegates to :func:`merge_dash_streams`.

        Args:
            video_path:  Path to the DASH video-only stream.
            audio_path:  Path to the DASH audio-only stream.
            output_path: Destination path for the merged MP4.

        Returns:
            :class:`MergeResult` with output path, duration, and audio flag.
        """
        return merge_dash_streams(video_path, audio_path, output_path)

    def extract_subs(
        self,
        video_path: Path,
        output_srt: Path,
        language: str = "vi",
    ) -> Optional[Path]:
        """Extract embedded subtitles from a video file.

        Delegates to :func:`extract_subtitles`.

        Args:
            video_path:  Path to the video file.
            output_srt:  Destination path for the extracted SRT file.
            language:    Preferred subtitle language code.

        Returns:
            Path to the SRT file if found, ``None`` otherwise.
        """
        return extract_subtitles(video_path, output_srt, language)

    def transcribe(
        self,
        video_path: Path,
        output_dir: Path,
        language: str = "vi",
    ) -> Optional[Path]:
        """Extract audio from a video and transcribe it with Whisper.

        Delegates to :func:`transcribe_video`.

        Args:
            video_path:  Path to the video file.
            output_dir:  Directory where the SRT file will be written.
            language:    Language code for Whisper transcription.

        Returns:
            Path to the SRT file if successful, ``None`` on failure.
        """
        return transcribe_video(video_path, output_dir, language)


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _probe_video(video_path: Path) -> tuple[float, bool]:
    """Probe a video file for duration and audio stream presence.

    Uses ffprobe when available; falls back to (0.0, True) on any error.

    Args:
        video_path: Path to the video file to probe.

    Returns:
        ``(duration_seconds, has_audio)`` tuple.
    """
    ffprobe = find_ffprobe()
    if ffprobe is None:
        logger.debug("ffprobe not found — skipping video probe")
        return 0.0, True

    # Probe duration
    duration = 0.0
    try:
        dur_cmd = [
            str(ffprobe),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        out = subprocess.check_output(dur_cmd, encoding="utf-8", stderr=subprocess.DEVNULL)
        duration = float(out.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        pass

    # Probe audio stream presence
    has_audio = True
    try:
        audio_cmd = [
            str(ffprobe),
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        out = subprocess.check_output(audio_cmd, encoding="utf-8", stderr=subprocess.DEVNULL)
        has_audio = bool(out.strip())
    except (subprocess.CalledProcessError, OSError):
        pass

    return duration, has_audio
