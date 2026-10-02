"""Compatibility facade for remote TTS. There is no local or paid fallback."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from loguru import logger

from server.audio.tts import TTSError, TTSProvider, TTSResult
from server.config import Settings


# ─── Provider chain builder ───────────────────────────────────────────────────


def build_provider_chain(settings: Settings) -> list[TTSProvider]:
    """Remote inference only. An unavailable worker must never trigger a local fallback."""
    from server.audio.remote import RemoteProvider

    return [RemoteProvider(settings)]


# ─── TTSService ───────────────────────────────────────────────────────────────


class TTSService:
    """Keep the existing synchronous API while delegating to remote inference and cache."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._providers = build_provider_chain(settings)
        logger.info(
            "[tts:service] initialized — primary=%s providers=[%s]",
            settings.tts.primary,
            ", ".join(p.backend_name() for p in self._providers),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        output_path: Optional[Path] = None,
        speed: float = 1.0,
    ) -> TTSResult:
        """Synthesise *text* using remote audio, with no fallback provider.

        Args:
            text: Narration text to synthesise.
            voice: Voice identifier.  If ``None``, the configured default voice
                   for the primary backend is used.
            output_path: Destination WAV file. If ``None``, a unique temp
                         path under ``storage/audio/`` is generated.
            speed: Playback speed multiplier (1.0 = native).

        Returns:
            ``TTSResult`` for the verified local audio file.

        Raises:
            TTSError: When the worker/input is unavailable or generation fails.
        """
        resolved_voice = voice or self.get_default_voice()
        resolved_path = output_path if output_path is not None else self._temp_path()

        audit_id = uuid.uuid4().hex[:8]
        logger.info(
            "[tts:audit:%s] synthesize — voice=%s speed=%.2f path=%s",
            audit_id,
            resolved_voice,
            speed,
            resolved_path,
        )

        try:
            result = self._providers[0].synthesize(
                text=text,
                voice=resolved_voice,
                output_path=resolved_path,
                speed=speed,
            )
            logger.info(
                "[tts:audit:%s] success — backend=%s duration=%.2fs",
                audit_id,
                result.backend,
                result.duration_sec,
            )
            return result
        except TTSError as exc:
            logger.error(
                "[tts:audit:%s] all providers failed — last_backend=%s error=%s",
                audit_id,
                exc.backend,
                exc.message,
            )
            raise

    def get_default_voice(self) -> str:
        """Return the configured default voice for the primary backend.

        Returns:
            Voice identifier string (e.g. ``"vi-VN-HoaiMyNeural"``).
        """
        return self._settings.tts.remote_default_voice

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _temp_path(self) -> Path:
        """Generate a unique temp path under ``storage/audio/``."""
        audio_dir = self._settings.data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir / f"tts_{uuid.uuid4().hex}.wav"
