"""Tasks 1.4 / 14 / 15.2 — Parametrized tests for ALL skills.

**Validates: Requirements 1, 2, 3, 5, 6** from
``app/.kiro/specs/video-variety-expansion/requirements.md``.

For every skill on disk:

- ``SkillLoader.validate_skill`` returns ``[]``.
- ``SkillLoader.load`` returns a ``LoadedSkill`` whose ``style`` passes
  ``validate_style_json``.
- The 7-file layout (Skill_Layout_7_File) is present.
- No ``*.py`` files appear inside the skill directory.
- ``style.json`` carries the 6 keys mandated by R3.11 / R2.5 / R1.4.
- ``style.json.negative_prompts`` has at least 8 entries (R2.6 / R3.13);
  ``_base`` only needs at least 5 (R1.5).
- ``prefix.md`` word count is at least 60 for new skills (R3.10), at least
  40 for legacy refactored skills (R2.3), and at least 60 for ``_base``
  (R1.3).
- The merged ``LoadedSkill.prefix`` carries the three core constraint
  phrases (R5.5) and at least one camera-lexicon keyword (R5.6) and at
  least one Veo 8-element keyword (implicit in the merge).
- Tripwire: the union of skill directories on disk equals
  ``{"_base"} | LEGACY_6_SKILLS | NEW_30_SKILLS`` (R3.1, R3.17, R5.14).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.skill_loader import SkillLoader
from server.content.style_validator import validate_style_json
from server.tests._skills_keywords import (
    ALL_KNOWN_SKILLS,
    ALL_NON_BASE_SKILLS,
    APP_ROOT,
    CAMERA_KEYWORDS,
    LEGACY_6_SKILLS,
    NEW_30_SKILLS,
    SKILLS_DIR,
    VEO_KEYWORDS,
    contains_all_constraints,
    contains_any,
    word_count,
)


# ─── Constants ───────────────────────────────────────────────────────────────


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

# Word-count thresholds per skill class
PREFIX_WORD_COUNT_NEW = 60        # R3.10
PREFIX_WORD_COUNT_LEGACY = 40     # R2.3
PREFIX_WORD_COUNT_BASE = 60       # R1.3

# negative_prompts entry-count thresholds
NEG_PROMPTS_MIN_NON_BASE = 8      # R2.6 / R3.13
NEG_PROMPTS_MIN_BASE = 5          # R1.5

TEMPLATE_FILE_MIN_WORDS = 30      # R2.7 / R3.14


# ─── Skill discovery (used by tripwire too) ─────────────────────────────────


def _discovered_skills() -> set[str]:
    return {
        d.name for d in SKILLS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    }


# ─── R1.6 / R2.2 / R3.4 — validate_skill returns [] for every skill ─────────


@pytest.mark.parametrize("skill_name", sorted(ALL_KNOWN_SKILLS))
def test_skill_validates_cleanly(skill_name: str) -> None:
    """**R1.6 / R2.2 / R3.4** — ``SkillLoader.validate_skill`` returns ``[]``."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    errors = SkillLoader(SKILLS_DIR).validate_skill(skill_name)
    assert errors == [], (
        f"Skill {skill_name!r} validation errors:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


# ─── R3.8 / R2.5 / R1.4 — load returns LoadedSkill with valid style ─────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_loads_with_valid_style(skill_name: str) -> None:
    """**R3.8 / R2.5** — ``load`` returns a LoadedSkill with a valid style."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    skill = SkillLoader(SKILLS_DIR).load(skill_name)
    style_errors = validate_style_json(skill.style)
    assert style_errors == [], (
        f"{skill_name!r} style.json failed validation: {style_errors}"
    )


# ─── R3.3 / R2.7 — 7-file layout ────────────────────────────────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_seven_file_layout(skill_name: str) -> None:
    """**R3.3** — Each skill has all 7 required files."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    missing = [f for f in REQUIRED_FILES if not (skill_dir / f).is_file()]
    assert not missing, (
        f"Skill {skill_name!r} is missing required files: {missing}"
    )


# ─── R2.10 / R3.2 / R6 — no Python files in any skill folder ────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_KNOWN_SKILLS))
def test_skill_no_python_files(skill_name: str) -> None:
    """**R2.10 / R3.2 / R6** — A skill directory MUST NOT contain ``*.py`` files."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    py_files = list(skill_dir.rglob("*.py"))
    assert py_files == [], (
        f"Skill {skill_name!r} contains Python files: "
        f"{[str(p.relative_to(skill_dir)) for p in py_files]}"
    )


# ─── R3.10 / R2.3 / R1.3 — prefix word count threshold ─────────────────────


@pytest.mark.parametrize("skill_name", sorted(NEW_30_SKILLS))
def test_new_skill_prefix_word_count_ge_60(skill_name: str) -> None:
    """**R3.10** — New skill prefix.md has at least 60 words."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    text = (SKILLS_DIR / skill_name / "prefix.md").read_text(encoding="utf-8")
    n = word_count(text)
    assert n >= PREFIX_WORD_COUNT_NEW, (
        f"{skill_name!r} prefix.md has only {n} words, need ≥ {PREFIX_WORD_COUNT_NEW}"
    )


@pytest.mark.parametrize("skill_name", sorted(LEGACY_6_SKILLS))
def test_legacy_skill_prefix_word_count_ge_40(skill_name: str) -> None:
    """**R2.3** — Refactored legacy skill prefix.md has at least 40 words."""
    text = (SKILLS_DIR / skill_name / "prefix.md").read_text(encoding="utf-8")
    n = word_count(text)
    assert n >= PREFIX_WORD_COUNT_LEGACY, (
        f"{skill_name!r} prefix.md has only {n} words, need ≥ {PREFIX_WORD_COUNT_LEGACY}"
    )


def test_base_prefix_word_count_ge_60() -> None:
    """**R1.3** — ``_base/prefix.md`` has at least 60 words."""
    text = (SKILLS_DIR / "_base" / "prefix.md").read_text(encoding="utf-8")
    n = word_count(text)
    assert n >= PREFIX_WORD_COUNT_BASE, (
        f"_base/prefix.md has only {n} words, need ≥ {PREFIX_WORD_COUNT_BASE}"
    )


# ─── R2.5 / R3.12 / R1.4 — style.json has all 6 required keys ──────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_KNOWN_SKILLS))
def test_skill_style_has_six_keys(skill_name: str) -> None:
    """**R3.12 / R2.5 / R1.4** — ``style.json`` contains all 6 required keys."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    style = json.loads((skill_dir / "style.json").read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_STYLE_KEYS if k not in style]
    assert not missing, (
        f"{skill_name!r} style.json is missing required keys: {missing}"
    )


# ─── R2.6 / R3.13 / R1.5 — negative_prompts threshold ──────────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_non_base_skill_negative_prompts_min_eight(skill_name: str) -> None:
    """**R2.6 / R3.13** — Non-base skill ``negative_prompts`` has ≥ 8 entries."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    style = json.loads((skill_dir / "style.json").read_text(encoding="utf-8"))
    np_ = style.get("negative_prompts", [])
    assert isinstance(np_, list), f"{skill_name!r} negative_prompts must be a list"
    assert len(np_) >= NEG_PROMPTS_MIN_NON_BASE, (
        f"{skill_name!r} negative_prompts has only {len(np_)} entries, "
        f"need ≥ {NEG_PROMPTS_MIN_NON_BASE}"
    )


def test_base_negative_prompts_min_five() -> None:
    """**R1.5** — ``_base/style.json.negative_prompts`` has ≥ 5 entries with the 3 core constraints."""
    style = json.loads((SKILLS_DIR / "_base" / "style.json").read_text(encoding="utf-8"))
    np_ = style.get("negative_prompts", [])
    assert isinstance(np_, list)
    assert len(np_) >= NEG_PROMPTS_MIN_BASE
    joined = " | ".join(np_).lower()
    for required in ("watermark", "logo"):
        assert required in joined, f"_base negative_prompts missing {required!r}"
    assert ("subtitle" in joined) or ("text overlay" in joined), (
        "_base negative_prompts missing subtitle/text overlay"
    )


# ─── R5.5 / R5.6 — merged prefix carries constraints + camera + Veo keywords ─


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_loaded_prefix_has_constraint_keywords(skill_name: str) -> None:
    """**R5.5** — After merging with ``_base``, the prefix carries the 3 core
    constraint phrases (provided by ``_base``)."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    skill = SkillLoader(SKILLS_DIR).load(skill_name)
    ok, missing = contains_all_constraints(skill.prefix)
    assert ok, (
        f"{skill_name!r} merged prefix missing constraint phrases: {missing}"
    )


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_loaded_prefix_has_camera_keyword(skill_name: str) -> None:
    """**R3.11 / R5.6** — Merged prefix contains at least one camera-lexicon keyword."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    skill = SkillLoader(SKILLS_DIR).load(skill_name)
    found = contains_any(skill.prefix, CAMERA_KEYWORDS)
    assert found is not None, (
        f"{skill_name!r} merged prefix carries no camera-lexicon keyword"
    )


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_loaded_prefix_has_veo_keyword(skill_name: str) -> None:
    """Merged prefix contains at least one Veo 8-element keyword."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    skill = SkillLoader(SKILLS_DIR).load(skill_name)
    found = contains_any(skill.prefix, VEO_KEYWORDS)
    assert found is not None, (
        f"{skill_name!r} merged prefix carries no Veo 8-element keyword"
    )


# ─── R3.16 — manifest.name matches the directory name ──────────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_name_matches_directory(skill_name: str) -> None:
    """**R3.16** — ``manifest.yaml.name`` matches the directory name."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    manifest = yaml.safe_load((skill_dir / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest.get("name") == skill_name, (
        f"manifest.name={manifest.get('name')!r} does not match directory name "
        f"{skill_name!r}"
    )


# ─── R2.7 / R3.14 — character/scene/motion files have substantive content ──


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
@pytest.mark.parametrize("filename", ["character.md", "scene.md", "motion.md"])
def test_skill_template_files_substantive(
    skill_name: str, filename: str
) -> None:
    """**R2.7 / R3.14** — Template files non-empty + ≥ 30 words + > 1 line."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    text = (skill_dir / filename).read_text(encoding="utf-8")
    assert text.strip(), f"{skill_name}/{filename} is empty"
    non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(non_empty_lines) > 1, (
        f"{skill_name}/{filename} only has {len(non_empty_lines)} line(s)"
    )
    assert word_count(text) >= TEMPLATE_FILE_MIN_WORDS, (
        f"{skill_name}/{filename} only has {word_count(text)} words"
    )


# ─── R2.8 / R3.15 — voice.yaml declares primary_backend + primary_voice ────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_skill_voice_yaml_complete(skill_name: str) -> None:
    """**R2.8 / R3.15** — ``voice.yaml`` carries primary_backend + primary_voice."""
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    voice = yaml.safe_load((skill_dir / "voice.yaml").read_text(encoding="utf-8"))
    assert isinstance(voice, dict)
    profile = voice.get("voice_profile", voice)
    assert profile.get("primary_backend"), (
        f"{skill_name}/voice.yaml missing 'primary_backend'"
    )
    assert profile.get("primary_voice"), (
        f"{skill_name}/voice.yaml missing 'primary_voice'"
    )


# ─── R3.1 / R3.17 / R5.14 — required-set tripwires ─────────────────────────


def test_required_30_skills_complete() -> None:
    """**R3.1** — All 30 new skills exist on disk."""
    discovered = _discovered_skills()
    missing = NEW_30_SKILLS - discovered
    assert not missing, (
        f"Missing required new skills (R3.1): {sorted(missing)}\n"
        f"Discovered: {sorted(discovered)}"
    )


def test_no_extra_skills_outside_known_sets() -> None:
    """**R3.17 / R5.14** — Tripwire: no surprise skill directories.

    Every skill on disk must be either ``_base``, in ``LEGACY_6_SKILLS``, or
    in ``NEW_30_SKILLS``.  Lights up if someone adds a skill folder without
    updating the spec/tests.
    """
    discovered = _discovered_skills()
    extra = discovered - ALL_KNOWN_SKILLS
    assert not extra, (
        f"Found unknown skill directories: {sorted(extra)}. "
        f"Either add them to NEW_30_SKILLS / LEGACY_6_SKILLS or remove them."
    )
