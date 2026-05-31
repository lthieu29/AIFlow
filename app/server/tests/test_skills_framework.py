"""Unit tests for Task 4.0.3 — Skills framework.

Covers:
- validate_style_json: required keys, type checks, optional keys, edge cases
- load_style_json: happy path, missing file, invalid JSON, validation errors
- SkillLoader.load: happy path, _base inheritance, missing skill, caching
- SkillLoader.list_skills: excludes _base, sorted, missing dir
- SkillLoader.validate_skill: valid skill, missing manifest, bad style
- apply_skill_to_scene: prefix prepended, empty prefix, original unchanged
- LoadedSkill dataclass fields
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — build minimal skill directories in tmp_path
# ─────────────────────────────────────────────────────────────────────────────


def _write_manifest(skill_dir: Path, content: str) -> None:
    (skill_dir / "manifest.yaml").write_text(content, encoding="utf-8")


def _write_style(skill_dir: Path, data: dict) -> None:
    (skill_dir / "style.json").write_text(json.dumps(data), encoding="utf-8")


def _write_prefix(skill_dir: Path, text: str) -> None:
    (skill_dir / "prefix.md").write_text(text, encoding="utf-8")


def _make_base_skill(skills_dir: Path) -> Path:
    """Create a minimal _base skill directory."""
    base_dir = skills_dir / "_base"
    base_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        base_dir,
        "name: _base\nversion: 1.0.0\nadapter_type: ''\nstyle_ref: style.json\n",
    )
    _write_style(
        base_dir,
        {
            "art_style": "photorealistic",
            "lighting": "natural even lighting",
            "color_palette": "neutral",
        },
    )
    _write_prefix(base_dir, "Base camera lock rules. Base safety rules.")
    return base_dir


def _make_fashion_skill(skills_dir: Path) -> Path:
    """Create a minimal ecommerce-fashion skill directory."""
    skill_dir = skills_dir / "ecommerce-fashion"
    skill_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(
        skill_dir,
        (
            "name: ecommerce-fashion\n"
            "version: 1.0.0\n"
            "adapter_type: ecommerce_product\n"
            "extends: _base\n"
            "style_ref: style.json\n"
            "voice: vi-VN-HoaiMyNeural\n"
        ),
    )
    _write_style(
        skill_dir,
        {
            "art_style": "editorial fashion photography",
            "lighting": "soft even key light",
            "color_palette": "muted earth tones",
        },
    )
    _write_prefix(skill_dir, "Fashion skill prefix text.")
    return skill_dir


# ═════════════════════════════════════════════════════════════════════════════
# validate_style_json
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateStyleJson:
    def _valid(self) -> dict:
        return {
            "art_style": "editorial fashion photography",
            "lighting": "soft even key light",
            "color_palette": "muted earth tones",
        }

    def test_valid_minimal(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json(self._valid())
        assert errors == []

    def test_valid_with_all_optional_keys(self):
        from server.content.style_validator import validate_style_json

        style = {
            **self._valid(),
            "camera_rules": "static frame",
            "negative_prompts": ["blurry", "low quality"],
            "aspect_ratio": "9:16",
            "lens": "85mm",
            "post": "film grain",
        }
        errors = validate_style_json(style)
        assert errors == []

    def test_color_palette_as_list(self):
        from server.content.style_validator import validate_style_json

        style = {**self._valid(), "color_palette": ["cream", "earth tones"]}
        errors = validate_style_json(style)
        assert errors == []

    def test_missing_art_style(self):
        from server.content.style_validator import validate_style_json

        style = {k: v for k, v in self._valid().items() if k != "art_style"}
        errors = validate_style_json(style)
        assert any("art_style" in e for e in errors)

    def test_missing_lighting(self):
        from server.content.style_validator import validate_style_json

        style = {k: v for k, v in self._valid().items() if k != "lighting"}
        errors = validate_style_json(style)
        assert any("lighting" in e for e in errors)

    def test_missing_color_palette(self):
        from server.content.style_validator import validate_style_json

        style = {k: v for k, v in self._valid().items() if k != "color_palette"}
        errors = validate_style_json(style)
        assert any("color_palette" in e for e in errors)

    def test_art_style_wrong_type(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "art_style": 42})
        assert any("art_style" in e for e in errors)

    def test_lighting_wrong_type(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "lighting": ["a", "b"]})
        assert any("lighting" in e for e in errors)

    def test_color_palette_wrong_type(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "color_palette": 123})
        assert any("color_palette" in e for e in errors)

    def test_color_palette_list_with_non_string_item(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "color_palette": ["ok", 99]})
        assert any("color_palette" in e for e in errors)

    def test_empty_art_style_string(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "art_style": "   "})
        assert any("art_style" in e for e in errors)

    def test_empty_color_palette_list(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "color_palette": []})
        assert any("color_palette" in e for e in errors)

    def test_negative_prompts_wrong_type(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "negative_prompts": "blurry"})
        assert any("negative_prompts" in e for e in errors)

    def test_negative_prompts_list_with_non_string(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "negative_prompts": ["ok", 42]})
        assert any("negative_prompts" in e for e in errors)

    def test_aspect_ratio_wrong_type(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json({**self._valid(), "aspect_ratio": 9.16})
        assert any("aspect_ratio" in e for e in errors)

    def test_non_dict_input(self):
        from server.content.style_validator import validate_style_json

        errors = validate_style_json(["not", "a", "dict"])  # type: ignore[arg-type]
        assert any("object" in e for e in errors)

    def test_extra_keys_tolerated(self):
        from server.content.style_validator import validate_style_json

        style = {**self._valid(), "custom_field": "anything", "lens": "85mm"}
        errors = validate_style_json(style)
        assert errors == []


# ═════════════════════════════════════════════════════════════════════════════
# load_style_json
# ═════════════════════════════════════════════════════════════════════════════


class TestLoadStyleJson:
    def test_loads_valid_file(self, tmp_path):
        from server.content.style_validator import load_style_json

        style_path = tmp_path / "style.json"
        style_path.write_text(
            json.dumps({
                "art_style": "editorial",
                "lighting": "soft",
                "color_palette": "neutral",
            }),
            encoding="utf-8",
        )
        result = load_style_json(style_path)
        assert result["art_style"] == "editorial"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        from server.content.style_validator import load_style_json

        with pytest.raises(FileNotFoundError) as exc_info:
            load_style_json(tmp_path / "nonexistent.json")
        assert "style.json" in str(exc_info.value)

    def test_invalid_json_raises_value_error(self, tmp_path):
        from server.content.style_validator import load_style_json

        style_path = tmp_path / "style.json"
        style_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_style_json(style_path)

    def test_validation_failure_raises_value_error(self, tmp_path):
        from server.content.style_validator import load_style_json

        style_path = tmp_path / "style.json"
        # Missing required keys
        style_path.write_text(json.dumps({"art_style": "ok"}), encoding="utf-8")
        with pytest.raises(ValueError) as exc_info:
            load_style_json(style_path)
        assert "lighting" in str(exc_info.value)

    def test_returns_dict_with_all_fields(self, tmp_path):
        from server.content.style_validator import load_style_json

        data = {
            "art_style": "editorial",
            "lighting": "soft",
            "color_palette": ["cream", "earth"],
            "negative_prompts": ["blurry"],
            "aspect_ratio": "9:16",
        }
        style_path = tmp_path / "style.json"
        style_path.write_text(json.dumps(data), encoding="utf-8")
        result = load_style_json(style_path)
        assert result["color_palette"] == ["cream", "earth"]
        assert result["negative_prompts"] == ["blurry"]


# ═════════════════════════════════════════════════════════════════════════════
# LoadedSkill dataclass
# ═════════════════════════════════════════════════════════════════════════════


class TestLoadedSkill:
    def test_fields_accessible(self, tmp_path):
        from server.content.skill_loader import LoadedSkill
        from server.content.skill_manifest import SkillManifest

        manifest = SkillManifest.model_validate({
            "name": "test",
            "version": "1.0.0",
            "adapter_type": "script_direct",
        })
        skill = LoadedSkill(
            manifest=manifest,
            style={"art_style": "x", "lighting": "y", "color_palette": "z"},
            prefix="Test prefix.",
            skill_dir=tmp_path,
        )
        assert skill.manifest.name == "test"
        assert skill.style["art_style"] == "x"
        assert skill.prefix == "Test prefix."
        assert skill.skill_dir == tmp_path


# ═════════════════════════════════════════════════════════════════════════════
# SkillLoader.load
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillLoaderLoad:
    def test_loads_simple_skill(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        _write_manifest(
            skill_dir,
            "name: my-skill\nversion: 1.0.0\nadapter_type: script_direct\nstyle_ref: style.json\n",
        )
        _write_style(skill_dir, {"art_style": "x", "lighting": "y", "color_palette": "z"})
        _write_prefix(skill_dir, "My skill prefix.")

        loader = SkillLoader(tmp_path)
        skill = loader.load("my-skill")

        assert skill.manifest.name == "my-skill"
        assert skill.style["art_style"] == "x"
        assert skill.prefix == "My skill prefix."
        assert skill.skill_dir == skill_dir

    def test_load_with_base_inheritance_merges_prefix(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)
        _make_fashion_skill(tmp_path)

        loader = SkillLoader(tmp_path)
        skill = loader.load("ecommerce-fashion")

        # Prefix should contain both _base and skill-specific text
        assert "Base camera lock rules" in skill.prefix
        assert "Fashion skill prefix text" in skill.prefix

    def test_load_base_prefix_comes_first(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)
        _make_fashion_skill(tmp_path)

        loader = SkillLoader(tmp_path)
        skill = loader.load("ecommerce-fashion")

        base_pos = skill.prefix.index("Base camera lock rules")
        fashion_pos = skill.prefix.index("Fashion skill prefix text")
        assert base_pos < fashion_pos

    def test_load_without_extends_uses_only_skill_prefix(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)

        skill_dir = tmp_path / "standalone"
        skill_dir.mkdir()
        _write_manifest(
            skill_dir,
            "name: standalone\nversion: 1.0.0\nadapter_type: script_direct\n",
        )
        _write_prefix(skill_dir, "Standalone prefix only.")

        loader = SkillLoader(tmp_path)
        skill = loader.load("standalone")

        assert "Standalone prefix only." in skill.prefix
        assert "Base camera lock rules" not in skill.prefix

    def test_load_missing_skill_raises_file_not_found(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load("nonexistent-skill")

    def test_load_caches_result(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)
        _make_fashion_skill(tmp_path)

        loader = SkillLoader(tmp_path)
        skill1 = loader.load("ecommerce-fashion")
        skill2 = loader.load("ecommerce-fashion")

        assert skill1 is skill2  # Same object from cache

    def test_load_skill_without_prefix_md(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        skill_dir = tmp_path / "no-prefix"
        skill_dir.mkdir()
        _write_manifest(
            skill_dir,
            "name: no-prefix\nversion: 1.0.0\nadapter_type: script_direct\n",
        )
        # No prefix.md

        loader = SkillLoader(tmp_path)
        skill = loader.load("no-prefix")
        assert skill.prefix == ""

    def test_load_skill_without_style_falls_back_to_base(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)

        skill_dir = tmp_path / "no-style"
        skill_dir.mkdir()
        _write_manifest(
            skill_dir,
            "name: no-style\nversion: 1.0.0\nadapter_type: script_direct\nextends: _base\n",
        )
        # No style.json

        loader = SkillLoader(tmp_path)
        skill = loader.load("no-style")
        # Should fall back to _base style
        assert skill.style.get("art_style") == "photorealistic"

    def test_load_skill_voice_from_manifest(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)
        _make_fashion_skill(tmp_path)

        loader = SkillLoader(tmp_path)
        skill = loader.load("ecommerce-fashion")
        assert skill.manifest.voice == "vi-VN-HoaiMyNeural"


# ═════════════════════════════════════════════════════════════════════════════
# SkillLoader.list_skills
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillLoaderListSkills:
    def test_lists_skills_excluding_base(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_base_skill(tmp_path)
        _make_fashion_skill(tmp_path)

        loader = SkillLoader(tmp_path)
        skills = loader.list_skills()

        assert "ecommerce-fashion" in skills
        assert "_base" not in skills

    def test_returns_sorted_list(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        for name in ("zebra-skill", "alpha-skill", "mango-skill"):
            d = tmp_path / name
            d.mkdir()
            _write_manifest(d, f"name: {name}\nversion: 1.0.0\nadapter_type: x\n")

        loader = SkillLoader(tmp_path)
        skills = loader.list_skills()
        assert skills == sorted(skills)

    def test_empty_when_no_skills(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(tmp_path)
        assert loader.list_skills() == []

    def test_excludes_dirs_without_manifest(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        # Directory without manifest.yaml
        (tmp_path / "no-manifest").mkdir()
        # Directory with manifest.yaml
        d = tmp_path / "has-manifest"
        d.mkdir()
        _write_manifest(d, "name: has-manifest\nversion: 1.0.0\nadapter_type: x\n")

        loader = SkillLoader(tmp_path)
        skills = loader.list_skills()
        assert "has-manifest" in skills
        assert "no-manifest" not in skills

    def test_missing_skills_dir_returns_empty(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(tmp_path / "nonexistent")
        assert loader.list_skills() == []


# ═════════════════════════════════════════════════════════════════════════════
# SkillLoader.validate_skill
# ═════════════════════════════════════════════════════════════════════════════


class TestSkillLoaderValidateSkill:
    def test_valid_skill_returns_no_errors(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        _make_fashion_skill(tmp_path)
        loader = SkillLoader(tmp_path)
        errors = loader.validate_skill("ecommerce-fashion")
        assert errors == []

    def test_missing_skill_dir_returns_error(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(tmp_path)
        errors = loader.validate_skill("nonexistent")
        assert any("not found" in e for e in errors)

    def test_missing_manifest_returns_error(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        (tmp_path / "bad-skill").mkdir()
        loader = SkillLoader(tmp_path)
        errors = loader.validate_skill("bad-skill")
        assert any("manifest.yaml" in e for e in errors)

    def test_invalid_style_json_returns_error(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        skill_dir = tmp_path / "bad-style"
        skill_dir.mkdir()
        _write_manifest(
            skill_dir,
            "name: bad-style\nversion: 1.0.0\nadapter_type: x\nstyle_ref: style.json\n",
        )
        # style.json missing required keys
        (skill_dir / "style.json").write_text(
            json.dumps({"art_style": "ok"}), encoding="utf-8"
        )

        loader = SkillLoader(tmp_path)
        errors = loader.validate_skill("bad-style")
        assert len(errors) > 0

    def test_missing_style_ref_file_returns_error(self, tmp_path):
        from server.content.skill_loader import SkillLoader

        skill_dir = tmp_path / "missing-style"
        skill_dir.mkdir()
        _write_manifest(
            skill_dir,
            "name: missing-style\nversion: 1.0.0\nadapter_type: x\nstyle_ref: style.json\n",
        )
        # style.json not created

        loader = SkillLoader(tmp_path)
        errors = loader.validate_skill("missing-style")
        assert any("style_ref" in e or "style.json" in e for e in errors)


# ═════════════════════════════════════════════════════════════════════════════
# apply_skill_to_scene
# ═════════════════════════════════════════════════════════════════════════════


class TestApplySkillToScene:
    def _make_skill(self, prefix: str, tmp_path: Path) -> "LoadedSkill":
        from server.content.skill_loader import LoadedSkill
        from server.content.skill_manifest import SkillManifest

        manifest = SkillManifest.model_validate({
            "name": "test-skill",
            "version": "1.0.0",
            "adapter_type": "script_direct",
        })
        return LoadedSkill(
            manifest=manifest,
            style={"art_style": "x", "lighting": "y", "color_palette": "z"},
            prefix=prefix,
            skill_dir=tmp_path,
        )

    def test_prefix_prepended_to_prompt(self, tmp_path):
        from server.content.base import SceneSpec
        from server.content.skill_loader import apply_skill_to_scene

        skill = self._make_skill("Skill prefix.", tmp_path)
        scene = SceneSpec(order=0, prompt="Original prompt.")
        result = apply_skill_to_scene(scene, skill)

        assert result.prompt.startswith("Skill prefix.")
        assert "Original prompt." in result.prompt

    def test_prefix_and_prompt_separated_by_blank_line(self, tmp_path):
        from server.content.base import SceneSpec
        from server.content.skill_loader import apply_skill_to_scene

        skill = self._make_skill("Prefix.", tmp_path)
        scene = SceneSpec(order=0, prompt="Prompt.")
        result = apply_skill_to_scene(scene, skill)

        assert "Prefix.\n\nPrompt." == result.prompt

    def test_empty_prefix_returns_original_prompt_unchanged(self, tmp_path):
        from server.content.base import SceneSpec
        from server.content.skill_loader import apply_skill_to_scene

        skill = self._make_skill("", tmp_path)
        scene = SceneSpec(order=0, prompt="Original prompt.")
        result = apply_skill_to_scene(scene, skill)

        assert result.prompt == "Original prompt."

    def test_original_scene_not_modified(self, tmp_path):
        from server.content.base import SceneSpec
        from server.content.skill_loader import apply_skill_to_scene

        skill = self._make_skill("Prefix.", tmp_path)
        scene = SceneSpec(order=0, prompt="Original.")
        apply_skill_to_scene(scene, skill)

        assert scene.prompt == "Original."  # Original unchanged

    def test_other_fields_preserved(self, tmp_path):
        from server.content.base import SceneSpec
        from server.content.skill_loader import apply_skill_to_scene

        skill = self._make_skill("Prefix.", tmp_path)
        scene = SceneSpec(
            order=3,
            prompt="Prompt.",
            duration=12.0,
            location_hint="indoor_studio",
            narration="Narration text.",
        )
        result = apply_skill_to_scene(scene, skill)

        assert result.order == 3
        assert result.duration == 12.0
        assert result.location_hint == "indoor_studio"
        assert result.narration == "Narration text."

    def test_returns_new_scene_spec_instance(self, tmp_path):
        from server.content.base import SceneSpec
        from server.content.skill_loader import apply_skill_to_scene

        skill = self._make_skill("Prefix.", tmp_path)
        scene = SceneSpec(order=0, prompt="Prompt.")
        result = apply_skill_to_scene(scene, skill)

        assert result is not scene


# ═════════════════════════════════════════════════════════════════════════════
# Integration — real skills directory
# ═════════════════════════════════════════════════════════════════════════════


class TestRealSkillsDirectory:
    """Integration tests against the actual skills/ directory in the repo."""

    @pytest.fixture
    def skills_dir(self) -> Path:
        # Navigate from this test file up to the app root, then into skills/
        return Path(__file__).resolve().parents[2] / "skills"

    def test_base_skill_manifest_exists(self, skills_dir):
        assert (skills_dir / "_base" / "manifest.yaml").exists()

    def test_base_skill_prefix_exists(self, skills_dir):
        assert (skills_dir / "_base" / "prefix.md").exists()

    def test_base_skill_style_exists(self, skills_dir):
        assert (skills_dir / "_base" / "style.json").exists()

    def test_base_style_is_valid(self, skills_dir):
        from server.content.style_validator import load_style_json

        style = load_style_json(skills_dir / "_base" / "style.json")
        assert "art_style" in style

    def test_ecommerce_fashion_manifest_exists(self, skills_dir):
        assert (skills_dir / "ecommerce-fashion" / "manifest.yaml").exists()

    def test_ecommerce_fashion_style_is_valid(self, skills_dir):
        from server.content.style_validator import load_style_json

        style = load_style_json(skills_dir / "ecommerce-fashion" / "style.json")
        # ``art_style`` is allowed to grow with extra Veo 8-element detail
        # (e.g. "editorial fashion photography, magazine-grade photoreal, ...").
        # Just enforce the canonical phrase appears at the head.
        assert "editorial fashion photography" in style["art_style"]

    def test_skill_loader_loads_ecommerce_fashion(self, skills_dir):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(skills_dir)
        skill = loader.load("ecommerce-fashion")

        assert skill.manifest.name == "ecommerce-fashion"
        assert skill.manifest.voice == "vi-VN-HoaiMyNeural"
        # _base prefix.md contains camera lock and safety rules
        assert "Camera lock" in skill.prefix or "camera" in skill.prefix.lower()
        assert "fashion" in skill.prefix.lower() or "editorial" in skill.prefix.lower()

    def test_skill_loader_lists_ecommerce_fashion(self, skills_dir):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(skills_dir)
        skills = loader.list_skills()

        assert "ecommerce-fashion" in skills
        assert "_base" not in skills

    def test_skill_loader_validates_ecommerce_fashion(self, skills_dir):
        from server.content.skill_loader import SkillLoader

        loader = SkillLoader(skills_dir)
        errors = loader.validate_skill("ecommerce-fashion")
        assert errors == []

    def test_content_package_exports_skill_loader(self):
        from server.content import SkillLoader, LoadedSkill, apply_skill_to_scene

        assert SkillLoader is not None
        assert LoadedSkill is not None
        assert apply_skill_to_scene is not None

    def test_content_package_exports_style_validator(self):
        from server.content import validate_style_json, load_style_json

        assert validate_style_json is not None
        assert load_style_json is not None
