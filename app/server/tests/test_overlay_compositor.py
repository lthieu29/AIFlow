"""Unit tests for server/render/overlay_compositor.py.

Tests cover:
- OverlayConfig / OverlayResult dataclass construction
- OverlayCompositor.__init__() raises FileNotFoundError when ffmpeg missing
- build_overlay_command() produces correct FFmpeg filter_complex
- OverlayCompositor.composite() end-to-end with mocked FFmpeg
- composite_overlay() convenience wrapper
- overlay_template_on_video() high-level async helper with mocked renderer + compositor

Phase 3.5.4 — Task 3.5.4
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import asyncio

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.render.overlay_compositor import (
    OverlayCompositor,
    OverlayConfig,
    OverlayResult,
    build_overlay_command,
    composite_overlay,
    overlay_template_on_video,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fake_ffmpeg() -> Path:
    return Path("/fake/ffmpeg.exe")


def _make_config(tmp_path: Path, **kwargs) -> OverlayConfig:
    """Create a minimal OverlayConfig with real temp files."""
    base = tmp_path / "base.mp4"
    base.write_bytes(b"fake mp4 data")
    overlay = tmp_path / "overlay.webm"
    overlay.write_bytes(b"fake webm data")
    output = tmp_path / "output.mp4"

    defaults = dict(
        base_video=base,
        overlay_video=overlay,
        output_path=output,
        start_time=0.0,
        x=0,
        y=0,
        scale=1.0,
    )
    defaults.update(kwargs)
    return OverlayConfig(**defaults)


# ─── OverlayConfig / OverlayResult dataclasses ────────────────────────────────

class TestDataclasses:
    def test_overlay_config_defaults(self, tmp_path):
        base = tmp_path / "base.mp4"
        overlay = tmp_path / "overlay.webm"
        output = tmp_path / "out.mp4"
        config = OverlayConfig(
            base_video=base,
            overlay_video=overlay,
            output_path=output,
        )
        assert config.start_time == 0.0
        assert config.x == 0
        assert config.y == 0
        assert config.scale == 1.0

    def test_overlay_config_custom_values(self, tmp_path):
        base = tmp_path / "base.mp4"
        overlay = tmp_path / "overlay.webm"
        output = tmp_path / "out.mp4"
        config = OverlayConfig(
            base_video=base,
            overlay_video=overlay,
            output_path=output,
            start_time=2.5,
            x=100,
            y=200,
            scale=0.5,
        )
        assert config.start_time == pytest.approx(2.5)
        assert config.x == 100
        assert config.y == 200
        assert config.scale == pytest.approx(0.5)

    def test_overlay_result_fields(self, tmp_path):
        result = OverlayResult(
            output_path=tmp_path / "out.mp4",
            duration=12.5,
        )
        assert result.duration == pytest.approx(12.5)
        assert result.output_path == tmp_path / "out.mp4"


# ─── OverlayCompositor.__init__ ───────────────────────────────────────────────

class TestOverlayCompositorInit:
    def test_raises_when_ffmpeg_missing(self):
        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=None,
        ):
            with pytest.raises(FileNotFoundError, match="ffmpeg"):
                OverlayCompositor()

    def test_stores_ffmpeg_path(self):
        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            compositor = OverlayCompositor()
        assert compositor._ffmpeg == _fake_ffmpeg()


# ─── build_overlay_command ────────────────────────────────────────────────────

class TestBuildOverlayCommand:
    def _make_compositor(self) -> OverlayCompositor:
        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            return OverlayCompositor()

    def test_ffmpeg_binary_is_first_arg(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        assert cmd[0] == str(_fake_ffmpeg())

    def test_output_path_is_last_arg(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        assert cmd[-1] == str(config.output_path)

    def test_base_video_is_first_input(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        # First -i should be the base video
        i_idx = cmd.index("-i")
        assert cmd[i_idx + 1] == str(config.base_video)

    def test_overlay_video_is_second_input(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        # Find all -i occurrences
        i_indices = [i for i, v in enumerate(cmd) if v == "-i"]
        assert len(i_indices) >= 2
        assert cmd[i_indices[1] + 1] == str(config.overlay_video)

    def test_filter_complex_contains_scale(self, tmp_path):
        config = _make_config(tmp_path, scale=0.5)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        fc_idx = cmd.index("-filter_complex")
        filter_str = cmd[fc_idx + 1]
        assert "scale=iw*0.5:ih*0.5" in filter_str

    def test_filter_complex_contains_overlay_position(self, tmp_path):
        config = _make_config(tmp_path, x=100, y=200)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        fc_idx = cmd.index("-filter_complex")
        filter_str = cmd[fc_idx + 1]
        assert "overlay=100:200" in filter_str

    def test_filter_complex_contains_between_enable(self, tmp_path):
        config = _make_config(tmp_path, start_time=2.0)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=3.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        fc_idx = cmd.index("-filter_complex")
        filter_str = cmd[fc_idx + 1]
        # start=2.0, end=2.0+3.0=5.0
        assert "between(t," in filter_str
        assert "2.000000" in filter_str
        assert "5.000000" in filter_str

    def test_filter_complex_maps_out_stream(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        assert "-map" in cmd
        map_idx = cmd.index("-map")
        assert cmd[map_idx + 1] == "[out]"

    def test_maps_audio_from_base_video(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        # Find all -map values
        map_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-map"]
        assert "0:a?" in map_values

    def test_encodes_h264_aac(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        assert "libx264" in cmd
        assert "aac" in cmd

    def test_movflags_faststart(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        assert "-movflags" in cmd
        mf_idx = cmd.index("-movflags")
        assert "+faststart" in cmd[mf_idx + 1]

    def test_probe_failure_uses_fallback_duration(self, tmp_path):
        """When probe_duration raises, a generous fallback end time is used."""
        config = _make_config(tmp_path, start_time=1.0)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            side_effect=Exception("probe failed"),
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        fc_idx = cmd.index("-filter_complex")
        filter_str = cmd[fc_idx + 1]
        # Fallback is 3600s, so end = 1.0 + 3600 = 3601.0
        assert "3601.000000" in filter_str

    def test_scale_1_produces_iw_times_1(self, tmp_path):
        config = _make_config(tmp_path, scale=1.0)
        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            cmd = build_overlay_command(config, config.output_path, _fake_ffmpeg())
        fc_idx = cmd.index("-filter_complex")
        filter_str = cmd[fc_idx + 1]
        assert "scale=iw*1.0:ih*1.0" in filter_str


# ─── OverlayCompositor.composite ─────────────────────────────────────────────

class TestOverlayCompositorComposite:
    def _make_compositor(self) -> OverlayCompositor:
        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            return OverlayCompositor()

    def test_raises_when_base_video_missing(self, tmp_path):
        compositor = self._make_compositor()
        config = OverlayConfig(
            base_video=tmp_path / "nonexistent.mp4",
            overlay_video=tmp_path / "overlay.webm",
            output_path=tmp_path / "out.mp4",
        )
        with pytest.raises(FileNotFoundError, match="Base video not found"):
            compositor.composite(config)

    def test_raises_when_overlay_missing(self, tmp_path):
        compositor = self._make_compositor()
        base = tmp_path / "base.mp4"
        base.write_bytes(b"fake")
        config = OverlayConfig(
            base_video=base,
            overlay_video=tmp_path / "nonexistent.webm",
            output_path=tmp_path / "out.mp4",
        )
        with pytest.raises(FileNotFoundError, match="Overlay video not found"):
            compositor.composite(config)

    def test_composite_returns_overlay_result(self, tmp_path):
        compositor = self._make_compositor()
        config = _make_config(tmp_path)

        def _fake_run(cmd, **kwargs):
            # Simulate FFmpeg creating the output file
            Path(cmd[-1]).touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch(
            "server.render.overlay_compositor._run_ffmpeg_cmd",
        ) as mock_run:
            mock_run.side_effect = lambda cmd, **kw: Path(cmd[-1]).touch()
            with patch(
                "server.render.overlay_compositor.probe_duration",
                return_value=10.0,
            ):
                result = compositor.composite(config)

        assert isinstance(result, OverlayResult)
        assert result.output_path == config.output_path

    def test_composite_creates_output_parent_dir(self, tmp_path):
        compositor = self._make_compositor()
        nested_output = tmp_path / "subdir" / "deep" / "output.mp4"
        config = _make_config(tmp_path, output_path=nested_output)

        with patch(
            "server.render.overlay_compositor._run_ffmpeg_cmd",
        ) as mock_run:
            mock_run.side_effect = lambda cmd, **kw: nested_output.touch()
            with patch(
                "server.render.overlay_compositor.probe_duration",
                return_value=5.0,
            ):
                compositor.composite(config)

        assert nested_output.parent.is_dir()

    def test_composite_probes_output_duration(self, tmp_path):
        compositor = self._make_compositor()
        config = _make_config(tmp_path)

        probe_calls: list[Path] = []

        def _fake_probe(path: Path) -> float:
            probe_calls.append(path)
            return 15.0

        with patch(
            "server.render.overlay_compositor._run_ffmpeg_cmd",
        ) as mock_run:
            mock_run.side_effect = lambda cmd, **kw: config.output_path.touch()
            with patch(
                "server.render.overlay_compositor.probe_duration",
                side_effect=_fake_probe,
            ):
                result = compositor.composite(config)

        # First probe call is for overlay duration (in build_overlay_command),
        # second is for output duration
        assert result.duration == pytest.approx(15.0)

    def test_composite_falls_back_to_base_duration_on_probe_failure(self, tmp_path):
        compositor = self._make_compositor()
        config = _make_config(tmp_path)

        call_count = [0]

        def _fake_probe(path: Path) -> float:
            call_count[0] += 1
            if call_count[0] == 1:
                return 5.0  # overlay duration (build_overlay_command)
            raise Exception("probe failed")  # output probe fails

        with patch(
            "server.render.overlay_compositor._run_ffmpeg_cmd",
        ) as mock_run:
            mock_run.side_effect = lambda cmd, **kw: config.output_path.touch()
            with patch(
                "server.render.overlay_compositor.probe_duration",
                side_effect=_fake_probe,
            ):
                # Should not raise — falls back to base video probe
                # (which also fails → duration=0.0)
                result = compositor.composite(config)

        assert result.duration == pytest.approx(0.0)

    def test_composite_raises_on_ffmpeg_failure(self, tmp_path):
        compositor = self._make_compositor()
        config = _make_config(tmp_path)

        with patch(
            "server.render.overlay_compositor.probe_duration",
            return_value=5.0,
        ):
            with patch(
                "server.render.overlay_compositor._run_ffmpeg_cmd",
                side_effect=subprocess.CalledProcessError(1, ["ffmpeg"], stderr=b"error"),
            ):
                with pytest.raises(subprocess.CalledProcessError):
                    compositor.composite(config)


# ─── composite_overlay convenience wrapper ────────────────────────────────────

class TestCompositeOverlay:
    def test_delegates_to_compositor(self, tmp_path):
        config = _make_config(tmp_path)
        expected_result = OverlayResult(output_path=config.output_path, duration=5.0)

        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            with patch.object(
                OverlayCompositor,
                "composite",
                return_value=expected_result,
            ) as mock_composite:
                result = composite_overlay(config)

        mock_composite.assert_called_once_with(config)
        assert result is expected_result

    def test_raises_when_ffmpeg_missing(self, tmp_path):
        config = _make_config(tmp_path)
        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=None,
        ):
            with pytest.raises(FileNotFoundError, match="ffmpeg"):
                composite_overlay(config)


# ─── overlay_template_on_video high-level async helper ───────────────────────

class TestOverlayTemplateOnVideo:
    @pytest.mark.asyncio
    async def test_raises_for_unknown_template(self, tmp_path):
        base = tmp_path / "base.mp4"
        base.write_bytes(b"fake")
        with pytest.raises(KeyError):
            await overlay_template_on_video(
                base_video=base,
                template_name="nonexistent_template",
                template_vars={},
                output_path=tmp_path / "out.mp4",
            )

    @pytest.mark.asyncio
    async def test_calls_renderer_with_template_metadata(self, tmp_path):
        base = tmp_path / "base.mp4"
        base.write_bytes(b"fake")
        output = tmp_path / "out.mp4"

        mock_render_result = MagicMock()
        mock_render_result.output_path = tmp_path / "overlay.webm"

        mock_overlay_result = OverlayResult(output_path=output, duration=10.0)

        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            with patch(
                "server.render.overlay_compositor.PlaywrightRenderer",
            ) as MockRenderer:
                renderer_instance = AsyncMock()
                renderer_instance.render = AsyncMock(return_value=mock_render_result)
                MockRenderer.return_value = renderer_instance

                with patch.object(
                    OverlayCompositor,
                    "composite",
                    return_value=mock_overlay_result,
                ):
                    with patch(
                        "server.render.overlay_compositor.get_template_path",
                        return_value=tmp_path / "intro_card.html",
                    ):
                        result = await overlay_template_on_video(
                            base_video=base,
                            template_name="intro_card",
                            template_vars={"TITLE": "Test", "SUBTITLE": "Sub", "BRAND": "Brand"},
                            output_path=output,
                            start_time=1.0,
                            x=50,
                            y=100,
                            scale=0.8,
                        )

        assert result is mock_overlay_result
        # Verify renderer was called
        renderer_instance.render.assert_called_once()
        render_req = renderer_instance.render.call_args[0][0]
        assert render_req.template_vars == {"TITLE": "Test", "SUBTITLE": "Sub", "BRAND": "Brand"}
        assert render_req.background == "transparent"

    @pytest.mark.asyncio
    async def test_passes_start_time_x_y_scale_to_compositor(self, tmp_path):
        base = tmp_path / "base.mp4"
        base.write_bytes(b"fake")
        output = tmp_path / "out.mp4"

        mock_render_result = MagicMock()
        mock_render_result.output_path = tmp_path / "overlay.webm"

        mock_overlay_result = OverlayResult(output_path=output, duration=10.0)
        composite_configs: list[OverlayConfig] = []

        def _fake_composite(config: OverlayConfig) -> OverlayResult:
            composite_configs.append(config)
            return mock_overlay_result

        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            with patch(
                "server.render.overlay_compositor.PlaywrightRenderer",
            ) as MockRenderer:
                renderer_instance = AsyncMock()
                renderer_instance.render = AsyncMock(return_value=mock_render_result)
                MockRenderer.return_value = renderer_instance

                with patch.object(
                    OverlayCompositor,
                    "composite",
                    side_effect=_fake_composite,
                ):
                    with patch(
                        "server.render.overlay_compositor.get_template_path",
                        return_value=tmp_path / "lower_third.html",
                    ):
                        await overlay_template_on_video(
                            base_video=base,
                            template_name="lower_third",
                            template_vars={"NAME": "Alice", "TITLE": "CEO"},
                            output_path=output,
                            start_time=3.5,
                            x=80,
                            y=1600,
                            scale=0.9,
                        )

        assert len(composite_configs) == 1
        cfg = composite_configs[0]
        assert cfg.start_time == pytest.approx(3.5)
        assert cfg.x == 80
        assert cfg.y == 1600
        assert cfg.scale == pytest.approx(0.9)
        assert cfg.base_video == base
        assert cfg.output_path == output

    @pytest.mark.asyncio
    async def test_returns_overlay_result(self, tmp_path):
        base = tmp_path / "base.mp4"
        base.write_bytes(b"fake")
        output = tmp_path / "out.mp4"

        expected = OverlayResult(output_path=output, duration=7.5)

        with patch(
            "server.render.overlay_compositor.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            with patch(
                "server.render.overlay_compositor.PlaywrightRenderer",
            ) as MockRenderer:
                renderer_instance = AsyncMock()
                renderer_instance.render = AsyncMock(return_value=MagicMock())
                MockRenderer.return_value = renderer_instance

                with patch.object(
                    OverlayCompositor,
                    "composite",
                    return_value=expected,
                ):
                    with patch(
                        "server.render.overlay_compositor.get_template_path",
                        return_value=tmp_path / "outro_card.html",
                    ):
                        result = await overlay_template_on_video(
                            base_video=base,
                            template_name="outro_card",
                            template_vars={"TITLE": "Bye", "CTA": "Subscribe", "BRAND": "X"},
                            output_path=output,
                        )

        assert result is expected


# ─── server.render __init__ exports ──────────────────────────────────────────

class TestRenderPackageExports:
    def test_overlay_compositor_exported(self):
        from server.render import OverlayCompositor
        assert OverlayCompositor is not None

    def test_overlay_config_exported(self):
        from server.render import OverlayConfig
        assert OverlayConfig is not None

    def test_overlay_result_exported(self):
        from server.render import OverlayResult
        assert OverlayResult is not None

    def test_build_overlay_command_exported(self):
        from server.render import build_overlay_command
        assert callable(build_overlay_command)

    def test_composite_overlay_exported(self):
        from server.render import composite_overlay
        assert callable(composite_overlay)

    def test_overlay_template_on_video_exported(self):
        from server.render import overlay_template_on_video
        assert callable(overlay_template_on_video)

    def test_existing_exports_still_present(self):
        """Ensure Phase 3.3 exports are not broken."""
        from server.render import (
            VideoComposer,
            compose_video,
            ComposeConfig,
            ComposeResult,
            ClipInput,
            SubtitleConfig,
            SubtitleSegment,
            reconcile_durations,
        )
        assert VideoComposer is not None
