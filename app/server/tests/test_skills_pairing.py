"""Task 15.1 / 15.3 — Skill ↔ adapter pairing tests + core preservation tripwire.

**Validates: Requirements 4.1 / 4.2 / 4.3 / 4.6 / 4.7 / 6.1–6.7**

For every non-base skill:

- ``manifest.adapter_type`` is registered in :class:`AdapterRegistry`.
- Every entry in ``manifest.supported_adapters`` is registered.
- ``adapter_type`` is contained in ``supported_adapters``.
- ``video_remaster`` is NEVER listed in ``supported_adapters`` (it is a
  passthrough adapter that bypasses Veo3, so style skills do not apply).

A small core-preservation tripwire asserts that ``SkillLoader``'s public
surface is unchanged (no accidental rename / removal of ``load`` /
``validate_skill`` / ``list_skills``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.registry import AdapterRegistry
from server.content.skill_loader import SkillLoader
from server.tests._skills_keywords import (
    ALL_NON_BASE_SKILLS,
    SKILLS_DIR,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> AdapterRegistry:
    """Fresh AdapterRegistry with auto-discovery run once."""
    reg = AdapterRegistry()
    reg.auto_discover("server.content.adapters")
    return reg


def _read_manifest(skill_name: str) -> dict:
    raw = (SKILLS_DIR / skill_name / "manifest.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(raw) or {}


# ─── R4.1 — adapter_type is registered ──────────────────────────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_adapter_type_is_registered(
    registry: AdapterRegistry, skill_name: str
) -> None:
    """**R4.1** — ``manifest.adapter_type`` exists in AdapterRegistry."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    manifest = _read_manifest(skill_name)
    adapter_type = manifest.get("adapter_type")
    assert adapter_type, f"{skill_name}: manifest.adapter_type is empty"
    available = registry.list_types()
    assert adapter_type in available, (
        f"{skill_name}: adapter_type={adapter_type!r} not in registry. "
        f"Available: {available}"
    )


# ─── R4.2 — every entry in supported_adapters is registered ────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_supported_adapters_all_registered(
    registry: AdapterRegistry, skill_name: str
) -> None:
    """**R4.2** — Every entry in ``supported_adapters`` is registered."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    manifest = _read_manifest(skill_name)
    supported = manifest.get("supported_adapters") or []
    assert isinstance(supported, list) and supported, (
        f"{skill_name}: supported_adapters must be a non-empty list"
    )
    available = set(registry.list_types())
    missing = [t for t in supported if t not in available]
    assert not missing, (
        f"{skill_name}: supported_adapters references unknown adapter_type(s): "
        f"{missing}. Available: {sorted(available)}"
    )


# ─── R4.3 — adapter_type ∈ supported_adapters ──────────────────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_adapter_type_is_in_supported_adapters(skill_name: str) -> None:
    """**R4.3** — The skill's primary ``adapter_type`` is also listed in
    its ``supported_adapters``."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    manifest = _read_manifest(skill_name)
    adapter_type = manifest.get("adapter_type")
    supported = manifest.get("supported_adapters") or []
    assert adapter_type in supported, (
        f"{skill_name}: adapter_type={adapter_type!r} not in supported_adapters"
        f"={supported}"
    )


# ─── R4.7 — video_remaster never in supported_adapters ─────────────────────


@pytest.mark.parametrize("skill_name", sorted(ALL_NON_BASE_SKILLS))
def test_video_remaster_not_in_supported_adapters(skill_name: str) -> None:
    """**R4.7** — ``video_remaster`` is a passthrough adapter; it must NOT
    appear in any skill's ``supported_adapters``."""
    if not (SKILLS_DIR / skill_name).is_dir():
        pytest.skip(f"skill {skill_name!r} not yet implemented")
    manifest = _read_manifest(skill_name)
    supported = manifest.get("supported_adapters") or []
    assert "video_remaster" not in supported, (
        f"{skill_name}: 'video_remaster' must not be in supported_adapters "
        f"(it is a passthrough adapter, R4.7)"
    )


# ─── R6 — Skill_Loader public surface preserved ────────────────────────────


def test_no_changes_to_skill_loader_core() -> None:
    """**R6.2** — ``SkillLoader``'s public surface is unchanged.

    Tripwire that lights up if anyone renames or removes
    ``load`` / ``validate_skill`` / ``list_skills``.
    """
    assert hasattr(SkillLoader, "load")
    assert hasattr(SkillLoader, "validate_skill")
    assert hasattr(SkillLoader, "list_skills")
    # And the BASE_SKILL constant is the way to merge the _base prefix.
    assert getattr(SkillLoader, "BASE_SKILL", None) == "_base"


def test_registry_unchanged_after_auto_discover(registry: AdapterRegistry) -> None:
    """**R6.8** — After auto-discovery, the registry contains the expected
    set of adapter types (12 — content-expansion stable surface)."""
    types = set(registry.list_types())
    expected = {
        "blog_article",
        "document_summary",
        "ecommerce_product",
        "epub_novel",
        "lyric_video",
        "narrative_script",
        "news_bulletin",
        "photo_slideshow",
        "podcast_caption",
        "script_direct",
        "storyboard_manual",
        "video_remaster",
    }
    missing = expected - types
    assert not missing, f"Registry missing adapter types: {missing}"
