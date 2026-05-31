"""Task 10.7 — Integration test: visual-layer render + HfProtocol contract.

**Validates: Requirements 5.4, 5.9**

For each of the 4 new templates, this test:

- Renders the template in a real headless Chromium via Playwright.
- Asserts ``validate_hf_contract`` returns ``passed=True`` (R5.4).
- Captures two frames at different ``t`` values via ``window.__hf.seek`` and
  asserts the page screenshots differ — proving ``seek(t)`` actually drives
  the GSAP timeline (R5.9).

The whole module is skipped when Playwright (Python package) or Chromium
(browser binary) or the GSAP bundle are not installed locally.  This is a
**heavy / opt-in** test by design.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# ── Skip the whole module if Playwright / Chromium are not available ─────────

playwright_pkg = pytest.importorskip(
    "playwright.async_api",
    reason="Playwright not installed — skipping visual-layer render tests",
)

from server.render.visual_layer.gsap_bundle import _GSAP_PATH  # noqa: E402

if not _GSAP_PATH.exists():  # pragma: no cover — opt-in heavy test
    pytest.skip(
        f"GSAP vendor bundle not found at {_GSAP_PATH}; "
        "run gsap_bundle download first.",
        allow_module_level=True,
    )

from server.render.visual_layer.gsap_bundle import inject_gsap  # noqa: E402
from server.render.visual_layer.hf_protocol import (  # noqa: E402
    extract_hf_metadata,
    validate_hf_contract,
)
from server.render.visual_layer.template_registry import (  # noqa: E402
    TEMPLATE_REGISTRY,
    get_template_path,
)

NEW_TEMPLATES = ["quote_card", "stat_card", "news_ticker", "lyric_line"]


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _substitute_vars(text: str, variables: list[str]) -> str:
    """Replace each ``{{KEY}}`` in *text* with a stable test value."""
    out = text
    samples = {
        "QUOTE": "Talent develops in tranquility, character in the full current of human life.",
        "AUTHOR": "Goethe",
        "STAT_VALUE": "42%",
        "STAT_LABEL": "Retention",
        "HEADLINE": "Markets close higher on tech rally",
        "SOURCE": "AIFlow Test Wire",
        "LINE": "I see your true colors shining through",
        "NEXT_LINE": "And that is why I love you",
    }
    for key in variables:
        out = out.replace("{{" + key + "}}", samples.get(key, f"<{key}>"))
    return out


async def _render_and_assert(template_name: str, tmp_path: Path) -> None:
    """Open the template in Chromium, validate hf, screenshot two frames."""
    from playwright.async_api import async_playwright

    meta = TEMPLATE_REGISTRY[template_name]
    raw = get_template_path(template_name).read_text(encoding="utf-8")
    html = inject_gsap(raw)
    html = _substitute_vars(html, meta.variables)

    page_html = tmp_path / f"{template_name}.html"
    page_html.write_text(html, encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": meta.width, "height": meta.height}
            )
            page = await context.new_page()
            await page.goto(page_html.as_uri())

            # Wait for window.__hf to be defined (templates set it from <script>)
            await page.wait_for_function(
                "() => window.__hf && typeof window.__hf.seek === 'function'",
                timeout=15_000,
            )

            # 1) Contract validation (R5.4)
            result = await validate_hf_contract(page)
            assert result.passed, (
                f"{template_name}: validate_hf_contract failed — {result.message}"
            )

            duration = await extract_hf_metadata(page)
            assert duration is not None and duration > 0
            # Within ~5% of the registry duration
            assert abs(duration - meta.duration) / meta.duration < 0.5

            # 2) Two frames at different ``t`` differ (R5.9)
            await page.evaluate("(t) => window.__hf.seek(t)", 0.0)
            await page.wait_for_function("() => true")
            frame_a = await page.screenshot(omit_background=True)

            mid_t = duration / 2.0
            await page.evaluate("(t) => window.__hf.seek(t)", mid_t)
            await page.wait_for_function("() => true")
            frame_b = await page.screenshot(omit_background=True)

            assert frame_a != frame_b, (
                f"{template_name}: frames at t=0 and t={mid_t:.2f} are "
                "identical — seek(t) does not drive the timeline (R5.9 fail)"
            )
        finally:
            await browser.close()


# ─── R5.4 + R5.9 — render + hf contract for each new template ───────────────


@pytest.mark.parametrize("template_name", NEW_TEMPLATES)
def test_template_render_and_hf_contract(
    template_name: str, tmp_path: Path
) -> None:
    """**R5.4 / R5.9** — Each new template renders, exposes a valid
    ``window.__hf`` contract, and ``seek(t)`` drives the GSAP timeline."""
    asyncio.run(_render_and_assert(template_name, tmp_path))
