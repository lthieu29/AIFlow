"""Task 7.5 — Unit tests for the 4 new data-only skills.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.9, 3.10, 3.11, 3.12, 3.13**

Parametrised over the 4 new skills:

- ``explainer-tech``      → adapter_type ``narrative_script``
- ``cinematic-action``    → adapter_type ``narrative_script``
- ``ecommerce-tech``      → adapter_type ``ecommerce_product``
- ``ecommerce-food``      → adapter_type ``ecommerce_product``

Checks (per skill):
- ``SkillLoader.validate_skill`` returns ``[]`` (R3.4).
- ``SkillLoader.load`` returns a ``LoadedSkill`` with a valid ``style``
  (R3.7) — ``validate_style_json`` must accept it.
- All 7 layout files exist (R3.3).
- No Python files anywhere in the skill directory (R3.2).
- ``prefix.md`` has at least 20 non-whitespace words (R3.10).
- ``style.json`` carries the 6 keys used by the original skills (R3.11).
- ``character.md``/``scene.md``/``motion.md`` carry substantive content (R3.12).
- ``voice.yaml`` declares ``primary_backend`` + ``primary_voice`` (R3.13).
- ``ecommerce-tech`` and ``ecommerce-food`` declare ``adapter_type:
  ecommerce_product`` (R3.9).
- ``extends: _base`` skills get the ``_base`` prefix prepended (R3.6).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.skill_loader import SkillLoader
from server.content.style_validator import validate_style_json


SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

NEW_SKILLS = [
    "explainer-tech",
    "cinematic-action",
    "ecommerce-tech",
    "ecommerce-food",
]

ECOMMERCE_SKILLS = {"ecommerce-tech", "ecommerce-food"}

REQUIRED_FILES = (
    "manifest.yaml",
    "style.json",
    "prefix.md",
    "character.md",
    "scene.md",
    "motion.md",
    "voice.yaml",
)

REQUIRED_STYLE_KEYS = (
    "art_style",
    "lighting",
    "color_palette",
    "camera_rules",
    "negative_prompts",
    "aspect_ratio",
)


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


# ─── R3.4 — validate_skill returns [] ────────────────────────────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_validate_skill_returns_empty(skill_name: str) -> None:
    """**R3.4** — ``SkillLoader.validate_skill`` returns ``[]`` for each new skill."""
    loader = SkillLoader(SKILLS_DIR)
    errors = loader.validate_skill(skill_name)
    assert errors == [], (
        f"Skill {skill_name!r} validation errors:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


# ─── R3.7 — load() returns a LoadedSkill with valid style ───────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_load_returns_valid_loaded_skill(skill_name: str) -> None:
    """**R3.7** — ``load()`` returns a LoadedSkill whose ``style`` passes
    ``validate_style_json``."""
    loader = SkillLoader(SKILLS_DIR)
    skill = loader.load(skill_name)

    assert skill.manifest.name == skill_name
    assert skill.skill_dir == SKILLS_DIR / skill_name

    style_errors = validate_style_json(skill.style)
    assert style_errors == [], (
        f"{skill_name!r} style.json failed validation: {style_errors}"
    )


# ─── R3.3 — 7-file layout ────────────────────────────────────────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_seven_file_layout(skill_name: str) -> None:
    """**R3.3** — Each skill has all 7 required files."""
    skill_dir = SKILLS_DIR / skill_name
    missing = [f for f in REQUIRED_FILES if not (skill_dir / f).is_file()]
    assert not missing, (
        f"Skill {skill_name!r} is missing required files: {missing}"
    )


# ─── R3.2 — no Python files in skill folder ──────────────────────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_no_python_files(skill_name: str) -> None:
    """**R3.2** — A skill directory MUST NOT contain any ``*.py`` files."""
    skill_dir = SKILLS_DIR / skill_name
    py_files = list(skill_dir.rglob("*.py"))
    assert py_files == [], (
        f"Skill {skill_name!r} contains Python files: "
        f"{[str(p.relative_to(skill_dir)) for p in py_files]}"
    )


# ─── R3.10 — prefix.md ≥ 20 words ────────────────────────────────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_prefix_has_at_least_20_words(skill_name: str) -> None:
    """**R3.10** — ``prefix.md`` has at least 20 non-whitespace words."""
    text = (SKILLS_DIR / skill_name / "prefix.md").read_text(encoding="utf-8")
    n = _word_count(text)
    assert n >= 20, f"{skill_name!r} prefix.md has only {n} words, need ≥ 20"


# ─── R3.11 — style.json carries the 6 expected keys ─────────────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_style_json_has_all_six_keys(skill_name: str) -> None:
    """**R3.11** — ``style.json`` contains the 6 keys used by the original
    skills: ``art_style``, ``lighting``, ``color_palette``, ``camera_rules``,
    ``negative_prompts``, ``aspect_ratio``."""
    style = json.loads(
        (SKILLS_DIR / skill_name / "style.json").read_text(encoding="utf-8")
    )
    missing = [k for k in REQUIRED_STYLE_KEYS if k not in style]
    assert not missing, (
        f"{skill_name!r} style.json is missing required keys: {missing}"
    )


# ─── R3.12 — character/scene/motion non-empty + substantive ─────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
@pytest.mark.parametrize("filename", ["character.md", "scene.md", "motion.md"])
def test_template_files_have_substantive_content(
    skill_name: str, filename: str
) -> None:
    """**R3.12** — character/scene/motion files are non-empty and contain
    substantive template content (more than just a single-line title)."""
    text = (SKILLS_DIR / skill_name / filename).read_text(encoding="utf-8")
    assert text.strip(), f"{skill_name}/{filename} is empty"
    # "Substantive" — at least 30 words AND more than one non-empty line
    non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(non_empty_lines) > 1, (
        f"{skill_name}/{filename} only has {len(non_empty_lines)} line(s)"
    )
    assert _word_count(text) >= 30, (
        f"{skill_name}/{filename} only has {_word_count(text)} words"
    )


# ─── R3.13 — voice.yaml declares primary_backend + primary_voice ────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_voice_yaml_declares_primary_backend_and_voice(skill_name: str) -> None:
    """**R3.13** — ``voice.yaml`` carries a usable voice profile with
    ``primary_backend`` and ``primary_voice`` fields."""
    voice = yaml.safe_load(
        (SKILLS_DIR / skill_name / "voice.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(voice, dict), (
        f"{skill_name}/voice.yaml must be a YAML mapping"
    )
    profile = voice.get("voice_profile", voice)  # accept top-level or nested
    assert profile.get("primary_backend"), (
        f"{skill_name}/voice.yaml is missing 'primary_backend'"
    )
    assert profile.get("primary_voice"), (
        f"{skill_name}/voice.yaml is missing 'primary_voice'"
    )


# ─── R3.9 — ecommerce-* skills declare adapter_type: ecommerce_product ──────


@pytest.mark.parametrize("skill_name", sorted(ECOMMERCE_SKILLS))
def test_ecommerce_skills_target_ecommerce_product(skill_name: str) -> None:
    """**R3.9** — ``ecommerce-tech`` and ``ecommerce-food`` declare
    ``adapter_type: ecommerce_product`` to be compatible with the existing
    e-commerce adapter."""
    manifest = yaml.safe_load(
        (SKILLS_DIR / skill_name / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest.get("adapter_type") == "ecommerce_product", (
        f"{skill_name}/manifest.yaml: expected adapter_type=ecommerce_product, "
        f"got {manifest.get('adapter_type')!r}"
    )


# ─── R3.6 — extends: _base merges the _base prefix ──────────────────────────


@pytest.mark.parametrize("skill_name", NEW_SKILLS)
def test_extends_base_prepends_base_prefix(skill_name: str) -> None:
    """**R3.6** — When a skill declares ``extends: _base``, the resolved
    ``LoadedSkill.prefix`` includes the ``_base/prefix.md`` content."""
    manifest = yaml.safe_load(
        (SKILLS_DIR / skill_name / "manifest.yaml").read_text(encoding="utf-8")
    )
    extends = manifest.get("extends")
    if extends != "_base":
        pytest.skip(f"{skill_name!r} does not declare extends: _base")

    loaded = SkillLoader(SKILLS_DIR).load(skill_name)
    base_prefix = (SKILLS_DIR / "_base" / "prefix.md").read_text(encoding="utf-8").strip()
    own_prefix = (SKILLS_DIR / skill_name / "prefix.md").read_text(encoding="utf-8").strip()

    # Take a stable substring of each to assert presence
    assert base_prefix[:30] in loaded.prefix, (
        f"{skill_name}: _base prefix substring not found in merged prefix"
    )
    assert own_prefix[:30] in loaded.prefix, (
        f"{skill_name}: own prefix substring not found in merged prefix"
    )
