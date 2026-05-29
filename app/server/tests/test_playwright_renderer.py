"""Unit tests for server/render/visual_layer/playwright_renderer.py and gsap_bundle.py.

Tests cover:
- RenderRequest / RenderResult dataclass construction
- PlaywrightRenderer.__init__() raises FileNotFoundError when ffmpeg missing
- PlaywrightRenderer._assemble_video() builds correct FFmpeg command
- PlaywrightRenderer.render() end-to-end with mocked Playwright + FFmpeg
- render_html_to_video() convenience wrapper
- get_gsap_bundle_path() raises RuntimeError when bundle missing
- get_gsap_bundle_path() returns path when bundle exists
- inject_gsap() replaces placeholder with file:/// URI
- inject_gsap() raises RuntimeError when bundle missing

Phase 3.5.1 — Task 3.5.1
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import asyncio

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.render.visual_layer.playwright_renderer import (
    PlaywrightRenderer,
    RenderRequest,
    RenderResult,
    render_html_to_video,
)
from server.render.visual_layer.gsap_bundle import (
    get_gsap_bundle_path,
    inject_gsap,
    _GSAP_PATH,
    _GSAP_PLACEHOLDER,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fake_ffmpeg() -> Path:
    return Path("/fake/ffmpeg.exe")


def _make_request(tmp_path: Path, duration: float = 1.0, fps: int = 5) -> RenderRequest:
    """Create a minimal RenderRequest pointing at a real temp HTML file."""
    template = tmp_path / "test_template.html"
    template.write_text(
        "<html><body><script>"
        "window.__hf = { duration: 1.0, seek(t) {} };"
        "</script></body></html>",
        encoding="utf-8",
    )
    return RenderRequest(
        template_path=template,
        template_vars={"TITLE": "Test Title"},
        duration_sec=duration,
        output_path=tmp_path / "output.webm",
        width=1080,
        height=1920,
        fps=fps,
        background="transparent",
    )


# ─── RenderRequest / RenderResult ─────────────────────────────────────────────

class TestDataclasses:
    def test_render_request_defaults(self, tmp_path):
        req = RenderRequest(
            template_path=tmp_path / "t.html",
            template_vars={},
            duration_sec=3.0,
            output_path=tmp_path / "out.webm",
        )
        assert req.width == 1080
        assert req.height == 1920
        assert req.fps == 30
        assert req.background == "transparent"
        assert req.gsap_auto_download is False

    def test_render_result_fields(self, tmp_path):
        result = RenderResult(
            output_path=tmp_path / "out.webm",
            duration_sec=5.0,
            frame_count=150,
            width=1080,
            height=1920,
            fps=30,
        )
        assert result.frame_count == 150
        assert result.duration_sec == pytest.approx(5.0)


# ─── PlaywrightRenderer.__init__ ─────────────────────────────────────────────

class TestPlaywrightRendererInit:
    def test_raises_when_ffmpeg_missing(self):
        with patch("server.render.visual_layer.playwright_renderer.find_ffmpeg", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffmpeg"):
                PlaywrightRenderer()

    def test_stores_ffmpeg_path(self):
        with patch(
            "server.render.visual_layer.playwright_renderer.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            renderer = PlaywrightRenderer()
        assert renderer._ffmpeg == _fake_ffmpeg()


# ─── PlaywrightRenderer._assemble_video ──────────────────────────────────────

class TestAssembleVideo:
    def _make_renderer(self) -> PlaywrightRenderer:
        with patch(
            "server.render.visual_layer.playwright_renderer.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            return PlaywrightRenderer()

    def test_transparent_uses_yuva420p(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path)
        req.background = "transparent"

        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("server.render.visual_layer.playwright_renderer.subprocess.run", side_effect=_fake_run):
            renderer._assemble_video(req, frames_dir, 5)

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        assert "yuva420p" in cmd
        assert "libvpx-vp9" in cmd
        assert "-auto-alt-ref" in cmd
        assert "0" in cmd  # auto-alt-ref value

    def test_opaque_uses_yuv420p(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path)
        req.background = "black"

        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("server.render.visual_layer.playwright_renderer.subprocess.run", side_effect=_fake_run):
            renderer._assemble_video(req, frames_dir, 5)

        cmd = captured_cmd[0]
        assert "yuv420p" in cmd
        assert "yuva420p" not in cmd

    def test_ffmpeg_binary_is_first_arg(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path)

        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("server.render.visual_layer.playwright_renderer.subprocess.run", side_effect=_fake_run):
            renderer._assemble_video(req, frames_dir, 5)

        assert captured_cmd[0][0] == str(_fake_ffmpeg())

    def test_output_path_is_last_arg(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path)

        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("server.render.visual_layer.playwright_renderer.subprocess.run", side_effect=_fake_run):
            renderer._assemble_video(req, frames_dir, 5)

        assert captured_cmd[0][-1] == str(req.output_path)

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path)

        def _fail_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 1
            mock.stderr = b"FFmpeg error"
            raise subprocess.CalledProcessError(1, cmd, stderr=b"FFmpeg error")

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("server.render.visual_layer.playwright_renderer.subprocess.run", side_effect=_fail_run):
            with pytest.raises(subprocess.CalledProcessError):
                renderer._assemble_video(req, frames_dir, 5)

    def test_fps_passed_to_ffmpeg(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path, fps=24)

        captured_cmd: list[list[str]] = []

        def _fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            mock = MagicMock()
            mock.returncode = 0
            return mock

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        with patch("server.render.visual_layer.playwright_renderer.subprocess.run", side_effect=_fake_run):
            renderer._assemble_video(req, frames_dir, 5)

        cmd = captured_cmd[0]
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "24"


# ─── PlaywrightRenderer.render() — end-to-end with mocked Playwright ─────────

class TestPlaywrightRendererRender:
    """Tests for the full render() method with Playwright mocked out."""

    def _make_renderer(self) -> PlaywrightRenderer:
        with patch(
            "server.render.visual_layer.playwright_renderer.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            return PlaywrightRenderer()

    def _make_playwright_mock(self, frames_dir_ref: list[Path]) -> MagicMock:
        """Build a mock async_playwright context manager that writes fake PNGs."""

        async def _fake_screenshot(**kwargs):
            path = Path(kwargs["path"])
            # Write a minimal 1x1 PNG (valid PNG header)
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n"  # PNG signature
                b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
                b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
                b"\x00\x00\x00IEND\xaeB`\x82"
            )

        page_mock = AsyncMock()
        page_mock.goto = AsyncMock()
        page_mock.wait_for_function = AsyncMock()
        page_mock.evaluate = AsyncMock()
        page_mock.screenshot = AsyncMock(side_effect=_fake_screenshot)

        context_mock = AsyncMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)

        browser_mock = AsyncMock()
        browser_mock.new_context = AsyncMock(return_value=context_mock)
        browser_mock.close = AsyncMock()

        chromium_mock = AsyncMock()
        chromium_mock.launch = AsyncMock(return_value=browser_mock)

        pw_instance = AsyncMock()
        pw_instance.chromium = chromium_mock
        pw_instance.__aenter__ = AsyncMock(return_value=pw_instance)
        pw_instance.__aexit__ = AsyncMock(return_value=False)

        return pw_instance

    @pytest.mark.asyncio
    async def test_render_raises_when_template_missing(self, tmp_path):
        renderer = self._make_renderer()
        req = RenderRequest(
            template_path=tmp_path / "nonexistent.html",
            template_vars={},
            duration_sec=1.0,
            output_path=tmp_path / "out.webm",
        )
        with pytest.raises(FileNotFoundError, match="Template not found"):
            await renderer.render(req)

    @pytest.mark.asyncio
    async def test_render_returns_render_result(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path, duration=0.1, fps=5)  # 1 frame

        pw_mock = self._make_playwright_mock([])

        def _fake_run(cmd, **kwargs):
            # Simulate FFmpeg creating the output file
            Path(cmd[-1]).touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch(
            "server.render.visual_layer.playwright_renderer.async_playwright",
            return_value=pw_mock,
        ):
            with patch(
                "server.render.visual_layer.playwright_renderer.inject_gsap",
                side_effect=lambda html, **kw: html,
            ):
                with patch(
                    "server.render.visual_layer.playwright_renderer.subprocess.run",
                    side_effect=_fake_run,
                ):
                    result = await renderer.render(req)

        assert isinstance(result, RenderResult)
        assert result.output_path == req.output_path
        assert result.duration_sec == pytest.approx(0.1)
        assert result.width == 1080
        assert result.height == 1920
        assert result.fps == 5

    @pytest.mark.asyncio
    async def test_render_frame_count_matches_duration_fps(self, tmp_path):
        renderer = self._make_renderer()
        # 2 seconds at 10 fps = 20 frames
        req = _make_request(tmp_path, duration=2.0, fps=10)

        screenshot_calls: list[dict] = []

        async def _fake_screenshot(**kwargs):
            screenshot_calls.append(kwargs)
            Path(kwargs["path"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        page_mock = AsyncMock()
        page_mock.goto = AsyncMock()
        page_mock.wait_for_function = AsyncMock()
        page_mock.evaluate = AsyncMock()
        page_mock.screenshot = AsyncMock(side_effect=_fake_screenshot)

        context_mock = AsyncMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)

        browser_mock = AsyncMock()
        browser_mock.new_context = AsyncMock(return_value=context_mock)
        browser_mock.close = AsyncMock()

        chromium_mock = AsyncMock()
        chromium_mock.launch = AsyncMock(return_value=browser_mock)

        pw_instance = AsyncMock()
        pw_instance.chromium = chromium_mock
        pw_instance.__aenter__ = AsyncMock(return_value=pw_instance)
        pw_instance.__aexit__ = AsyncMock(return_value=False)

        def _fake_run(cmd, **kwargs):
            Path(cmd[-1]).touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch(
            "server.render.visual_layer.playwright_renderer.async_playwright",
            return_value=pw_instance,
        ):
            with patch(
                "server.render.visual_layer.playwright_renderer.inject_gsap",
                side_effect=lambda html, **kw: html,
            ):
                with patch(
                    "server.render.visual_layer.playwright_renderer.subprocess.run",
                    side_effect=_fake_run,
                ):
                    result = await renderer.render(req)

        assert result.frame_count == 20
        assert len(screenshot_calls) == 20

    @pytest.mark.asyncio
    async def test_render_transparent_uses_omit_background(self, tmp_path):
        renderer = self._make_renderer()
        req = _make_request(tmp_path, duration=0.1, fps=2)
        req.background = "transparent"

        screenshot_kwargs_list: list[dict] = []

        async def _fake_screenshot(**kwargs):
            screenshot_kwargs_list.append(kwargs)
            Path(kwargs["path"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        page_mock = AsyncMock()
        page_mock.goto = AsyncMock()
        page_mock.wait_for_function = AsyncMock()
        page_mock.evaluate = AsyncMock()
        page_mock.screenshot = AsyncMock(side_effect=_fake_screenshot)

        context_mock = AsyncMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)

        browser_mock = AsyncMock()
        browser_mock.new_context = AsyncMock(return_value=context_mock)
        browser_mock.close = AsyncMock()

        chromium_mock = AsyncMock()
        chromium_mock.launch = AsyncMock(return_value=browser_mock)

        pw_instance = AsyncMock()
        pw_instance.chromium = chromium_mock
        pw_instance.__aenter__ = AsyncMock(return_value=pw_instance)
        pw_instance.__aexit__ = AsyncMock(return_value=False)

        def _fake_run(cmd, **kwargs):
            Path(cmd[-1]).touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch(
            "server.render.visual_layer.playwright_renderer.async_playwright",
            return_value=pw_instance,
        ):
            with patch(
                "server.render.visual_layer.playwright_renderer.inject_gsap",
                side_effect=lambda html, **kw: html,
            ):
                with patch(
                    "server.render.visual_layer.playwright_renderer.subprocess.run",
                    side_effect=_fake_run,
                ):
                    await renderer.render(req)

        # All screenshots should have omit_background=True
        for kwargs in screenshot_kwargs_list:
            assert kwargs.get("omit_background") is True

    @pytest.mark.asyncio
    async def test_render_template_vars_substituted(self, tmp_path):
        renderer = self._make_renderer()

        # Template with a variable
        template = tmp_path / "tpl.html"
        template.write_text(
            "<html><body>{{TITLE}}<script>"
            "window.__hf = { duration: 1.0, seek(t) {} };"
            "</script></body></html>",
            encoding="utf-8",
        )

        req = RenderRequest(
            template_path=template,
            template_vars={"TITLE": "My Video"},
            duration_sec=0.1,
            output_path=tmp_path / "out.webm",
            fps=2,
        )

        written_html: list[str] = []

        async def _fake_goto(url, **kwargs):
            # Read the temp HTML that was written
            # URL is file:///path/to/template.html
            html_path = Path(url.replace("file:///", "").replace("file://", ""))
            if html_path.is_file():
                written_html.append(html_path.read_text(encoding="utf-8"))

        async def _fake_screenshot(**kwargs):
            Path(kwargs["path"]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        page_mock = AsyncMock()
        page_mock.goto = AsyncMock(side_effect=_fake_goto)
        page_mock.wait_for_function = AsyncMock()
        page_mock.evaluate = AsyncMock()
        page_mock.screenshot = AsyncMock(side_effect=_fake_screenshot)

        context_mock = AsyncMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)

        browser_mock = AsyncMock()
        browser_mock.new_context = AsyncMock(return_value=context_mock)
        browser_mock.close = AsyncMock()

        chromium_mock = AsyncMock()
        chromium_mock.launch = AsyncMock(return_value=browser_mock)

        pw_instance = AsyncMock()
        pw_instance.chromium = chromium_mock
        pw_instance.__aenter__ = AsyncMock(return_value=pw_instance)
        pw_instance.__aexit__ = AsyncMock(return_value=False)

        def _fake_run(cmd, **kwargs):
            Path(cmd[-1]).touch()
            mock = MagicMock()
            mock.returncode = 0
            return mock

        with patch(
            "server.render.visual_layer.playwright_renderer.async_playwright",
            return_value=pw_instance,
        ):
            with patch(
                "server.render.visual_layer.playwright_renderer.inject_gsap",
                side_effect=lambda html, **kw: html,
            ):
                with patch(
                    "server.render.visual_layer.playwright_renderer.subprocess.run",
                    side_effect=_fake_run,
                ):
                    await renderer.render(req)

        # The written HTML should have the variable substituted
        assert len(written_html) == 1
        assert "My Video" in written_html[0]
        assert "{{TITLE}}" not in written_html[0]


# ─── render_html_to_video convenience wrapper ─────────────────────────────────

class TestRenderHtmlToVideo:
    @pytest.mark.asyncio
    async def test_delegates_to_renderer(self, tmp_path):
        template = tmp_path / "t.html"
        template.write_text(
            "<html><body><script>"
            "window.__hf = { duration: 1.0, seek(t) {} };"
            "</script></body></html>",
            encoding="utf-8",
        )
        output = tmp_path / "out.webm"

        mock_result = RenderResult(
            output_path=output,
            duration_sec=1.0,
            frame_count=30,
            width=1080,
            height=1920,
            fps=30,
        )

        with patch(
            "server.render.visual_layer.playwright_renderer.find_ffmpeg",
            return_value=_fake_ffmpeg(),
        ):
            with patch.object(PlaywrightRenderer, "render", new=AsyncMock(return_value=mock_result)):
                result = await render_html_to_video(
                    html_path=template,
                    output_path=output,
                    duration=1.0,
                    fps=30,
                    template_vars={"KEY": "val"},
                )

        assert result is mock_result


# ─── get_gsap_bundle_path ─────────────────────────────────────────────────────

class TestGetGsapBundlePath:
    def test_raises_when_bundle_missing(self, tmp_path):
        """Should raise RuntimeError with helpful message when bundle not found."""
        with patch(
            "server.render.visual_layer.gsap_bundle._GSAP_PATH",
            tmp_path / "nonexistent.js",
        ):
            with pytest.raises(RuntimeError, match="Missing GSAP vendor bundle"):
                get_gsap_bundle_path()

    def test_returns_path_when_bundle_exists(self, tmp_path):
        """Should return the path when the bundle file exists."""
        fake_gsap = tmp_path / "gsap.min.js"
        fake_gsap.write_text("// GSAP mock", encoding="utf-8")

        with patch("server.render.visual_layer.gsap_bundle._GSAP_PATH", fake_gsap):
            result = get_gsap_bundle_path()

        assert result == fake_gsap

    def test_error_message_contains_curl_command(self, tmp_path):
        """Error message should include a curl download command."""
        with patch(
            "server.render.visual_layer.gsap_bundle._GSAP_PATH",
            tmp_path / "nonexistent.js",
        ):
            with pytest.raises(RuntimeError) as exc_info:
                get_gsap_bundle_path()

        assert "curl" in str(exc_info.value)

    def test_auto_download_calls_download(self, tmp_path):
        """auto_download=True should attempt to download the bundle."""
        fake_gsap = tmp_path / "gsap.min.js"

        def _fake_urlretrieve(url, dest):
            Path(dest).write_text("// GSAP downloaded", encoding="utf-8")

        with patch("server.render.visual_layer.gsap_bundle._GSAP_PATH", fake_gsap):
            with patch("server.render.visual_layer.gsap_bundle._VENDOR_DIR", tmp_path):
                with patch(
                    "server.render.visual_layer.gsap_bundle.urllib.request.urlretrieve",
                    side_effect=_fake_urlretrieve,
                ):
                    result = get_gsap_bundle_path(auto_download=True)

        assert result == fake_gsap
        assert fake_gsap.read_text() == "// GSAP downloaded"


# ─── inject_gsap ─────────────────────────────────────────────────────────────

class TestInjectGsap:
    def test_replaces_placeholder_with_file_uri(self, tmp_path):
        """Should replace {{__VENDOR_GSAP__}} with a file:/// URI."""
        fake_gsap = tmp_path / "gsap.min.js"
        fake_gsap.write_text("// GSAP", encoding="utf-8")

        html = '<script src="{{__VENDOR_GSAP__}}"></script>'

        with patch("server.render.visual_layer.gsap_bundle._GSAP_PATH", fake_gsap):
            result = inject_gsap(html)

        assert _GSAP_PLACEHOLDER not in result
        assert "file:///" in result
        assert "gsap.min.js" in result

    def test_uses_forward_slashes_in_uri(self, tmp_path):
        """File URI should use forward slashes (works on Windows too)."""
        fake_gsap = tmp_path / "gsap.min.js"
        fake_gsap.write_text("// GSAP", encoding="utf-8")

        html = '<script src="{{__VENDOR_GSAP__}}"></script>'

        with patch("server.render.visual_layer.gsap_bundle._GSAP_PATH", fake_gsap):
            result = inject_gsap(html)

        # Should not have Windows-style backslashes in the URI
        uri_start = result.find("file:///")
        uri_end = result.find('"', uri_start)
        uri = result[uri_start:uri_end]
        assert "\\" not in uri

    def test_raises_when_bundle_missing(self, tmp_path):
        """Should raise RuntimeError when GSAP bundle is not present."""
        html = '<script src="{{__VENDOR_GSAP__}}"></script>'

        with patch(
            "server.render.visual_layer.gsap_bundle._GSAP_PATH",
            tmp_path / "nonexistent.js",
        ):
            with pytest.raises(RuntimeError, match="Missing GSAP vendor bundle"):
                inject_gsap(html)

    def test_no_placeholder_html_unchanged(self, tmp_path):
        """HTML without the placeholder should be returned unchanged."""
        fake_gsap = tmp_path / "gsap.min.js"
        fake_gsap.write_text("// GSAP", encoding="utf-8")

        html = "<html><body>No placeholder here</body></html>"

        with patch("server.render.visual_layer.gsap_bundle._GSAP_PATH", fake_gsap):
            result = inject_gsap(html)

        assert result == html

    def test_multiple_placeholders_all_replaced(self, tmp_path):
        """All occurrences of the placeholder should be replaced."""
        fake_gsap = tmp_path / "gsap.min.js"
        fake_gsap.write_text("// GSAP", encoding="utf-8")

        html = (
            '<script src="{{__VENDOR_GSAP__}}"></script>'
            '<script src="{{__VENDOR_GSAP__}}"></script>'
        )

        with patch("server.render.visual_layer.gsap_bundle._GSAP_PATH", fake_gsap):
            result = inject_gsap(html)

        assert result.count(_GSAP_PLACEHOLDER) == 0
        assert result.count("file:///") == 2
