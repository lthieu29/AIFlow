"""Unit tests for Task 4.2 — NarrativeScriptAdapter.

Covers:
- parser.py: parse_markdown_script, extract_location_hint
  - H2-heading-based scene splitting
  - Narration extraction (**Narration:** and > blockquote)
  - Location hint extraction
  - Paragraph fallback when no H2 headings
  - Empty / whitespace input
- adapter.py: NarrativeScriptAdapter.validate_input, adapt (async)
  - Valid markdown → SceneList
  - Scene count, order, duration, prompt, narration
  - Skill application (best-effort)
  - Invalid input raises AdapterError
- Auto-discovery: ADAPTER instance and ADAPTER_CLASS exports
- Integration: 1 markdown → video (SceneList)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── Fixtures / helpers ───────────────────────────────────────────────────────

SIMPLE_MARKDOWN = """\
## Cảnh 1: Giới thiệu

Đây là cảnh mở đầu của video. Nhân vật chính xuất hiện.

**Narration:** Xin chào các bạn, hôm nay chúng ta sẽ khám phá một câu chuyện thú vị.

**Location:** indoor_home

## Cảnh 2: Cao trào

Nhân vật đối mặt với thử thách lớn nhất.

> Đây là khoảnh khắc quyết định của câu chuyện.

## Cảnh 3: Kết thúc

Mọi thứ được giải quyết. Nhân vật trở về nhà.

**Narration:** Và đó là kết thúc của câu chuyện hôm nay.
**Location:** outdoor_urban
"""

NO_HEADING_MARKDOWN = """\
Đây là đoạn văn đầu tiên. Nó mô tả cảnh mở đầu của video.

Đây là đoạn văn thứ hai. Nhân vật gặp khó khăn và phải vượt qua.

Đây là đoạn văn cuối cùng. Mọi thứ kết thúc tốt đẹp.
"""


def _make_input(
    raw_content: str = SIMPLE_MARKDOWN,
    skill_name: str | None = None,
    options: dict | None = None,
) -> "AdapterInput":
    from server.content.base import AdapterInput

    return AdapterInput(
        source_type="narrative",
        raw_content=raw_content,
        skill_name=skill_name,
        options=options or {},
    )


# ═════════════════════════════════════════════════════════════════════════════
# parser.py — parse_markdown_script
# ═════════════════════════════════════════════════════════════════════════════


class TestParseMarkdownScript:
    def test_empty_string_returns_empty_list(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        assert parse_markdown_script("") == []

    def test_whitespace_only_returns_empty_list(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        assert parse_markdown_script("   \n\n  ") == []

    def test_h2_headings_create_scenes(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert len(scenes) == 3

    def test_scene_order_is_sequential(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        for i, scene in enumerate(scenes):
            assert scene.order == i

    def test_heading_extracted_correctly(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert scenes[0].heading == "Cảnh 1: Giới thiệu"
        assert scenes[1].heading == "Cảnh 2: Cao trào"
        assert scenes[2].heading == "Cảnh 3: Kết thúc"

    def test_bold_narration_extracted(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert "Xin chào các bạn" in scenes[0].narration

    def test_blockquote_narration_extracted(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert "khoảnh khắc quyết định" in scenes[1].narration

    def test_location_hint_extracted(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert scenes[0].location_hint == "indoor_home"
        assert scenes[2].location_hint == "outdoor_urban"

    def test_scene_without_location_hint_is_none(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert scenes[1].location_hint is None

    def test_body_does_not_contain_narration_marker(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert "**Narration:**" not in scenes[0].body

    def test_body_does_not_contain_location_marker(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        assert "**Location:**" not in scenes[0].body

    def test_body_does_not_contain_blockquote_marker(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        # blockquote lines should be stripped from body
        assert not any(line.startswith(">") for line in scenes[1].body.splitlines())

    def test_single_scene_no_heading(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        md = "Đây là một đoạn văn duy nhất không có tiêu đề."
        scenes = parse_markdown_script(md)
        assert len(scenes) == 1
        assert scenes[0].order == 0

    def test_paragraph_fallback_when_no_h2(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(NO_HEADING_MARKDOWN)
        assert len(scenes) == 3

    def test_paragraph_fallback_order_sequential(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(NO_HEADING_MARKDOWN)
        for i, scene in enumerate(scenes):
            assert scene.order == i

    def test_paragraph_fallback_body_non_empty(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        scenes = parse_markdown_script(NO_HEADING_MARKDOWN)
        for scene in scenes:
            assert scene.body.strip() or scene.narration.strip()

    def test_h1_heading_not_treated_as_scene_boundary(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        md = "# Title\n\nSome content.\n\n## Scene 1\n\nScene content."
        scenes = parse_markdown_script(md)
        # Only ## creates scene boundaries
        assert len(scenes) == 1
        assert scenes[0].heading == "Scene 1"

    def test_multiple_narration_lines_joined(self):
        from server.content.adapters.narrative_script.parser import parse_markdown_script

        md = """\
## Scene

**Narration:** First line.
**Narration:** Second line.
"""
        scenes = parse_markdown_script(md)
        assert "First line." in scenes[0].narration
        assert "Second line." in scenes[0].narration

    def test_returns_list_of_narrative_scene(self):
        from server.content.adapters.narrative_script.parser import (
            NarrativeScene,
            parse_markdown_script,
        )

        scenes = parse_markdown_script(SIMPLE_MARKDOWN)
        for scene in scenes:
            assert isinstance(scene, NarrativeScene)


# ═════════════════════════════════════════════════════════════════════════════
# parser.py — extract_location_hint
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractLocationHint:
    def test_extracts_location_from_bold_tag(self):
        from server.content.adapters.narrative_script.parser import extract_location_hint

        text = "Some text.\n**Location:** indoor_cafe\nMore text."
        assert extract_location_hint(text) == "indoor_cafe"

    def test_returns_none_when_no_location_tag(self):
        from server.content.adapters.narrative_script.parser import extract_location_hint

        assert extract_location_hint("No location here.") is None

    def test_returns_none_for_empty_string(self):
        from server.content.adapters.narrative_script.parser import extract_location_hint

        assert extract_location_hint("") is None

    def test_strips_whitespace_from_value(self):
        from server.content.adapters.narrative_script.parser import extract_location_hint

        text = "**Location:**   outdoor_urban   "
        assert extract_location_hint(text) == "outdoor_urban"

    def test_case_insensitive(self):
        from server.content.adapters.narrative_script.parser import extract_location_hint

        text = "**LOCATION:** abstract"
        assert extract_location_hint(text) == "abstract"


# ═════════════════════════════════════════════════════════════════════════════
# NarrativeScriptAdapter.validate_input
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateInput:
    def _adapter(self):
        from server.content.adapters.narrative_script.adapter import NarrativeScriptAdapter

        return NarrativeScriptAdapter()

    def test_valid_markdown_returns_empty_errors(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input())
        assert errors == []

    def test_empty_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="narrative", raw_content="")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_whitespace_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="narrative", raw_content="   \n  ")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_minimal_content_is_valid(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input("Some text."))
        assert errors == []


# ═════════════════════════════════════════════════════════════════════════════
# NarrativeScriptAdapter.adapt (async)
# ═════════════════════════════════════════════════════════════════════════════


class TestAdapt:
    def _adapter(self):
        from server.content.adapters.narrative_script.adapter import NarrativeScriptAdapter

        return NarrativeScriptAdapter()

    @pytest.mark.asyncio
    async def test_returns_scene_list(self):
        from server.content.base import SceneList

        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert isinstance(result, SceneList)

    @pytest.mark.asyncio
    async def test_scene_count_matches_h2_headings(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert len(result.scenes) == 3

    @pytest.mark.asyncio
    async def test_scenes_have_sequential_order(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for i, scene in enumerate(result.scenes):
            assert scene.order == i

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
            assert scene.prompt and scene.prompt.strip()

    @pytest.mark.asyncio
    async def test_each_scene_has_narration(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.narration and scene.narration.strip()

    @pytest.mark.asyncio
    async def test_duration_within_bounds(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert 3.0 <= scene.duration <= 30.0

    @pytest.mark.asyncio
    async def test_location_hint_set_when_present(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        # Scene 0 has **Location:** indoor_home
        assert result.scenes[0].location_hint == "indoor_home"

    @pytest.mark.asyncio
    async def test_location_hint_none_when_absent(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        # Scene 1 has no location tag
        assert result.scenes[1].location_hint is None

    @pytest.mark.asyncio
    async def test_metadata_contains_adapter_type(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["adapter"] == "narrative_script"

    @pytest.mark.asyncio
    async def test_metadata_contains_scene_count(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["scene_count"] == 3

    @pytest.mark.asyncio
    async def test_default_voice_is_vietnamese(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.voice == "vi-VN-HoaiMyNeural"

    @pytest.mark.asyncio
    async def test_custom_voice_from_options(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(options={"voice": "vi-VN-NamMinhNeural"}))
        assert result.voice == "vi-VN-NamMinhNeural"

    @pytest.mark.asyncio
    async def test_empty_content_raises_adapter_error(self):
        from server.content.base import AdapterError, AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="narrative", raw_content="")
        with pytest.raises(AdapterError) as exc_info:
            await adapter.adapt(ai)
        assert exc_info.value.code == "ADAPTER_INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_paragraph_fallback_produces_scenes(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(NO_HEADING_MARKDOWN))
        assert len(result.scenes) == 3

    @pytest.mark.asyncio
    async def test_paragraph_fallback_scene_list_validates(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(NO_HEADING_MARKDOWN))
        ok, errors = result.validate()
        assert ok is True, errors

    @pytest.mark.asyncio
    async def test_nonexistent_skill_does_not_raise(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(skill_name="nonexistent-skill-xyz"))
        assert len(result.scenes) == 3

    @pytest.mark.asyncio
    async def test_skill_prefix_applied_when_skill_exists(self, tmp_path):
        """When a valid skill is applied, its prefix should appear in every prompt."""
        skill_dir = tmp_path / "skills" / "test-narrative-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "manifest.yaml").write_text(
            "name: test-narrative-skill\nversion: 1.0.0\nadapter_type: narrative_script\n",
            encoding="utf-8",
        )
        (skill_dir / "prefix.md").write_text(
            "NARRATIVE_SKILL_PREFIX. Cinematic style.",
            encoding="utf-8",
        )

        from server.content.adapters.narrative_script.adapter import NarrativeScriptAdapter
        from server.content.skill_loader import SkillLoader, apply_skill_to_scene

        adapter = NarrativeScriptAdapter()
        result_no_skill = await adapter.adapt(_make_input())

        loader = SkillLoader(tmp_path / "skills")
        skill = loader.load("test-narrative-skill")
        scenes_with_skill = [
            apply_skill_to_scene(scene, skill) for scene in result_no_skill.scenes
        ]

        for scene in scenes_with_skill:
            assert "NARRATIVE_SKILL_PREFIX" in scene.prompt

    @pytest.mark.asyncio
    async def test_heading_appears_in_prompt(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert "Cảnh 1: Giới thiệu" in result.scenes[0].prompt

    @pytest.mark.asyncio
    async def test_narration_from_bold_tag_in_scene(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert "Xin chào các bạn" in result.scenes[0].narration

    @pytest.mark.asyncio
    async def test_narration_from_blockquote_in_scene(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert "khoảnh khắc quyết định" in result.scenes[1].narration


# ═════════════════════════════════════════════════════════════════════════════
# Auto-discovery exports
# ═════════════════════════════════════════════════════════════════════════════


class TestAutoDiscovery:
    def test_adapter_instance_exported(self):
        from server.content.adapters.narrative_script.adapter import ADAPTER

        assert ADAPTER is not None
        assert ADAPTER.adapter_type == "narrative_script"

    def test_adapter_class_exported(self):
        from server.content.adapters.narrative_script.adapter import ADAPTER_CLASS

        assert ADAPTER_CLASS is not None
        assert ADAPTER_CLASS.adapter_type == "narrative_script"

    def test_adapter_satisfies_protocol(self):
        from server.content.adapters.narrative_script.adapter import ADAPTER
        from server.content.base import ContentAdapter

        assert isinstance(ADAPTER, ContentAdapter)

    def test_registry_auto_discover_finds_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        assert "narrative_script" in registry.list_types()

    def test_registry_get_returns_correct_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        adapter = registry.get("narrative_script")
        assert adapter.adapter_type == "narrative_script"


# ═════════════════════════════════════════════════════════════════════════════
# Integration: 1 markdown → video (SceneList)
# ═════════════════════════════════════════════════════════════════════════════


class TestMarkdownToVideo:
    """End-to-end test: 1 markdown narrative → SceneList ready for video pipeline."""

    @pytest.mark.asyncio
    async def test_markdown_to_scene_list(self):
        """Simulate the full flow: markdown script → SceneList."""
        from server.content.adapters.narrative_script.adapter import NarrativeScriptAdapter
        from server.content.base import AdapterInput, SceneList

        markdown = """\
## Mở đầu: Buổi sáng tại Hà Nội

Ánh nắng ban mai chiếu qua cửa sổ. Thành phố đang thức dậy.

**Narration:** Hà Nội — thành phố ngàn năm văn hiến, nơi mỗi buổi sáng đều mang một câu chuyện riêng.

**Location:** outdoor_urban

## Cao trào: Khám phá phố cổ

Những con phố nhỏ quanh co, mùi cà phê trứng thơm lừng.

> Đây là nơi lịch sử và hiện đại giao thoa, tạo nên một Hà Nội độc đáo không nơi nào có được.

**Location:** indoor_cafe

## Kết thúc: Hoàng hôn trên Hồ Tây

Mặt trời dần khuất sau những tòa nhà cao tầng. Hồ Tây phản chiếu ánh vàng.

**Narration:** Và khi hoàng hôn buông xuống, Hà Nội lại trở về với nhịp sống bình yên của mình.

**Location:** outdoor_nature
"""

        adapter = NarrativeScriptAdapter()
        ai = AdapterInput(
            source_type="narrative",
            raw_content=markdown,
            options={"project_id": "test_hanoi_vlog"},
        )

        result = await adapter.adapt(ai)

        # Verify it's a valid SceneList
        assert isinstance(result, SceneList)
        ok, errors = result.validate()
        assert ok is True, f"SceneList validation failed: {errors}"

        # Verify structure
        assert len(result.scenes) == 3
        assert result.scenes[0].order == 0
        assert result.scenes[1].order == 1
        assert result.scenes[2].order == 2

        # Verify all scenes have content
        for scene in result.scenes:
            assert scene.prompt.strip()
            assert scene.narration and scene.narration.strip()
            assert 3.0 <= scene.duration <= 30.0

        # Verify location hints
        assert result.scenes[0].location_hint == "outdoor_urban"
        assert result.scenes[1].location_hint == "indoor_cafe"
        assert result.scenes[2].location_hint == "outdoor_nature"

        # Verify headings appear in prompts
        assert "Mở đầu: Buổi sáng tại Hà Nội" in result.scenes[0].prompt
        assert "Cao trào: Khám phá phố cổ" in result.scenes[1].prompt
        assert "Kết thúc: Hoàng hôn trên Hồ Tây" in result.scenes[2].prompt

        # Verify narrations
        assert "Hà Nội" in result.scenes[0].narration
        assert "lịch sử và hiện đại" in result.scenes[1].narration
        assert "hoàng hôn" in result.scenes[2].narration

        # Verify cost estimate
        cost = result.estimate_cost()
        assert cost["veo3_clips"] == 3
        assert cost["total_video_duration_sec"] > 0
