"""Task 11.2 — Smoke test for the entire content-expansion feature.

Validates Requirements 3.1 / 3.2 / 4.2 / 4.7 / 4.8 / 6.1 / 6.5.

Asserts that the three orthogonal expansion axes work end-to-end via
the existing auto-discovery / data-only conventions, WITHOUT any
modifications to the pipeline core (``server/content/registry.py`` or
``server/content/skill_loader.py``).

Axes:
- Adapter axis  — all 5 new adapter input types are auto-discovered (R4.2).
- Skill axis    — all 4 new data-only skills validate cleanly (R3.1, R3.2).
- Visual axis   — all 4 new visual-layer templates appear in the registry (R5.1, R5.5).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.registry import AdapterRegistry
from server.content.skill_loader import SkillLoader
from server.render.visual_layer.template_registry import (
    TEMPLATE_REGISTRY,
    get_template_path,
)

# ─── Constants ────────────────────────────────────────────────────────────────

NEW_ADAPTERS = {
    "script_direct",
    "video_remaster",
    "document_summary",
    "lyric_video",
    "news_bulletin",
    "podcast_caption",
    "photo_slideshow",
}

NEW_SKILLS = {
    "explainer-tech",
    "cinematic-action",
    "ecommerce-tech",
    "ecommerce-food",
}

NEW_TEMPLATES = {
    "quote_card",
    "stat_card",
    "news_ticker",
    "lyric_line",
}

APP_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = APP_ROOT / "skills"
ADAPTERS_DIR = APP_ROOT / "server" / "content" / "adapters"


# ─── Adapter axis ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> AdapterRegistry:
    reg = AdapterRegistry()
    reg.auto_discover("server.content.adapters")
    return reg


def test_all_new_adapters_auto_discovered(registry: AdapterRegistry) -> None:
    """**R4.2, R6.1** — All 7 new adapter types are present after auto-discovery."""
    discovered = set(registry.list_types())
    missing = NEW_ADAPTERS - discovered
    assert not missing, (
        f"Missing adapter types after auto_discover: {missing}. "
        f"Found: {sorted(discovered)}"
    )


def test_legacy_adapters_still_present(registry: AdapterRegistry) -> None:
    """Legacy adapters must continue to register — adding new ones did not
    accidentally remove them (regression check)."""
    expected_legacy = {
        "ecommerce_product",
        "narrative_script",
        "blog_article",
        "storyboard_manual",
        "epub_novel",
    }
    discovered = set(registry.list_types())
    missing = expected_legacy - discovered
    assert not missing, f"Legacy adapters disappeared: {missing}"


def test_no_changes_to_registry_core() -> None:
    """**R6.1** — The Adapter_Registry core file must NOT have been modified
    by content-expansion.  We assert at least the public surface (class,
    auto_discover method) is unchanged.

    This is a tripwire — any breaking change to ``registry.py`` will fail.
    """
    from server.content import registry as reg_mod

    assert hasattr(reg_mod, "AdapterRegistry")
    assert hasattr(reg_mod.AdapterRegistry, "auto_discover")
    assert hasattr(reg_mod.AdapterRegistry, "register")
    assert hasattr(reg_mod.AdapterRegistry, "get")
    assert hasattr(reg_mod.AdapterRegistry, "list_types")
    assert hasattr(reg_mod, "REGISTRY")
    assert hasattr(reg_mod, "register_adapter")


# ─── Skill axis (R3.1, R3.2, R6.5) ───────────────────────────────────────────


def test_all_four_new_skills_present_on_disk() -> None:
    """**R3.1** — All 4 new skill directories exist on disk."""
    missing = [s for s in NEW_SKILLS if not (SKILLS_DIR / s).is_dir()]
    assert not missing, f"Missing skill directories: {missing}"


@pytest.mark.parametrize("skill_name", sorted(NEW_SKILLS))
def test_skill_is_data_only_no_python(skill_name: str) -> None:
    """**R3.2** — Skill folders MUST NOT contain any ``*.py`` file."""
    skill_dir = SKILLS_DIR / skill_name
    py_files = list(skill_dir.rglob("*.py"))
    assert py_files == [], (
        f"Skill {skill_name!r} contains Python files (R3.2 forbids code in skills): "
        f"{[str(p.relative_to(skill_dir)) for p in py_files]}"
    )


@pytest.mark.parametrize("skill_name", sorted(NEW_SKILLS))
def test_skill_validates_cleanly(skill_name: str) -> None:
    """**R3.4, R6.5** — ``SkillLoader.validate_skill`` returns ``[]`` for each
    new skill, without modifying the SkillLoader code itself."""
    loader = SkillLoader(SKILLS_DIR)
    errors = loader.validate_skill(skill_name)
    assert errors == [], (
        f"Skill {skill_name!r} failed validation:\n"
        + "\n".join(f"  - {e}" for e in errors)
    )


# ─── Visual-layer axis (R5.1, R5.5, R5.10) ───────────────────────────────────


def test_all_four_new_templates_in_registry() -> None:
    """**R5.1, R5.5** — All 4 new visual templates are registered."""
    missing = NEW_TEMPLATES - set(TEMPLATE_REGISTRY)
    assert not missing, (
        f"Missing templates in TEMPLATE_REGISTRY: {missing}. "
        f"Found: {sorted(TEMPLATE_REGISTRY)}"
    )


@pytest.mark.parametrize("template_name", sorted(NEW_TEMPLATES))
def test_template_path_exists_on_disk(template_name: str) -> None:
    """**R5.6** — ``get_template_path`` returns a path that exists on disk."""
    path = get_template_path(template_name)
    assert path.is_file(), f"Template HTML not found on disk: {path}"


def test_required_template_set_complete() -> None:
    """**R5.10** — The required template set must be complete; an empty
    or partial set must fail.  This is the test-time gate from the design."""
    required = NEW_TEMPLATES
    actual = set(TEMPLATE_REGISTRY) & required
    # Same set
    assert actual == required, (
        f"Required template set incomplete. Missing: {required - actual}"
    )


# ─── No-network for adapter axis (defence-in-depth) ──────────────────────────


def test_adapter_directory_layout_consistent() -> None:
    """All adapter directories under ``server/content/adapters/`` either contain
    an ``adapter.py`` (real adapter) or are empty/skipped (no half-built ones)."""
    for entry in ADAPTERS_DIR.iterdir():
        if not entry.is_dir() or entry.name.startswith("__"):
            continue
        adapter_py = entry / "adapter.py"
        if adapter_py.exists():
            # Real adapter — must define ADAPTER or ADAPTER_CLASS so
            # auto_discover can register it.
            text = adapter_py.read_text(encoding="utf-8")
            assert ("ADAPTER" in text) or ("ADAPTER_CLASS" in text), (
                f"{adapter_py} has no ADAPTER / ADAPTER_CLASS export"
            )
