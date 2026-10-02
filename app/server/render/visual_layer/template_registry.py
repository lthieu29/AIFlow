"""Template registry for visual layer HTML+GSAP templates.

Maps template names to their ``HfTemplateMetadata`` and provides a helper
to resolve the absolute path to a template file.

Usage::

    from server.render.visual_layer.template_registry import (
        TEMPLATE_REGISTRY,
        get_template_path,
    )

    meta = TEMPLATE_REGISTRY["intro_card"]
    path = get_template_path("intro_card")

All templates live in ``server/render/visual_layer/templates/``.

Phase 3.5.3 — Task 3.5.3
"""

from __future__ import annotations

from pathlib import Path

from server.render.visual_layer.hf_protocol import HfTemplateMetadata

# ─── Constants ────────────────────────────────────────────────────────────────

#: Absolute path to the templates directory.
TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"

# ─── Registry ─────────────────────────────────────────────────────────────────

#: Mapping of template name → HfTemplateMetadata.
#:
#: Template names are the HTML filename without the ``.html`` extension.
#: Duration values are the *design-time* durations; the actual rendered
#: duration is determined by ``window.__hf.duration`` at runtime (GSAP
#: timeline may differ slightly due to easing).
TEMPLATE_REGISTRY: dict[str, HfTemplateMetadata] = {
    "intro_card": HfTemplateMetadata(
        name="intro_card",
        duration=5.0,
        width=1080,
        height=1920,
        variables=["TITLE", "SUBTITLE", "BRAND"],
    ),
    "outro_card": HfTemplateMetadata(
        name="outro_card",
        duration=4.0,
        width=1080,
        height=1920,
        variables=["TITLE", "CTA", "BRAND"],
    ),
    "lower_third": HfTemplateMetadata(
        name="lower_third",
        duration=3.0,
        width=1080,
        height=1920,
        variables=["NAME", "TITLE"],
    ),
    "chapter_title": HfTemplateMetadata(
        name="chapter_title",
        duration=3.0,
        width=1080,
        height=1920,
        variables=["CHAPTER_NUM", "CHAPTER_TITLE"],
    ),
    "product_card": HfTemplateMetadata(
        name="product_card",
        duration=5.0,
        width=1080,
        height=1920,
        variables=["PRODUCT_NAME", "PRICE", "DESCRIPTION"],
    ),
    "stat_card": HfTemplateMetadata(
        name="stat_card",
        duration=4.0,
        width=1080,
        height=1920,
        variables=["STAT_VALUE", "STAT_LABEL"],
    ),
    "quote_card": HfTemplateMetadata(
        name="quote_card",
        duration=5.0,
        width=1080,
        height=1920,
        variables=["QUOTE", "AUTHOR"],
    ),
    "news_ticker": HfTemplateMetadata(
        name="news_ticker",
        duration=6.0,
        width=1080,
        height=1920,
        variables=["HEADLINE", "SOURCE"],
    ),
    "lyric_line": HfTemplateMetadata(
        name="lyric_line",
        duration=4.0,
        width=1080,
        height=1920,
        variables=["LINE", "NEXT_LINE"],
    ),
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_template_path(name: str) -> Path:
    """Return the absolute path to a template HTML file.

    Args:
        name: Template name (e.g. ``"intro_card"``), without the ``.html``
              extension.

    Returns:
        Absolute ``Path`` to the template file.

    Raises:
        KeyError: If *name* is not in ``TEMPLATE_REGISTRY``.
        FileNotFoundError: If the template file does not exist on disk.
    """
    if name not in TEMPLATE_REGISTRY:
        available = ", ".join(sorted(TEMPLATE_REGISTRY))
        raise KeyError(
            f"Unknown template {name!r}. Available templates: {available}"
        )

    path = TEMPLATES_DIR / f"{name}.html"
    if not path.is_file():
        raise FileNotFoundError(
            f"Template file not found: {path}\n"
            f"Expected at: {TEMPLATES_DIR / (name + '.html')}"
        )
    return path


def list_templates() -> list[str]:
    """Return a sorted list of all registered template names.

    Returns:
        Sorted list of template name strings.
    """
    return sorted(TEMPLATE_REGISTRY)
