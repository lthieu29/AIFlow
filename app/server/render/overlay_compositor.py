"""Overlay compositor — composites a WebM (with alpha) onto a base MP4 video.

Implements the FFmpeg overlay filter graph for Phase 3.5.4.  Takes a Veo3
base video (MP4) and a visual-layer overlay (WebM with VP9 alpha channel)
and produces a composited MP4 output.

High-level async helper ``overlay_template_on_video()`` ties together the
template registry, PlaywrightRenderer, and OverlayCompositor into a single
call.

FFmpeg filter graph used::

    [1:v]scale=iw*{scale}:ih*{scale}[ov];
    [0:v][ov]overlay={x}:{y}:enable='between(t,{start},{end})'[out]

Output is encoded as H.264 + AAC with ``-movflags +faststart``.

FFmpeg binary: vendor/ffmpeg.exe (Windows-native, via find_ffmpeg() from
server.audio.ffmpeg_utils — vendor/ first, then PATH fallback).

Phase 3.5.4 — Task 3.5.4
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from server.audio.ffmpeg_utils import find_ffmpeg, probe_duration
from server.render.visual_layer.playwright_renderer import PlaywrightRenderer, RenderRequest
from server.render.visual_layer.template_registry import TEMPLATE_REGISTRY, get_template_path


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class OverlayConfig:
    """Configuration for a single overlay composite operation.

    Attributes:
        base_video:    Path to the Veo3 base video (MP4).
        overlay_video: Path to the visual layer WebM with alpha channel.
        output_path:   Destination path for the composited MP4.
        start_time:    When to start the overlay in seconds (default 0.0).
        x:             Horizontal position of the overlay in pixels (default 0).
        y:             Vertical position of the overlay in pixels (default 0).
        scale:         Scale factor applied to the overlay (default 1.0).
    """
    base_video: Path
    overlay_video: Path
    output_path: Path
    start_time: float = 0.0
    x: int = 0
    y: int = 0
    scale: float = 1.0


@dataclass
class OverlayResult:
    """Result of a completed overlay composite operation.

    Attributes:
        output_path: Path to the composited MP4 file.
        duration:    Total duration of the output video in seconds.
    """
    output_path: Path
    duration: float


# ─── FFmpeg command builder ───────────────────────────────────────────────────

def build_overlay_command(
    config: OverlayConfig,
    output_path: Path,
    ffmpeg_bin: Path,
) -> list[str]:
    """Build the FFmpeg argument list for the overlay composite operation.

    Constructs a filter_complex that:
    1. Scales the overlay WebM by *config.scale*.
    2. Overlays the scaled WebM onto the base video at (*config.x*, *config.y*)
       for the duration of the overlay clip, starting at *config.start_time*.
    3. Maps the composited video stream and the base video's audio stream.
    4. Encodes to H.264 + AAC MP4 with ``-movflags +faststart``.

    The overlay end time is derived by probing the overlay WebM duration.
    If probing fails, a generous fallback of 3600 s (1 hour) is used so the
    overlay is always visible for its full natural duration.

    Args:
        config:      Overlay configuration.
        output_path: Destination file path for the composited MP4.
        ffmpeg_bin:  Absolute path to the ffmpeg binary.

    Returns:
        List of strings suitable for ``subprocess.run()``.
    """
    # Probe overlay duration for the enable expression end time.
    try:
        overlay_duration = probe_duration(config.overlay_video)
    except Exception:  # noqa: BLE001
        overlay_duration = 3600.0  # generous fallback

    start = config.start_time
    end = start + overlay_duration
    scale = config.scale
    x = config.x
    y = config.y

    # Filter graph:
    #   [1:v]scale=iw*{scale}:ih*{scale}[ov]
    #   [0:v][ov]overlay={x}:{y}:enable='between(t,{start},{end})'[out]
    filter_complex = (
        f"[1:v]scale=iw*{scale}:ih*{scale}[ov];"
        f"[0:v][ov]overlay={x}:{y}:enable='between(t,{start:.6f},{end:.6f})'[out]"
    )

    cmd: list[str] = [
        str(ffmpeg_bin), "-y",
        # Input 0: base video (MP4)
        "-i", str(config.base_video),
        # Input 1: overlay WebM (with alpha)
        "-i", str(config.overlay_video),
        "-filter_complex", filter_complex,
        # Map composited video
        "-map", "[out]",
        # Map audio from base video (stream 0, audio track 0)
        "-map", "0:a?",
        # Encode H.264 + AAC
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "256k",
        # Faststart for streaming
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd


# ─── Compositor ───────────────────────────────────────────────────────────────

class OverlayCompositor:
    """Composites a WebM overlay (with alpha) onto a base MP4 video.

    Usage::

        compositor = OverlayCompositor()
        result = compositor.composite(config)
        print(result.output_path)  # path/to/composited.mp4

    The compositor is stateless — each ``composite()`` call is independent.

    Raises:
        FileNotFoundError: If ffmpeg is not available at construction time.
    """

    def __init__(self) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            raise FileNotFoundError(
                "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
            )
        self._ffmpeg = ffmpeg
        logger.debug("[overlay_compositor] ffmpeg binary: {}", self._ffmpeg)

    # ── Public API ────────────────────────────────────────────────────────────

    def composite(self, config: OverlayConfig) -> OverlayResult:
        """Composite the overlay WebM onto the base MP4 video.

        Steps:
            1. Build the FFmpeg filter_complex command.
            2. Execute FFmpeg.
            3. Probe the output duration.
            4. Return OverlayResult.

        Args:
            config: Overlay configuration.

        Returns:
            OverlayResult with output_path and duration.

        Raises:
            FileNotFoundError: If the base video or overlay file does not exist.
            subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
        """
        if not config.base_video.is_file():
            raise FileNotFoundError(
                f"Base video not found: {config.base_video}"
            )
        if not config.overlay_video.is_file():
            raise FileNotFoundError(
                f"Overlay video not found: {config.overlay_video}"
            )

        config.output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "[overlay_compositor] composite start: base={} overlay={} start={:.2f}s x={} y={} scale={}",
            config.base_video.name,
            config.overlay_video.name,
            config.start_time,
            config.x,
            config.y,
            config.scale,
        )

        cmd = build_overlay_command(config, config.output_path, self._ffmpeg)

        logger.debug("[overlay_compositor] FFmpeg cmd: {}", " ".join(cmd))
        _run_ffmpeg_cmd(cmd)

        # Probe output duration
        try:
            duration = probe_duration(config.output_path)
        except Exception:  # noqa: BLE001
            # Fall back to base video duration if probing fails
            try:
                duration = probe_duration(config.base_video)
            except Exception:  # noqa: BLE001
                duration = 0.0

        logger.info(
            "[overlay_compositor] composite done → {} ({:.2f}s)",
            config.output_path,
            duration,
        )
        return OverlayResult(output_path=config.output_path, duration=duration)


# ─── Convenience wrapper ──────────────────────────────────────────────────────

def composite_overlay(config: OverlayConfig) -> OverlayResult:
    """Convenience wrapper — create an OverlayCompositor and run composite().

    Args:
        config: Overlay configuration.

    Returns:
        OverlayResult with output_path and duration.

    Raises:
        FileNotFoundError: If ffmpeg is not available.
        subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
    """
    return OverlayCompositor().composite(config)


# ─── High-level async helper ──────────────────────────────────────────────────

async def overlay_template_on_video(
    base_video: Path,
    template_name: str,
    template_vars: dict[str, str],
    output_path: Path,
    start_time: float = 0.0,
    x: int = 0,
    y: int = 0,
    scale: float = 1.0,
    fps: int = 30,
    gsap_auto_download: bool = False,
) -> OverlayResult:
    """Render an HTML template and composite it onto a base video.

    High-level async function that ties together the template registry,
    PlaywrightRenderer, and OverlayCompositor:

    1. Look up *template_name* in ``TEMPLATE_REGISTRY`` to get metadata
       (duration, width, height).
    2. Resolve the template HTML path via ``get_template_path()``.
    3. Render the HTML template → WebM (with alpha) using
       ``PlaywrightRenderer``.
    4. Composite the WebM onto *base_video* using ``OverlayCompositor``.
    5. Return the ``OverlayResult``.

    Intermediate WebM files are written to a sibling temp directory next to
    *output_path* and cleaned up after compositing.

    Args:
        base_video:         Path to the Veo3 base video (MP4).
        template_name:      Name of the registered template (e.g. ``"intro_card"``).
        template_vars:      Dict of ``{{KEY}}`` → value substitutions for the template.
        output_path:        Destination path for the composited MP4.
        start_time:         When to start the overlay in seconds (default 0.0).
        x:                  Horizontal position of the overlay (default 0).
        y:                  Vertical position of the overlay (default 0).
        scale:              Scale factor for the overlay (default 1.0).
        fps:                Frames per second for rendering (default 30).
        gsap_auto_download: Download GSAP bundle if missing (default False).

    Returns:
        OverlayResult with output_path and duration.

    Raises:
        KeyError: If *template_name* is not in ``TEMPLATE_REGISTRY``.
        FileNotFoundError: If the template file, base video, or ffmpeg is missing.
        RuntimeError: If the GSAP bundle is missing or the template is invalid.
        subprocess.CalledProcessError: If FFmpeg fails.
    """
    # 1. Look up template metadata
    meta = TEMPLATE_REGISTRY[template_name]
    template_path = get_template_path(template_name)

    logger.info(
        "[overlay_compositor] overlay_template_on_video: template={} base={} start={:.2f}s",
        template_name,
        base_video.name,
        start_time,
    )

    # 2. Render HTML → WebM in a temp directory
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aiflow_overlay_") as tmp_str:
        tmp_dir = Path(tmp_str)
        overlay_webm = tmp_dir / f"{template_name}_overlay.webm"

        renderer = PlaywrightRenderer()
        render_req = RenderRequest(
            template_path=template_path,
            template_vars=template_vars,
            duration_sec=meta.duration,
            output_path=overlay_webm,
            width=meta.width,
            height=meta.height,
            fps=fps,
            background="transparent",
            gsap_auto_download=gsap_auto_download,
        )
        await renderer.render(render_req)

        logger.debug(
            "[overlay_compositor] rendered overlay WebM: {} ({:.1f}s)",
            overlay_webm,
            meta.duration,
        )

        # 3. Composite WebM onto base video
        compositor = OverlayCompositor()
        overlay_config = OverlayConfig(
            base_video=base_video,
            overlay_video=overlay_webm,
            output_path=output_path,
            start_time=start_time,
            x=x,
            y=y,
            scale=scale,
        )
        result = compositor.composite(overlay_config)

    # tmp_dir (and overlay_webm) cleaned up automatically on context exit
    return result


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _run_ffmpeg_cmd(cmd: list[str], timeout: int = 600) -> None:
    """Execute an FFmpeg command list and raise on failure.

    Args:
        cmd:     Full command list (binary + args).
        timeout: Maximum seconds to wait (default 600 = 10 min).

    Raises:
        subprocess.CalledProcessError: If FFmpeg exits with non-zero code.
        subprocess.TimeoutExpired:     If the process exceeds *timeout*.
    """
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace")
        logger.error(
            "[overlay_compositor] FFmpeg failed (rc={}): {}",
            result.returncode,
            stderr[-2000:],
        )
        raise subprocess.CalledProcessError(
            returncode=result.returncode,
            cmd=cmd,
            stderr=result.stderr,
        )
