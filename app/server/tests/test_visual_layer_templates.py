"""Unit tests for visual layer template registry and HTML templates.

Tests cover:
- TEMPLATE_REGISTRY contents and metadata validation
- get_template_path() happy path and error cases
- list_templates() returns all expected names
- Each template HTML file exists on disk
- Each template HTML contains required HfProtocol elements
- Each template HTML contains required variable placeholders
- Each template HTML contains the GSAP vendor placeholder
- __init__.py re-exports for Phase 3.5.3 symbols

Phase 3.5.3 — Task 3.5.3
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.render.visual_layer.hf_protocol import HfTemplateMetadata
from server.render.visual_layer.template_registry import (
    TEMPLATE_REGISTRY,
    TEMPLATES_DIR,
    get_template_path,
    list_templates,
)

# ─── Expected template definitions ───────────────────────────────────────────

#: Ground-truth for all 5 templates.
EXPECTED_TEMPLATES: dict[str, dict] = {
    "intro_card": {
        "duration": 5.0,
        "width": 1080,
        "height": 1920,
        "variables": {"TITLE", "SUBTITLE", "BRAND"},
    },
    "outro_card": {
        "duration": 4.0,
        "width": 1080,
        "height": 1920,
        "variables": {"TITLE", "CTA", "BRAND"},
    },
    "lower_third": {
        "duration": 3.0,
        "width": 1080,
        "height": 1920,
        "variables": {"NAME", "TITLE"},
    },
    "chapter_title": {
        "duration": 3.0,
        "width": 1080,
        "height": 1920,
        "variables": {"CHAPTER_NUM", "CHAPTER_TITLE"},
    },
    "product_card": {
        "duration": 5.0,
        "width": 1080,
        "height": 1920,
        "variables": {"PRODUCT_NAME", "PRICE", "DESCRIPTION"},
    },
    # ── content-expansion task 10 (4 new templates) ──────────────────────────
    "quote_card": {
        "duration": 5.0,
        "width": 1080,
        "height": 1920,
        "variables": {"QUOTE", "AUTHOR"},
    },
    "stat_card": {
        "duration": 4.0,
        "width": 1080,
        "height": 1920,
        "variables": {"STAT_VALUE", "STAT_LABEL"},
    },
    "news_ticker": {
        "duration": 6.0,
        "width": 1080,
        "height": 1920,
        "variables": {"HEADLINE", "SOURCE"},
    },
    "lyric_line": {
        "duration": 4.0,
        "width": 1080,
        "height": 1920,
        "variables": {"LINE", "NEXT_LINE"},
    },
}

#: Required template set introduced by content-expansion R5.10.
REQUIRED_NEW_TEMPLATES = {"quote_card", "stat_card", "news_ticker", "lyric_line"}


# ─── TEMPLATE_REGISTRY ────────────────────────────────────────────────────────

class TestTemplateRegistry:
    def test_registry_has_all_expected_templates(self):
        assert set(TEMPLATE_REGISTRY.keys()) == set(EXPECTED_TEMPLATES.keys())

    def test_registry_values_are_hf_template_metadata(self):
        for name, meta in TEMPLATE_REGISTRY.items():
            assert isinstance(meta, HfTemplateMetadata), (
                f"TEMPLATE_REGISTRY[{name!r}] should be HfTemplateMetadata, "
                f"got {type(meta).__name__}"
            )

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_metadata_name_matches_key(self, name: str):
        assert TEMPLATE_REGISTRY[name].name == name

    @pytest.mark.parametrize("name,expected", [
        (n, d["duration"]) for n, d in EXPECTED_TEMPLATES.items()
    ])
    def test_metadata_duration(self, name: str, expected: float):
        assert TEMPLATE_REGISTRY[name].duration == pytest.approx(expected)

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_metadata_width_1080(self, name: str):
        assert TEMPLATE_REGISTRY[name].width == 1080

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_metadata_height_1920(self, name: str):
        assert TEMPLATE_REGISTRY[name].height == 1920

    @pytest.mark.parametrize("name,expected", [
        (n, d["variables"]) for n, d in EXPECTED_TEMPLATES.items()
    ])
    def test_metadata_variables(self, name: str, expected: set):
        assert set(TEMPLATE_REGISTRY[name].variables) == expected

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_metadata_duration_positive(self, name: str):
        assert TEMPLATE_REGISTRY[name].duration > 0

    def test_all_durations_reasonable(self):
        """All durations should be between 1s and 10s for short-video use."""
        for name, meta in TEMPLATE_REGISTRY.items():
            assert 1.0 <= meta.duration <= 10.0, (
                f"{name}: duration {meta.duration} outside [1, 10]"
            )


# ─── get_template_path ────────────────────────────────────────────────────────

class TestGetTemplatePath:
    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_returns_path_for_known_template(self, name: str):
        path = get_template_path(name)
        assert isinstance(path, Path)

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_returned_path_is_absolute(self, name: str):
        path = get_template_path(name)
        assert path.is_absolute()

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_returned_path_exists(self, name: str):
        path = get_template_path(name)
        assert path.is_file(), f"Template file missing: {path}"

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_returned_path_has_html_extension(self, name: str):
        path = get_template_path(name)
        assert path.suffix == ".html"

    @pytest.mark.parametrize("name", list(EXPECTED_TEMPLATES))
    def test_returned_path_stem_matches_name(self, name: str):
        path = get_template_path(name)
        assert path.stem == name

    def test_raises_key_error_for_unknown_template(self):
        with pytest.raises(KeyError, match="Unknown template"):
            get_template_path("nonexistent_template")

    def test_error_message_lists_available_templates(self):
        with pytest.raises(KeyError) as exc_info:
            get_template_path("bad_name")
        msg = str(exc_info.value)
        for name in EXPECTED_TEMPLATES:
            assert name in msg

    def test_raises_file_not_found_when_file_missing(self, tmp_path, monkeypatch):
        """If registry has an entry but file is missing, raise FileNotFoundError."""
        import server.render.visual_layer.template_registry as reg_mod
        monkeypatch.setattr(reg_mod, "TEMPLATES_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            get_template_path("intro_card")


# ─── list_templates ───────────────────────────────────────────────────────────

class TestListTemplates:
    def test_returns_list(self):
        result = list_templates()
        assert isinstance(result, list)

    def test_returns_all_expected_names(self):
        result = list_templates()
        assert set(result) == set(EXPECTED_TEMPLATES.keys())

    def test_returns_sorted_list(self):
        result = list_templates()
        assert result == sorted(result)

    def test_no_duplicates(self):
        result = list_templates()
        assert len(result) == len(set(result))


# ─── TEMPLATES_DIR ────────────────────────────────────────────────────────────

class TestTemplatesDir:
    def test_templates_dir_is_path(self):
        assert isinstance(TEMPLATES_DIR, Path)

    def test_templates_dir_exists(self):
        assert TEMPLATES_DIR.is_dir(), f"Templates directory missing: {TEMPLATES_DIR}"

    def test_templates_dir_contains_html_files(self):
        html_files = list(TEMPLATES_DIR.glob("*.html"))
        assert len(html_files) >= len(EXPECTED_TEMPLATES), (
            f"Expected at least {len(EXPECTED_TEMPLATES)} HTML files in {TEMPLATES_DIR}, found {len(html_files)}"
        )


# ─── HTML template content validation ────────────────────────────────────────

class TestTemplateHtmlContent:
    """Validate that each HTML template file has the required structure."""

    @pytest.fixture(params=list(EXPECTED_TEMPLATES))
    def template_name(self, request):
        return request.param

    @pytest.fixture
    def template_html(self, template_name: str) -> str:
        path = get_template_path(template_name)
        return path.read_text(encoding="utf-8")

    def test_is_valid_html5(self, template_html: str):
        """Template must start with <!DOCTYPE html>."""
        assert template_html.strip().lower().startswith("<!doctype html>")

    def test_has_charset_utf8(self, template_html: str):
        """Template must declare UTF-8 charset."""
        assert 'charset="UTF-8"' in template_html or "charset='UTF-8'" in template_html

    def test_has_gsap_vendor_placeholder(self, template_html: str):
        """Template must use {{__VENDOR_GSAP__}} placeholder (not CDN URL)."""
        assert "{{__VENDOR_GSAP__}}" in template_html

    def test_no_cdn_gsap_url(self, template_html: str):
        """Template must NOT reference GSAP from CDN."""
        assert "cdn.jsdelivr.net" not in template_html
        assert "cdnjs.cloudflare.com" not in template_html

    def test_exposes_window_hf(self, template_html: str):
        """Template must expose window.__hf."""
        assert "window.__hf" in template_html

    def test_hf_has_duration(self, template_html: str):
        """window.__hf must have a duration property."""
        assert "duration" in template_html

    def test_hf_has_seek_function(self, template_html: str):
        """window.__hf must have a seek function."""
        assert "seek" in template_html

    def test_hf_seek_calls_timeline(self, template_html: str):
        """seek(t) must call tl.seek(t) (GSAP timeline)."""
        assert "tl.seek(t)" in template_html

    def test_transparent_background(self, template_html: str):
        """Template must set transparent background for alpha channel."""
        assert "transparent" in template_html

    def test_body_background_transparent(self, template_html: str):
        """Template must set document.body.style.background = 'transparent'."""
        assert "document.body.style.background" in template_html
        assert "'transparent'" in template_html or '"transparent"' in template_html

    def test_gsap_timeline_paused(self, template_html: str):
        """GSAP timeline must be created with paused: true."""
        assert "paused: true" in template_html

    def test_stage_dimensions_1080x1920(self, template_html: str):
        """Template must reference 1080px width and 1920px height."""
        assert "1080" in template_html
        assert "1920" in template_html

    def test_has_script_tag(self, template_html: str):
        """Template must have a <script> tag."""
        assert "<script" in template_html.lower()

    def test_has_closing_html_tag(self, template_html: str):
        """Template must have a closing </html> tag."""
        assert "</html>" in template_html.lower()


# ─── Per-template variable placeholder tests ─────────────────────────────────

class TestTemplateVariablePlaceholders:
    """Each template must contain {{VAR}} placeholders for its declared variables."""

    @pytest.mark.parametrize("name,expected", [
        (n, d["variables"]) for n, d in EXPECTED_TEMPLATES.items()
    ])
    def test_all_variables_present_in_html(self, name: str, expected: set):
        path = get_template_path(name)
        html = path.read_text(encoding="utf-8")
        for var in expected:
            placeholder = f"{{{{{var}}}}}"
            assert placeholder in html, (
                f"Template {name!r} missing placeholder {placeholder!r}"
            )


# ─── Specific template structure tests ───────────────────────────────────────

class TestIntroCardTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("intro_card").read_text(encoding="utf-8")

    def test_has_title_element(self, html: str):
        assert "TITLE" in html

    def test_has_subtitle_element(self, html: str):
        assert "SUBTITLE" in html

    def test_has_brand_element(self, html: str):
        assert "BRAND" in html

    def test_full_screen_overlay(self, html: str):
        """Should be full-screen (1080×1920)."""
        assert "1080px" in html
        assert "1920px" in html

    def test_fade_animation(self, html: str):
        """Should have opacity animation (fade in)."""
        assert "opacity" in html


class TestOutroCardTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("outro_card").read_text(encoding="utf-8")

    def test_has_title_element(self, html: str):
        assert "TITLE" in html

    def test_has_cta_element(self, html: str):
        assert "CTA" in html

    def test_has_brand_element(self, html: str):
        assert "BRAND" in html

    def test_fade_in_out_animation(self, html: str):
        """Should have opacity animation for fade in/out."""
        assert "opacity" in html


class TestLowerThirdTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("lower_third").read_text(encoding="utf-8")

    def test_has_name_element(self, html: str):
        assert "NAME" in html

    def test_has_title_element(self, html: str):
        assert "TITLE" in html

    def test_positioned_at_bottom(self, html: str):
        """Lower third should be positioned near the bottom of the screen."""
        assert "bottom" in html

    def test_slide_animation(self, html: str):
        """Should have translateX or x animation (slide in from left)."""
        assert "translateX" in html or "x: 0" in html or "x:" in html


class TestChapterTitleTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("chapter_title").read_text(encoding="utf-8")

    def test_has_chapter_num_element(self, html: str):
        assert "CHAPTER_NUM" in html

    def test_has_chapter_title_element(self, html: str):
        assert "CHAPTER_TITLE" in html

    def test_centered_layout(self, html: str):
        """Chapter title should be centered on screen."""
        assert "center" in html

    def test_scale_animation(self, html: str):
        """Should have scale animation."""
        assert "scale" in html


class TestProductCardTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("product_card").read_text(encoding="utf-8")

    def test_has_product_name_element(self, html: str):
        assert "PRODUCT_NAME" in html

    def test_has_price_element(self, html: str):
        assert "PRICE" in html

    def test_has_description_element(self, html: str):
        assert "DESCRIPTION" in html

    def test_positioned_at_bottom(self, html: str):
        """Product card should be positioned at the bottom."""
        assert "bottom" in html

    def test_slide_up_animation(self, html: str):
        """Should have translateY or y animation (slide up)."""
        assert "translateY" in html or "y: 0" in html or "y:" in html


# ─── __init__.py re-exports ───────────────────────────────────────────────────

class TestInitReexports:
    def test_template_registry_importable_from_package(self):
        from server.render.visual_layer import (
            TEMPLATE_REGISTRY,
            TEMPLATES_DIR,
            get_template_path,
            list_templates,
        )
        assert isinstance(TEMPLATE_REGISTRY, dict)
        assert isinstance(TEMPLATES_DIR, Path)
        assert callable(get_template_path)
        assert callable(list_templates)

    def test_registry_symbols_in_all(self):
        import server.render.visual_layer as pkg
        for name in ["TEMPLATE_REGISTRY", "TEMPLATES_DIR", "get_template_path", "list_templates"]:
            assert name in pkg.__all__, f"{name!r} missing from __all__"

    def test_all_phase_symbols_present(self):
        """All Phase 3.5.1, 3.5.2, and 3.5.3 symbols should be in __all__."""
        import server.render.visual_layer as pkg
        expected = {
            # 3.5.1
            "PlaywrightRenderer", "RenderRequest", "RenderResult",
            "get_gsap_bundle_path", "inject_gsap",
            # 3.5.2
            "HfProtocolContract", "HfTemplateMetadata", "HfValidationResult",
            "validate_hf_contract", "extract_hf_metadata",
            "HF_BOILERPLATE_GSAP", "HF_BOILERPLATE_CUSTOM",
            # 3.5.3
            "TEMPLATE_REGISTRY", "TEMPLATES_DIR", "get_template_path", "list_templates",
        }
        for sym in expected:
            assert sym in pkg.__all__, f"{sym!r} missing from __all__"

# ─── content-expansion task 10.6 — new templates (R5.1/5.2/5.5/5.6/5.10) ─────

class TestNewTemplatesRegistered:
    """The 4 content-expansion templates must be registered + present on disk."""

    @pytest.mark.parametrize("name", sorted(REQUIRED_NEW_TEMPLATES))
    def test_in_registry(self, name: str):
        assert name in TEMPLATE_REGISTRY, f"{name!r} missing from TEMPLATE_REGISTRY"

    @pytest.mark.parametrize("name", sorted(REQUIRED_NEW_TEMPLATES))
    def test_file_exists_on_disk(self, name: str):
        path = get_template_path(name)
        assert path.is_file(), f"Template file missing on disk: {path}"


class TestRequiredTemplateSet:
    """R5.10 — the required template set acceptance gate.

    Implemented as a pytest gate (not an import-time check): the suite FAILS
    if any required template is missing, and an empty set does NOT pass.
    """

    def test_all_required_templates_present(self):
        missing = REQUIRED_NEW_TEMPLATES - set(TEMPLATE_REGISTRY.keys())
        assert not missing, f"Missing required templates: {sorted(missing)}"
        for name in REQUIRED_NEW_TEMPLATES:
            assert get_template_path(name).is_file()

    def test_missing_one_fails_the_set(self):
        """Removing any required template must make the set-check fail."""
        available = set(TEMPLATE_REGISTRY.keys())
        for victim in REQUIRED_NEW_TEMPLATES:
            simulated = available - {victim}
            assert REQUIRED_NEW_TEMPLATES - simulated, (
                f"Set check should fail when {victim!r} is absent"
            )

    def test_empty_set_does_not_pass(self):
        """An empty registry must not satisfy the required set."""
        assert REQUIRED_NEW_TEMPLATES - set(), "Empty set must not satisfy required gate"


class TestQuoteCardTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("quote_card").read_text(encoding="utf-8")

    def test_has_quote_element(self, html: str):
        assert "QUOTE" in html

    def test_has_author_element(self, html: str):
        assert "AUTHOR" in html

    def test_has_animation(self, html: str):
        assert "opacity" in html or "scale" in html


class TestStatCardTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("stat_card").read_text(encoding="utf-8")

    def test_has_stat_value_element(self, html: str):
        assert "STAT_VALUE" in html

    def test_has_stat_label_element(self, html: str):
        assert "STAT_LABEL" in html

    def test_has_animation(self, html: str):
        assert "scale" in html or "opacity" in html


class TestNewsTickerTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("news_ticker").read_text(encoding="utf-8")

    def test_has_headline_element(self, html: str):
        assert "HEADLINE" in html

    def test_has_source_element(self, html: str):
        assert "SOURCE" in html

    def test_has_horizontal_motion(self, html: str):
        assert "translateX" in html or "x:" in html or "xPercent" in html


class TestLyricLineTemplate:
    @pytest.fixture
    def html(self) -> str:
        return get_template_path("lyric_line").read_text(encoding="utf-8")

    def test_has_line_element(self, html: str):
        assert "{{LINE}}" in html

    def test_has_next_line_element(self, html: str):
        assert "NEXT_LINE" in html

    def test_has_fade_animation(self, html: str):
        assert "opacity" in html
