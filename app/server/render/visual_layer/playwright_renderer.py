"""Playwright renderer — HTML+GSAP → WebM/MP4 with alpha channel.

Implements the core visual layer renderer for Phase 3.5.  Uses headless
Chromium (via Playwright) to capture frames from HTML+GSAP templates and
assembles them into a WebM file with alpha channel using FFmpeg.

HfProtocol contract (every template must expose):
    window.__hf = {
        duration: <float>,          // total seconds
        seek(t) { ... }             // set page state to time t (0 ≤ t ≤ duration)
    }

Render pipeline:
    1. Substitute template variables ({{KEY}} → value)
    2. Replace {{__VENDOR_GSAP__}} with local file:/// URI
    3. Write temp HTML to disk, load in headless Chromium
    4. Wait for window.__hf to be available
    5. Capture frames: for each frame i, call window.__hf.seek(i/fps),
       wait for requestAnimationFrame, screenshot with omit_background=True
    6. Assemble PNG sequence → WebM (VP9 + yuva420p) via FFmpeg
    7. Clean up temp files, return RenderResult

FFmpeg binary: vendor/ffmpeg.exe (Windows-native, via find_ffmpeg() from
server.audio.ffmpeg_utils — vendor/ first, then PATH fallback).

Phase 3.5.1 — Task 3.5.1
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from loguru import logger

from server.audio.ffmpeg_utils import find_ffmpeg
from server.render.visual_layer.gsap_bundle import inject_gsap

# Lazy import of Playwright — not available until `pip install playwright`.
# Imported at module level so tests can patch it via
# ``server.render.visual_layer.playwright_renderer.async_playwright``.
try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover
    async_playwright = None  # type: ignore[assignment]

# ─── Types ────────────────────────────────────────────────────────────────────

BackgroundMode = Literal["transparent", "black", "white"]


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class RenderRequest:
    """Input configuration for a single render operation.

    Attributes:
        template_path:   Path to the HTML template file.
        template_vars:   Dict of ``{{KEY}}`` → value substitutions.
        duration_sec:    Total animation duration in seconds.
        output_path:     Destination path for the output WebM file.
        width:           Viewport width in pixels (default 1080).
        height:          Viewport height in pixels (default 1920).
        fps:             Frames per second (default 30).
        background:      Background mode — "transparent" produces alpha
                         channel in the output (default "transparent").
        gsap_auto_download: If True, download GSAP bundle if missing.
    """
    template_path: Path
    template_vars: dict[str, str]
    duration_sec: float
    output_path: Path
    width: int = 1080
    height: int = 1920
    fps: int = 30
    background: BackgroundMode = "transparent"
    gsap_auto_download: bool = False


@dataclass
class RenderResult:
    """Result of a completed render operation.

    Attributes:
        output_path:    Path to the rendered WebM file.
        duration_sec:   Actual duration rendered (seconds).
        frame_count:    Number of frames captured.
        width:          Output width in pixels.
        height:         Output height in pixels.
        fps:            Frames per second used.
    """
    output_path: Path
    duration_sec: float
    frame_count: int
    width: int
    height: int
    fps: int


# ─── Renderer ─────────────────────────────────────────────────────────────────

class PlaywrightRenderer:
    """Async renderer: HTML+GSAP template → WebM with alpha channel.

    Usage::

        renderer = PlaywrightRenderer()
        result = await renderer.render(request)
        print(result.output_path)  # path/to/overlay.webm

    The renderer is stateless — each ``render()`` call is independent.
    Browser instances are not reused between calls (Phase 3.5 simplicity;
    can be optimised in Phase 4+ by passing a shared browser context).

    Raises:
        FileNotFoundError: If ffmpeg is not available.
        RuntimeError: If the GSAP vendor bundle is missing.
        RuntimeError: If the template does not expose ``window.__hf``.
        subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
    """

    def __init__(self) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise FileNotFoundError(
                "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
            )
        self._ffmpeg = ffmpeg
        logger.debug("[playwright_renderer] ffmpeg binary: {}", self._ffmpeg)

    # ── Public API ────────────────────────────────────────────────────────────

    async def render(self, req: RenderRequest) -> RenderResult:
        """Render an HTML+GSAP template to a WebM file with alpha channel.

        Args:
            req: Render request configuration.

        Returns:
            RenderResult with output path and metadata.

        Raises:
            FileNotFoundError: If the template file does not exist.
            RuntimeError: If GSAP bundle is missing or template is invalid.
            subprocess.CalledProcessError: If FFmpeg fails.
        """
        if not req.template_path.is_file():
            raise FileNotFoundError(
                f"Template not found: {req.template_path}"
            )

        req.output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "[playwright_renderer] render start: template={} duration={:.1f}s fps={} {}x{}",
            req.template_path.name,
            req.duration_sec,
            req.fps,
            req.width,
            req.height,
        )

        # Use a temp directory for intermediate files (frames + temp HTML)
        with tempfile.TemporaryDirectory(prefix="aiflow_vl_") as tmp_str:
            tmp_dir = Path(tmp_str)
            frames_dir = tmp_dir / "frames"
            frames_dir.mkdir()

            frame_count = await self._capture_frames(req, tmp_dir, frames_dir)
            self._assemble_video(req, frames_dir, frame_count)

        logger.info(
            "[playwright_renderer] render done → {} ({} frames)",
            req.output_path,
            frame_count,
        )

        return RenderResult(
            output_path=req.output_path,
            duration_sec=req.duration_sec,
            frame_count=frame_count,
            width=req.width,
            height=req.height,
            fps=req.fps,
        )

    # ── Frame capture ─────────────────────────────────────────────────────────

    async def _capture_frames(
        self,
        req: RenderRequest,
        tmp_dir: Path,
        frames_dir: Path,
    ) -> int:
        """Capture PNG frames from the HTML template using Playwright.

        Args:
            req:        Render request.
            tmp_dir:    Temporary directory for the processed HTML file.
            frames_dir: Directory where frame PNGs will be written.

        Returns:
            Number of frames captured.

        Raises:
            RuntimeError: If ``window.__hf`` is not exposed by the template.
        """
        # Verify Playwright is available (module-level import may have failed)
        if async_playwright is None:
            raise ImportError(
                "playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        # 1. Prepare HTML: substitute vars + inject GSAP
        html = req.template_path.read_text(encoding="utf-8")
        html = inject_gsap(html, auto_download=req.gsap_auto_download)
        for key, val in req.template_vars.items():
            html = html.replace(f"{{{{{key}}}}}", str(val))

        # 2. Write processed HTML to temp file
        temp_html = tmp_dir / "template.html"
        temp_html.write_text(html, encoding="utf-8")

        total_frames = max(1, int(req.duration_sec * req.fps))

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": req.width, "height": req.height},
                    device_scale_factor=1,
                )
                page = await context.new_page()

                # 3. Load the template
                await page.goto(f"file:///{temp_html.as_posix()}")

                # 4. Wait for HfProtocol contract
                try:
                    await page.wait_for_function(
                        "window.__hf && typeof window.__hf.seek === 'function'",
                        timeout=10_000,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"Template {req.template_path.name} does not expose window.__hf.seek(). "
                        f"Check that GSAP loaded and the <script> block runs correctly. "
                        f"Original error: {exc}"
                    ) from exc

                logger.debug(
                    "[playwright_renderer] window.__hf ready, capturing {} frames …",
                    total_frames,
                )

                # 5. Capture frames
                for i in range(total_frames):
                    t = i / req.fps
                    await page.evaluate(f"window.__hf.seek({t})")
                    # Wait one animation frame for GSAP to repaint
                    await page.evaluate("new Promise(r => requestAnimationFrame(r))")

                    frame_path = frames_dir / f"frame_{i:05d}.png"
                    screenshot_kwargs: dict = {
                        "path": str(frame_path),
                        "type": "png",
                    }
                    if req.background == "transparent":
                        screenshot_kwargs["omit_background"] = True

                    await page.screenshot(**screenshot_kwargs)

                    if (i + 1) % 30 == 0 or i == total_frames - 1:
                        logger.debug(
                            "[playwright_renderer] captured {}/{} frames",
                            i + 1,
                            total_frames,
                        )

            finally:
                await browser.close()

        return total_frames

    # ── Video assembly ────────────────────────────────────────────────────────

    def _assemble_video(
        self,
        req: RenderRequest,
        frames_dir: Path,
        frame_count: int,
    ) -> None:
        """Assemble PNG frame sequence into a WebM file using FFmpeg.

        Uses VP9 codec with yuva420p pixel format to preserve the alpha
        channel captured from Playwright screenshots.

        Args:
            req:         Render request (for fps, output_path, background).
            frames_dir:  Directory containing frame_00000.png … frame_NNNNN.png
            frame_count: Total number of frames (used for logging only).

        Raises:
            subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
        """
        logger.debug(
            "[playwright_renderer] assembling {} frames → {}",
            frame_count,
            req.output_path,
        )

        if req.background == "transparent":
            # VP9 with alpha channel (yuva420p)
            cmd = [
                str(self._ffmpeg), "-y",
                "-r", str(req.fps),
                "-i", str(frames_dir / "frame_%05d.png"),
                "-c:v", "libvpx-vp9",
                "-pix_fmt", "yuva420p",
                "-b:v", "2M",
                "-auto-alt-ref", "0",   # required for VP9 alpha
                str(req.output_path),
            ]
        else:
            # Opaque output — use VP9 without alpha (or could use libx264)
            cmd = [
                str(self._ffmpeg), "-y",
                "-r", str(req.fps),
                "-i", str(frames_dir / "frame_%05d.png"),
                "-c:v", "libvpx-vp9",
                "-pix_fmt", "yuv420p",
                "-b:v", "2M",
                str(req.output_path),
            ]

        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            logger.error(
                "[playwright_renderer] FFmpeg failed (rc={}): {}",
                result.returncode,
                stderr[-2000:],
            )
            raise subprocess.CalledProcessError(
                returncode=result.returncode,
                cmd=cmd,
                stderr=result.stderr,
            )


# ─── Convenience function ─────────────────────────────────────────────────────

async def render_html_to_video(
    html_path: Path,
    output_path: Path,
    duration: float,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    template_vars: Optional[dict[str, str]] = None,
    background: BackgroundMode = "transparent",
    gsap_auto_download: bool = False,
) -> RenderResult:
    """Convenience wrapper — create a PlaywrightRenderer and render one template.

    Args:
        html_path:          Path to the HTML template file.
        output_path:        Destination path for the output WebM file.
        duration:           Total animation duration in seconds.
        fps:                Frames per second (default 30).
        width:              Viewport width in pixels (default 1080).
        height:             Viewport height in pixels (default 1920).
        template_vars:      Optional dict of ``{{KEY}}`` → value substitutions.
        background:         Background mode (default "transparent").
        gsap_auto_download: Download GSAP bundle if missing (default False).

    Returns:
        RenderResult with output path and metadata.

    Raises:
        FileNotFoundError: If ffmpeg or the template is not found.
        RuntimeError: If GSAP bundle is missing or template is invalid.
        subprocess.CalledProcessError: If FFmpeg fails.
    """
    renderer = PlaywrightRenderer()
    req = RenderRequest(
        template_path=html_path,
        template_vars=template_vars or {},
        duration_sec=duration,
        output_path=output_path,
        width=width,
        height=height,
        fps=fps,
        background=background,
        gsap_auto_download=gsap_auto_download,
    )
    return await renderer.render(req)
