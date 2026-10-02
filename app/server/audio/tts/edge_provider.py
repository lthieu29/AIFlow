"""EdgeProvider — Microsoft Edge TTS backend (online fallback).

Uses the ``edge_tts`` library (async) wrapped in a synchronous interface
to satisfy the ``TTSProvider`` Protocol defined in ``server/audio/tts/__init__.py``.

Output format: MP3 192kbps mono 24kHz (AIFlow standard per spec 10).

Phase 3.1 — Task 3.1.2
"""

import asyncio
import logging
import socket
from pathlib import Path

from server.audio.tts import TTSError, TTSProvider, TTSResult  # noqa: F401 (Protocol)
from server.audio.ffmpeg_utils import probe_duration, run_ffmpeg

log = logging.getLogger(__name__)

# ─── Voice catalog ────────────────────────────────────────────────────────────

# Vietnamese voices + a few bilingual options useful for AIFlow narration.
EDGE_VOICES: dict[str, str] = {
    "vi-VN-HoaiMyNeural": "Nữ, ấm, neutral — default",
    "vi-VN-NamMinhNeural": "Nam, trẻ, năng lượng",
    "en-US-AriaNeural": "Nữ EN — narration bilingual",
    "en-US-GuyNeural": "Nam EN",
}

DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

# ─── Availability helpers ─────────────────────────────────────────────────────

def _edge_tts_importable() -> bool:
    """Return True if the ``edge_tts`` package can be imported."""
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def _network_reachable(host: str = "speech.platform.bing.com", port: int = 443, timeout: float = 2.0) -> bool:
    """Quick TCP probe to check whether the Edge TTS endpoint is reachable."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ─── Rate conversion ──────────────────────────────────────────────────────────

def _speed_to_rate(speed: float) -> str:
    """Convert a speed multiplier to the SSML ``rate`` percent string.

    Examples:
        1.0  → "+0%"
        1.2  → "+20%"
        0.8  → "-20%"
    """
    pct = round((speed - 1.0) * 100)
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct}%"


# ─── EdgeProvider ─────────────────────────────────────────────────────────────

class EdgeProvider:
    """Synchronous wrapper around the async ``edge_tts`` library.

    Implements the ``TTSProvider`` Protocol (sync interface).  All async
    operations are executed via ``asyncio.run()`` so callers don't need to
    manage an event loop.
    """

    # ── Protocol methods ──────────────────────────────────────────────────────

    def backend_name(self) -> str:
        return "edge_tts"

    def is_available(self) -> bool:
        """Return True when edge_tts is installed AND the network is reachable."""
        if not _edge_tts_importable():
            log.debug("[edge_tts] package not importable")
            return False
        if not _network_reachable():
            log.debug("[edge_tts] network not reachable")
            return False
        return True

    def synthesize(
        self,
        text: str,
        voice: str,
        output_path: Path,
        speed: float = 1.0,
    ) -> TTSResult:
        """Synthesise *text* with Edge TTS and write an MP3 to *output_path*.

        The output is re-encoded by ffmpeg to ensure 192kbps mono 24kHz MP3
        regardless of what edge_tts produces natively.

        Args:
            text: Narration text to synthesise.
            voice: Edge TTS voice identifier (e.g. ``"vi-VN-HoaiMyNeural"``).
                   Falls back to ``DEFAULT_VOICE`` if empty.
            output_path: Destination ``.mp3`` file path.
            speed: Playback speed multiplier (1.0 = native).

        Returns:
            TTSResult with success=True, output_path, duration_sec, backend.

        Raises:
            TTSError: On any synthesis or encoding failure.
        """
        if not text.strip():
            raise TTSError(message="Empty text provided to EdgeProvider", backend="edge_tts")

        resolved_voice = voice.strip() if voice.strip() else DEFAULT_VOICE

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        rate = _speed_to_rate(speed)
        log.info("[edge_tts] synthesize voice=%s rate=%s → %s", resolved_voice, rate, output_path)

        # edge_tts saves directly to a file path; we use a temp path so we can
        # re-encode to the AIFlow standard format afterwards.
        raw_path = output_path.with_suffix(".edge_raw.mp3")

        try:
            asyncio.run(self._async_synthesize(text, resolved_voice, rate, raw_path))
        except Exception as exc:
            raw_path.unlink(missing_ok=True)
            raise TTSError(
                message=f"edge_tts synthesis failed: {exc}",
                backend="edge_tts",
            ) from exc

        # Validate raw output
        if not raw_path.exists() or raw_path.stat().st_size < 512:
            raw_path.unlink(missing_ok=True)
            raise TTSError(
                message="edge_tts returned empty or too-small audio file",
                backend="edge_tts",
            )

        # Re-encode to AIFlow standard: MP3 192kbps mono 24kHz
        try:
            run_ffmpeg([
                "-y",
                "-i", str(raw_path),
                "-codec:a", "libmp3lame",
                "-b:a", "192k",
                "-ac", "1",
                "-ar", "24000",
                str(output_path),
            ])
        except Exception as exc:
            raise TTSError(
                message=f"ffmpeg re-encode failed: {exc}",
                backend="edge_tts",
            ) from exc
        finally:
            raw_path.unlink(missing_ok=True)

        if not output_path.exists() or output_path.stat().st_size < 512:
            raise TTSError(
                message=f"Output file invalid after encoding: {output_path}",
                backend="edge_tts",
            )

        try:
            duration_sec = probe_duration(output_path)
        except Exception as exc:
            raise TTSError(
                message=f"ffprobe duration check failed: {exc}",
                backend="edge_tts",
            ) from exc

        log.info("[edge_tts] done — duration=%.2fs path=%s", duration_sec, output_path)

        return TTSResult(
            success=True,
            output_path=output_path,
            duration_sec=duration_sec,
            backend="edge_tts",
        )

    # ── Internal async helper ─────────────────────────────────────────────────

    @staticmethod
    async def _async_synthesize(text: str, voice: str, rate: str, output_path: Path) -> None:
        """Run the edge_tts async API and save audio to *output_path*.

        Raises:
            ImportError: If edge_tts is not installed.
            edge_tts.exceptions.NoAudioReceived: If Microsoft returns no audio.
            Exception: On any other network or API error.
        """
        import edge_tts  # imported here so the module loads even without edge_tts

        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        await communicate.save(str(output_path))
