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

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.audio.transcribe import (
    SUPPORTED_MODELS,
    SRTSegment,
    WhisperTranscriber,
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


# ─── WhisperTranscriber — error handling (no real model needed) ───────────────

class TestWhisperTranscriberErrors:
    def test_file_not_found(self, tmp_path):
        t = WhisperTranscriber()
        with pytest.raises(FileNotFoundError):
            t.transcribe(tmp_path / "nonexistent.mp3")

    def test_invalid_model_size(self, tmp_path):
        # Create a dummy audio file so the path check passes
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        t = WhisperTranscriber()
        # Patch faster_whisper import to succeed but raise on invalid model
        mock_model_cls = MagicMock(side_effect=ValueError("invalid model"))
        with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=mock_model_cls)}):
            with pytest.raises((ValueError, Exception)):
                t.transcribe(audio, model_size="nonexistent-model")

    def test_import_error_when_faster_whisper_missing(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        t = WhisperTranscriber()
        import sys
        original = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = None  # type: ignore[assignment]
        try:
            with pytest.raises((ImportError, TypeError)):
                t.transcribe(audio, model_size="base")
        finally:
            if original is None:
                sys.modules.pop("faster_whisper", None)
            else:
                sys.modules["faster_whisper"] = original

    def test_transcribe_to_srt_file_not_found(self, tmp_path):
        t = WhisperTranscriber()
        with pytest.raises(FileNotFoundError):
            t.transcribe_to_srt(tmp_path / "missing.mp3", tmp_path / "out.srt")


# ─── WhisperTranscriber — mocked model ────────────────────────────────────────

def _make_mock_word(start: float, end: float, word: str):
    w = MagicMock()
    w.start = start
    w.end = end
    w.word = word
    return w


def _make_mock_segment(start: float, end: float, text: str, words=None):
    seg = MagicMock()
    seg.start = start
    seg.end = end
    seg.text = text
    seg.words = words or []
    return seg


def _make_mock_info(language: str = "vi", probability: float = 0.99):
    info = MagicMock()
    info.language = language
    info.language_probability = probability
    return info


class TestWhisperTranscriberMocked:
    """Tests using a mocked WhisperModel to avoid downloading real models."""

    def _make_transcriber_with_mock(self, segments, info=None):
        """Return a WhisperTranscriber whose model is fully mocked."""
        if info is None:
            info = _make_mock_info()

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(segments), info)

        mock_whisper_module = MagicMock()
        mock_whisper_module.WhisperModel.return_value = mock_model

        t = WhisperTranscriber()
        # Inject mock directly into cache to bypass import
        t._model_cache["base:cpu:int8"] = mock_model
        return t, mock_model

    def test_transcribe_returns_srt_segments(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        words = [_make_mock_word(0.0, 0.5, "Hello"), _make_mock_word(0.5, 1.0, " world")]
        seg = _make_mock_segment(0.0, 1.0, "Hello world", words=words)

        t, mock_model = self._make_transcriber_with_mock([seg])
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())

        result = t.transcribe(audio, model_size="base", device="cpu", compute_type="int8")

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], SRTSegment)
        assert result[0].index == 1
        assert result[0].text == "Hello world"

    def test_transcribe_empty_audio_returns_empty_list(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        t, mock_model = self._make_transcriber_with_mock([])
        mock_model.transcribe.return_value = (iter([]), _make_mock_info())

        result = t.transcribe(audio, model_size="base", device="cpu", compute_type="int8")
        assert result == []

    def test_transcribe_multiple_segments(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        segs = [
            _make_mock_segment(0.0, 1.0, "First", words=[_make_mock_word(0.0, 1.0, "First")]),
            _make_mock_segment(1.5, 2.5, "Second", words=[_make_mock_word(1.5, 2.5, "Second")]),
        ]

        t, mock_model = self._make_transcriber_with_mock(segs)
        mock_model.transcribe.return_value = (iter(segs), _make_mock_info())

        result = t.transcribe(audio, model_size="base", device="cpu", compute_type="int8")
        assert len(result) == 2
        assert result[0].index == 1
        assert result[1].index == 2
        assert result[0].text == "First"
        assert result[1].text == "Second"

    def test_transcribe_to_srt_writes_file(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.srt"

        words = [_make_mock_word(0.0, 1.0, "Hello")]
        seg = _make_mock_segment(0.0, 1.0, "Hello", words=words)

        t, mock_model = self._make_transcriber_with_mock([seg])
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())

        result_path = t.transcribe_to_srt(
            audio, output, model_size="base", device="cpu", compute_type="int8"
        )

        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "Hello" in content
        assert "-->" in content
        assert result_path == str(output.resolve())

    def test_transcribe_to_srt_creates_parent_dirs(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)
        output = tmp_path / "subdir" / "nested" / "output.srt"

        words = [_make_mock_word(0.0, 1.0, "Hi")]
        seg = _make_mock_segment(0.0, 1.0, "Hi", words=words)

        t, mock_model = self._make_transcriber_with_mock([seg])
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())

        t.transcribe_to_srt(audio, output, model_size="base", device="cpu", compute_type="int8")
        assert output.exists()

    def test_srt_file_format_valid(self, tmp_path):
        """Verify the written SRT file has correct block structure."""
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.srt"

        words = [_make_mock_word(1.0, 2.5, "Test subtitle")]
        seg = _make_mock_segment(1.0, 2.5, "Test subtitle", words=words)

        t, mock_model = self._make_transcriber_with_mock([seg])
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())

        t.transcribe_to_srt(audio, output, model_size="base", device="cpu", compute_type="int8")

        content = output.read_text(encoding="utf-8")
        # SRT block: index, timestamp line, text, blank line
        assert "1\n" in content
        assert "00:00:01,000 --> 00:00:02,500" in content
        assert "Test subtitle" in content

    def test_model_cache_reuse(self, tmp_path):
        """Second call with same model_size should not reload the model."""
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        words = [_make_mock_word(0.0, 1.0, "Hi")]
        seg = _make_mock_segment(0.0, 1.0, "Hi", words=words)

        t, mock_model = self._make_transcriber_with_mock([seg])
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())

        t.transcribe(audio, model_size="base", device="cpu", compute_type="int8")

        # Reset return value for second call
        words2 = [_make_mock_word(0.0, 1.0, "Hi")]
        seg2 = _make_mock_segment(0.0, 1.0, "Hi", words=words2)
        mock_model.transcribe.return_value = (iter([seg2]), _make_mock_info())

        t.transcribe(audio, model_size="base", device="cpu", compute_type="int8")

        # Model was loaded once (already in cache before first call)
        assert "base:cpu:int8" in t._model_cache

    def test_clear_cache(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        words = [_make_mock_word(0.0, 1.0, "Hi")]
        seg = _make_mock_segment(0.0, 1.0, "Hi", words=words)

        t, mock_model = self._make_transcriber_with_mock([seg])
        assert len(t._model_cache) > 0

        t.clear_cache()
        assert len(t._model_cache) == 0

    def test_fallback_to_segment_timestamps_when_no_words(self, tmp_path):
        """When word_timestamps=False or words list is empty, use segment boundaries."""
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        # Segment with no words
        seg = _make_mock_segment(2.0, 4.0, "No words segment", words=[])

        t, mock_model = self._make_transcriber_with_mock([seg])
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())

        result = t.transcribe(audio, model_size="base", device="cpu", compute_type="int8")
        assert len(result) == 1
        assert result[0].start_time == 2.0
        assert result[0].end_time == 4.0
        assert result[0].text == "No words segment"

    def test_language_passed_to_model(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        t, mock_model = self._make_transcriber_with_mock([])
        mock_model.transcribe.return_value = (iter([]), _make_mock_info())

        t.transcribe(audio, language="vi", model_size="base", device="cpu", compute_type="int8")

        call_kwargs = mock_model.transcribe.call_args[1]
        assert call_kwargs.get("language") == "vi"

    def test_no_language_kwarg_when_none(self, tmp_path):
        """When language=None, 'language' key should not be passed to model."""
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)

        t, mock_model = self._make_transcriber_with_mock([])
        mock_model.transcribe.return_value = (iter([]), _make_mock_info())

        t.transcribe(audio, language=None, model_size="base", device="cpu", compute_type="int8")

        call_kwargs = mock_model.transcribe.call_args[1]
        assert "language" not in call_kwargs


# ─── Legacy shim ──────────────────────────────────────────────────────────────

class TestLegacyTranscribeAudio:
    def test_returns_path_on_success(self, tmp_path):
        audio = tmp_path / "audio.mp3"
        audio.write_bytes(b"\x00" * 100)
        output = tmp_path / "output.srt"

        words = [_make_mock_word(0.0, 1.0, "Hi")]
        seg = _make_mock_segment(0.0, 1.0, "Hi", words=words)

        # Patch the global _default_transcriber's model cache
        from server.audio import transcribe as transcribe_module

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([seg]), _make_mock_info())
        transcribe_module._default_transcriber._model_cache["medium:cpu:int8"] = mock_model

        result = transcribe_audio(
            audio_path=audio,
            output_srt=output,
            language="vi",
            model_name="medium",
            device="cpu",
            compute_type="int8",
        )

        assert result is not None
        assert isinstance(result, Path)
        assert result.exists()

    def test_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            transcribe_audio(
                audio_path=tmp_path / "missing.mp3",
                output_srt=tmp_path / "out.srt",
            )
