"""Unit tests for server/content/crawlers/stream_merger.py (Task 4.5.5).

All FFmpeg subprocess calls and Whisper imports are mocked so tests run
without real binaries or GPU hardware.

Covers:
- MergeResult dataclass construction
- merge_dash_streams() happy path + error cases
- extract_subtitles() happy path + no-subtitle fallback
- transcribe_video() happy path + failure cases
- StreamMerger class construction + delegation
- _probe_video() helper
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── MergeResult ──────────────────────────────────────────────────────────────


class TestMergeResult:
    def test_fields(self, tmp_path):
        from server.content.crawlers.stream_merger import MergeResult

        r = MergeResult(
            output_path=tmp_path / "out.mp4",
            duration=120.5,
            has_audio=True,
        )
        assert r.output_path == tmp_path / "out.mp4"
        assert r.duration == pytest.approx(120.5)
        assert r.has_audio is True

    def test_no_audio_flag(self, tmp_path):
        from server.content.crawlers.stream_merger import MergeResult

        r = MergeResult(output_path=tmp_path / "v.mp4", duration=0.0, has_audio=False)
        assert r.has_audio is False

    def test_is_dataclass(self):
        import dataclasses
        from server.content.crawlers.stream_merger import MergeResult

        assert dataclasses.is_dataclass(MergeResult)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _fake_ffmpeg(tmp_path: Path) -> Path:
    """Create a fake ffmpeg binary in tmp_path/vendor/."""
    vendor = tmp_path / "vendor"
    vendor.mkdir(exist_ok=True)
    ffmpeg = vendor / "ffmpeg.exe"
    ffmpeg.write_bytes(b"fake")
    return ffmpeg


def _patch_find_ffmpeg(fake_path: Path):
    """Return a context manager that patches find_ffmpeg in stream_merger."""
    return patch(
        "server.content.crawlers.stream_merger.find_ffmpeg",
        return_value=fake_path,
    )


def _patch_find_ffprobe(fake_path):
    return patch(
        "server.content.crawlers.stream_merger.find_ffprobe",
        return_value=fake_path,
    )


def _ok_run(*args, **kwargs):
    """Fake subprocess.run that always succeeds."""
    m = MagicMock()
    m.returncode = 0
    return m


def _fail_run(*args, **kwargs):
    """Fake subprocess.run that always fails (returncode=1)."""
    m = MagicMock()
    m.returncode = 1
    m.stderr = b"error"
    return m


# ─── merge_dash_streams ───────────────────────────────────────────────────────


class TestMergeDashStreams:
    def test_happy_path_returns_merge_result(self, tmp_path):
        from server.content.crawlers.stream_merger import merge_dash_streams

        video = tmp_path / "video.mp4"
        audio = tmp_path / "audio.m4a"
        output = tmp_path / "merged.mp4"
        video.write_bytes(b"fake video")
        audio.write_bytes(b"fake audio")
        # Simulate ffmpeg creating the output file
        output.write_bytes(b"fake merged")

        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             _patch_find_ffprobe(None), \
             patch("subprocess.run", side_effect=_ok_run):
            result = merge_dash_streams(video, audio, output)

        assert result.output_path == output
        assert isinstance(result.duration, float)
        assert isinstance(result.has_audio, bool)

    def test_raises_when_ffmpeg_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import merge_dash_streams

        video = tmp_path / "v.mp4"
        audio = tmp_path / "a.m4a"
        video.write_bytes(b"x")
        audio.write_bytes(b"x")

        with patch("server.content.crawlers.stream_merger.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg not found"):
                merge_dash_streams(video, audio, tmp_path / "out.mp4")

    def test_raises_when_video_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import merge_dash_streams

        audio = tmp_path / "audio.m4a"
        audio.write_bytes(b"x")
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg):
            with pytest.raises(FileNotFoundError, match="Video stream not found"):
                merge_dash_streams(tmp_path / "nonexistent.mp4", audio, tmp_path / "out.mp4")

    def test_raises_when_audio_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import merge_dash_streams

        video = tmp_path / "video.mp4"
        video.write_bytes(b"x")
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg):
            with pytest.raises(FileNotFoundError, match="Audio stream not found"):
                merge_dash_streams(video, tmp_path / "nonexistent.m4a", tmp_path / "out.mp4")

    def test_raises_on_ffmpeg_error(self, tmp_path):
        from server.content.crawlers.stream_merger import merge_dash_streams

        video = tmp_path / "v.mp4"
        audio = tmp_path / "a.m4a"
        video.write_bytes(b"x")
        audio.write_bytes(b"x")
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
            with pytest.raises(subprocess.CalledProcessError):
                merge_dash_streams(video, audio, tmp_path / "out.mp4")

    def test_creates_output_parent_dir(self, tmp_path):
        from server.content.crawlers.stream_merger import merge_dash_streams

        video = tmp_path / "v.mp4"
        audio = tmp_path / "a.m4a"
        video.write_bytes(b"x")
        audio.write_bytes(b"x")
        output = tmp_path / "nested" / "deep" / "out.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"fake merged")

        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             _patch_find_ffprobe(None), \
             patch("subprocess.run", side_effect=_ok_run):
            result = merge_dash_streams(video, audio, output)

        assert result.output_path == output

    def test_ffmpeg_cmd_uses_copy_codec(self, tmp_path):
        """Verify -c copy is passed (no re-encoding)."""
        from server.content.crawlers.stream_merger import merge_dash_streams

        video = tmp_path / "v.mp4"
        audio = tmp_path / "a.m4a"
        output = tmp_path / "out.mp4"
        video.write_bytes(b"x")
        audio.write_bytes(b"x")
        output.write_bytes(b"fake merged")

        ffmpeg = _fake_ffmpeg(tmp_path)
        captured_cmd = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            m = MagicMock()
            m.returncode = 0
            return m

        with _patch_find_ffmpeg(ffmpeg), \
             _patch_find_ffprobe(None), \
             patch("subprocess.run", side_effect=capture_run):
            merge_dash_streams(video, audio, output)

        assert "-c" in captured_cmd
        copy_idx = captured_cmd.index("-c")
        assert captured_cmd[copy_idx + 1] == "copy"


# ─── extract_subtitles ────────────────────────────────────────────────────────


class TestExtractSubtitles:
    def test_returns_srt_path_when_subtitles_found(self, tmp_path):
        from server.content.crawlers.stream_merger import extract_subtitles

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        output_srt = tmp_path / "subs.srt"
        ffmpeg = _fake_ffmpeg(tmp_path)

        def fake_run(cmd, **kwargs):
            # Simulate ffmpeg writing the SRT file
            output_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n")
            m = MagicMock()
            m.returncode = 0
            return m

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=fake_run):
            result = extract_subtitles(video, output_srt, language="vi")

        assert result == output_srt
        assert output_srt.exists()

    def test_returns_none_when_no_subtitles(self, tmp_path):
        from server.content.crawlers.stream_merger import extract_subtitles

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        output_srt = tmp_path / "subs.srt"
        ffmpeg = _fake_ffmpeg(tmp_path)

        # Both attempts fail (no subtitle streams)
        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=_fail_run):
            result = extract_subtitles(video, output_srt, language="vi")

        assert result is None
        assert not output_srt.exists()

    def test_raises_when_ffmpeg_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import extract_subtitles

        video = tmp_path / "video.mp4"
        video.write_bytes(b"x")

        with patch("server.content.crawlers.stream_merger.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg not found"):
                extract_subtitles(video, tmp_path / "subs.srt")

    def test_raises_when_video_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import extract_subtitles

        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg):
            with pytest.raises(FileNotFoundError, match="Video file not found"):
                extract_subtitles(tmp_path / "nonexistent.mp4", tmp_path / "subs.srt")

    def test_falls_back_to_first_stream_when_language_not_found(self, tmp_path):
        """First attempt (language-specific) fails; second (s:0) succeeds."""
        from server.content.crawlers.stream_merger import extract_subtitles

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        output_srt = tmp_path / "subs.srt"
        ffmpeg = _fake_ffmpeg(tmp_path)

        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            m = MagicMock()
            if call_count[0] == 1:
                # First call (language-specific) fails
                m.returncode = 1
            else:
                # Second call (s:0 fallback) succeeds
                output_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n")
                m.returncode = 0
            return m

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=fake_run):
            result = extract_subtitles(video, output_srt, language="en")

        assert result == output_srt
        assert call_count[0] == 2


# ─── transcribe_video ─────────────────────────────────────────────────────────


class TestTranscribeVideo:
    def test_happy_path_returns_srt_path(self, tmp_path):
        from server.content.crawlers.stream_merger import transcribe_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        output_dir = tmp_path / "subs"
        expected_srt = output_dir / "video.srt"
        ffmpeg = _fake_ffmpeg(tmp_path)

        def fake_run(cmd, **kwargs):
            # Simulate ffmpeg extracting audio
            audio_out = [a for a in cmd if a.endswith(".wav")]
            if audio_out:
                Path(audio_out[0]).write_bytes(b"fake wav")
            m = MagicMock()
            m.returncode = 0
            return m

        mock_transcribe = MagicMock(return_value=expected_srt)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("server.content.crawlers.stream_merger.transcribe_audio", mock_transcribe):
            result = transcribe_video(video, output_dir, language="vi")

        assert result == expected_srt
        mock_transcribe.assert_called_once()
        # Verify language was passed through
        _, kwargs = mock_transcribe.call_args
        assert kwargs.get("language") == "vi" or mock_transcribe.call_args[0][2] == "vi" \
            or mock_transcribe.call_args.kwargs.get("language") == "vi"

    def test_returns_none_when_audio_extraction_fails(self, tmp_path):
        from server.content.crawlers.stream_merger import transcribe_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=_fail_run):
            result = transcribe_video(video, tmp_path / "subs", language="vi")

        assert result is None

    def test_returns_none_when_faster_whisper_not_installed(self, tmp_path):
        from server.content.crawlers.stream_merger import transcribe_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        ffmpeg = _fake_ffmpeg(tmp_path)

        def fake_run(cmd, **kwargs):
            audio_out = [a for a in cmd if a.endswith(".wav")]
            if audio_out:
                Path(audio_out[0]).write_bytes(b"fake wav")
            m = MagicMock()
            m.returncode = 0
            return m

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=fake_run), \
             patch(
                 "server.content.crawlers.stream_merger.transcribe_audio",
                 side_effect=ImportError("faster-whisper not installed"),
             ):
            result = transcribe_video(video, tmp_path / "subs", language="vi")

        assert result is None

    def test_raises_when_ffmpeg_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import transcribe_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"x")

        with patch("server.content.crawlers.stream_merger.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg not found"):
                transcribe_video(video, tmp_path / "subs")

    def test_raises_when_video_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import transcribe_video

        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg):
            with pytest.raises(FileNotFoundError, match="Video file not found"):
                transcribe_video(tmp_path / "nonexistent.mp4", tmp_path / "subs")

    def test_returns_none_when_transcription_raises(self, tmp_path):
        from server.content.crawlers.stream_merger import transcribe_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        ffmpeg = _fake_ffmpeg(tmp_path)

        def fake_run(cmd, **kwargs):
            audio_out = [a for a in cmd if a.endswith(".wav")]
            if audio_out:
                Path(audio_out[0]).write_bytes(b"fake wav")
            m = MagicMock()
            m.returncode = 0
            return m

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=fake_run), \
             patch(
                 "server.content.crawlers.stream_merger.transcribe_audio",
                 side_effect=RuntimeError("model load failed"),
             ):
            result = transcribe_video(video, tmp_path / "subs")

        assert result is None


# ─── StreamMerger class ───────────────────────────────────────────────────────


class TestStreamMerger:
    def test_init_raises_when_ffmpeg_missing(self):
        from server.content.crawlers.stream_merger import StreamMerger

        with patch("server.content.crawlers.stream_merger.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg not found"):
                StreamMerger()

    def test_init_succeeds_when_ffmpeg_found(self, tmp_path):
        from server.content.crawlers.stream_merger import StreamMerger

        ffmpeg = _fake_ffmpeg(tmp_path)
        with _patch_find_ffmpeg(ffmpeg):
            merger = StreamMerger()
        assert merger is not None

    def test_merge_delegates_to_merge_dash_streams(self, tmp_path):
        from server.content.crawlers.stream_merger import StreamMerger, MergeResult

        ffmpeg = _fake_ffmpeg(tmp_path)
        expected = MergeResult(output_path=tmp_path / "out.mp4", duration=60.0, has_audio=True)

        with _patch_find_ffmpeg(ffmpeg):
            merger = StreamMerger()

        with patch(
            "server.content.crawlers.stream_merger.merge_dash_streams",
            return_value=expected,
        ) as mock_merge:
            result = merger.merge(tmp_path / "v.mp4", tmp_path / "a.m4a", tmp_path / "out.mp4")

        mock_merge.assert_called_once_with(
            tmp_path / "v.mp4", tmp_path / "a.m4a", tmp_path / "out.mp4"
        )
        assert result is expected

    def test_extract_subs_delegates_to_extract_subtitles(self, tmp_path):
        from server.content.crawlers.stream_merger import StreamMerger

        ffmpeg = _fake_ffmpeg(tmp_path)
        srt = tmp_path / "subs.srt"

        with _patch_find_ffmpeg(ffmpeg):
            merger = StreamMerger()

        with patch(
            "server.content.crawlers.stream_merger.extract_subtitles",
            return_value=srt,
        ) as mock_extract:
            result = merger.extract_subs(tmp_path / "v.mp4", srt, language="en")

        mock_extract.assert_called_once_with(tmp_path / "v.mp4", srt, "en")
        assert result is srt

    def test_transcribe_delegates_to_transcribe_video(self, tmp_path):
        from server.content.crawlers.stream_merger import StreamMerger

        ffmpeg = _fake_ffmpeg(tmp_path)
        srt = tmp_path / "subs" / "video.srt"

        with _patch_find_ffmpeg(ffmpeg):
            merger = StreamMerger()

        with patch(
            "server.content.crawlers.stream_merger.transcribe_video",
            return_value=srt,
        ) as mock_transcribe:
            result = merger.transcribe(tmp_path / "v.mp4", tmp_path / "subs", language="vi")

        mock_transcribe.assert_called_once_with(tmp_path / "v.mp4", tmp_path / "subs", "vi")
        assert result is srt

    def test_extract_subs_returns_none_when_no_subs(self, tmp_path):
        from server.content.crawlers.stream_merger import StreamMerger

        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg):
            merger = StreamMerger()

        with patch(
            "server.content.crawlers.stream_merger.extract_subtitles",
            return_value=None,
        ):
            result = merger.extract_subs(tmp_path / "v.mp4", tmp_path / "subs.srt")

        assert result is None


# ─── _probe_video helper ──────────────────────────────────────────────────────


class TestProbeVideo:
    def test_returns_defaults_when_ffprobe_missing(self, tmp_path):
        from server.content.crawlers.stream_merger import _probe_video

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")

        with _patch_find_ffprobe(None):
            duration, has_audio = _probe_video(video)

        assert duration == 0.0
        assert has_audio is True

    def test_parses_duration_from_ffprobe(self, tmp_path):
        from server.content.crawlers.stream_merger import _probe_video

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        ffprobe = tmp_path / "ffprobe.exe"
        ffprobe.write_bytes(b"fake")

        call_count = [0]

        def fake_check_output(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "95.5\n"   # duration probe
            return "audio\n"      # audio stream probe

        with _patch_find_ffprobe(ffprobe), \
             patch("subprocess.check_output", side_effect=fake_check_output):
            duration, has_audio = _probe_video(video)

        assert duration == pytest.approx(95.5)
        assert has_audio is True

    def test_has_audio_false_when_no_audio_stream(self, tmp_path):
        from server.content.crawlers.stream_merger import _probe_video

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        ffprobe = tmp_path / "ffprobe.exe"
        ffprobe.write_bytes(b"fake")

        call_count = [0]

        def fake_check_output(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "30.0\n"
            return ""   # no audio stream

        with _patch_find_ffprobe(ffprobe), \
             patch("subprocess.check_output", side_effect=fake_check_output):
            duration, has_audio = _probe_video(video)

        assert duration == pytest.approx(30.0)
        assert has_audio is False

    def test_gracefully_handles_probe_error(self, tmp_path):
        from server.content.crawlers.stream_merger import _probe_video

        video = tmp_path / "v.mp4"
        video.write_bytes(b"x")
        ffprobe = tmp_path / "ffprobe.exe"
        ffprobe.write_bytes(b"fake")

        with _patch_find_ffprobe(ffprobe), \
             patch(
                 "subprocess.check_output",
                 side_effect=subprocess.CalledProcessError(1, "ffprobe"),
             ):
            duration, has_audio = _probe_video(video)

        # Should not raise; returns safe defaults
        assert duration == 0.0
        assert has_audio is True


# ─── transcribe_audio (server.audio.transcribe) ───────────────────────────────


class TestTranscribeAudio:
    @pytest.fixture(autouse=True)
    def _clear_whisper_cache(self):
        """Isolate tests that mock faster_whisper.

        The module-level ``_default_transcriber`` caches loaded models by
        ``model_size:device:compute_type``. Without clearing it, a mock model
        cached by one test would be reused by the next (since ``_get_model``
        returns the cached instance without re-importing faster_whisper),
        breaking ``patch.dict(sys.modules, ...)`` mocking.
        """
        from server.audio import transcribe as transcribe_module

        transcribe_module._default_transcriber.clear_cache()
        yield
        transcribe_module._default_transcriber.clear_cache()

    def test_raises_when_audio_missing(self, tmp_path):
        from server.audio.transcribe import transcribe_audio

        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            transcribe_audio(tmp_path / "nonexistent.wav", tmp_path / "out.srt")

    def test_raises_when_faster_whisper_not_installed(self, tmp_path):
        from server.audio.transcribe import transcribe_audio

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake wav")

        with patch.dict(sys.modules, {"faster_whisper": None}):
            with pytest.raises(ImportError, match="faster-whisper"):
                transcribe_audio(audio, tmp_path / "out.srt")

    def test_writes_srt_file(self, tmp_path):
        from server.audio.transcribe import transcribe_audio

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake wav")
        output_srt = tmp_path / "out.srt"

        # Build mock segment
        seg = MagicMock()
        seg.start = 0.0
        seg.end = 2.5
        seg.text = " Hello world"

        mock_info = MagicMock()
        mock_info.language = "vi"
        mock_info.language_probability = 0.99

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg], mock_info)

        mock_whisper_module = MagicMock()
        mock_whisper_module.WhisperModel.return_value = mock_model

        with patch.dict(sys.modules, {"faster_whisper": mock_whisper_module}):
            result = transcribe_audio(audio, output_srt, language="vi")

        assert result == output_srt
        assert output_srt.exists()
        content = output_srt.read_text(encoding="utf-8")
        assert "Hello world" in content
        assert "00:00:00,000 --> 00:00:02,500" in content

    def test_returns_none_when_no_segments(self, tmp_path):
        from server.audio.transcribe import transcribe_audio

        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"fake wav")

        mock_info = MagicMock()
        mock_info.language = "vi"
        mock_info.language_probability = 0.1

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], mock_info)

        mock_whisper_module = MagicMock()
        mock_whisper_module.WhisperModel.return_value = mock_model

        with patch.dict(sys.modules, {"faster_whisper": mock_whisper_module}):
            result = transcribe_audio(audio, tmp_path / "out.srt")

        assert result is None

    def test_format_timestamp(self):
        from server.audio.transcribe import _format_timestamp

        assert _format_timestamp(0.0) == "00:00:00,000"
        assert _format_timestamp(61.5) == "00:01:01,500"
        assert _format_timestamp(3661.123) == "01:01:01,123"
        assert _format_timestamp(3600.0) == "01:00:00,000"
