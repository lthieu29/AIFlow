"""Unit tests for server/audio/tts/edge_provider.py.

Tests cover:
- Protocol compliance (EdgeProvider satisfies TTSProvider)
- is_available() logic (import check + network check)
- _speed_to_rate() conversion
- synthesize() happy path (mocked edge_tts + ffmpeg)
- synthesize() error paths (empty text, network failure, empty output)

Phase 3.1 — Task 3.1.2
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.audio.tts import TTSError, TTSProvider, TTSResult
from server.audio.tts.edge_provider import (
    DEFAULT_VOICE,
    EDGE_VOICES,
    EdgeProvider,
    _speed_to_rate,
)


# ─── Protocol compliance ──────────────────────────────────────────────────────

def test_edge_provider_satisfies_tts_provider_protocol():
    """EdgeProvider must be an instance of the TTSProvider Protocol."""
    provider = EdgeProvider()
    assert isinstance(provider, TTSProvider)


def test_backend_name_returns_edge_tts():
    provider = EdgeProvider()
    assert provider.backend_name() == "edge_tts"


# ─── _speed_to_rate ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("speed,expected", [
    (1.0, "+0%"),
    (1.2, "+20%"),
    (0.8, "-20%"),
    (1.5, "+50%"),
    (0.5, "-50%"),
])
def test_speed_to_rate_conversion(speed, expected):
    assert _speed_to_rate(speed) == expected


# ─── is_available ─────────────────────────────────────────────────────────────

def test_is_available_false_when_edge_tts_not_importable():
    provider = EdgeProvider()
    with patch("server.audio.tts.edge_provider._edge_tts_importable", return_value=False):
        assert provider.is_available() is False


def test_is_available_false_when_network_unreachable():
    provider = EdgeProvider()
    with patch("server.audio.tts.edge_provider._edge_tts_importable", return_value=True), \
         patch("server.audio.tts.edge_provider._network_reachable", return_value=False):
        assert provider.is_available() is False


def test_is_available_true_when_both_checks_pass():
    provider = EdgeProvider()
    with patch("server.audio.tts.edge_provider._edge_tts_importable", return_value=True), \
         patch("server.audio.tts.edge_provider._network_reachable", return_value=True):
        assert provider.is_available() is True


# ─── synthesize — error paths ─────────────────────────────────────────────────

def test_synthesize_raises_on_empty_text(tmp_path):
    provider = EdgeProvider()
    with pytest.raises(TTSError) as exc_info:
        provider.synthesize("", "vi-VN-HoaiMyNeural", tmp_path / "out.mp3")
    assert exc_info.value.backend == "edge_tts"
    assert "empty" in exc_info.value.message.lower()


def test_synthesize_raises_on_whitespace_only_text(tmp_path):
    provider = EdgeProvider()
    with pytest.raises(TTSError):
        provider.synthesize("   \n\t  ", "vi-VN-HoaiMyNeural", tmp_path / "out.mp3")


def test_synthesize_raises_when_async_fails(tmp_path):
    """If edge_tts raises during async synthesis, TTSError must be raised."""
    provider = EdgeProvider()
    output_path = tmp_path / "out.mp3"

    with patch.object(
        EdgeProvider,
        "_async_synthesize",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network error"),
    ):
        with pytest.raises(TTSError) as exc_info:
            provider.synthesize("Hello world", "vi-VN-HoaiMyNeural", output_path)
        assert exc_info.value.backend == "edge_tts"
        assert "network error" in exc_info.value.message


def test_synthesize_raises_when_raw_file_empty(tmp_path):
    """If edge_tts writes an empty file, TTSError must be raised."""
    provider = EdgeProvider()
    output_path = tmp_path / "out.mp3"

    async def _fake_synthesize(text, voice, rate, path):
        # Write an empty file to simulate edge_tts returning nothing
        Path(path).write_bytes(b"")

    with patch.object(EdgeProvider, "_async_synthesize", new=_fake_synthesize):
        with pytest.raises(TTSError) as exc_info:
            provider.synthesize("Hello world", "vi-VN-HoaiMyNeural", output_path)
        assert exc_info.value.backend == "edge_tts"


# ─── synthesize — happy path ──────────────────────────────────────────────────

def test_synthesize_happy_path(tmp_path):
    """synthesize() must return TTSResult with success=True and correct fields."""
    provider = EdgeProvider()
    output_path = tmp_path / "out.mp3"

    # Fake raw audio bytes (>512 bytes to pass size check)
    fake_audio = b"\xff\xfb" + b"\x00" * 600

    # _async_synthesize is a staticmethod; patch.object replaces it on the class.
    # When called as self._async_synthesize(...), Python does NOT pass self for
    # staticmethods, so the replacement function must match the original signature.
    async def _fake_synthesize(text, voice, rate, path):
        Path(path).write_bytes(fake_audio)

    with patch.object(EdgeProvider, "_async_synthesize", staticmethod(_fake_synthesize)), \
         patch("server.audio.tts.edge_provider.run_ffmpeg") as mock_ffmpeg, \
         patch("server.audio.tts.edge_provider.probe_duration", return_value=3.5):

        def _fake_ffmpeg(args, **kwargs):
            Path(args[-1]).write_bytes(fake_audio)

        mock_ffmpeg.side_effect = _fake_ffmpeg

        result = provider.synthesize("Xin chào thế giới", "vi-VN-HoaiMyNeural", output_path)

    assert isinstance(result, TTSResult)
    assert result.success is True
    assert result.backend == "edge_tts"
    assert result.output_path == output_path
    assert result.duration_sec == pytest.approx(3.5)
    assert result.error is None


def test_synthesize_uses_default_voice_when_empty(tmp_path):
    """Empty voice string must fall back to DEFAULT_VOICE."""
    provider = EdgeProvider()
    output_path = tmp_path / "out.mp3"
    fake_audio = b"\xff\xfb" + b"\x00" * 600

    captured_voice = []

    async def _fake_synthesize(text, voice, rate, path):
        captured_voice.append(voice)
        Path(path).write_bytes(fake_audio)

    with patch.object(EdgeProvider, "_async_synthesize", staticmethod(_fake_synthesize)), \
         patch("server.audio.tts.edge_provider.run_ffmpeg") as mock_ffmpeg, \
         patch("server.audio.tts.edge_provider.probe_duration", return_value=2.0):

        def _fake_ffmpeg(args, **kwargs):
            Path(args[-1]).write_bytes(fake_audio)

        mock_ffmpeg.side_effect = _fake_ffmpeg

        provider.synthesize("Xin chào", "", output_path)

    assert captured_voice[0] == DEFAULT_VOICE


def test_synthesize_passes_rate_to_async(tmp_path):
    """Speed multiplier must be converted to SSML rate and passed to edge_tts."""
    provider = EdgeProvider()
    output_path = tmp_path / "out.mp3"
    fake_audio = b"\xff\xfb" + b"\x00" * 600

    captured_rate = []

    async def _fake_synthesize(text, voice, rate, path):
        captured_rate.append(rate)
        Path(path).write_bytes(fake_audio)

    with patch.object(EdgeProvider, "_async_synthesize", staticmethod(_fake_synthesize)), \
         patch("server.audio.tts.edge_provider.run_ffmpeg") as mock_ffmpeg, \
         patch("server.audio.tts.edge_provider.probe_duration", return_value=2.0):

        def _fake_ffmpeg(args, **kwargs):
            Path(args[-1]).write_bytes(fake_audio)

        mock_ffmpeg.side_effect = _fake_ffmpeg

        provider.synthesize("Xin chào", "vi-VN-HoaiMyNeural", output_path, speed=1.2)

    assert captured_rate[0] == "+20%"


def test_synthesize_creates_output_directory(tmp_path):
    """synthesize() must create the output directory if it doesn't exist."""
    provider = EdgeProvider()
    nested_path = tmp_path / "deep" / "nested" / "out.mp3"
    fake_audio = b"\xff\xfb" + b"\x00" * 600

    async def _fake_synthesize(text, voice, rate, path):
        Path(path).write_bytes(fake_audio)

    with patch.object(EdgeProvider, "_async_synthesize", staticmethod(_fake_synthesize)), \
         patch("server.audio.tts.edge_provider.run_ffmpeg") as mock_ffmpeg, \
         patch("server.audio.tts.edge_provider.probe_duration", return_value=1.0):

        def _fake_ffmpeg(args, **kwargs):
            Path(args[-1]).write_bytes(fake_audio)

        mock_ffmpeg.side_effect = _fake_ffmpeg

        result = provider.synthesize("Xin chào", "vi-VN-HoaiMyNeural", nested_path)

    assert nested_path.parent.exists()


# ─── Voice catalog ────────────────────────────────────────────────────────────

def test_default_voice_is_vietnamese_female():
    assert DEFAULT_VOICE == "vi-VN-HoaiMyNeural"


def test_edge_voices_contains_vietnamese_voices():
    assert "vi-VN-HoaiMyNeural" in EDGE_VOICES
    assert "vi-VN-NamMinhNeural" in EDGE_VOICES


def test_default_voice_is_in_edge_voices():
    assert DEFAULT_VOICE in EDGE_VOICES
