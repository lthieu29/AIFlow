"""Skills API routes.

Endpoints:
    GET /api/skills — list all available skills (data-only packs in skills/)

The UI uses this to populate the skill picker dynamically instead of
hard-coding a single skill.

Task: content-expansion follow-up (UI wiring)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel

from server.config import Settings, load_settings

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ─── Dependency ───────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    return load_settings()


# ─── Response model ───────────────────────────────────────────────────────────


class SkillInfo(BaseModel):
    """Public metadata for one skill."""

    id: str
    name: str
    adapter_type: str
    supported_adapters: list[str] = []
    description: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _skills_dir() -> Path:
    """Locate the repository-level ``skills/`` directory.

    ``server/api/routes/skills.py`` → parents[3] == ``app/``.
    """
    return Path(__file__).resolve().parents[3] / "skills"


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("", response_model=list[SkillInfo])
def list_skills(settings: Settings = Depends(get_settings)) -> list[SkillInfo]:
    """List all available skills, excluding the shared ``_base`` pack.

    Reads each skill's ``manifest.yaml`` for metadata. Skills that fail to
    load are skipped (logged) so one bad pack does not break the picker.

    Returns:
        Sorted list of :class:`SkillInfo` (by ``id``).
    """
    from server.content.skill_loader import SkillLoader

    skills_dir = _skills_dir()
    loader = SkillLoader(skills_dir)

    result: list[SkillInfo] = []
    for skill_id in loader.list_skills():
        try:
            loaded = loader.load(skill_id)
            manifest = loaded.manifest
            supported = list(
                getattr(manifest, "supported_adapters", None)
                or getattr(manifest, "options", {}).get("supported_adapters", [])
                or [manifest.adapter_type]
            )
            description = (
                getattr(manifest, "description", None)
                or getattr(manifest, "options", {}).get("description")
            )
            result.append(
                SkillInfo(
                    id=skill_id,
                    name=getattr(manifest, "name", skill_id),
                    adapter_type=manifest.adapter_type,
                    supported_adapters=supported,
                    description=description,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[skills] skipping %r — failed to load: %s", skill_id, exc)

    logger.info("[skills] returning %d skill(s)", len(result))
    return sorted(result, key=lambda s: s.id)
