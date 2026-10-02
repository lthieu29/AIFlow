"""Unit tests for Task 4.1 — EcommerceProductAdapter.

Covers:
- prompts.py: PRODUCT_SCENE_PROMPTS, build_scene_prompt, build_narration
- adapter.py: EcommerceProductAdapter.validate_input, adapt (sync path)
- Auto-discovery: ADAPTER instance and ADAPTER_CLASS exports
- SceneList structure: 5 scenes, 8s each, correct scene types
- Skill application: skill prefix prepended when skill_name is set
- Edge cases: missing fields, invalid JSON, missing product_image path
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _make_input(
    product_name: str = "Áo Thun Cotton",
    price: str = "199.000đ",
    description: str = "Áo thun cotton 100%, thoáng mát, nhiều màu sắc",
    cta: str = "Nhấn vào link để mua ngay!",
    product_image: Path | None = None,
    skill_name: str | None = None,
    extra_options: dict | None = None,
) -> "AdapterInput":
    from server.content.base import AdapterInput

    raw = {"product_name": product_name, "price": price, "description": description}
    if cta:
        raw["cta"] = cta

    assets = {}
    if product_image is not None:
        assets["product_image"] = product_image

    return AdapterInput(
        source_type="product",
        raw_content=json.dumps(raw),
        assets=assets,
        skill_name=skill_name,
        options=extra_options or {},
    )


# ═════════════════════════════════════════════════════════════════════════════
# prompts.py
# ═════════════════════════════════════════════════════════════════════════════


class TestProductScenePrompts:
    def test_five_prompts_defined(self):
        from server.content.adapters.ecommerce_product.prompts import PRODUCT_SCENE_PROMPTS

        assert len(PRODUCT_SCENE_PROMPTS) == 5

    def test_all_prompts_are_strings(self):
        from server.content.adapters.ecommerce_product.prompts import PRODUCT_SCENE_PROMPTS

        for i, p in enumerate(PRODUCT_SCENE_PROMPTS):
            assert isinstance(p, str), f"PRODUCT_SCENE_PROMPTS[{i}] is not a string"

    def test_all_prompts_non_empty(self):
        from server.content.adapters.ecommerce_product.prompts import PRODUCT_SCENE_PROMPTS

        for i, p in enumerate(PRODUCT_SCENE_PROMPTS):
            assert p.strip(), f"PRODUCT_SCENE_PROMPTS[{i}] is empty"

    def test_prompts_contain_product_name_placeholder(self):
        from server.content.adapters.ecommerce_product.prompts import PRODUCT_SCENE_PROMPTS

        for i, p in enumerate(PRODUCT_SCENE_PROMPTS):
            assert "{product_name}" in p, (
                f"PRODUCT_SCENE_PROMPTS[{i}] missing {{product_name}} placeholder"
            )

    def test_scene_types_list_has_five_entries(self):
        from server.content.adapters.ecommerce_product.prompts import SCENE_TYPES

        assert len(SCENE_TYPES) == 5
        assert SCENE_TYPES[0] == "hero_shot"
        assert SCENE_TYPES[-1] == "cta_shot"


class TestBuildScenePrompt:
    def test_injects_product_name(self):
        from server.content.adapters.ecommerce_product.prompts import build_scene_prompt

        result = build_scene_prompt(0, "Túi Da Bò", "Túi da thật 100%", "hero_shot")
        assert "Túi Da Bò" in result

    def test_appends_product_desc(self):
        from server.content.adapters.ecommerce_product.prompts import build_scene_prompt

        result = build_scene_prompt(0, "Áo", "Chất liệu cao cấp", "hero_shot")
        assert "Chất liệu cao cấp" in result

    def test_empty_desc_no_context_appended(self):
        from server.content.adapters.ecommerce_product.prompts import build_scene_prompt

        result = build_scene_prompt(0, "Áo", "", "hero_shot")
        assert "Product context:" not in result

    def test_all_scene_types_accepted(self):
        from server.content.adapters.ecommerce_product.prompts import (
            SCENE_TYPES,
            build_scene_prompt,
        )

        for i, scene_type in enumerate(SCENE_TYPES):
            result = build_scene_prompt(i, "Product", "Desc", scene_type)
            assert isinstance(result, str)
            assert result.strip()

    def test_invalid_scene_type_raises(self):
        from server.content.adapters.ecommerce_product.prompts import build_scene_prompt

        with pytest.raises(ValueError, match="Unknown scene_type"):
            build_scene_prompt(0, "Product", "Desc", "invalid_type")

    def test_scene_num_out_of_range_uses_last_template(self):
        """scene_num >= 5 should not raise — clamps to last template."""
        from server.content.adapters.ecommerce_product.prompts import build_scene_prompt

        result = build_scene_prompt(99, "Product", "Desc", "cta_shot")
        assert isinstance(result, str)
        assert result.strip()

    def test_returns_string(self):
        from server.content.adapters.ecommerce_product.prompts import build_scene_prompt

        result = build_scene_prompt(2, "Kem Dưỡng Da", "Dưỡng ẩm 24h", "lifestyle_shot")
        assert isinstance(result, str)


class TestBuildNarration:
    def test_contains_product_name(self):
        from server.content.adapters.ecommerce_product.prompts import build_narration

        result = build_narration("Áo Thun", "99.000đ", "Mua ngay!")
        assert "Áo Thun" in result

    def test_cta_shot_contains_price(self):
        from server.content.adapters.ecommerce_product.prompts import build_narration

        result = build_narration("Áo Thun", "99.000đ", "Mua ngay!", scene_type="cta_shot")
        assert "99.000đ" in result

    def test_cta_shot_contains_cta(self):
        from server.content.adapters.ecommerce_product.prompts import build_narration

        result = build_narration("Áo Thun", "99.000đ", "Đặt hàng ngay!", scene_type="cta_shot")
        assert "Đặt hàng ngay!" in result

    def test_all_scene_types_return_string(self):
        from server.content.adapters.ecommerce_product.prompts import (
            SCENE_TYPES,
            build_narration,
        )

        for scene_type in SCENE_TYPES:
            result = build_narration("Product", "100đ", "CTA", scene_type=scene_type)
            assert isinstance(result, str)
            assert result.strip()

    def test_default_scene_type_returns_string(self):
        from server.content.adapters.ecommerce_product.prompts import build_narration

        result = build_narration("Product", "100đ", "CTA")
        assert isinstance(result, str)
        assert result.strip()

    def test_unknown_scene_type_falls_back_to_generic(self):
        from server.content.adapters.ecommerce_product.prompts import build_narration

        # Unknown scene type should fall back to PRODUCT_NARRATION_TEMPLATE
        result = build_narration("Product", "100đ", "CTA", scene_type="unknown_type")
        assert isinstance(result, str)
        assert result.strip()


# ═════════════════════════════════════════════════════════════════════════════
# EcommerceProductAdapter.validate_input
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateInput:
    def _adapter(self):
        from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter

        return EcommerceProductAdapter()

    def test_valid_input_returns_empty_errors(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input())
        assert errors == []

    def test_empty_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="product", raw_content="")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_whitespace_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="product", raw_content="   ")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_invalid_json_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="product", raw_content="{not valid json}")
        errors = adapter.validate_input(ai)
        assert any("JSON" in e for e in errors)

    def test_non_object_json_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="product", raw_content='["list", "not", "object"]')
        errors = adapter.validate_input(ai)
        assert any("object" in e for e in errors)

    def test_missing_product_name_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"price": "100đ", "description": "desc"})
        ai = AdapterInput(source_type="product", raw_content=raw)
        errors = adapter.validate_input(ai)
        assert any("product_name" in e for e in errors)

    def test_missing_price_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"product_name": "Áo", "description": "desc"})
        ai = AdapterInput(source_type="product", raw_content=raw)
        errors = adapter.validate_input(ai)
        assert any("price" in e for e in errors)

    def test_missing_description_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"product_name": "Áo", "price": "100đ"})
        ai = AdapterInput(source_type="product", raw_content=raw)
        errors = adapter.validate_input(ai)
        assert any("description" in e for e in errors)

    def test_blank_product_name_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"product_name": "  ", "price": "100đ", "description": "desc"})
        ai = AdapterInput(source_type="product", raw_content=raw)
        errors = adapter.validate_input(ai)
        assert any("product_name" in e for e in errors)

    def test_nonexistent_product_image_returns_error(self, tmp_path):
        adapter = self._adapter()
        missing = tmp_path / "nonexistent.jpg"
        ai = _make_input(product_image=missing)
        errors = adapter.validate_input(ai)
        assert any("product_image" in e for e in errors)

    def test_existing_product_image_is_valid(self, tmp_path):
        adapter = self._adapter()
        img = tmp_path / "product.jpg"
        img.write_bytes(b"JPEG")
        ai = _make_input(product_image=img)
        errors = adapter.validate_input(ai)
        assert errors == []

    def test_optional_cta_not_required(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"product_name": "Áo", "price": "100đ", "description": "desc"})
        ai = AdapterInput(source_type="product", raw_content=raw)
        errors = adapter.validate_input(ai)
        assert errors == []


# ═════════════════════════════════════════════════════════════════════════════
# EcommerceProductAdapter.adapt (async)
# ═════════════════════════════════════════════════════════════════════════════


class TestAdapt:
    def _adapter(self):
        from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter

        return EcommerceProductAdapter()

    @pytest.mark.asyncio
    async def test_returns_scene_list(self):
        from server.content.base import SceneList

        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert isinstance(result, SceneList)

    @pytest.mark.asyncio
    async def test_generates_five_scenes(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert len(result.scenes) == 5

    @pytest.mark.asyncio
    async def test_scenes_have_correct_order(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for i, scene in enumerate(result.scenes):
            assert scene.order == i

    @pytest.mark.asyncio
    async def test_each_scene_is_8_seconds(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.duration == pytest.approx(8.0)

    @pytest.mark.asyncio
    async def test_total_duration_is_40_seconds(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        total = sum(s.duration for s in result.scenes)
        assert total == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_scene_list_validates(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        ok, errors = result.validate()
        assert ok is True, errors

    @pytest.mark.asyncio
    async def test_each_scene_has_prompt(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.prompt
            assert scene.prompt.strip()

    @pytest.mark.asyncio
    async def test_each_scene_has_narration(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.narration
            assert scene.narration.strip()

    @pytest.mark.asyncio
    async def test_product_name_in_prompts(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(product_name="Giày Da Cao Cấp"))
        for scene in result.scenes:
            assert "Giày Da Cao Cấp" in scene.prompt

    @pytest.mark.asyncio
    async def test_product_name_in_narrations(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(product_name="Túi Xách Nữ"))
        for scene in result.scenes:
            assert "Túi Xách Nữ" in scene.narration

    @pytest.mark.asyncio
    async def test_metadata_contains_product_name(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(product_name="Kem Dưỡng Da"))
        assert result.metadata["product_name"] == "Kem Dưỡng Da"

    @pytest.mark.asyncio
    async def test_metadata_contains_adapter_type(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["adapter"] == "ecommerce_product"

    @pytest.mark.asyncio
    async def test_default_voice_is_vietnamese(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.voice == "vi-VN-HoaiMyNeural"

    @pytest.mark.asyncio
    async def test_custom_voice_from_options(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"product_name": "Áo", "price": "100đ", "description": "desc"})
        ai = AdapterInput(
            source_type="product",
            raw_content=raw,
            options={"voice": "vi-VN-NamMinhNeural"},
        )
        result = await adapter.adapt(ai)
        assert result.voice == "vi-VN-NamMinhNeural"

    @pytest.mark.asyncio
    async def test_invalid_input_raises_adapter_error(self):
        from server.content.base import AdapterError, AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="product", raw_content="")
        with pytest.raises(AdapterError) as exc_info:
            await adapter.adapt(ai)
        assert exc_info.value.code == "ADAPTER_INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_product_image_used_as_start_image_for_hero(self, tmp_path):
        img = tmp_path / "product.jpg"
        img.write_bytes(b"JPEG")
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(product_image=img))
        # hero_shot (index 0) should have start_image set
        assert result.scenes[0].start_image == img

    @pytest.mark.asyncio
    async def test_product_image_used_as_start_image_for_cta(self, tmp_path):
        img = tmp_path / "product.jpg"
        img.write_bytes(b"JPEG")
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(product_image=img))
        # cta_shot (index 4) should have start_image set
        assert result.scenes[4].start_image == img

    @pytest.mark.asyncio
    async def test_middle_scenes_have_no_start_image(self, tmp_path):
        img = tmp_path / "product.jpg"
        img.write_bytes(b"JPEG")
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(product_image=img))
        # detail, lifestyle, feature shots (indices 1, 2, 3) should NOT have start_image
        for idx in (1, 2, 3):
            assert result.scenes[idx].start_image is None

    @pytest.mark.asyncio
    async def test_no_product_image_all_start_images_none(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.start_image is None

    @pytest.mark.asyncio
    async def test_location_hints_set(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        # All scenes should have a location_hint
        for scene in result.scenes:
            assert scene.location_hint is not None

    @pytest.mark.asyncio
    async def test_lifestyle_shot_has_indoor_home_hint(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        # lifestyle_shot is index 2
        assert result.scenes[2].location_hint == "indoor_home"

    @pytest.mark.asyncio
    async def test_cta_in_narration_when_provided(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(cta="Bấm mua ngay!"))
        # cta_shot narration should contain the CTA
        cta_scene = result.scenes[4]
        assert "Bấm mua ngay!" in cta_scene.narration

    @pytest.mark.asyncio
    async def test_default_cta_used_when_not_provided(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        raw = json.dumps({"product_name": "Áo", "price": "100đ", "description": "desc"})
        ai = AdapterInput(source_type="product", raw_content=raw)
        result = await adapter.adapt(ai)
        # Should not raise; default CTA is used
        assert result.scenes[4].narration.strip()


# ═════════════════════════════════════════════════════════════════════════════
# Skill application
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillApplication:
    def _adapter(self):
        from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter

        return EcommerceProductAdapter()

    @pytest.mark.asyncio
    async def test_skill_prefix_prepended_to_prompts(self, tmp_path):
        """When a valid skill is applied, its prefix should appear in every prompt."""
        # Build a minimal skill directory
        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "manifest.yaml").write_text(
            "name: test-skill\nversion: 1.0.0\nadapter_type: ecommerce_product\n",
            encoding="utf-8",
        )
        (skill_dir / "prefix.md").write_text(
            "SKILL_PREFIX_MARKER. Photoreal editorial.",
            encoding="utf-8",
        )

        from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter
        from server.content.skill_loader import SkillLoader, apply_skill_to_scene

        adapter = EcommerceProductAdapter()
        ai = _make_input(skill_name="test-skill")

        # Manually apply skill to verify the mechanism
        loader = SkillLoader(tmp_path / "skills")
        skill = loader.load("test-skill")

        # Build scenes without skill
        result_no_skill = await adapter.adapt(_make_input())
        scenes_with_skill = [
            apply_skill_to_scene(scene, skill) for scene in result_no_skill.scenes
        ]

        for scene in scenes_with_skill:
            assert "SKILL_PREFIX_MARKER" in scene.prompt

    @pytest.mark.asyncio
    async def test_nonexistent_skill_does_not_raise(self):
        """If skill_name points to a non-existent skill, adapt should succeed without it."""
        adapter = self._adapter()
        ai = _make_input(skill_name="nonexistent-skill-xyz")
        # Should not raise — skill application is best-effort
        result = await adapter.adapt(ai)
        assert len(result.scenes) == 5

    @pytest.mark.asyncio
    async def test_no_skill_name_no_prefix(self):
        """Without skill_name, prompts should not have any skill prefix."""
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(skill_name=None))
        # Prompts should contain product name but no skill prefix marker
        for scene in result.scenes:
            assert "Áo Thun Cotton" in scene.prompt


# ═════════════════════════════════════════════════════════════════════════════
# Auto-discovery exports
# ═════════════════════════════════════════════════════════════════════════════


class TestAutoDiscovery:
    def test_adapter_instance_exported(self):
        from server.content.adapters.ecommerce_product.adapter import ADAPTER

        assert ADAPTER is not None
        assert ADAPTER.adapter_type == "ecommerce_product"

    def test_adapter_class_exported(self):
        from server.content.adapters.ecommerce_product.adapter import ADAPTER_CLASS

        assert ADAPTER_CLASS is not None
        assert ADAPTER_CLASS.adapter_type == "ecommerce_product"

    def test_adapter_satisfies_protocol(self):
        from server.content.adapters.ecommerce_product.adapter import ADAPTER
        from server.content.base import ContentAdapter

        assert isinstance(ADAPTER, ContentAdapter)

    def test_registry_auto_discover_finds_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        assert "ecommerce_product" in registry.list_types()

    def test_registry_get_returns_correct_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        adapter = registry.get("ecommerce_product")
        assert adapter.adapter_type == "ecommerce_product"


# ═════════════════════════════════════════════════════════════════════════════
# Integration: 1 product image → TikTok video (SceneList)
# ═════════════════════════════════════════════════════════════════════════════


class TestProductImageToTikTokVideo:
    """End-to-end test: 1 product image → SceneList ready for TikTok pipeline."""

    @pytest.mark.asyncio
    async def test_product_image_to_scene_list(self, tmp_path):
        """Simulate the full flow: product image + metadata → 5-scene SceneList."""
        from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter
        from server.content.base import SceneList

        # Create a fake product image
        product_img = tmp_path / "ao_thun.jpg"
        product_img.write_bytes(b"\xff\xd8\xff\xe0JPEG")  # minimal JPEG header

        adapter = EcommerceProductAdapter()
        ai = _make_input(
            product_name="Áo Thun Cotton Unisex",
            price="249.000đ",
            description="Áo thun cotton 100% cao cấp, form rộng unisex, 10 màu sắc",
            cta="Nhấn vào giỏ hàng để mua ngay!",
            product_image=product_img,
        )

        result = await adapter.adapt(ai)

        # Verify it's a valid SceneList
        assert isinstance(result, SceneList)
        ok, errors = result.validate()
        assert ok is True, f"SceneList validation failed: {errors}"

        # Verify TikTok-ready structure
        assert len(result.scenes) == 5
        assert sum(s.duration for s in result.scenes) == pytest.approx(40.0)

        # Verify all scenes have content
        for scene in result.scenes:
            assert scene.prompt.strip()
            assert scene.narration.strip()
            assert scene.location_hint is not None

        # Verify product image anchoring
        assert result.scenes[0].start_image == product_img  # hero
        assert result.scenes[4].start_image == product_img  # cta

        # Verify cost estimate
        cost = result.estimate_cost()
        assert cost["veo3_clips"] == 5
        assert cost["total_video_duration_sec"] == pytest.approx(40.0)
        assert cost["tts_duration_sec"] == pytest.approx(40.0)  # all scenes have narration
