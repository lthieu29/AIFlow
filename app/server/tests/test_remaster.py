"""Unit tests for server/content/crawlers/remaster.py (Task 4.5.6).

All Gemini API calls and FFmpeg subprocess calls are mocked so tests run
without real binaries, GPU hardware, or network access.

Covers:
- RemasterPreset enum values
- RemasterConfig dataclass defaults
- RemasterResult dataclass construction
- translate_srt() — happy path, no-client fallback, missing file, empty SRT
- remaster_video() — LIGHT, AGGRESSIVE, TRANSLATE_ONLY presets
- _escape_srt_path_for_ffmpeg() helper
- _build_subtitle_burn_cmd() helper
- VideoRemaster.__init__() validation
- VideoRemaster.remaster() async pipeline (mocked StreamMerger)
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _fake_ffmpeg(tmp_path: Path) -> Path:
    """Create a fake ffmpeg binary in tmp_path."""
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"fake")
    return ffmpeg


def _patch_find_ffmpeg(fake_path):
    return patch(
        "server.content.crawlers.remaster.find_ffmpeg",
        return_value=fake_path,
    )


def _ok_run(*args, **kwargs):
    m = MagicMock()
    m.returncode = 0
    return m


def _sample_srt() -> str:
    return (
        "1\n00:00:01,000 --> 00:00:03,000\n你好世界\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\n这是一个测试\n\n"
    )


# ─── RemasterPreset ───────────────────────────────────────────────────────────


class TestRemasterPreset:
    def test_values(self):
        from server.content.crawlers.remaster import RemasterPreset

        assert RemasterPreset.LIGHT.value == "light"
        assert RemasterPreset.AGGRESSIVE.value == "aggressive"
        assert RemasterPreset.TRANSLATE_ONLY.value == "translate_only"

    def test_is_str_enum(self):
        from server.content.crawlers.remaster import RemasterPreset

        assert isinstance(RemasterPreset.LIGHT, str)
        assert RemasterPreset.LIGHT == "light"

    def test_three_members(self):
        from server.content.crawlers.remaster import RemasterPreset

        assert len(list(RemasterPreset)) == 3


# ─── RemasterConfig ───────────────────────────────────────────────────────────


class TestRemasterConfig:
    def test_defaults(self):
        from server.content.crawlers.remaster import RemasterConfig, RemasterPreset

        cfg = RemasterConfig()
        assert cfg.preset == RemasterPreset.LIGHT
        assert cfg.source_language == "zh"
        assert cfg.target_language == "vi"
        assert cfg.gemini_client is None

    def test_custom_values(self):
        from server.content.crawlers.remaster import RemasterConfig, RemasterPreset

        mock_client = MagicMock()
        cfg = RemasterConfig(
            preset=RemasterPreset.AGGRESSIVE,
            source_language="en",
            target_language="fr",
            gemini_client=mock_client,
        )
        assert cfg.preset == RemasterPreset.AGGRESSIVE
        assert cfg.source_language == "en"
        assert cfg.target_language == "fr"
        assert cfg.gemini_client is mock_client

    def test_is_dataclass(self):
        import dataclasses
        from server.content.crawlers.remaster import RemasterConfig

        assert dataclasses.is_dataclass(RemasterConfig)


# ─── RemasterResult ───────────────────────────────────────────────────────────


class TestRemasterResult:
    def test_fields(self, tmp_path):
        from server.content.crawlers.remaster import RemasterPreset, RemasterResult

        r = RemasterResult(
            output_path=tmp_path / "out.mp4",
            translated_srt=tmp_path / "out_vi.srt",
            original_srt=tmp_path / "out_zh.srt",
            preset=RemasterPreset.LIGHT,
        )
        assert r.output_path == tmp_path / "out.mp4"
        assert r.translated_srt == tmp_path / "out_vi.srt"
        assert r.original_srt == tmp_path / "out_zh.srt"
        assert r.preset == RemasterPreset.LIGHT

    def test_optional_original_srt(self, tmp_path):
        from server.content.crawlers.remaster import RemasterPreset, RemasterResult

        r = RemasterResult(
            output_path=tmp_path / "out.mp4",
            translated_srt=tmp_path / "out_vi.srt",
            original_srt=None,
            preset=RemasterPreset.TRANSLATE_ONLY,
        )
        assert r.original_srt is None

    def test_is_dataclass(self):
        import dataclasses
        from server.content.crawlers.remaster import RemasterResult

        assert dataclasses.is_dataclass(RemasterResult)


# ─── translate_srt ────────────────────────────────────────────────────────────


class TestTranslateSrt:
    def test_happy_path_writes_translated_srt(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        srt = tmp_path / "video_zh.srt"
        srt.write_text(_sample_srt(), encoding="utf-8")

        mock_client = MagicMock()
        mock_client.generate_text.side_effect = ["Xin chào thế giới", "Đây là một bài kiểm tra"]

        cfg = RemasterConfig(
            source_language="zh",
            target_language="vi",
            gemini_client=mock_client,
        )
        result = translate_srt(srt, cfg)

        assert result.name == "video_vi.srt"
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "Xin chào thế giới" in content
        assert "Đây là một bài kiểm tra" in content
        # Timestamps must be preserved
        assert "00:00:01,000 --> 00:00:03,000" in content
        assert "00:00:04,000 --> 00:00:06,000" in content

    def test_returns_original_when_no_gemini_client(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        srt = tmp_path / "video.srt"
        srt.write_text(_sample_srt(), encoding="utf-8")

        cfg = RemasterConfig(gemini_client=None)
        result = translate_srt(srt, cfg)

        assert result == srt

    def test_returns_original_when_srt_missing(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        missing = tmp_path / "nonexistent.srt"
        cfg = RemasterConfig(gemini_client=MagicMock())
        result = translate_srt(missing, cfg)

        assert result == missing

    def test_returns_original_when_srt_empty(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        srt = tmp_path / "empty.srt"
        srt.write_text("", encoding="utf-8")

        cfg = RemasterConfig(gemini_client=MagicMock())
        result = translate_srt(srt, cfg)

        assert result == srt

    def test_falls_back_to_original_text_on_gemini_error(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        srt = tmp_path / "video.srt"
        srt.write_text(_sample_srt(), encoding="utf-8")

        mock_client = MagicMock()
        mock_client.generate_text.side_effect = RuntimeError("API error")

        cfg = RemasterConfig(gemini_client=mock_client)
        result = translate_srt(srt, cfg)

        # Should still write a translated SRT (with original text as fallback)
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        # Original Chinese text preserved as fallback
        assert "你好世界" in content

    def test_strips_source_language_suffix_from_stem(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        srt = tmp_path / "myvideo_zh.srt"
        srt.write_text(_sample_srt(), encoding="utf-8")

        mock_client = MagicMock()
        mock_client.generate_text.return_value = "translated"

        cfg = RemasterConfig(source_language="zh", target_language="vi", gemini_client=mock_client)
        result = translate_srt(srt, cfg)

        # Should be myvideo_vi.srt, not myvideo_zh_vi.srt
        assert result.name == "myvideo_vi.srt"

    def test_gemini_called_once_per_segment(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, translate_srt

        srt = tmp_path / "video.srt"
        srt.write_text(_sample_srt(), encoding="utf-8")

        mock_client = MagicMock()
        mock_client.generate_text.return_value = "translated"

        cfg = RemasterConfig(gemini_client=mock_client)
        translate_srt(srt, cfg)

        # 2 segments → 2 Gemini calls
        assert mock_client.generate_text.call_count == 2


# ─── _escape_srt_path_for_ffmpeg ─────────────────────────────────────────────


class TestEscapeSrtPath:
    def test_windows_backslashes_converted(self, tmp_path):
        from server.content.crawlers.remaster import _escape_srt_path_for_ffmpeg

        p = Path("C:\\Users\\test\\video.srt")
        result = _escape_srt_path_for_ffmpeg(p)
        assert "\\" not in result.replace("\\:", "")  # only escaped colon remains

    def test_windows_drive_colon_escaped(self):
        from server.content.crawlers.remaster import _escape_srt_path_for_ffmpeg

        p = Path("C:/Users/test/video.srt")
        result = _escape_srt_path_for_ffmpeg(p)
        assert "C\\:/" in result

    def test_unix_path_unchanged(self):
        from server.content.crawlers.remaster import _escape_srt_path_for_ffmpeg

        p = Path("/home/user/video.srt")
        result = _escape_srt_path_for_ffmpeg(p)
        assert result == "/home/user/video.srt"


# ─── _build_subtitle_burn_cmd ─────────────────────────────────────────────────


class TestBuildSubtitleBurnCmd:
    def test_returns_list_of_strings(self, tmp_path):
        from server.content.crawlers.remaster import _build_subtitle_burn_cmd

        ffmpeg = tmp_path / "ffmpeg.exe"
        video = tmp_path / "video.mp4"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "out.mp4"

        cmd = _build_subtitle_burn_cmd(ffmpeg, video, srt, output)
        assert isinstance(cmd, list)
        assert all(isinstance(s, str) for s in cmd)

    def test_includes_subtitles_filter(self, tmp_path):
        from server.content.crawlers.remaster import _build_subtitle_burn_cmd

        ffmpeg = tmp_path / "ffmpeg.exe"
        video = tmp_path / "video.mp4"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "out.mp4"

        cmd = _build_subtitle_burn_cmd(ffmpeg, video, srt, output)
        cmd_str = " ".join(cmd)
        assert "subtitles=" in cmd_str

    def test_includes_libx264(self, tmp_path):
        from server.content.crawlers.remaster import _build_subtitle_burn_cmd

        ffmpeg = tmp_path / "ffmpeg.exe"
        cmd = _build_subtitle_burn_cmd(
            ffmpeg, tmp_path / "v.mp4", tmp_path / "s.srt", tmp_path / "o.mp4"
        )
        assert "libx264" in cmd

    def test_output_path_is_last_arg(self, tmp_path):
        from server.content.crawlers.remaster import _build_subtitle_burn_cmd

        ffmpeg = tmp_path / "ffmpeg.exe"
        output = tmp_path / "out.mp4"
        cmd = _build_subtitle_burn_cmd(
            ffmpeg, tmp_path / "v.mp4", tmp_path / "s.srt", output
        )
        assert cmd[-1] == str(output)


# ─── remaster_video ───────────────────────────────────────────────────────────


class TestRemasterVideo:
    def test_translate_only_returns_original_video(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, remaster_video,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        srt = tmp_path / "subs_vi.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nXin chào\n\n", encoding="utf-8")
        output = tmp_path / "out.mp4"

        cfg = RemasterConfig(preset=RemasterPreset.TRANSLATE_ONLY)
        result = remaster_video(video, srt, output, cfg)

        assert result.output_path == video  # original, not output
        assert result.translated_srt == srt
        assert result.original_srt is None
        assert result.preset == RemasterPreset.TRANSLATE_ONLY
        # Output file should NOT be created
        assert not output.exists()

    def test_light_preset_runs_ffmpeg(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, remaster_video,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        srt = tmp_path / "subs_vi.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nXin chào\n\n", encoding="utf-8")
        output = tmp_path / "out.mp4"
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=_ok_run):
            result = remaster_video(video, srt, output, RemasterConfig(preset=RemasterPreset.LIGHT))

        assert result.output_path == output
        assert result.preset == RemasterPreset.LIGHT

    def test_aggressive_preset_falls_back_to_light(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, remaster_video,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        srt = tmp_path / "subs_vi.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nXin chào\n\n", encoding="utf-8")
        output = tmp_path / "out.mp4"
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=_ok_run):
            result = remaster_video(
                video, srt, output, RemasterConfig(preset=RemasterPreset.AGGRESSIVE)
            )

        # Falls back to subtitle burn-in
        assert result.output_path == output
        assert result.preset == RemasterPreset.AGGRESSIVE

    def test_aggressive_preset_emits_clear_warning_R7_5(
        self, tmp_path, caplog
    ):
        """**R7.5** — AGGRESSIVE preset must emit a clear warning that TTS
        replacement is not yet implemented (so the user is not misled into
        thinking the audio was replaced) and must NOT execute any audio
        substitution.  The behaviour falls back to LIGHT (subtitle burn-in)."""
        import logging
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, remaster_video,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        srt = tmp_path / "subs_vi.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nXin chao\n\n", encoding="utf-8")
        output = tmp_path / "out.mp4"
        ffmpeg = _fake_ffmpeg(tmp_path)

        cmds_run: list[list[str]] = []

        def _capture_run(cmd, *args, **kwargs):
            cmds_run.append(list(cmd))
            m = MagicMock()
            m.returncode = 0
            return m

        with caplog.at_level(logging.WARNING, logger="server.content.crawlers.remaster"), \
             _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=_capture_run):
            result = remaster_video(
                video, srt, output, RemasterConfig(preset=RemasterPreset.AGGRESSIVE)
            )

        # 1. A WARNING-level message about TTS not being implemented was logged
        warning_messages = [
            r.getMessage()
            for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert any(
            "TTS" in m and "not yet implemented" in m for m in warning_messages
        ), (
            f"Expected an AGGRESSIVE warning about TTS not yet implemented, "
            f"got: {warning_messages}"
        )

        # 2. The single FFmpeg call burns subs (LIGHT behaviour) and does
        #    NOT do any audio substitution (no -map / -i for a TTS audio file).
        assert len(cmds_run) == 1
        cmd = cmds_run[0]
        # subtitle burn-in path is asserted by the presence of -vf subtitles=
        joined = " ".join(cmd)
        assert "subtitles=" in joined, (
            f"Expected subtitles burn-in, got cmd: {cmd}"
        )
        # audio is copied, not regenerated
        assert "-c:a" in cmd and "copy" in cmd, (
            f"Expected -c:a copy (no audio replacement), got cmd: {cmd}"
        )

        # 3. The result still tags itself as AGGRESSIVE so the caller can see
        #    which preset was requested, but the actual behaviour was LIGHT.
        assert result.preset == RemasterPreset.AGGRESSIVE
        assert result.output_path == output

    def test_raises_when_video_missing(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, remaster_video

        srt = tmp_path / "subs.srt"
        srt.write_text("", encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="Video file not found"):
            remaster_video(
                tmp_path / "nonexistent.mp4",
                srt,
                tmp_path / "out.mp4",
                RemasterConfig(),
            )

    def test_raises_when_ffmpeg_missing_for_light(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, remaster_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        srt = tmp_path / "subs.srt"
        srt.write_text("", encoding="utf-8")

        with patch("server.content.crawlers.remaster.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg not found"):
                remaster_video(video, srt, tmp_path / "out.mp4", RemasterConfig())

    def test_raises_on_ffmpeg_error(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, remaster_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        srt = tmp_path / "subs.srt"
        srt.write_text("", encoding="utf-8")
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
            with pytest.raises(subprocess.CalledProcessError):
                remaster_video(video, srt, tmp_path / "out.mp4", RemasterConfig())

    def test_creates_output_parent_dir(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, remaster_video

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        srt = tmp_path / "subs.srt"
        srt.write_text("", encoding="utf-8")
        output = tmp_path / "nested" / "deep" / "out.mp4"
        ffmpeg = _fake_ffmpeg(tmp_path)

        with _patch_find_ffmpeg(ffmpeg), \
             patch("subprocess.run", side_effect=_ok_run):
            remaster_video(video, srt, output, RemasterConfig())

        assert output.parent.exists()


# ─── VideoRemaster.__init__ ───────────────────────────────────────────────────


class TestVideoRemasterInit:
    def test_accepts_valid_config(self):
        from server.content.crawlers.remaster import RemasterConfig, VideoRemaster

        remaster = VideoRemaster(RemasterConfig())
        assert remaster is not None

    def test_raises_on_invalid_config(self):
        from server.content.crawlers.remaster import VideoRemaster

        with pytest.raises(ValueError, match="RemasterConfig"):
            VideoRemaster("not a config")  # type: ignore[arg-type]

    def test_raises_on_none_config(self):
        from server.content.crawlers.remaster import VideoRemaster

        with pytest.raises(ValueError, match="RemasterConfig"):
            VideoRemaster(None)  # type: ignore[arg-type]


# ─── VideoRemaster.remaster (async) ──────────────────────────────────────────


class TestVideoRemasterAsync:
    """Tests for the async remaster() pipeline with mocked StreamMerger."""

    def test_translate_only_pipeline(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, VideoRemaster,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        srt_path = tmp_path / f"video_{RemasterConfig().source_language}.srt"

        mock_merger = MagicMock()
        mock_merger.extract_subs.return_value = srt_path
        srt_path.write_text(_sample_srt(), encoding="utf-8")

        cfg = RemasterConfig(preset=RemasterPreset.TRANSLATE_ONLY, gemini_client=None)
        remaster = VideoRemaster(cfg)

        with patch(
            "server.content.crawlers.remaster.StreamMerger",
            return_value=mock_merger,
        ):
            result = asyncio.run(remaster.remaster(video, tmp_path))

        assert result.preset == RemasterPreset.TRANSLATE_ONLY
        assert result.output_path == video  # no video modification

    def test_light_pipeline_with_translation(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, VideoRemaster,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        srt_path = tmp_path / "video_zh.srt"
        srt_path.write_text(_sample_srt(), encoding="utf-8")

        mock_merger = MagicMock()
        mock_merger.extract_subs.return_value = srt_path

        mock_client = MagicMock()
        mock_client.generate_text.return_value = "Xin chào"

        ffmpeg = _fake_ffmpeg(tmp_path)
        cfg = RemasterConfig(
            preset=RemasterPreset.LIGHT,
            source_language="zh",
            target_language="vi",
            gemini_client=mock_client,
        )
        remaster = VideoRemaster(cfg)

        with patch(
            "server.content.crawlers.remaster.StreamMerger",
            return_value=mock_merger,
        ), _patch_find_ffmpeg(ffmpeg), \
           patch("subprocess.run", side_effect=_ok_run):
            result = asyncio.run(remaster.remaster(video, tmp_path))

        assert result.preset == RemasterPreset.LIGHT
        assert result.translated_srt.name.endswith("_vi.srt")
        assert result.original_srt == srt_path

    def test_raises_when_video_missing(self, tmp_path):
        from server.content.crawlers.remaster import RemasterConfig, VideoRemaster

        remaster = VideoRemaster(RemasterConfig())

        with pytest.raises(FileNotFoundError, match="Video file not found"):
            asyncio.run(remaster.remaster(tmp_path / "nonexistent.mp4", tmp_path))

    def test_falls_back_to_transcription_when_no_embedded_subs(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, VideoRemaster,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        transcribed_srt = tmp_path / "video.srt"
        transcribed_srt.write_text(_sample_srt(), encoding="utf-8")

        mock_merger = MagicMock()
        mock_merger.extract_subs.return_value = None  # no embedded subs
        mock_merger.transcribe.return_value = transcribed_srt

        cfg = RemasterConfig(preset=RemasterPreset.TRANSLATE_ONLY, gemini_client=None)
        remaster = VideoRemaster(cfg)

        with patch(
            "server.content.crawlers.remaster.StreamMerger",
            return_value=mock_merger,
        ):
            result = asyncio.run(remaster.remaster(video, tmp_path))

        mock_merger.transcribe.assert_called_once()
        assert result.preset == RemasterPreset.TRANSLATE_ONLY

    def test_writes_empty_srt_when_both_extraction_and_transcription_fail(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, VideoRemaster,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")

        mock_merger = MagicMock()
        mock_merger.extract_subs.return_value = None
        mock_merger.transcribe.return_value = None

        cfg = RemasterConfig(preset=RemasterPreset.TRANSLATE_ONLY, gemini_client=None)
        remaster = VideoRemaster(cfg)

        with patch(
            "server.content.crawlers.remaster.StreamMerger",
            return_value=mock_merger,
        ):
            result = asyncio.run(remaster.remaster(video, tmp_path))

        # Pipeline should complete gracefully with empty SRT
        assert result.preset == RemasterPreset.TRANSLATE_ONLY

    def test_handles_ffmpeg_missing_gracefully_in_get_subtitles(self, tmp_path):
        from server.content.crawlers.remaster import (
            RemasterConfig, RemasterPreset, VideoRemaster,
        )

        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")

        cfg = RemasterConfig(preset=RemasterPreset.TRANSLATE_ONLY, gemini_client=None)
        remaster = VideoRemaster(cfg)

        with patch(
            "server.content.crawlers.remaster.StreamMerger",
            side_effect=FileNotFoundError("ffmpeg not found"),
        ):
            result = asyncio.run(remaster.remaster(video, tmp_path))

        # Should complete gracefully with empty SRT
        assert result.preset == RemasterPreset.TRANSLATE_ONLY
