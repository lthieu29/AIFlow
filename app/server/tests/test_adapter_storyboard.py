"""Unit tests for Task 4.4 — StoryboardManualAdapter.

Covers:
- schema.py: StoryboardScene, Storyboard, validate_storyboard, STORYBOARD_JSON_SCHEMA
- adapter.py: StoryboardManualAdapter.validate_input, adapt (async)
- Auto-discovery: ADAPTER instance and ADAPTER_CLASS exports
- SceneList structure: correct scene count, durations, orders
- Skill application: skill prefix prepended when skill_name is set
- Edge cases: missing fields, invalid JSON, non-contiguous orders, bad paths
- Integration: 1 JSON storyboard → video (SceneList)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _make_storyboard_json(
    title: str = "Test Video",
    voice: str | None = "vi-VN-HoaiMyNeural",
    scenes: list[dict] | None = None,
) -> str:
    if scenes is None:
        scenes = [
            {
                "order": 0,
                "prompt": "A beautiful sunrise over the mountains.",
                "duration": 8.0,
                "narration": "Bình minh ló dạng trên đỉnh núi.",
                "location_hint": "outdoor_nature",
            },
            {
                "order": 1,
                "prompt": "A person hiking through a forest trail.",
                "duration": 8.0,
                "narration": "Hành trình khám phá thiên nhiên.",
                "location_hint": "outdoor_nature",
            },
        ]
    data: dict = {"title": title, "scenes": scenes}
    if voice is not None:
        data["voice"] = voice
    return json.dumps(data)


def _make_input(
    raw_content: str | None = None,
    skill_name: str | None = None,
    options: dict | None = None,
) -> "AdapterInput":
    from server.content.base import AdapterInput

    return AdapterInput(
        source_type="storyboard",
        raw_content=raw_content if raw_content is not None else _make_storyboard_json(),
        skill_name=skill_name,
        options=options or {},
    )


# ═════════════════════════════════════════════════════════════════════════════
# schema.py — StoryboardScene
# ═════════════════════════════════════════════════════════════════════════════


class TestStoryboardScene:
    def test_minimal_valid_scene(self):
        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        scene = StoryboardScene(order=0, prompt="A sunny day.")
        assert scene.order == 0
        assert scene.prompt == "A sunny day."
        assert scene.duration == 8.0
        assert scene.narration is None
        assert scene.location_hint is None
        assert scene.start_image is None

    def test_blank_prompt_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        with pytest.raises(ValidationError):
            StoryboardScene(order=0, prompt="   ")

    def test_empty_prompt_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        with pytest.raises(ValidationError):
            StoryboardScene(order=0, prompt="")

    def test_duration_below_min_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        with pytest.raises(ValidationError):
            StoryboardScene(order=0, prompt="Prompt.", duration=2.9)

    def test_duration_above_max_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        with pytest.raises(ValidationError):
            StoryboardScene(order=0, prompt="Prompt.", duration=30.1)

    def test_duration_at_boundaries_valid(self):
        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        s1 = StoryboardScene(order=0, prompt="Prompt.", duration=3.0)
        s2 = StoryboardScene(order=0, prompt="Prompt.", duration=30.0)
        assert s1.duration == 3.0
        assert s2.duration == 30.0

    def test_start_image_nonexistent_raises(self, tmp_path):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        missing = str(tmp_path / "nonexistent.jpg")
        with pytest.raises(ValidationError):
            StoryboardScene(order=0, prompt="Prompt.", start_image=missing)

    def test_start_image_existing_is_valid(self, tmp_path):
        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        img = tmp_path / "frame.jpg"
        img.write_bytes(b"JPEG")
        scene = StoryboardScene(order=0, prompt="Prompt.", start_image=str(img))
        assert scene.start_image == str(img)

    def test_start_image_none_is_valid(self):
        from server.content.adapters.storyboard_manual.schema import StoryboardScene

        scene = StoryboardScene(order=0, prompt="Prompt.", start_image=None)
        assert scene.start_image is None


# ═════════════════════════════════════════════════════════════════════════════
# schema.py — Storyboard
# ═════════════════════════════════════════════════════════════════════════════


class TestStoryboard:
    def _minimal_scene(self, order: int = 0) -> dict:
        return {"order": order, "prompt": f"Scene {order} prompt."}

    def test_minimal_valid_storyboard(self):
        from server.content.adapters.storyboard_manual.schema import Storyboard

        sb = Storyboard(scenes=[self._minimal_scene()])
        assert sb.title == ""
        assert sb.voice is None
        assert len(sb.scenes) == 1

    def test_empty_scenes_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import Storyboard

        with pytest.raises(ValidationError):
            Storyboard(scenes=[])

    def test_non_contiguous_orders_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import Storyboard

        with pytest.raises(ValidationError):
            Storyboard(scenes=[
                {"order": 0, "prompt": "First."},
                {"order": 2, "prompt": "Third — skipped 1."},
            ])

    def test_orders_not_starting_from_zero_raises(self):
        from pydantic import ValidationError

        from server.content.adapters.storyboard_manual.schema import Storyboard

        with pytest.raises(ValidationError):
            Storyboard(scenes=[{"order": 1, "prompt": "Starts at 1."}])

    def test_multiple_scenes_valid(self):
        from server.content.adapters.storyboard_manual.schema import Storyboard

        sb = Storyboard(scenes=[self._minimal_scene(i) for i in range(5)])
        assert len(sb.scenes) == 5

    def test_title_and_voice_set(self):
        from server.content.adapters.storyboard_manual.schema import Storyboard

        sb = Storyboard(
            title="My Video",
            voice="vi-VN-HoaiMyNeural",
            scenes=[self._minimal_scene()],
        )
        assert sb.title == "My Video"
        assert sb.voice == "vi-VN-HoaiMyNeural"


# ═════════════════════════════════════════════════════════════════════════════
# schema.py — validate_storyboard
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateStoryboard:
    def _valid_data(self) -> dict:
        return {
            "title": "Test",
            "scenes": [{"order": 0, "prompt": "A prompt."}],
        }

    def test_valid_data_returns_true(self):
        from server.content.adapters.storyboard_manual.schema import validate_storyboard

        ok, errors = validate_storyboard(self._valid_data())
        assert ok is True
        assert errors == []

    def test_empty_scenes_returns_false(self):
        from server.content.adapters.storyboard_manual.schema import validate_storyboard

        ok, errors = validate_storyboard({"scenes": []})
        assert ok is False
        assert len(errors) > 0

    def test_missing_scenes_returns_false(self):
        from server.content.adapters.storyboard_manual.schema import validate_storyboard

        ok, errors = validate_storyboard({"title": "No scenes"})
        assert ok is False
        assert len(errors) > 0

    def test_non_contiguous_orders_returns_false(self):
        from server.content.adapters.storyboard_manual.schema import validate_storyboard

        ok, errors = validate_storyboard({
            "scenes": [
                {"order": 0, "prompt": "First."},
                {"order": 5, "prompt": "Gap."},
            ]
        })
        assert ok is False
        assert len(errors) > 0

    def test_blank_prompt_returns_false(self):
        from server.content.adapters.storyboard_manual.schema import validate_storyboard

        ok, errors = validate_storyboard({
            "scenes": [{"order": 0, "prompt": ""}]
        })
        assert ok is False
        assert len(errors) > 0

    def test_errors_are_strings(self):
        from server.content.adapters.storyboard_manual.schema import validate_storyboard

        ok, errors = validate_storyboard({"scenes": []})
        assert ok is False
        for e in errors:
            assert isinstance(e, str)


# ═════════════════════════════════════════════════════════════════════════════
# schema.py — STORYBOARD_JSON_SCHEMA
# ═════════════════════════════════════════════════════════════════════════════


class TestStoryboardJsonSchema:
    def test_schema_is_dict(self):
        from server.content.adapters.storyboard_manual.schema import STORYBOARD_JSON_SCHEMA

        assert isinstance(STORYBOARD_JSON_SCHEMA, dict)

    def test_schema_has_required_keys(self):
        from server.content.adapters.storyboard_manual.schema import STORYBOARD_JSON_SCHEMA

        assert "type" in STORYBOARD_JSON_SCHEMA
        assert "properties" in STORYBOARD_JSON_SCHEMA
        assert "scenes" in STORYBOARD_JSON_SCHEMA["properties"]

    def test_schema_requires_scenes(self):
        from server.content.adapters.storyboard_manual.schema import STORYBOARD_JSON_SCHEMA

        assert "scenes" in STORYBOARD_JSON_SCHEMA.get("required", [])


# ═════════════════════════════════════════════════════════════════════════════
# adapter.py — StoryboardManualAdapter.validate_input
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateInput:
    def _adapter(self):
        from server.content.adapters.storyboard_manual.adapter import StoryboardManualAdapter

        return StoryboardManualAdapter()

    def test_valid_input_returns_empty_errors(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input())
        assert errors == []

    def test_empty_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="storyboard", raw_content="")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_whitespace_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="storyboard", raw_content="   ")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_invalid_json_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="storyboard", raw_content="{not valid json}")
        errors = adapter.validate_input(ai)
        assert any("JSON" in e for e in errors)

    def test_json_array_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="storyboard", raw_content='["not", "an", "object"]')
        errors = adapter.validate_input(ai)
        assert any("object" in e for e in errors)

    def test_missing_scenes_returns_error(self):
        adapter = self._adapter()
        raw = json.dumps({"title": "No scenes"})
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert len(errors) > 0

    def test_empty_scenes_returns_error(self):
        adapter = self._adapter()
        raw = json.dumps({"scenes": []})
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert len(errors) > 0

    def test_non_contiguous_orders_returns_error(self):
        adapter = self._adapter()
        raw = json.dumps({
            "scenes": [
                {"order": 0, "prompt": "First."},
                {"order": 2, "prompt": "Gap."},
            ]
        })
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert len(errors) > 0

    def test_blank_prompt_returns_error(self):
        adapter = self._adapter()
        raw = json.dumps({"scenes": [{"order": 0, "prompt": ""}]})
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert len(errors) > 0

    def test_duration_out_of_range_returns_error(self):
        adapter = self._adapter()
        raw = json.dumps({"scenes": [{"order": 0, "prompt": "P.", "duration": 1.0}]})
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert len(errors) > 0

    def test_nonexistent_start_image_returns_error(self, tmp_path):
        adapter = self._adapter()
        missing = str(tmp_path / "nonexistent.jpg")
        raw = json.dumps({"scenes": [{"order": 0, "prompt": "P.", "start_image": missing}]})
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert len(errors) > 0

    def test_existing_start_image_is_valid(self, tmp_path):
        adapter = self._adapter()
        img = tmp_path / "frame.jpg"
        img.write_bytes(b"JPEG")
        raw = json.dumps({"scenes": [{"order": 0, "prompt": "P.", "start_image": str(img)}]})
        errors = adapter.validate_input(_make_input(raw_content=raw))
        assert errors == []


# ═════════════════════════════════════════════════════════════════════════════
# adapter.py — StoryboardManualAdapter.adapt (async)
# ═════════════════════════════════════════════════════════════════════════════


class TestAdapt:
    def _adapter(self):
        from server.content.adapters.storyboard_manual.adapter import StoryboardManualAdapter

        return StoryboardManualAdapter()

    @pytest.mark.asyncio
    async def test_returns_scene_list(self):
        from server.content.base import SceneList

        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert isinstance(result, SceneList)

    @pytest.mark.asyncio
    async def test_scene_count_matches_input(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": i, "prompt": f"Scene {i}."} for i in range(4)
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert len(result.scenes) == 4

    @pytest.mark.asyncio
    async def test_scenes_have_correct_order(self):
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
    async def test_prompts_preserved(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": 0, "prompt": "UNIQUE_PROMPT_MARKER_XYZ"}
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].prompt == "UNIQUE_PROMPT_MARKER_XYZ"

    @pytest.mark.asyncio
    async def test_narration_preserved(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": 0, "prompt": "P.", "narration": "NARRATION_MARKER_ABC"}
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].narration == "NARRATION_MARKER_ABC"

    @pytest.mark.asyncio
    async def test_duration_preserved(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": 0, "prompt": "P.", "duration": 12.0}
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].duration == pytest.approx(12.0)

    @pytest.mark.asyncio
    async def test_default_duration_is_8(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[{"order": 0, "prompt": "P."}])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].duration == pytest.approx(8.0)

    @pytest.mark.asyncio
    async def test_location_hint_preserved(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": 0, "prompt": "P.", "location_hint": "indoor_cafe"}
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].location_hint == "indoor_cafe"

    @pytest.mark.asyncio
    async def test_voice_from_storyboard(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(voice="vi-VN-NamMinhNeural")
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.voice == "vi-VN-NamMinhNeural"

    @pytest.mark.asyncio
    async def test_voice_from_options_overrides_storyboard(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(voice="vi-VN-HoaiMyNeural")
        result = await adapter.adapt(_make_input(
            raw_content=raw,
            options={"voice": "vi-VN-NamMinhNeural"},
        ))
        assert result.voice == "vi-VN-NamMinhNeural"

    @pytest.mark.asyncio
    async def test_no_voice_is_none(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(voice=None)
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.voice is None

    @pytest.mark.asyncio
    async def test_metadata_contains_adapter_type(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["adapter"] == "storyboard_manual"

    @pytest.mark.asyncio
    async def test_metadata_contains_title(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(title="My Awesome Video")
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.metadata["title"] == "My Awesome Video"

    @pytest.mark.asyncio
    async def test_metadata_contains_scene_count(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": i, "prompt": f"Scene {i}."} for i in range(3)
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.metadata["scene_count"] == 3

    @pytest.mark.asyncio
    async def test_invalid_input_raises_adapter_error(self):
        from server.content.base import AdapterError, AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="storyboard", raw_content="")
        with pytest.raises(AdapterError) as exc_info:
            await adapter.adapt(ai)
        assert exc_info.value.code == "ADAPTER_INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_start_image_converted_to_path(self, tmp_path):
        adapter = self._adapter()
        img = tmp_path / "frame.jpg"
        img.write_bytes(b"JPEG")
        raw = _make_storyboard_json(scenes=[
            {"order": 0, "prompt": "P.", "start_image": str(img)}
        ])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].start_image == img

    @pytest.mark.asyncio
    async def test_no_start_image_is_none(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[{"order": 0, "prompt": "P."}])
        result = await adapter.adapt(_make_input(raw_content=raw))
        assert result.scenes[0].start_image is None

    @pytest.mark.asyncio
    async def test_project_id_from_options(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(options={"project_id": "my_project_123"}))
        assert result.project_id == "my_project_123"

    @pytest.mark.asyncio
    async def test_default_project_id(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.project_id == "storyboard_manual"


# ═════════════════════════════════════════════════════════════════════════════
# Skill application
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillApplication:
    def _adapter(self):
        from server.content.adapters.storyboard_manual.adapter import StoryboardManualAdapter

        return StoryboardManualAdapter()

    @pytest.mark.asyncio
    async def test_skill_prefix_prepended_to_prompts(self, tmp_path):
        skill_dir = tmp_path / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "manifest.yaml").write_text(
            "name: test-skill\nversion: 1.0.0\nadapter_type: storyboard_manual\n",
            encoding="utf-8",
        )
        (skill_dir / "prefix.md").write_text(
            "STORYBOARD_SKILL_PREFIX_MARKER. Photoreal.",
            encoding="utf-8",
        )

        from server.content.adapters.storyboard_manual.adapter import StoryboardManualAdapter
        from server.content.skill_loader import SkillLoader, apply_skill_to_scene

        adapter = StoryboardManualAdapter()
        result_no_skill = await adapter.adapt(_make_input())

        loader = SkillLoader(tmp_path / "skills")
        skill = loader.load("test-skill")
        scenes_with_skill = [
            apply_skill_to_scene(scene, skill) for scene in result_no_skill.scenes
        ]

        for scene in scenes_with_skill:
            assert "STORYBOARD_SKILL_PREFIX_MARKER" in scene.prompt

    @pytest.mark.asyncio
    async def test_nonexistent_skill_does_not_raise(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(skill_name="nonexistent-skill-xyz"))
        assert len(result.scenes) >= 1

    @pytest.mark.asyncio
    async def test_no_skill_name_prompts_unchanged(self):
        adapter = self._adapter()
        raw = _make_storyboard_json(scenes=[
            {"order": 0, "prompt": "ORIGINAL_PROMPT_NO_SKILL"}
        ])
        result = await adapter.adapt(_make_input(raw_content=raw, skill_name=None))
        assert result.scenes[0].prompt == "ORIGINAL_PROMPT_NO_SKILL"


# ═════════════════════════════════════════════════════════════════════════════
# Auto-discovery exports
# ═════════════════════════════════════════════════════════════════════════════


class TestAutoDiscovery:
    def test_adapter_instance_exported(self):
        from server.content.adapters.storyboard_manual.adapter import ADAPTER

        assert ADAPTER is not None
        assert ADAPTER.adapter_type == "storyboard_manual"

    def test_adapter_class_exported(self):
        from server.content.adapters.storyboard_manual.adapter import ADAPTER_CLASS

        assert ADAPTER_CLASS is not None
        assert ADAPTER_CLASS.adapter_type == "storyboard_manual"

    def test_adapter_satisfies_protocol(self):
        from server.content.adapters.storyboard_manual.adapter import ADAPTER
        from server.content.base import ContentAdapter

        assert isinstance(ADAPTER, ContentAdapter)

    def test_registry_auto_discover_finds_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        assert "storyboard_manual" in registry.list_types()

    def test_registry_get_returns_correct_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        adapter = registry.get("storyboard_manual")
        assert adapter.adapter_type == "storyboard_manual"


# ═════════════════════════════════════════════════════════════════════════════
# Integration: 1 JSON storyboard → video (SceneList)
# ═════════════════════════════════════════════════════════════════════════════


class TestJsonToVideo:
    """End-to-end test: 1 JSON storyboard → SceneList ready for video pipeline."""

    @pytest.mark.asyncio
    async def test_storyboard_json_to_scene_list(self, tmp_path):
        from server.content.adapters.storyboard_manual.adapter import StoryboardManualAdapter
        from server.content.base import SceneList

        # Create a fake start-frame image
        start_img = tmp_path / "scene0_start.jpg"
        start_img.write_bytes(b"\xff\xd8\xff\xe0JPEG")

        storyboard_data = {
            "title": "Cà Phê Sáng",
            "voice": "vi-VN-HoaiMyNeural",
            "scenes": [
                {
                    "order": 0,
                    "prompt": "Close-up of a steaming coffee cup on a wooden table.",
                    "duration": 8.0,
                    "narration": "Bắt đầu ngày mới với ly cà phê thơm ngon.",
                    "location_hint": "indoor_cafe",
                    "start_image": str(start_img),
                },
                {
                    "order": 1,
                    "prompt": "Person smiling while drinking coffee, warm morning light.",
                    "duration": 8.0,
                    "narration": "Hương vị đậm đà, khó quên.",
                    "location_hint": "indoor_cafe",
                },
                {
                    "order": 2,
                    "prompt": "Aerial view of a coffee plantation at sunrise.",
                    "duration": 10.0,
                    "narration": "Từ những hạt cà phê chọn lọc kỹ càng.",
                    "location_hint": "outdoor_nature",
                },
            ],
        }

        from server.content.base import AdapterInput

        adapter = StoryboardManualAdapter()
        ai = AdapterInput(
            source_type="storyboard",
            raw_content=json.dumps(storyboard_data),
            options={"project_id": "ca_phe_sang_001"},
        )

        result = await adapter.adapt(ai)

        # Verify it's a valid SceneList
        assert isinstance(result, SceneList)
        ok, errors = result.validate()
        assert ok is True, f"SceneList validation failed: {errors}"

        # Verify structure
        assert len(result.scenes) == 3
        assert result.project_id == "ca_phe_sang_001"
        assert result.voice == "vi-VN-HoaiMyNeural"
        assert result.metadata["title"] == "Cà Phê Sáng"
        assert result.metadata["adapter"] == "storyboard_manual"

        # Verify scene content preserved
        assert result.scenes[0].prompt == storyboard_data["scenes"][0]["prompt"]
        assert result.scenes[0].narration == storyboard_data["scenes"][0]["narration"]
        assert result.scenes[0].location_hint == "indoor_cafe"
        assert result.scenes[0].start_image == start_img
        assert result.scenes[1].start_image is None
        assert result.scenes[2].duration == pytest.approx(10.0)

        # Verify cost estimate
        cost = result.estimate_cost()
        assert cost["veo3_clips"] == 3
        assert cost["total_video_duration_sec"] == pytest.approx(26.0)
