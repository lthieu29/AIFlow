"""Whisper-based audio transcription utilities.

Wraps faster-whisper to transcribe audio files and produce SRT subtitle files.

Phase 3 / Task 4.5.5
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def transcribe_audio(
    audio_path: Path,
    output_srt: Path,
    language: str = "vi",
    model_name: str = "medium",
    device: str = "cpu",
    compute_type: str = "int8",
) -> Optional[Path]:
    """Transcribe an audio file using faster-whisper and write an SRT file.

    Args:
        audio_path:   Path to the audio file (wav, mp3, m4a, etc.).
        output_srt:   Destination path for the generated SRT file.
        language:     Language code for transcription (e.g. "vi", "en").
        model_name:   Whisper model size: tiny/base/small/medium/large-v3.
        device:       Inference device: "cpu" or "cuda".
        compute_type: Quantisation type: "int8", "float16", "float32".

    Returns:
        Path to the written SRT file, or ``None`` if transcription produced
        no segments (silent audio, import error, etc.).

    Raises:
        FileNotFoundError: If *audio_path* does not exist.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    try:
        from faster_whisper import WhisperModel  # type: ignore[import]
    except ImportError as exc:
        logger.error(
            "faster-whisper is not installed. "
            "Install it with: pip install faster-whisper  (or pip install aiflow[audio])"
        )
        raise ImportError(
            "faster-whisper is required for transcription. "
            "Install with: pip install faster-whisper"
        ) from exc

    logger.info(
        "Loading Whisper model '%s' on %s (%s) …", model_name, device, compute_type
    )
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    logger.info("Transcribing %s (language=%s) …", audio_path, language)
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
    )

    # Materialise the generator so we can check if it's empty
    segment_list = list(segments)
    if not segment_list:
        logger.warning("Transcription produced no segments for %s", audio_path)
        return None

    logger.debug(
        "Detected language '%s' (probability %.2f)",
        info.language,
        info.language_probability,
    )

    # Write SRT
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    with output_srt.open("w", encoding="utf-8") as fh:
        for idx, seg in enumerate(segment_list, start=1):
            fh.write(f"{idx}\n")
            fh.write(
                f"{_format_timestamp(seg.start)} --> {_format_timestamp(seg.end)}\n"
            )
            fh.write(f"{seg.text.strip()}\n\n")

    logger.info("SRT written to %s (%d segments)", output_srt, len(segment_list))
    return output_srt
