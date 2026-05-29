"""server.render.visual_layer — HTML+GSAP → WebM/MP4 overlay renderer.

Implements the mini-hyperframes visual layer (Phase 3.5).  Renders HTML
templates with GSAP animations into video files with alpha channel for
overlay onto Veo3 base videos.

Public API:
    PlaywrightRenderer   — async renderer: HTML template → WebM with alpha
    RenderRequest        — input configuration dataclass
    RenderResult         — output result dataclass
    get_gsap_bundle_path — locate the local GSAP vendor bundle
    inject_gsap          — replace {{__VENDOR_GSAP__}} placeholder in HTML

HfProtocol types (Phase 3.5.2):
    HfProtocolContract   — TypedDict mirroring the window.__hf JS interface
    HfTemplateMetadata   — metadata a template must declare
    HfValidationResult   — result of contract validation
    validate_hf_contract — async: validate window.__hf on a Playwright page
    extract_hf_metadata  — async: read window.__hf.duration from a page

Template registry (Phase 3.5.3):
    TEMPLATE_REGISTRY    — dict mapping template name → HfTemplateMetadata
    TEMPLATES_DIR        — Path to the templates directory
    get_template_path    — resolve template name → absolute Path
    list_templates       — list all registered template names

HfProtocol contract (every template must expose):
    window.__hf = {
        duration: <float>,          // total seconds
        seek(t) { ... }             // set page state to time t (0 ≤ t ≤ duration)
    }

Phase 3.5.1 — Task 3.5.1
Phase 3.5.2 — Task 3.5.2
Phase 3.5.3 — Task 3.5.3
"""

from server.render.visual_layer.gsap_bundle import get_gsap_bundle_path, inject_gsap
from server.render.visual_layer.hf_protocol import (
    HF_BOILERPLATE_CUSTOM,
    HF_BOILERPLATE_GSAP,
    HfProtocolContract,
    HfTemplateMetadata,
    HfValidationResult,
    extract_hf_metadata,
    validate_hf_contract,
)
from server.render.visual_layer.playwright_renderer import (
    PlaywrightRenderer,
    RenderRequest,
    RenderResult,
)
from server.render.visual_layer.template_registry import (
    TEMPLATE_REGISTRY,
    TEMPLATES_DIR,
    get_template_path,
    list_templates,
)

__all__ = [
    # Phase 3.5.1
    "PlaywrightRenderer",
    "RenderRequest",
    "RenderResult",
    "get_gsap_bundle_path",
    "inject_gsap",
    # Phase 3.5.2
    "HfProtocolContract",
    "HfTemplateMetadata",
    "HfValidationResult",
    "validate_hf_contract",
    "extract_hf_metadata",
    "HF_BOILERPLATE_GSAP",
    "HF_BOILERPLATE_CUSTOM",
    # Phase 3.5.3
    "TEMPLATE_REGISTRY",
    "TEMPLATES_DIR",
    "get_template_path",
    "list_templates",
]
