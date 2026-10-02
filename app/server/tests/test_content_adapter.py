"""Unit tests for the ContentAdapter framework (Task 4.0.1).

Covers:
- SceneSpec dataclass construction and defaults
- SceneList dataclass construction, validate(), and estimate_cost()
- AdapterInput dataclass construction and defaults
- AdapterError attributes
- ContentAdapter Protocol runtime_checkable behaviour
- AdapterRegistry: register, get, list_types, auto_discover, register_adapter decorator
- SkillManifest Pydantic model validation
- load_skill_manifest() happy path and error paths
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

# Ensure the server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — minimal concrete adapter for testing
# ─────────────────────────────────────────────────────────────────────────────


def _make_minimal_adapter_cls(type_name: str = "test_adapter"):
    """Return a minimal class that satisfies the ContentAdapter Protocol."""
    from server.content.base import AdapterInput, SceneList, SceneSpec

    class _MinimalAdapter:
        async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
            return SceneList(
                project_id="proj_test",
                scenes=[SceneSpec(order=0, prompt="test prompt")],
            )

        def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
            return []

    # Set adapter_type after class definition to avoid Python 3.14 scoping issue
    _MinimalAdapter.adapter_type = type_name  # type: ignore[attr-defined]
    return _MinimalAdapter


# ─────────────────────────────────────────────────────────────────────────────
# SceneSpec
# ─────────────────────────────────────────────────────────────────────────────


class TestSceneSpec:
    def test_required_fields(self):
        from server.content.base import SceneSpec

        s = SceneSpec(order=0, prompt="A woman walks into a café.")
        assert s.order == 0
        assert s.prompt == "A woman walks into a café."

    def test_default_duration(self):
        from server.content.base import SceneSpec

        s = SceneSpec(order=1, prompt="Scene 2")
        assert s.duration == 8.0

    def test_optional_fields_default_to_none(self):
        from server.content.base import SceneSpec

        s = SceneSpec(order=0, prompt="p")
        assert s.start_image is None
        assert s.location_hint is None
        assert s.narration is None

    def test_all_fields_set(self, tmp_path):
        from server.content.base import SceneSpec

        img = tmp_path / "frame.png"
        img.write_bytes(b"\x89PNG")
        s = SceneSpec(
            order=2,
            prompt="Hero enters building.",
            duration=10.0,
            start_image=img,
            location_hint="indoor_office",
            narration="The hero steps inside.",
        )
        assert s.order == 2
        assert s.duration == 10.0
        assert s.start_image == img
        assert s.location_hint == "indoor_office"
        assert s.narration == "The hero steps inside."


# ─────────────────────────────────────────────────────────────────────────────
# SceneList
# ─────────────────────────────────────────────────────────────────────────────


class TestSceneList:
    def _make_scene_list(self, n: int = 3) -> "SceneList":
        from server.content.base import SceneList, SceneSpec

        scenes = [SceneSpec(order=i, prompt=f"Scene {i}", narration=f"Narration {i}") for i in range(n)]
        return SceneList(project_id="proj_abc", scenes=scenes)

    def test_construction(self):
        from server.content.base import SceneList, SceneSpec

        sl = SceneList(
            project_id="p1",
            scenes=[SceneSpec(order=0, prompt="p")],
        )
        assert sl.project_id == "p1"
        assert len(sl.scenes) == 1

    def test_optional_fields_default(self):
        from server.content.base import SceneList, SceneSpec

        sl = SceneList(project_id="p1", scenes=[SceneSpec(order=0, prompt="p")])
        assert sl.style_ref is None
        assert sl.voice is None
        assert sl.metadata == {}

    def test_validate_valid_scene_list(self):
        sl = self._make_scene_list(3)
        ok, errors = sl.validate()
        assert ok is True
        assert errors == []

    def test_validate_empty_scenes(self):
        from server.content.base import SceneList

        sl = SceneList(project_id="p1", scenes=[])
        ok, errors = sl.validate()
        assert ok is False
        assert any("empty" in e for e in errors)

    def test_validate_non_contiguous_order(self):
        from server.content.base import SceneList, SceneSpec

        sl = SceneList(
            project_id="p1",
            scenes=[
                SceneSpec(order=0, prompt="a"),
                SceneSpec(order=2, prompt="b"),  # gap — should be 1
            ],
        )
        ok, errors = sl.validate()
        assert ok is False
        assert any("order" in e for e in errors)

    def test_validate_duration_too_short(self):
        from server.content.base import SceneList, SceneSpec

        sl = SceneList(
            project_id="p1",
            scenes=[SceneSpec(order=0, prompt="a", duration=1.0)],
        )
        ok, errors = sl.validate()
        assert ok is False
        assert any("duration" in e for e in errors)

    def test_validate_duration_too_long(self):
        from server.content.base import SceneList, SceneSpec

        sl = SceneList(
            project_id="p1",
            scenes=[SceneSpec(order=0, prompt="a", duration=60.0)],
        )
        ok, errors = sl.validate()
        assert ok is False
        assert any("duration" in e for e in errors)

    def test_validate_duration_boundary_values(self):
        from server.content.base import SceneList, SceneSpec

        # Exactly 3.0 and 30.0 are valid
        sl = SceneList(
            project_id="p1",
            scenes=[
                SceneSpec(order=0, prompt="a", duration=3.0),
                SceneSpec(order=1, prompt="b", duration=30.0),
            ],
        )
        ok, errors = sl.validate()
        assert ok is True, errors

    def test_estimate_cost_counts_clips(self):
        sl = self._make_scene_list(5)
        cost = sl.estimate_cost()
        assert cost["veo3_clips"] == 5

    def test_estimate_cost_total_duration(self):
        sl = self._make_scene_list(3)  # 3 × 8.0 = 24.0
        cost = sl.estimate_cost()
        assert cost["total_video_duration_sec"] == pytest.approx(24.0)

    def test_estimate_cost_tts_duration_only_narrated_scenes(self):
        from server.content.base import SceneList, SceneSpec

        sl = SceneList(
            project_id="p1",
            scenes=[
                SceneSpec(order=0, prompt="a", duration=8.0, narration="Hello"),
                SceneSpec(order=1, prompt="b", duration=8.0),  # no narration
                SceneSpec(order=2, prompt="c", duration=8.0, narration="World"),
            ],
        )
        cost = sl.estimate_cost()
        assert cost["tts_duration_sec"] == pytest.approx(16.0)


# ─────────────────────────────────────────────────────────────────────────────
# AdapterInput
# ─────────────────────────────────────────────────────────────────────────────


class TestAdapterInput:
    def test_required_fields(self):
        from server.content.base import AdapterInput

        ai = AdapterInput(source_type="product", raw_content='{"name": "shirt"}')
        assert ai.source_type == "product"
        assert ai.raw_content == '{"name": "shirt"}'

    def test_defaults(self):
        from server.content.base import AdapterInput

        ai = AdapterInput(source_type="blog", raw_content="https://example.com")
        assert ai.assets == {}
        assert ai.skill_name is None
        assert ai.options == {}

    def test_assets_and_options(self, tmp_path):
        from server.content.base import AdapterInput

        img = tmp_path / "product.jpg"
        img.write_bytes(b"JPEG")
        ai = AdapterInput(
            source_type="product",
            raw_content="",
            assets={"product_image": img},
            skill_name="ecommerce-fashion",
            options={"tone": "fun"},
        )
        assert ai.assets["product_image"] == img
        assert ai.skill_name == "ecommerce-fashion"
        assert ai.options["tone"] == "fun"


# ─────────────────────────────────────────────────────────────────────────────
# AdapterError
# ─────────────────────────────────────────────────────────────────────────────


class TestAdapterError:
    def test_basic_attributes(self):
        from server.content.base import AdapterError

        err = AdapterError("ADAPTER_NOT_FOUND", "No adapter: foo")
        assert err.code == "ADAPTER_NOT_FOUND"
        assert err.message == "No adapter: foo"
        assert err.details == {}

    def test_details_stored(self):
        from server.content.base import AdapterError

        err = AdapterError("ADAPTER_INVALID_INPUT", "Bad input", details={"field": "url"})
        assert err.details["field"] == "url"

    def test_is_exception(self):
        from server.content.base import AdapterError

        with pytest.raises(AdapterError) as exc_info:
            raise AdapterError("CODE", "message")
        assert exc_info.value.code == "CODE"

    def test_str_is_message(self):
        from server.content.base import AdapterError

        err = AdapterError("X", "human readable message")
        assert "human readable message" in str(err)


# ─────────────────────────────────────────────────────────────────────────────
# ContentAdapter Protocol
# ─────────────────────────────────────────────────────────────────────────────


class TestContentAdapterProtocol:
    def test_isinstance_check_passes_for_conforming_class(self):
        from server.content.base import ContentAdapter

        cls = _make_minimal_adapter_cls()
        instance = cls()
        assert isinstance(instance, ContentAdapter)

    def test_isinstance_check_fails_for_missing_adapt(self):
        from server.content.base import ContentAdapter

        class _Bad:
            adapter_type = "bad"

            def validate_input(self, input):  # noqa: A002
                return []

            # no adapt() method

        assert not isinstance(_Bad(), ContentAdapter)

    def test_isinstance_check_fails_for_missing_validate_input(self):
        from server.content.base import ContentAdapter, AdapterInput, SceneList, SceneSpec

        class _Bad:
            adapter_type = "bad"

            async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
                return SceneList(project_id="x", scenes=[SceneSpec(order=0, prompt="p")])

            # no validate_input() method

        assert not isinstance(_Bad(), ContentAdapter)

    def test_adapter_type_attribute_required(self):
        from server.content.base import ContentAdapter, AdapterInput, SceneList, SceneSpec

        class _NoType:
            async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
                return SceneList(project_id="x", scenes=[SceneSpec(order=0, prompt="p")])

            def validate_input(self, input) -> list[str]:  # noqa: A002
                return []

        # Missing adapter_type — Protocol check fails
        assert not isinstance(_NoType(), ContentAdapter)


# ─────────────────────────────────────────────────────────────────────────────
# AdapterRegistry
# ─────────────────────────────────────────────────────────────────────────────


class TestAdapterRegistry:
    def _fresh_registry(self):
        from server.content.registry import AdapterRegistry

        return AdapterRegistry()

    def test_register_and_get(self):
        registry = self._fresh_registry()
        cls = _make_minimal_adapter_cls("reg_test")
        registry.register(cls)
        adapter = registry.get("reg_test")
        assert adapter.adapter_type == "reg_test"

    def test_get_unknown_raises_adapter_error(self):
        from server.content.base import AdapterError

        registry = self._fresh_registry()
        with pytest.raises(AdapterError) as exc_info:
            registry.get("nonexistent")
        assert exc_info.value.code == "ADAPTER_NOT_FOUND"

    def test_list_types_empty(self):
        registry = self._fresh_registry()
        assert registry.list_types() == []

    def test_list_types_sorted(self):
        registry = self._fresh_registry()
        for name in ("zebra", "alpha", "mango"):
            registry.register(_make_minimal_adapter_cls(name))
        assert registry.list_types() == ["alpha", "mango", "zebra"]

    def test_register_missing_adapter_type_raises(self):
        from server.content.base import AdapterError

        registry = self._fresh_registry()

        class _NoType:
            async def adapt(self, input):  # noqa: A002
                pass

            def validate_input(self, input):  # noqa: A002
                return []

        with pytest.raises(AdapterError) as exc_info:
            registry.register(_NoType)
        assert exc_info.value.code == "ADAPTER_MISSING_TYPE"

    def test_register_overwrites_existing(self):
        registry = self._fresh_registry()
        cls1 = _make_minimal_adapter_cls("dup")
        cls2 = _make_minimal_adapter_cls("dup")
        registry.register(cls1)
        registry.register(cls2)  # should not raise
        # Still retrievable
        assert registry.get("dup").adapter_type == "dup"

    def test_register_returns_class(self):
        registry = self._fresh_registry()
        cls = _make_minimal_adapter_cls("ret_test")
        result = registry.register(cls)
        assert result is cls

    def test_auto_discover_no_package(self):
        """auto_discover on a non-existent package should not raise."""
        registry = self._fresh_registry()
        registry.auto_discover("server.content.adapters.nonexistent_pkg_xyz")
        assert registry.list_types() == []

    def test_auto_discover_finds_adapter_instance(self, tmp_path, monkeypatch):
        """auto_discover should register adapters that expose ADAPTER instance."""
        import importlib
        import sys

        # Build a fake package in tmp_path
        pkg_dir = tmp_path / "fake_adapters"
        sub_dir = pkg_dir / "my_adapter"
        sub_dir.mkdir(parents=True)
        (pkg_dir / "__init__.py").write_text("")
        (sub_dir / "__init__.py").write_text("")
        (sub_dir / "adapter.py").write_text(
            "class _A:\n"
            "    adapter_type = 'discovered_adapter'\n"
            "    async def adapt(self, input): pass\n"
            "    def validate_input(self, input): return []\n"
            "ADAPTER = _A()\n"
        )

        # Add tmp_path to sys.path so importlib can find the package
        monkeypatch.syspath_prepend(str(tmp_path))

        registry = self._fresh_registry()
        registry.auto_discover("fake_adapters")
        assert "discovered_adapter" in registry.list_types()

        # Cleanup sys.modules to avoid pollution
        for key in list(sys.modules.keys()):
            if "fake_adapters" in key:
                del sys.modules[key]


# ─────────────────────────────────────────────────────────────────────────────
# register_adapter decorator
# ─────────────────────────────────────────────────────────────────────────────


class TestRegisterAdapterDecorator:
    def test_decorator_registers_with_global_registry(self):
        """@register_adapter should add the class to the module-level REGISTRY."""
        from server.content.registry import REGISTRY, register_adapter

        @register_adapter
        class _DecoratorTestAdapter:
            adapter_type = "decorator_test_unique_xyz"

            async def adapt(self, input):  # noqa: A002
                pass

            def validate_input(self, input):  # noqa: A002
                return []

        assert "decorator_test_unique_xyz" in REGISTRY.list_types()

    def test_decorator_returns_class_unchanged(self):
        from server.content.registry import register_adapter

        @register_adapter
        class _ReturnTest:
            adapter_type = "return_test_unique_xyz"

            async def adapt(self, input):  # noqa: A002
                pass

            def validate_input(self, input):  # noqa: A002
                return []

        assert _ReturnTest.adapter_type == "return_test_unique_xyz"


# ─────────────────────────────────────────────────────────────────────────────
# SkillManifest
# ─────────────────────────────────────────────────────────────────────────────


class TestSkillManifest:
    def _minimal_data(self) -> dict:
        return {
            "name": "ecommerce-fashion",
            "version": "1.0.0",
            "adapter_type": "ecommerce_product",
        }

    def test_minimal_valid_manifest(self):
        from server.content.skill_manifest import SkillManifest

        m = SkillManifest.model_validate(self._minimal_data())
        assert m.name == "ecommerce-fashion"
        assert m.version == "1.0.0"
        assert m.adapter_type == "ecommerce_product"

    def test_defaults(self):
        from server.content.skill_manifest import SkillManifest

        m = SkillManifest.model_validate(self._minimal_data())
        assert m.style_ref is None
        assert m.voice is None
        assert m.camera_lock is True
        assert m.safety_level == "standard"
        assert m.options == {}

    def test_all_fields(self):
        from server.content.skill_manifest import SkillManifest

        data = {
            **self._minimal_data(),
            "style_ref": "style.json",
            "voice": "vi-VN-HoaiMyNeural",
            "camera_lock": False,
            "safety_level": "strict",
            "options": {"default_aspect_ratio": "9:16"},
        }
        m = SkillManifest.model_validate(data)
        assert m.style_ref == "style.json"
        assert m.voice == "vi-VN-HoaiMyNeural"
        assert m.camera_lock is False
        assert m.safety_level == "strict"
        assert m.options["default_aspect_ratio"] == "9:16"

    def test_safety_level_strict(self):
        from server.content.skill_manifest import SkillManifest

        m = SkillManifest.model_validate({**self._minimal_data(), "safety_level": "strict"})
        assert m.safety_level == "strict"

    def test_safety_level_relaxed(self):
        from server.content.skill_manifest import SkillManifest

        m = SkillManifest.model_validate({**self._minimal_data(), "safety_level": "relaxed"})
        assert m.safety_level == "relaxed"

    def test_invalid_safety_level_raises(self):
        from pydantic import ValidationError
        from server.content.skill_manifest import SkillManifest

        with pytest.raises(ValidationError):
            SkillManifest.model_validate({**self._minimal_data(), "safety_level": "none"})

    def test_missing_required_name_raises(self):
        from pydantic import ValidationError
        from server.content.skill_manifest import SkillManifest

        data = {"version": "1.0.0", "adapter_type": "x"}
        with pytest.raises(ValidationError):
            SkillManifest.model_validate(data)

    def test_missing_required_version_raises(self):
        from pydantic import ValidationError
        from server.content.skill_manifest import SkillManifest

        data = {"name": "x", "adapter_type": "y"}
        with pytest.raises(ValidationError):
            SkillManifest.model_validate(data)

    def test_extra_fields_allowed(self):
        """manifest.yaml may have extra keys (e.g. 'extends', 'description')."""
        from server.content.skill_manifest import SkillManifest

        data = {**self._minimal_data(), "extends": "_base", "description": "Fashion skill"}
        m = SkillManifest.model_validate(data)
        assert m.name == "ecommerce-fashion"


# ─────────────────────────────────────────────────────────────────────────────
# load_skill_manifest
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadSkillManifest:
    def _write_manifest(self, skill_dir: Path, content: str) -> None:
        (skill_dir / "manifest.yaml").write_text(content, encoding="utf-8")

    def test_loads_valid_manifest(self, tmp_path):
        from server.content.skill_manifest import load_skill_manifest

        self._write_manifest(
            tmp_path,
            "name: ecommerce-fashion\nversion: 1.0.0\nadapter_type: ecommerce_product\n",
        )
        m = load_skill_manifest(tmp_path)
        assert m.name == "ecommerce-fashion"
        assert m.version == "1.0.0"

    def test_loads_manifest_with_all_fields(self, tmp_path):
        from server.content.skill_manifest import load_skill_manifest

        yaml_content = (
            "name: test-skill\n"
            "version: 2.0.0\n"
            "adapter_type: script_direct\n"
            "style_ref: style.json\n"
            "voice: vi-VN-HoaiMyNeural\n"
            "camera_lock: false\n"
            "safety_level: strict\n"
            "options:\n"
            "  default_aspect_ratio: '16:9'\n"
        )
        self._write_manifest(tmp_path, yaml_content)
        m = load_skill_manifest(tmp_path)
        assert m.style_ref == "style.json"
        assert m.camera_lock is False
        assert m.safety_level == "strict"
        assert m.options["default_aspect_ratio"] == "16:9"

    def test_missing_manifest_raises_file_not_found(self, tmp_path):
        from server.content.skill_manifest import load_skill_manifest

        with pytest.raises(FileNotFoundError) as exc_info:
            load_skill_manifest(tmp_path)
        assert "manifest.yaml" in str(exc_info.value)

    def test_invalid_yaml_raises_value_error(self, tmp_path):
        from server.content.skill_manifest import load_skill_manifest

        (tmp_path / "manifest.yaml").write_text("{{invalid: yaml: :", encoding="utf-8")
        with pytest.raises(ValueError):
            load_skill_manifest(tmp_path)

    def test_non_mapping_yaml_raises_value_error(self, tmp_path):
        from server.content.skill_manifest import load_skill_manifest

        (tmp_path / "manifest.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError) as exc_info:
            load_skill_manifest(tmp_path)
        assert "mapping" in str(exc_info.value)

    def test_manifest_with_extra_keys_loads_ok(self, tmp_path):
        """Extra keys like 'extends' or 'description' must not cause errors."""
        from server.content.skill_manifest import load_skill_manifest

        self._write_manifest(
            tmp_path,
            "name: x\nversion: 1.0.0\nadapter_type: y\nextends: _base\ndescription: test\n",
        )
        m = load_skill_manifest(tmp_path)
        assert m.name == "x"

    def test_error_message_includes_path(self, tmp_path):
        from server.content.skill_manifest import load_skill_manifest

        with pytest.raises(FileNotFoundError) as exc_info:
            load_skill_manifest(tmp_path)
        assert str(tmp_path) in str(exc_info.value)
