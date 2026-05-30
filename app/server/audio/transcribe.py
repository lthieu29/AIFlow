"""Whisper-based audio transcription utilities.

Wraps faster-whisper to transcribe audio files and produce SRT subtitle files.
Lifted and adapted from MoneyPrinterTurbo's ``app/services/subtitle.py``.

Phase 3 / Task 3.3.1
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# ─── Types ────────────────────────────────────────────────────────────────────

ModelSize = Literal["tiny", "base", "small", "medium", "large-v2", "large-v3"]

SUPPORTED_MODELS: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
)


# ─── SRT Segment ──────────────────────────────────────────────────────────────

@dataclass
class SRTSegment:
    """A single subtitle segment in SRT format.

    Attributes:
        index:      1-based segment index (SRT sequence number).
        start_time: Start time in seconds.
        end_time:   End time in seconds.
        text:       Subtitle text for this segment.
    """

    index: int
    start_time: float
    end_time: float
    text: str

    def to_srt_block(self) -> str:
        """Render this segment as a standard SRT block.

        Returns:
            Multi-line string in the form::

                1
                00:00:01,000 --> 00:00:03,500
                Hello world

        """
        start = _format_timestamp(self.start_time)
        end = _format_timestamp(self.end_time)
        return f"{self.index}\n{start} --> {end}\n{self.text}\n"


# ─── Timestamp formatting ─────────────────────────────────────────────────────

def _format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format ``HH:MM:SS,mmm``.

    Args:
        seconds: Time in seconds (may include fractional part).

    Returns:
        Formatted timestamp string, e.g. ``"00:01:23,456"``.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000))
    # Guard against rounding millis to 1000
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ─── Device detection ─────────────────────────────────────────────────────────

def _detect_device() -> str:
    """Auto-detect the best available inference device.

    Returns:
        ``"cuda"`` if a CUDA-capable GPU is available, otherwise ``"cpu"``.
    """
    try:
        import torch  # type: ignore[import]

        if torch.cuda.is_available():
            logger.debug("CUDA available — using GPU for Whisper inference")
            return "cuda"
    except ImportError:
        pass

    logger.debug("CUDA not available — using CPU for Whisper inference")
    return "cpu"


def _compute_type_for_device(device: str) -> str:
    """Return the recommended compute type for the given device.

    Args:
        device: ``"cuda"`` or ``"cpu"``.

    Returns:
        ``"float16"`` for CUDA (faster, lower VRAM), ``"int8"`` for CPU.
    """
    return "float16" if device == "cuda" else "int8"


# ─── WhisperTranscriber ───────────────────────────────────────────────────────

class WhisperTranscriber:
    """Lazy-loading, model-caching Whisper transcriber.

    Models are loaded on first use and cached by ``model_size`` so repeated
    calls with the same model avoid redundant disk I/O and GPU memory
    allocation.

    Usage::

        transcriber = WhisperTranscriber()
        segments = transcriber.transcribe(Path("audio.mp3"), language="vi")
        srt_path = transcriber.transcribe_to_srt(
            Path("audio.mp3"), Path("output.srt"), language="vi"
        )

    The class is a singleton-friendly object; you can also use the
    module-level convenience functions :func:`transcribe` and
    :func:`transcribe_to_srt` which share a global instance.
    """

    def __init__(self) -> None:
        # Cache: model_size -> WhisperModel instance
        self._model_cache: dict[str, object] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_model(self, model_size: str, device: str, compute_type: str) -> object:
        """Return a cached WhisperModel, loading it on first access.

        Args:
            model_size:   One of the supported model size strings.
            device:       ``"cuda"`` or ``"cpu"``.
            compute_type: Quantisation type (``"int8"``, ``"float16"``, etc.).

        Returns:
            A ``faster_whisper.WhisperModel`` instance.

        Raises:
            ImportError: If ``faster-whisper`` is not installed.
            ValueError:  If *model_size* is not in :data:`SUPPORTED_MODELS`.
        """
        if model_size not in SUPPORTED_MODELS:
            raise ValueError(
                f"Unsupported model size '{model_size}'. "
                f"Choose from: {', '.join(SUPPORTED_MODELS)}"
            )

        cache_key = f"{model_size}:{device}:{compute_type}"

        # Return cached model without importing faster_whisper again
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]

        # Only import when we actually need to load a new model
        try:
            from faster_whisper import WhisperModel  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "faster-whisper is required for transcription. "
                "Install with: pip install faster-whisper  "
                "(or: pip install aiflow[audio])"
            ) from exc

        logger.info(
            "Loading Whisper model '%s' on %s (%s) …",
            model_size,
            device,
            compute_type,
        )
        self._model_cache[cache_key] = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type,
        )
        logger.info("Whisper model '%s' loaded and cached.", model_size)

        return self._model_cache[cache_key]

    # ── Public API ────────────────────────────────────────────────────────────

    def transcribe(
        self,
        audio_path: Path,
        language: Optional[str] = None,
        model_size: str = "base",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        beam_size: int = 5,
        word_timestamps: bool = True,
        vad_filter: bool = True,
    ) -> list[SRTSegment]:
        """Transcribe an audio file and return a list of :class:`SRTSegment`.

        Adapted from MoneyPrinterTurbo ``subtitle.create()`` — uses word-level
        timestamps and VAD filtering for cleaner segment boundaries.

        Args:
            audio_path:      Path to the audio file (wav, mp3, m4a, etc.).
            language:        BCP-47 language code (e.g. ``"vi"``, ``"en"``).
                             Pass ``None`` to let Whisper auto-detect.
            model_size:      Whisper model size. One of ``tiny``, ``base``,
                             ``small``, ``medium``, ``large-v2``, ``large-v3``.
            device:          Inference device. Auto-detected if ``None``.
            compute_type:    Quantisation type. Derived from *device* if ``None``.
            beam_size:       Beam search width (higher = more accurate, slower).
            word_timestamps: Enable word-level timestamp extraction.
            vad_filter:      Apply Voice Activity Detection to filter silence.

        Returns:
            List of :class:`SRTSegment` objects (may be empty for silent audio).

        Raises:
            FileNotFoundError: If *audio_path* does not exist.
            ImportError:       If ``faster-whisper`` is not installed.
            ValueError:        If *model_size* is not supported.
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        resolved_device = device or _detect_device()
        resolved_compute = compute_type or _compute_type_for_device(resolved_device)

        model = self._get_model(model_size, resolved_device, resolved_compute)

        logger.info(
            "Transcribing '%s' (language=%s, model=%s) …",
            audio_path.name,
            language or "auto",
            model_size,
        )

        transcribe_kwargs: dict = {
            "beam_size": beam_size,
            "word_timestamps": word_timestamps,
            "vad_filter": vad_filter,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
        if language:
            transcribe_kwargs["language"] = language

        segments_iter, info = model.transcribe(str(audio_path), **transcribe_kwargs)  # type: ignore[union-attr]

        logger.debug(
            "Detected language '%s' (probability %.2f)",
            info.language,
            info.language_probability,
        )

        srt_segments: list[SRTSegment] = []
        idx = 1

        for segment in segments_iter:
            # Use word-level boundaries when available for tighter segments
            if word_timestamps and segment.words:
                seg_start: float = 0.0
                seg_end: float = 0.0
                seg_text: str = ""
                is_open = False

                for word in segment.words:
                    if not is_open:
                        seg_start = word.start
                        is_open = True

                    seg_end = word.end
                    seg_text += word.word

                # Flush remaining text as a segment
                cleaned = seg_text.strip()
                if cleaned:
                    srt_segments.append(
                        SRTSegment(
                            index=idx,
                            start_time=seg_start,
                            end_time=seg_end,
                            text=cleaned,
                        )
                    )
                    idx += 1
            else:
                # Fall back to segment-level timestamps
                cleaned = segment.text.strip()
                if cleaned:
                    srt_segments.append(
                        SRTSegment(
                            index=idx,
                            start_time=segment.start,
                            end_time=segment.end,
                            text=cleaned,
                        )
                    )
                    idx += 1

        logger.info(
            "Transcription complete: %d segment(s) from '%s'",
            len(srt_segments),
            audio_path.name,
        )
        return srt_segments

    def transcribe_to_srt(
        self,
        audio_path: Path,
        output_path: Path,
        language: Optional[str] = None,
        model_size: str = "base",
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> str:
        """Transcribe an audio file and write the result as an SRT file.

        Args:
            audio_path:  Path to the audio file.
            output_path: Destination path for the ``.srt`` file.
            language:    BCP-47 language code or ``None`` for auto-detect.
            model_size:  Whisper model size (default ``"base"``).
            device:      Inference device (auto-detected if ``None``).
            compute_type: Quantisation type (derived from *device* if ``None``).

        Returns:
            Absolute path to the written SRT file as a string.

        Raises:
            FileNotFoundError: If *audio_path* does not exist.
            ImportError:       If ``faster-whisper`` is not installed.
            ValueError:        If *model_size* is not supported.
        """
        segments = self.transcribe(
            audio_path=audio_path,
            language=language,
            model_size=model_size,
            device=device,
            compute_type=compute_type,
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", encoding="utf-8") as fh:
            for seg in segments:
                fh.write(seg.to_srt_block())
                fh.write("\n")  # blank line between blocks

        logger.info(
            "SRT written to '%s' (%d segment(s))",
            output_path,
            len(segments),
        )
        return str(output_path.resolve())

    def clear_cache(self) -> None:
        """Unload all cached models and free memory."""
        self._model_cache.clear()
        logger.info("Whisper model cache cleared.")


# ─── Module-level convenience API ─────────────────────────────────────────────

# Shared global instance — avoids reloading models across multiple calls.
_default_transcriber = WhisperTranscriber()


def transcribe(
    audio_path: Path,
    language: Optional[str] = None,
    model_size: str = "base",
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
) -> list[SRTSegment]:
    """Module-level convenience wrapper around :meth:`WhisperTranscriber.transcribe`.

    Uses a shared global :class:`WhisperTranscriber` instance so models are
    cached across calls within the same process.

    Args:
        audio_path:  Path to the audio file.
        language:    BCP-47 language code or ``None`` for auto-detect.
        model_size:  Whisper model size (default ``"base"``).
        device:      Inference device (auto-detected if ``None``).
        compute_type: Quantisation type (derived from *device* if ``None``).

    Returns:
        List of :class:`SRTSegment` objects.
    """
    return _default_transcriber.transcribe(
        audio_path=audio_path,
        language=language,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
    )


def transcribe_to_srt(
    audio_path: Path,
    output_path: Path,
    language: Optional[str] = None,
    model_size: str = "base",
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
) -> str:
    """Module-level convenience wrapper around :meth:`WhisperTranscriber.transcribe_to_srt`.

    Uses a shared global :class:`WhisperTranscriber` instance so models are
    cached across calls within the same process.

    Args:
        audio_path:  Path to the audio file.
        output_path: Destination path for the ``.srt`` file.
        language:    BCP-47 language code or ``None`` for auto-detect.
        model_size:  Whisper model size (default ``"base"``).
        device:      Inference device (auto-detected if ``None``).
        compute_type: Quantisation type (derived from *device* if ``None``).

    Returns:
        Absolute path to the written SRT file as a string.
    """
    return _default_transcriber.transcribe_to_srt(
        audio_path=audio_path,
        output_path=output_path,
        language=language,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
    )


# ─── Legacy compatibility shim ────────────────────────────────────────────────

def transcribe_audio(
    audio_path: Path,
    output_srt: Path,
    language: str = "vi",
    model_name: str = "medium",
    device: str = "cpu",
    compute_type: str = "int8",
) -> Optional[Path]:
    """Legacy function — prefer :func:`transcribe_to_srt` for new code.

    Transcribe an audio file using faster-whisper and write an SRT file.

    Args:
        audio_path:   Path to the audio file (wav, mp3, m4a, etc.).
        output_srt:   Destination path for the generated SRT file.
        language:     Language code for transcription (e.g. ``"vi"``, ``"en"``).
        model_name:   Whisper model size: tiny/base/small/medium/large-v3.
        device:       Inference device: ``"cpu"`` or ``"cuda"``.
        compute_type: Quantisation type: ``"int8"``, ``"float16"``, ``"float32"``.

    Returns:
        Path to the written SRT file, or ``None`` if transcription produced
        no segments (silent audio, import error, etc.).

    Raises:
        FileNotFoundError: If *audio_path* does not exist.
    """
    output_srt = Path(output_srt)

    # Transcribe first so we can detect the "no segments" case. We must not
    # rely on transcribe_to_srt() alone, because it always writes a file (even
    # an empty one) and returns a resolved path — the legacy contract requires
    # returning None when there is nothing to transcribe.
    segments = _default_transcriber.transcribe(
        audio_path=audio_path,
        language=language,
        model_size=model_name,
        device=device,
        compute_type=compute_type,
        word_timestamps=False,
    )

    if not segments:
        return None

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    with output_srt.open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(seg.to_srt_block())
            fh.write("\n")  # blank line between blocks

    return output_srt
