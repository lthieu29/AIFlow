"""TTS provider abstraction layer.

Defines the unified interface for all TTS backends, result/error types,
and the fallback chain that tries providers in order.

Phase 3.1 — Task 3.1.1
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)

# ─── Types ────────────────────────────────────────────────────────────────────

# Two supported backends per spec 10 (Phase 3.1 scope).
# vieneu_gpu_lmdeploy / vieneu_gpu_gguf / vieneu_cpu_standard / vieneu_cpu_turbo
# are sub-variants resolved at runtime inside VieNeuProvider; the public-facing
# BackendName used for routing and audit logs uses the two top-level names.
BackendName = Literal["vieneu", "edge_tts"]


# ─── Result ───────────────────────────────────────────────────────────────────

@dataclass
class TTSResult:
    """Result of a single TTS synthesis call.

    Fed directly into G4 quality gate and Whisper transcription.
    """

    success: bool
    """Whether synthesis completed without error."""

    output_path: Path
    """Path to the written audio file (.mp3 or .wav)."""

    duration_sec: float
    """Duration measured by ffprobe after the file is written."""

    backend: str
    """Backend that produced this result — for audit log."""

    error: Optional[str] = None
    """Human-readable error message when success=False."""


# ─── Error ────────────────────────────────────────────────────────────────────

class TTSError(Exception):
    """Raised by TTS providers on synthesis failure.

    Attributes:
        message: Human-readable description of what went wrong.
        backend: Name of the backend that raised the error (optional).
    """

    def __init__(self, message: str, backend: Optional[str] = None) -> None:
        self.message = message
        self.backend = backend
        super().__init__(message)

    def __repr__(self) -> str:
        return f"TTSError(message={self.message!r}, backend={self.backend!r})"


# ─── Protocol ─────────────────────────────────────────────────────────────────

@runtime_checkable
class TTSProvider(Protocol):
    """Structural interface that all TTS backends must satisfy.

    Providers are sync wrappers; async/threading is handled internally.
    The Protocol is ``runtime_checkable`` so ``isinstance`` checks work in
    tests and the fallback chain.
    """

    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        speed: float = 1.0,
    ) -> TTSResult:
        """Synthesise *text* and write the result to *output_path*.

        Args:
            text: Narration text to synthesise.
            voice: Voice identifier (backend-specific).
            output_path: Destination file path (.mp3 recommended).
            speed: Playback speed multiplier (1.0 = native).

        Returns:
            TTSResult with success=True and a valid output_path.

        Raises:
            TTSError: On any synthesis failure.
        """
        ...

    def is_available(self) -> bool:
        """Cheap pre-flight check — import OK, device reachable, etc.

        Returns:
            True if this provider can be used right now.
        """
        ...

    def backend_name(self) -> str:
        """Human-readable backend identifier used in logs and audit records."""
        ...


# ─── Fallback chain ───────────────────────────────────────────────────────────

class FallbackChain:
    """Try providers in order and return the first successful result.

    Usage::

        chain = FallbackChain([primary_provider, fallback_provider])
        result = chain.synthesize(text, voice, output_path)

    Each attempt is logged.  If all providers fail the last ``TTSError`` is
    re-raised with a ``TTS_ALL_FAILED`` message.
    """

    def __init__(self, providers: list[TTSProvider]) -> None:
        if not providers:
            raise ValueError("FallbackChain requires at least one provider.")
        self._providers = providers

    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        speed: float = 1.0,
    ) -> TTSResult:
        """Try each provider in order; return the first success.

        Args:
            text: Narration text to synthesise.
            voice: Voice identifier passed to each provider.
            output_path: Destination file path.
            speed: Playback speed multiplier.

        Returns:
            TTSResult from the first provider that succeeds.

        Raises:
            TTSError: When every provider in the chain has failed.
        """
        last_error: Optional[TTSError] = None

        for provider in self._providers:
            name = provider.backend_name()

            if not provider.is_available():
                log.warning("[tts:chain] %s unavailable — skipping", name)
                continue

            log.info("[tts:chain] attempting %s", name)
            try:
                result = provider.synthesize(text, voice, output_path, speed)
                log.info(
                    "[tts:chain] %s succeeded — duration=%.2fs",
                    name,
                    result.duration_sec,
                )
                return result
            except TTSError as exc:
                log.warning(
                    "[tts:chain] %s failed: %s — trying next provider",
                    name,
                    exc.message,
                )
                last_error = exc

        raise TTSError(
            message=(
                "All TTS providers failed. "
                f"Last error: {last_error.message if last_error else 'unknown'}"
            ),
            backend=last_error.backend if last_error else None,
        )
