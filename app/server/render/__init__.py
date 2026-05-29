"""server.render — video composition and visual layer rendering.

Public API:
    VideoComposer   — orchestrates final video assembly (Phase 3.3)
    compose_video   — convenience wrapper for VideoComposer.compose()
    ComposeConfig   — configuration dataclass for compose runs
    ComposeResult   — result dataclass returned by compose()
    ClipInput       — single scene clip descriptor
    SubtitleConfig  — subtitle rendering options
    SubtitleSegment — single timed subtitle entry
    reconcile_durations — audio-driven duration reconciliation helper

Overlay compositor (Phase 3.5.4):
    OverlayCompositor       — composites WebM overlay onto base MP4
    composite_overlay       — convenience wrapper for OverlayCompositor.composite()
    overlay_template_on_video — high-level async: template → WebM → composite
    OverlayConfig           — configuration dataclass for overlay runs
    OverlayResult           — result dataclass returned by composite()
    build_overlay_command   — build FFmpeg overlay filter_complex command
"""

from server.render.composer import (
    ClipInput,
    ComposeConfig,
    ComposeResult,
    SubtitleConfig,
    SubtitleSegment,
    VideoComposer,
    compose_video,
    reconcile_durations,
)
from server.render.overlay_compositor import (
    OverlayCompositor,
    OverlayConfig,
    OverlayResult,
    build_overlay_command,
    composite_overlay,
    overlay_template_on_video,
)

__all__ = [
    # Phase 3.3
    "ClipInput",
    "ComposeConfig",
    "ComposeResult",
    "SubtitleConfig",
    "SubtitleSegment",
    "VideoComposer",
    "compose_video",
    "reconcile_durations",
    # Phase 3.5.4
    "OverlayCompositor",
    "OverlayConfig",
    "OverlayResult",
    "build_overlay_command",
    "composite_overlay",
    "overlay_template_on_video",
]
