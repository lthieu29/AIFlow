"""Unit tests for server/audio/transcribe.py.

Tests cover:
- SRTSegment dataclass and SRT block rendering
- _format_timestamp helper
- WhisperTranscriber model validation and error handling
- Module-level convenience functions
- Legacy transcribe_audio shim

Phase 3 / Task 3.3.1
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from server.audio.transcribe import (
    SUPPORTED_MODELS,
    SRTSegment,
    _format_timestamp,
    transcribe,
    transcribe_audio,
    transcribe_to_srt,
)

# ─── _format_timestamp ────────────────────────────────────────────────────────

class TestFormatTimestamp:
    def test_zero(self):
        assert _format_timestamp(0.0) == "00:00:00,000"

    def test_one_second(self):
        assert _format_timestamp(1.0) == "00:00:01,000"

    def test_one_minute(self):
        assert _format_timestamp(60.0) == "00:01:00,000"

    def test_one_hour(self):
        assert _format_timestamp(3600.0) == "01:00:00,000"

    def test_fractional_millis(self):
        assert _format_timestamp(1.5) == "00:00:01,500"

    def test_millis_rounding(self):
        # 1.9999 should not overflow to ,1000
        result = _format_timestamp(1.9999)
        assert result.endswith(",999") or result.endswith(",000")

    def test_complex_time(self):
        # 1h 2m 3.456s
        assert _format_timestamp(3723.456) == "01:02:03,456"

    def test_format_structure(self):
        ts = _format_timestamp(65.123)
        parts = ts.split(",")
        assert len(parts) == 2
        hms = parts[0].split(":")
        assert len(hms) == 3


# ─── SRTSegment ───────────────────────────────────────────────────────────────

class TestSRTSegment:
    def test_basic_fields(self):
        seg = SRTSegment(index=1, start_time=0.0, end_time=2.5, text="Hello world")
        assert seg.index == 1
        assert seg.start_time == 0.0
        assert seg.end_time == 2.5
        assert seg.text == "Hello world"

    def test_to_srt_block_format(self):
        seg = SRTSegment(index=1, start_time=1.0, end_time=3.5, text="Test subtitle")
        block = seg.to_srt_block()
        lines = block.strip().splitlines()
        assert lines[0] == "1"
        assert "-->" in lines[1]
        assert lines[2] == "Test subtitle"

    def test_to_srt_block_timestamps(self):
        seg = SRTSegment(index=2, start_time=0.0, end_time=1.0, text="Hi")
        block = seg.to_srt_block()
        assert "00:00:00,000 --> 00:00:01,000" in block

    def test_to_srt_block_index(self):
        seg = SRTSegment(index=42, start_time=0.0, end_time=1.0, text="X")
        block = seg.to_srt_block()
        assert block.startswith("42\n")

    def test_to_srt_block_ends_with_newline(self):
        seg = SRTSegment(index=1, start_time=0.0, end_time=1.0, text="X")
        assert seg.to_srt_block().endswith("\n")

    def test_multiple_segments_srt_output(self):
        segments = [
            SRTSegment(index=1, start_time=0.0, end_time=1.0, text="First"),
            SRTSegment(index=2, start_time=1.5, end_time=3.0, text="Second"),
        ]
        srt = "\n".join(seg.to_srt_block() for seg in segments)
        assert "First" in srt
        assert "Second" in srt
        assert "1\n" in srt
        assert "2\n" in srt


# ─── SUPPORTED_MODELS ─────────────────────────────────────────────────────────

class TestSupportedModels:
    def test_contains_expected_sizes(self):
        for size in ("tiny", "base", "small", "medium", "large-v2", "large-v3"):
            assert size in SUPPORTED_MODELS

    def test_is_tuple(self):
        assert isinstance(SUPPORTED_MODELS, tuple)


# Local inference is intentionally disabled, even if a model was cached.
@pytest.mark.parametrize("entrypoint", ["class", "module", "srt", "legacy"])
@pytest.mark.parametrize("exists", [False, True])
def test_local_transcription_never_executes_model(tmp_path, monkeypatch, entrypoint, exists):
    from server.audio import transcribe as module
    model = MagicMock()
    monkeypatch.setattr(module._default_transcriber, "_model_cache", {"base:cpu:int8": model})
    audio, output = tmp_path / "audio.wav", tmp_path / "subtitles.srt"
    if exists:
        audio.write_bytes(b"audio")
    with pytest.raises(RuntimeError, match="STT local"):
        if entrypoint == "class":
            module._default_transcriber.transcribe(audio)
        elif entrypoint == "module":
            transcribe(audio)
        elif entrypoint == "srt":
            transcribe_to_srt(audio, output)
        else:
            transcribe_audio(audio, output)
    model.transcribe.assert_not_called()
    assert not output.exists()


@pytest.fixture
def remote_stt(tmp_path, monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace

    import httpx

    from server.production import transcribe as module
    content = {"segments": [{"start": 0.0, "end": 1.0, "text": "Hello world"}]}
    raw = json.dumps(content).encode()
    state = {"generation": 1, "raw": raw, "checksum": hashlib.sha256(raw).hexdigest(), "status": "succeeded", "calls": []}
    connection = SimpleNamespace(snapshot=lambda: ("https://test.trycloudflare.com", "test-only", state["generation"], {"capabilities": ["stt"], "stt_revision": "test-revision"}))
    monkeypatch.setattr(module, "connection", connection)
    def request(url, token, method, path, **kwargs):
        state["calls"].append((method, path, kwargs))
        return {"status": state["status"], "checksum": state["checksum"]}
    monkeypatch.setattr(module, "request", request)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=state["raw"]))
    client_type = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: client_type(transport=transport))
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fixture audio; network/model calls mocked")
    return module, audio, state


def test_remote_stt_submits_language_and_reuses_verified_cache(remote_stt, tmp_path):
    module, audio, state = remote_stt
    first = module.transcribe(audio, "vi", tmp_path, lambda: None)
    assert first[0]["text"] == "Hello world"
    assert state["calls"][0][2]["data"]["language"] == "vi"
    assert "Idempotency-Key" in state["calls"][0][2]["headers"]
    assert module.transcribe(audio, "vi", tmp_path, lambda: None) == first
    assert len(state["calls"]) == 1


def test_remote_stt_checksum_mismatch_cancels(remote_stt, tmp_path):
    module, audio, state = remote_stt
    state["checksum"] = "wrong"
    with pytest.raises(ValueError, match="Checksum"):
        module.transcribe(audio, "en", tmp_path, lambda: None)
    assert state["calls"][-1][1].endswith("/cancel")
    assert not list(tmp_path.rglob("transcripts/*.json"))


def test_remote_stt_corrupted_cache_is_rejected(remote_stt, tmp_path):
    module, audio, state = remote_stt
    module.transcribe(audio, "en", tmp_path, lambda: None)
    cache = next((tmp_path / "audio" / "transcripts").glob("*.json"))
    cache.write_text('{"content":{"segments":[]},"checksum":"wrong"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Cache STT"):
        module.transcribe(audio, "en", tmp_path, lambda: None)
    assert len(state["calls"]) == 1


def test_remote_stt_session_change_blocks_cache_use(remote_stt, tmp_path):
    module, audio, state = remote_stt
    module.transcribe(audio, "en", tmp_path, lambda: None)
    def checkpoint():
        state["generation"] += 1
    with pytest.raises(ValueError, match="Colab"):
        module.transcribe(audio, "en", tmp_path, checkpoint)


@pytest.mark.parametrize("status", ["failed", "cancelled", "interrupted"])
def test_remote_stt_failed_jobs_never_return_segments(remote_stt, tmp_path, status):
    module, audio, state = remote_stt
    state["status"] = status
    with pytest.raises(ValueError, match="Colab"):
        module.transcribe(audio, "en", tmp_path, lambda: None)
    assert state["calls"][-1][1].endswith("/cancel")
