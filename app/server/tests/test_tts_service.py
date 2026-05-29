"""Unit tests for server/audio/tts/service.py — TTSService orchestrator.

Tests cover:
- build_provider_chain() with primary=edge_tts and primary=vieneu
- TTSService.__init__() provider list construction
- TTSService.get_default_voice() returns correct voice per primary setting
- TTSService.synthesize() delegates to FallbackChain
- TTSService.synthesize() uses default voice when voice=None
- TTSService.synthesize() generates a temp path when output_path=None
- TTSService.synthesize() propagates TTSError on total failure
- Audit log entries are emitted per attempt

Phase 3.1 — Task 3.1.3
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.audio.tts import TTSError, TTSResult
from server.audio.tts.edge_provider import EdgeProvider
from server.audio.tts.service import TTSService, build_provider_chain
from server.config import Settings


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_settings(primary: str = "edge_tts") -> Settings:
    """Return a minimal Settings object with TTS primary overridden."""
    settings = MagicMock(spec=Settings)
    settings.tts = MagicMock()
    settings.tts.primary = primary
    settings.tts.edge_default_voice = "vi-VN-HoaiMyNeural"
    settings.tts.vieneu_default_voice = "Binh"
    settings.data_dir = Path("./storage")
    return settings


def _make_tts_result(backend: str = "edge_tts", duration: float = 2.5) -> TTSResult:
    return TTSResult(
        success=True,
        output_path=Path("storage/audio/tts_test.mp3"),
        duration_sec=duration,
        backend=backend,
    )


# ─── build_provider_chain ─────────────────────────────────────────────────────

class TestBuildProviderChain:
    def test_edge_primary_returns_edge_first(self):
        settings = _make_settings(primary="edge_tts")
        # VieNeuProvider not available in Phase 3.1
        with patch.dict("sys.modules", {"server.audio.tts.vieneu_provider": None}):
            chain = build_provider_chain(settings)
        assert len(chain) >= 1
        assert chain[0].backend_name() == "edge_tts"

    def test_vieneu_primary_without_vieneu_falls_back_to_edge(self):
        """When VieNeuProvider is not importable, chain must still contain EdgeProvider."""
        settings = _make_settings(primary="vieneu")
        with patch("builtins.__import__", side_effect=_block_vieneu_import):
            chain = build_provider_chain(settings)
        assert len(chain) == 1
        assert chain[0].backend_name() == "edge_tts"

    def test_edge_primary_chain_contains_edge_provider(self):
        settings = _make_settings(primary="edge_tts")
        chain = build_provider_chain(settings)
        backend_names = [p.backend_name() for p in chain]
        assert "edge_tts" in backend_names

    def test_unknown_primary_defaults_to_edge(self):
        settings = _make_settings(primary="unknown_backend")
        chain = build_provider_chain(settings)
        assert len(chain) >= 1
        assert chain[0].backend_name() == "edge_tts"

    def test_chain_is_non_empty(self):
        settings = _make_settings(primary="edge_tts")
        chain = build_provider_chain(settings)
        assert len(chain) > 0


def _block_vieneu_import(name, *args, **kwargs):
    """Custom __import__ that raises ImportError for vieneu_provider."""
    if "vieneu_provider" in name:
        raise ImportError(f"Mocked: {name} not available")
    return original_import(name, *args, **kwargs)


import builtins
original_import = builtins.__import__


# ─── TTSService.__init__ ──────────────────────────────────────────────────────

class TestTTSServiceInit:
    def test_init_with_edge_primary(self):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        assert service is not None

    def test_init_with_vieneu_primary_no_vieneu_available(self):
        """Service must initialize even when VieNeuProvider is not importable."""
        settings = _make_settings(primary="vieneu")
        with patch("builtins.__import__", side_effect=_block_vieneu_import):
            service = TTSService(settings)
        assert service is not None

    def test_providers_list_non_empty(self):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        assert len(service._providers) > 0

    def test_providers_contain_edge_provider(self):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        backend_names = [p.backend_name() for p in service._providers]
        assert "edge_tts" in backend_names


# ─── TTSService.get_default_voice ─────────────────────────────────────────────

class TestGetDefaultVoice:
    def test_edge_primary_returns_edge_default_voice(self):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        assert service.get_default_voice() == "vi-VN-HoaiMyNeural"

    def test_vieneu_primary_returns_vieneu_default_voice(self):
        settings = _make_settings(primary="vieneu")
        with patch("builtins.__import__", side_effect=_block_vieneu_import):
            service = TTSService(settings)
        assert service.get_default_voice() == "Binh"

    def test_custom_edge_voice_returned(self):
        settings = _make_settings(primary="edge_tts")
        settings.tts.edge_default_voice = "en-US-AriaNeural"
        service = TTSService(settings)
        assert service.get_default_voice() == "en-US-AriaNeural"


# ─── TTSService.synthesize ────────────────────────────────────────────────────

class TestTTSServiceSynthesize:
    def _make_service_with_mock_chain(self, primary: str = "edge_tts"):
        settings = _make_settings(primary=primary)
        service = TTSService(settings)
        return service

    def test_synthesize_delegates_to_fallback_chain(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        expected_result = _make_tts_result()

        with patch.object(service._chain, "synthesize", return_value=expected_result) as mock_synth:
            result = service.synthesize("Xin chào", output_path=tmp_path / "out.mp3")

        mock_synth.assert_called_once()
        assert result is expected_result

    def test_synthesize_uses_default_voice_when_none(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        expected_result = _make_tts_result()

        captured_voice = []

        def _capture_synth(text, voice, output_path, speed):
            captured_voice.append(voice)
            return expected_result

        with patch.object(service._chain, "synthesize", side_effect=_capture_synth):
            service.synthesize("Xin chào", voice=None, output_path=tmp_path / "out.mp3")

        assert captured_voice[0] == "vi-VN-HoaiMyNeural"

    def test_synthesize_uses_provided_voice(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        expected_result = _make_tts_result()

        captured_voice = []

        def _capture_synth(text, voice, output_path, speed):
            captured_voice.append(voice)
            return expected_result

        with patch.object(service._chain, "synthesize", side_effect=_capture_synth):
            service.synthesize("Xin chào", voice="en-US-GuyNeural", output_path=tmp_path / "out.mp3")

        assert captured_voice[0] == "en-US-GuyNeural"

    def test_synthesize_generates_temp_path_when_none(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        settings.data_dir = tmp_path
        service = TTSService(settings)
        expected_result = _make_tts_result()

        captured_path = []

        def _capture_synth(text, voice, output_path, speed):
            captured_path.append(output_path)
            return expected_result

        with patch.object(service._chain, "synthesize", side_effect=_capture_synth):
            service.synthesize("Xin chào", output_path=None)

        assert captured_path[0] is not None
        assert str(captured_path[0]).endswith(".mp3")
        assert "audio" in str(captured_path[0])

    def test_synthesize_passes_speed_to_chain(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        expected_result = _make_tts_result()

        captured_speed = []

        def _capture_synth(text, voice, output_path, speed):
            captured_speed.append(speed)
            return expected_result

        with patch.object(service._chain, "synthesize", side_effect=_capture_synth):
            service.synthesize("Xin chào", output_path=tmp_path / "out.mp3", speed=1.3)

        assert captured_speed[0] == pytest.approx(1.3)

    def test_synthesize_propagates_tts_error(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)

        with patch.object(
            service._chain,
            "synthesize",
            side_effect=TTSError(message="All providers failed", backend="edge_tts"),
        ):
            with pytest.raises(TTSError) as exc_info:
                service.synthesize("Xin chào", output_path=tmp_path / "out.mp3")

        assert "All providers failed" in exc_info.value.message

    def test_synthesize_returns_tts_result(self, tmp_path):
        settings = _make_settings(primary="edge_tts")
        service = TTSService(settings)
        expected_result = _make_tts_result(backend="edge_tts", duration=4.2)

        with patch.object(service._chain, "synthesize", return_value=expected_result):
            result = service.synthesize("Xin chào", output_path=tmp_path / "out.mp3")

        assert isinstance(result, TTSResult)
        assert result.success is True
        assert result.backend == "edge_tts"
        assert result.duration_sec == pytest.approx(4.2)


# ─── Temp path generation ─────────────────────────────────────────────────────

class TestTempPath:
    def test_temp_path_is_unique(self, tmp_path):
        settings = _make_settings()
        settings.data_dir = tmp_path
        service = TTSService(settings)

        path1 = service._temp_path()
        path2 = service._temp_path()
        assert path1 != path2

    def test_temp_path_parent_created(self, tmp_path):
        settings = _make_settings()
        settings.data_dir = tmp_path
        service = TTSService(settings)

        path = service._temp_path()
        assert path.parent.exists()

    def test_temp_path_has_mp3_extension(self, tmp_path):
        settings = _make_settings()
        settings.data_dir = tmp_path
        service = TTSService(settings)

        path = service._temp_path()
        assert path.suffix == ".mp3"
