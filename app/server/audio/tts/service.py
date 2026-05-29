"""TTSService — orchestrator for TTS provider selection and fallback.

Loads provider preference from settings, builds a provider chain (primary →
fallback), and delegates synthesis to the first available provider.

Phase 3.1 — Task 3.1.3

Notes:
    - Phase 3.1 only ships EdgeProvider.  VieNeuProvider is added in Phase 3.2.
    - If ``settings.tts.primary == "vieneu"`` but VieNeuProvider is not yet
      available (import fails), the chain silently falls back to EdgeProvider.
    - All synthesis attempts are audit-logged via loguru.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from loguru import logger

from server.audio.tts import FallbackChain, TTSError, TTSProvider, TTSResult
from server.audio.tts.edge_provider import EdgeProvider
from server.config import Settings


# ─── Provider chain builder ───────────────────────────────────────────────────


def build_provider_chain(settings: Settings) -> list[TTSProvider]:
    """Build an ordered list of TTS providers based on *settings*.

    The list is ordered primary-first.  Providers that cannot be imported
    (e.g. VieNeuProvider in Phase 3.1) are silently omitted so the chain
    always contains at least EdgeProvider.

    Args:
        settings: Loaded application settings.

    Returns:
        Non-empty list of ``TTSProvider`` instances.
    """
    primary = settings.tts.primary  # "vieneu" | "edge_tts"

    edge = EdgeProvider()

    # Try to import VieNeuProvider — only available from Phase 3.2 onward.
    vieneu: Optional[TTSProvider] = None
    try:
        from server.audio.tts.vieneu_provider import VieNeuProvider  # type: ignore[import]
        vieneu = VieNeuProvider(settings)
        logger.debug("[tts:chain] VieNeuProvider loaded")
    except ImportError:
        logger.debug("[tts:chain] VieNeuProvider not available (Phase 3.1) — edge_tts only")

    if primary == "vieneu":
        if vieneu is not None:
            return [vieneu, edge]
        # VieNeu not available yet — fall back to edge only
        logger.info(
            "[tts:chain] primary=vieneu but VieNeuProvider unavailable; "
            "using edge_tts as sole provider"
        )
        return [edge]

    if primary == "edge_tts":
        if vieneu is not None:
            return [edge, vieneu]
        return [edge]

    # Unknown primary — default to edge
    logger.warning("[tts:chain] Unknown primary=%r; defaulting to edge_tts", primary)
    return [edge]


# ─── TTSService ───────────────────────────────────────────────────────────────


class TTSService:
    """Orchestrates TTS provider selection and fallback.

    Usage::

        service = TTSService(settings)
        result = service.synthesize("Xin chào thế giới")

    The service is stateless between calls — it holds no open model handles in
    Phase 3.1.  Phase 3.2 will add ``close()`` for VieNeu model teardown.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._providers = build_provider_chain(settings)
        self._chain = FallbackChain(self._providers)
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
        """Synthesise *text* using the configured provider chain.

        Tries the primary provider first; falls back to subsequent providers on
        failure.  Every attempt is audit-logged.

        Args:
            text: Narration text to synthesise.
            voice: Voice identifier.  If ``None``, the configured default voice
                   for the primary backend is used.
            output_path: Destination ``.mp3`` file.  If ``None``, a unique temp
                         path under ``storage/audio/`` is generated.
            speed: Playback speed multiplier (1.0 = native).

        Returns:
            ``TTSResult`` from the first provider that succeeds.

        Raises:
            TTSError: When every provider in the chain has failed.
        """
        resolved_voice = voice if voice is not None else self.get_default_voice()
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
            result = self._chain.synthesize(
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
        primary = self._settings.tts.primary
        if primary == "vieneu":
            return self._settings.tts.vieneu_default_voice
        return self._settings.tts.edge_default_voice

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _temp_path(self) -> Path:
        """Generate a unique temp path under ``storage/audio/``."""
        audio_dir = self._settings.data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        return audio_dir / f"tts_{uuid.uuid4().hex}.mp3"
