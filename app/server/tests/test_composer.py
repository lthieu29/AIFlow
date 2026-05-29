"""Unit tests for server/render/composer.py — VideoComposer.

Tests cover:
- reconcile_durations() proportional scaling
- reconcile_durations() edge cases (empty, zero total, zero tts)
- _escape_drawtext() special character escaping
- build_compose_command() structure (inputs, filter_complex, output)
- build_compose_command() with TTS + BGM + subtitle
- build_compose_command() with direct_concat and ffmpeg_fade transitions
- VideoComposer.__init__() raises FileNotFoundError when ffmpeg missing
- VideoComposer.compose() raises ValueError on empty clips
- VideoComposer.compose() calls FFmpeg and returns ComposeResult

Phase 3.3 — Task 3.3.2
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.render.composer import (
    ClipInput,
    ComposeConfig,
    SubtitleConfig,
    SubtitleSegment,
    VideoComposer,
    _escape_drawtext,
    build_compose_command,
    compose_video,
    reconcile_durations,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_clip(path: str = "/tmp/clip.mp4", duration: float = 5.0) -> ClipInput:
    return ClipInput(file_path=Path(path), duration=duration)


def _make_config(
    clips: list[ClipInput] | None = None,
    tts_path: Path | None = None,
    bgm_path: Path | None = None,
    subtitle: SubtitleConfig | None = None,
) -> ComposeConfig:
    # Use sentinel to distinguish "not provided" from "empty list"
    resolved_clips = [_make_clip()] if clips is None else clips
    return ComposeConfig(
        project_id="test-proj",
        clips=resolved_clips,
        tts_path=tts_path,
        bgm_path=bgm_path,
        subtitle=subtitle,
        output_dir=Path("/tmp/output"),
    )


def _fake_ffmpeg() -> Path:
    """Return a fake ffmpeg path for tests that don't actually run FFmpeg."""
    return Path("/fake/ffmpeg.exe")


# ─── reconcile_durations ──────────────────────────────────────────────────────

class TestReconcileDurations:
    def test_proportional_scaling(self):
        clips = [_make_clip(duration=4.0), _make_clip(duration=6.0)]
        result = reconcile_durations(clips, tts_duration=20.0)
        assert len(result) == 2
        assert result[0].duration == pytest.approx(8.0)
        assert result[1].duration == pytest.approx(12.0)

    def test_total_matches_tts_duration(self):
        clips = [_make_clip(duration=3.0), _make_clip(duration=3.0), _make_clip(duration=4.0)]
        tts = 15.0
        result = reconcile_durations(clips, tts_duration=tts)
        total = sum(c.duration for c in result)
        assert total == pytest.approx(tts, rel=1e-3)

    def test_empty_clips_returns_empty(self):
        result = reconcile_durations([], tts_duration=10.0)
        assert result == []

    def test_zero_tts_returns_original(self):
        clips = [_make_clip(duration=5.0)]
        result = reconcile_durations(clips, tts_duration=0.0)
        assert result[0].duration == pytest.approx(5.0)

    def test_negative_tts_returns_original(self):
        clips = [_make_clip(duration=5.0)]
        result = reconcile_durations(clips, tts_duration=-1.0)
        assert result[0].duration == pytest.approx(5.0)

    def test_zero_original_total_distributes_evenly(self):
        clips = [_make_clip(duration=0.0), _make_clip(duration=0.0)]
        result = reconcile_durations(clips, tts_duration=10.0)
        assert result[0].duration == pytest.approx(5.0)
        assert result[1].duration == pytest.approx(5.0)

    def test_preserves_transition_and_has_audio(self):
        clip = ClipInput(
            file_path=Path("/tmp/c.mp4"),
            duration=5.0,
            transition="ffmpeg_fade",
            has_audio=True,
        )
        result = reconcile_durations([clip], tts_duration=10.0)
        assert result[0].transition == "ffmpeg_fade"
        assert result[0].has_audio is True

    def test_single_clip_gets_full_tts_duration(self):
        clips = [_make_clip(duration=3.0)]
        result = reconcile_durations(clips, tts_duration=7.5)
        assert result[0].duration == pytest.approx(7.5)

    def test_returns_new_list_not_mutating_original(self):
        clips = [_make_clip(duration=5.0)]
        result = reconcile_durations(clips, tts_duration=10.0)
        assert result is not clips
        assert clips[0].duration == pytest.approx(5.0)  # original unchanged


# ─── _escape_drawtext ─────────────────────────────────────────────────────────

class TestEscapeDrawtext:
    def test_colon_escaped(self):
        result = _escape_drawtext("time: 10:30")
        assert ":" not in result or "\\\\:" in result

    def test_percent_escaped(self):
        result = _escape_drawtext("50% off")
        assert "\\\\%" in result

    def test_brackets_escaped(self):
        result = _escape_drawtext("[sale]")
        assert "\\\\[" in result
        assert "\\\\]" in result

    def test_single_quote_replaced(self):
        result = _escape_drawtext("it's fine")
        # Straight apostrophe should be replaced with right single quotation mark
        assert "'" not in result
        assert "\u2019" in result

    def test_plain_text_unchanged_structure(self):
        result = _escape_drawtext("Hello World")
        assert "Hello World" in result

    def test_empty_string(self):
        assert _escape_drawtext("") == ""


# ─── build_compose_command ────────────────────────────────────────────────────

class TestBuildComposeCommand:
    def _build(self, config: ComposeConfig) -> list[str]:
        return build_compose_command(config, Path("/tmp/final.mp4"), _fake_ffmpeg())

    def test_raises_on_empty_clips(self):
        config = _make_config(clips=[])
        with pytest.raises(ValueError, match="empty"):
            build_compose_command(config, Path("/tmp/out.mp4"), _fake_ffmpeg())

    def test_ffmpeg_binary_is_first_arg(self):
        config = _make_config()
        cmd = self._build(config)
        assert cmd[0] == str(_fake_ffmpeg())

    def test_overwrite_flag_present(self):
        config = _make_config()
        cmd = self._build(config)
        assert "-y" in cmd

    def test_clip_input_present(self):
        config = _make_config(clips=[_make_clip("/tmp/scene1.mp4")])
        cmd = self._build(config)
        # Compare normalised paths (Windows uses backslashes)
        assert str(Path("/tmp/scene1.mp4")) in cmd

    def test_tts_input_present_when_provided(self, tmp_path):
        tts = tmp_path / "narration.mp3"
        tts.touch()
        config = _make_config(tts_path=tts)
        cmd = self._build(config)
        assert str(tts) in cmd

    def test_bgm_input_present_when_provided(self, tmp_path):
        bgm = tmp_path / "bgm.mp3"
        bgm.touch()
        config = _make_config(bgm_path=bgm)
        cmd = self._build(config)
        assert str(bgm) in cmd

    def test_filter_complex_flag_present(self):
        config = _make_config()
        cmd = self._build(config)
        assert "-filter_complex" in cmd

    def test_output_path_is_last_arg(self):
        config = _make_config()
        cmd = build_compose_command(config, Path("/tmp/final.mp4"), _fake_ffmpeg())
        assert cmd[-1] == str(Path("/tmp/final.mp4"))

    def test_libx264_codec(self):
        config = _make_config()
        cmd = self._build(config)
        assert "-c:v" in cmd
        assert "libx264" in cmd

    def test_aac_codec_when_audio_present(self, tmp_path):
        tts = tmp_path / "narration.mp3"
        tts.touch()
        config = _make_config(tts_path=tts)
        cmd = self._build(config)
        assert "-c:a" in cmd
        assert "aac" in cmd

    def test_no_audio_flag_when_no_audio(self):
        config = _make_config(tts_path=None, bgm_path=None)
        cmd = self._build(config)
        assert "-an" in cmd

    def test_faststart_flag(self):
        config = _make_config()
        cmd = self._build(config)
        assert "+faststart" in " ".join(cmd)

    def test_subtitle_drawtext_in_filter(self):
        sub = SubtitleConfig(
            segments=[SubtitleSegment(text="Hello", start_sec=0.0, end_sec=2.0)],
        )
        config = _make_config(subtitle=sub)
        cmd = self._build(config)
        filter_str = cmd[cmd.index("-filter_complex") + 1]
        assert "drawtext" in filter_str
        assert "Hello" in filter_str

    def test_two_clips_concat_filter(self):
        clips = [_make_clip("/tmp/a.mp4"), _make_clip("/tmp/b.mp4")]
        config = _make_config(clips=clips)
        cmd = self._build(config)
        filter_str = cmd[cmd.index("-filter_complex") + 1]
        assert "concat" in filter_str

    def test_ffmpeg_fade_uses_xfade(self):
        clips = [
            ClipInput(file_path=Path("/tmp/a.mp4"), duration=5.0, transition="direct_concat"),
            ClipInput(file_path=Path("/tmp/b.mp4"), duration=5.0, transition="ffmpeg_fade"),
        ]
        config = _make_config(clips=clips)
        cmd = self._build(config)
        filter_str = cmd[cmd.index("-filter_complex") + 1]
        assert "xfade" in filter_str

    def test_bgm_volume_applied(self, tmp_path):
        bgm = tmp_path / "bgm.mp3"
        bgm.touch()
        config = ComposeConfig(
            project_id="p",
            clips=[_make_clip()],
            bgm_path=bgm,
            bgm_volume=0.15,
            output_dir=Path("/tmp"),
        )
        cmd = build_compose_command(config, Path("/tmp/out.mp4"), _fake_ffmpeg())
        filter_str = cmd[cmd.index("-filter_complex") + 1]
        assert "0.150" in filter_str


# ─── VideoComposer ────────────────────────────────────────────────────────────

class TestVideoComposer:
    def test_init_raises_when_ffmpeg_missing(self):
        with patch("server.render.composer.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg"):
                VideoComposer()

    def test_compose_raises_on_empty_clips(self, tmp_path):
        with patch("server.render.composer.find_ffmpeg", return_value=Path("/fake/ffmpeg.exe")):
            composer = VideoComposer()
        config = ComposeConfig(
            project_id="p",
            clips=[],
            output_dir=tmp_path,
        )
        with pytest.raises(ValueError, match="empty"):
            composer.compose(config)

    def test_compose_calls_ffmpeg_and_returns_result(self, tmp_path):
        """compose() should call FFmpeg and return a ComposeResult."""
        clip_file = tmp_path / "scene.mp4"
        clip_file.touch()
        config = ComposeConfig(
            project_id="proj1",
            clips=[ClipInput(file_path=clip_file, duration=5.0)],
            output_dir=tmp_path,
        )

        def _fake_run(cmd, **kwargs):
            # Simulate FFmpeg creating the output file
            out = Path(cmd[-1])
            out.touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("server.render.composer.find_ffmpeg", return_value=Path("/fake/ffmpeg.exe")):
            with patch("server.render.composer.subprocess.run", side_effect=_fake_run):
                composer = VideoComposer()
                result = composer.compose(config)

        assert result.output_path == tmp_path / "final.mp4"
        assert len(result.reconciled_clips) == 1

    def test_compose_reconciles_durations_when_tts_provided(self, tmp_path):
        """When TTS audio is provided, clip durations should be reconciled."""
        clip_file = tmp_path / "scene.mp4"
        clip_file.touch()
        tts_file = tmp_path / "narration.mp3"
        tts_file.touch()

        config = ComposeConfig(
            project_id="proj2",
            clips=[
                ClipInput(file_path=clip_file, duration=3.0),
                ClipInput(file_path=clip_file, duration=7.0),
            ],
            tts_path=tts_file,
            output_dir=tmp_path,
        )

        def _fake_run(cmd, **kwargs):
            out = Path(cmd[-1])
            out.touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("server.render.composer.find_ffmpeg", return_value=Path("/fake/ffmpeg.exe")):
            with patch("server.render.composer.probe_duration", return_value=20.0):
                with patch("server.render.composer.subprocess.run", side_effect=_fake_run):
                    composer = VideoComposer()
                    result = composer.compose(config)

        # Total reconciled duration should match TTS (20s)
        total = sum(c.duration for c in result.reconciled_clips)
        assert total == pytest.approx(20.0, rel=1e-3)
        assert result.total_duration == pytest.approx(20.0)

    def test_compose_uses_default_output_dir_when_none(self, tmp_path):
        """When output_dir is None, composer creates storage/output/{project_id}/."""
        clip_file = tmp_path / "scene.mp4"
        clip_file.touch()
        config = ComposeConfig(
            project_id="myproj",
            clips=[ClipInput(file_path=clip_file, duration=5.0)],
            output_dir=None,
        )

        created_dirs: list[Path] = []

        def _fake_run(cmd, **kwargs):
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.touch()
            created_dirs.append(out.parent)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("server.render.composer.find_ffmpeg", return_value=Path("/fake/ffmpeg.exe")):
            with patch("server.render.composer.subprocess.run", side_effect=_fake_run):
                composer = VideoComposer()
                result = composer.compose(config)

        assert "myproj" in str(result.output_path)

    def test_compose_raises_on_ffmpeg_failure(self, tmp_path):
        """compose() should propagate CalledProcessError on FFmpeg failure."""
        clip_file = tmp_path / "scene.mp4"
        clip_file.touch()
        config = ComposeConfig(
            project_id="p",
            clips=[ClipInput(file_path=clip_file, duration=5.0)],
            output_dir=tmp_path,
        )

        def _fail_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 1
            mock.stderr = b"FFmpeg error"
            raise subprocess.CalledProcessError(1, cmd, stderr=b"FFmpeg error")

        with patch("server.render.composer.find_ffmpeg", return_value=Path("/fake/ffmpeg.exe")):
            with patch("server.render.composer.subprocess.run", side_effect=_fail_run):
                composer = VideoComposer()
                with pytest.raises(subprocess.CalledProcessError):
                    composer.compose(config)


# ─── compose_video convenience wrapper ───────────────────────────────────────

class TestComposeVideoWrapper:
    def test_compose_video_delegates_to_composer(self, tmp_path):
        clip_file = tmp_path / "scene.mp4"
        clip_file.touch()
        config = ComposeConfig(
            project_id="wrap",
            clips=[ClipInput(file_path=clip_file, duration=5.0)],
            output_dir=tmp_path,
        )

        def _fake_run(cmd, **kwargs):
            out = Path(cmd[-1])
            out.touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch("server.render.composer.find_ffmpeg", return_value=Path("/fake/ffmpeg.exe")):
            with patch("server.render.composer.subprocess.run", side_effect=_fake_run):
                result = compose_video(config)

        assert result.output_path.name == "final.mp4"
