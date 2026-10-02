"""Unit tests for server/render/visual_layer/hf_protocol.py.

Tests cover:
- HfTemplateMetadata construction and validation
- HfValidationResult fields
- validate_hf_contract() with various page states
- extract_hf_metadata() with various page states
- Module-level JS snippet constants
- __init__.py re-exports

Phase 3.5.2 — Task 3.5.2
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.render.visual_layer.hf_protocol import (
    HF_BOILERPLATE_CUSTOM,
    HF_BOILERPLATE_GSAP,
    HfProtocolContract,
    HfTemplateMetadata,
    HfValidationResult,
    extract_hf_metadata,
    validate_hf_contract,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_page(evaluate_return=None, evaluate_raises=None) -> AsyncMock:
    """Build a minimal Playwright Page mock."""
    page = AsyncMock()
    if evaluate_raises is not None:
        page.evaluate = AsyncMock(side_effect=evaluate_raises)
    else:
        page.evaluate = AsyncMock(return_value=evaluate_return)
    return page


# ─── HfTemplateMetadata ───────────────────────────────────────────────────────

class TestHfTemplateMetadata:
    def test_basic_construction(self):
        meta = HfTemplateMetadata(
            name="intro_card",
            duration=5.0,
            width=1080,
            height=1920,
            variables=["TITLE", "SUBTITLE"],
        )
        assert meta.name == "intro_card"
        assert meta.duration == pytest.approx(5.0)
        assert meta.width == 1080
        assert meta.height == 1920
        assert meta.variables == ["TITLE", "SUBTITLE"]

    def test_variables_defaults_to_empty_list(self):
        meta = HfTemplateMetadata(name="outro_card", duration=3.0, width=1080, height=1920)
        assert meta.variables == []

    def test_raises_on_zero_duration(self):
        with pytest.raises(ValueError, match="duration must be positive"):
            HfTemplateMetadata(name="bad", duration=0.0, width=1080, height=1920)

    def test_raises_on_negative_duration(self):
        with pytest.raises(ValueError, match="duration must be positive"):
            HfTemplateMetadata(name="bad", duration=-1.0, width=1080, height=1920)

    def test_raises_on_zero_width(self):
        with pytest.raises(ValueError, match="width/height must be positive"):
            HfTemplateMetadata(name="bad", duration=3.0, width=0, height=1920)

    def test_raises_on_zero_height(self):
        with pytest.raises(ValueError, match="width/height must be positive"):
            HfTemplateMetadata(name="bad", duration=3.0, width=1080, height=0)

    def test_raises_on_negative_dimensions(self):
        with pytest.raises(ValueError, match="width/height must be positive"):
            HfTemplateMetadata(name="bad", duration=3.0, width=-100, height=1920)

    def test_fractional_duration_accepted(self):
        meta = HfTemplateMetadata(name="short", duration=0.1, width=1080, height=1920)
        assert meta.duration == pytest.approx(0.1)


# ─── HfValidationResult ───────────────────────────────────────────────────────

class TestHfValidationResult:
    def test_passed_result(self):
        result = HfValidationResult(passed=True, message="ok", duration=5.0)
        assert result.passed is True
        assert result.message == "ok"
        assert result.duration == pytest.approx(5.0)

    def test_failed_result(self):
        result = HfValidationResult(passed=False, message="window.__hf is not defined")
        assert result.passed is False
        assert result.duration is None

    def test_duration_defaults_to_none(self):
        result = HfValidationResult(passed=False, message="error")
        assert result.duration is None


# ─── validate_hf_contract ─────────────────────────────────────────────────────

class TestValidateHfContract:
    @pytest.mark.asyncio
    async def test_valid_contract_returns_passed(self):
        page = _make_page(evaluate_return={"ok": True, "reason": "ok", "duration": 5.0})
        result = await validate_hf_contract(page)
        assert result.passed is True
        assert result.duration == pytest.approx(5.0)
        assert "valid" in result.message.lower()

    @pytest.mark.asyncio
    async def test_missing_hf_returns_failed(self):
        page = _make_page(
            evaluate_return={"ok": False, "reason": "window.__hf is not defined"}
        )
        result = await validate_hf_contract(page)
        assert result.passed is False
        assert "window.__hf is not defined" in result.message

    @pytest.mark.asyncio
    async def test_non_positive_duration_returns_failed(self):
        page = _make_page(
            evaluate_return={
                "ok": False,
                "reason": "window.__hf.duration must be a positive finite number, got: 0",
            }
        )
        result = await validate_hf_contract(page)
        assert result.passed is False
        assert "duration" in result.message

    @pytest.mark.asyncio
    async def test_seek_not_function_returns_failed(self):
        page = _make_page(
            evaluate_return={
                "ok": False,
                "reason": "window.__hf.seek must be a function",
            }
        )
        result = await validate_hf_contract(page)
        assert result.passed is False
        assert "seek" in result.message

    @pytest.mark.asyncio
    async def test_js_exception_returns_failed(self):
        page = _make_page(evaluate_raises=RuntimeError("page crashed"))
        result = await validate_hf_contract(page)
        assert result.passed is False
        assert "JavaScript evaluation error" in result.message

    @pytest.mark.asyncio
    async def test_unexpected_return_type_returns_failed(self):
        # evaluate() returns something other than a dict
        page = _make_page(evaluate_return="unexpected string")
        result = await validate_hf_contract(page)
        assert result.passed is False
        assert "Unexpected evaluate" in result.message

    @pytest.mark.asyncio
    async def test_duration_is_float_in_result(self):
        # duration comes back as int from JS (e.g. 5 not 5.0)
        page = _make_page(evaluate_return={"ok": True, "reason": "ok", "duration": 5})
        result = await validate_hf_contract(page)
        assert result.passed is True
        assert isinstance(result.duration, float)
        assert result.duration == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_missing_reason_key_uses_fallback(self):
        # ok=False but no "reason" key
        page = _make_page(evaluate_return={"ok": False})
        result = await validate_hf_contract(page)
        assert result.passed is False
        assert result.message  # non-empty fallback

    @pytest.mark.asyncio
    async def test_evaluate_called_once(self):
        page = _make_page(evaluate_return={"ok": True, "reason": "ok", "duration": 3.0})
        await validate_hf_contract(page)
        page.evaluate.assert_called_once()


# ─── extract_hf_metadata ──────────────────────────────────────────────────────

class TestExtractHfMetadata:
    @pytest.mark.asyncio
    async def test_returns_duration_when_valid(self):
        page = _make_page(evaluate_return=5.0)
        result = await extract_hf_metadata(page)
        assert result == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_returns_float_for_int_value(self):
        page = _make_page(evaluate_return=3)
        result = await extract_hf_metadata(page)
        assert isinstance(result, float)
        assert result == pytest.approx(3.0)

    @pytest.mark.asyncio
    async def test_returns_none_when_hf_undefined(self):
        # JS returns null when window.__hf is not defined
        page = _make_page(evaluate_return=None)
        result = await extract_hf_metadata(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_zero_duration(self):
        page = _make_page(evaluate_return=0)
        result = await extract_hf_metadata(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_negative_duration(self):
        page = _make_page(evaluate_return=-1.0)
        result = await extract_hf_metadata(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_js_exception(self):
        page = _make_page(evaluate_raises=Exception("page crashed"))
        result = await extract_hf_metadata(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_string_value(self):
        page = _make_page(evaluate_return="5.0")
        result = await extract_hf_metadata(page)
        assert result is None

    @pytest.mark.asyncio
    async def test_fractional_duration(self):
        page = _make_page(evaluate_return=0.5)
        result = await extract_hf_metadata(page)
        assert result == pytest.approx(0.5)


# ─── JS snippet constants ─────────────────────────────────────────────────────

class TestJsSnippetConstants:
    def test_gsap_boilerplate_contains_hf(self):
        assert "window.__hf" in HF_BOILERPLATE_GSAP

    def test_gsap_boilerplate_contains_duration(self):
        assert "duration" in HF_BOILERPLATE_GSAP

    def test_gsap_boilerplate_contains_seek(self):
        assert "seek" in HF_BOILERPLATE_GSAP

    def test_gsap_boilerplate_has_timeline_placeholder(self):
        assert "<TIMELINE_VAR>" in HF_BOILERPLATE_GSAP

    def test_custom_boilerplate_contains_hf(self):
        assert "window.__hf" in HF_BOILERPLATE_CUSTOM

    def test_custom_boilerplate_contains_duration(self):
        assert "duration" in HF_BOILERPLATE_CUSTOM

    def test_custom_boilerplate_contains_seek(self):
        assert "seek" in HF_BOILERPLATE_CUSTOM

    def test_both_boilerplates_are_strings(self):
        assert isinstance(HF_BOILERPLATE_GSAP, str)
        assert isinstance(HF_BOILERPLATE_CUSTOM, str)


# ─── __init__.py re-exports ───────────────────────────────────────────────────

class TestInitReexports:
    def test_hf_types_importable_from_package(self):
        from server.render.visual_layer import (
            HF_BOILERPLATE_CUSTOM,
            HF_BOILERPLATE_GSAP,
            HfProtocolContract,
            HfTemplateMetadata,
            HfValidationResult,
            extract_hf_metadata,
            validate_hf_contract,
        )
        assert HfTemplateMetadata is not None
        assert HfValidationResult is not None
        assert HfProtocolContract is not None
        assert callable(validate_hf_contract)
        assert callable(extract_hf_metadata)
        assert isinstance(HF_BOILERPLATE_GSAP, str)
        assert isinstance(HF_BOILERPLATE_CUSTOM, str)

    def test_all_exports_listed(self):
        import server.render.visual_layer as pkg
        for name in [
            "HfProtocolContract",
            "HfTemplateMetadata",
            "HfValidationResult",
            "validate_hf_contract",
            "extract_hf_metadata",
            "HF_BOILERPLATE_GSAP",
            "HF_BOILERPLATE_CUSTOM",
        ]:
            assert name in pkg.__all__, f"{name!r} missing from __all__"
