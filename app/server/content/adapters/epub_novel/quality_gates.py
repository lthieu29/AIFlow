"""EPUB novel adapter — quality gate integration layer.

This module provides the adapter-side interface for the three EPUB quality
checkpoints (EG1, EG2, EG3) and the skill restriction enforcement.

It acts as a thin facade over ``server.pipeline.gates.epub_checkpoints``,
keeping the adapter package self-contained and testable without importing
the full pipeline package.

Gates
-----
EG1 — Character Gate
    Triggered after character extraction.  The pipeline pauses so the user
    can review the extracted character list before scene generation begins.

EG2 — Plot Gate
    Triggered after chapter-to-scene mapping.  The user reviews the scene
    breakdown and can request re-chunking before Veo3 calls start.

EG3 — Style Gate
    Triggered after skill application.  The user reviews the merged style
    prefix and style.json before they are injected into every Veo3 prompt.

Skill restriction
-----------------
EPUB novel processing is restricted to the ``kdrama-romance`` skill.
Call :func:`check_epub_skill` to enforce this before running the adapter.

Usage::

    from server.content.adapters.epub_novel.quality_gates import (
        EPUB_ALLOWED_SKILL,
        EpubSkillRestrictionError,
        check_epub_skill,
        run_character_gate,
        run_plot_gate,
        run_style_gate,
    )

    # Enforce skill restriction
    check_epub_skill(input.skill_name)

    # After character extraction
    result = await run_character_gate(characters, project_id=project_id)

    # After scene mapping
    result = await run_plot_gate(scene_list, project_id=project_id)

    # After skill application
    result = await run_style_gate(style_info, project_id=project_id)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.content.base import SceneList
    from server.content.character_dedup import CharacterRef

from server.pipeline.gates.epub_checkpoints import (
    EPUB_ALLOWED_SKILL,
    EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
    EPUB_GATE_NAMES,
    EpubSkillRestrictionError,
    validate_epub_skill,
)

logger = logging.getLogger(__name__)

# Re-export for convenience so callers only need to import from this module.
__all__ = [
    "EPUB_ALLOWED_SKILL",
    "EPUB_GATE_DEFAULT_TIMEOUT_HOURS",
    "EPUB_GATE_NAMES",
    "EpubSkillRestrictionError",
    "EpubGateResult",
    "check_epub_skill",
    "run_character_gate",
    "run_plot_gate",
    "run_style_gate",
]


# ─── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class EpubGateResult:
    """Result of an EPUB quality checkpoint evaluation.

    Attributes:
        gate_id:  Gate identifier: ``"EG1"``, ``"EG2"``, or ``"EG3"``.
        status:   Outcome: ``"checking"`` (gate created, awaiting user) |
                  ``"passed"`` | ``"overridden"`` | ``"skipped"``.
        message:  Human-readable description.
        payload:  The artifact that was submitted for review (characters,
                  scene list, or style info).
    """

    gate_id: str
    status: str  # checking | passed | overridden | skipped
    message: str = field(default="")
    payload: Any = field(default=None)


# ─── Skill restriction ────────────────────────────────────────────────────────


def check_epub_skill(skill_name: str | None) -> None:
    """Enforce the EPUB novel skill restriction.

    EPUB novel processing is restricted to the ``kdrama-romance`` skill.
    Passing ``None`` (no skill specified) is also rejected.

    This is a thin wrapper around
    :func:`~server.pipeline.gates.epub_checkpoints.validate_epub_skill`
    that also emits a structured log message.

    Args:
        skill_name: The skill name from ``AdapterInput.skill_name``.

    Raises:
        :class:`~server.pipeline.gates.epub_checkpoints.EpubSkillRestrictionError`:
            If *skill_name* is not ``"kdrama-romance"``.
    """
    if skill_name != EPUB_ALLOWED_SKILL:
        logger.warning(
            "EPUB novel adapter: skill restriction violated — "
            "requested=%r, allowed=%r",
            skill_name,
            EPUB_ALLOWED_SKILL,
        )
    validate_epub_skill(skill_name)
    logger.debug(
        "EPUB novel adapter: skill restriction OK — skill=%r", skill_name
    )


# ─── Gate runners ─────────────────────────────────────────────────────────────


async def run_character_gate(
    characters: list["CharacterRef"],
    *,
    project_id: int | None = None,
    session: Any = None,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
) -> EpubGateResult:
    """EG1 — Character Gate.

    Called after character extraction.  Logs the extracted character list
    and, when a DB session and project_id are provided, creates an EG1
    :class:`~server.db.models.quality_gate.QualityGate` record so the UI
    can surface the review checkpoint.

    In the current implementation this is an **async stub** — it logs the
    characters and returns ``status="checking"`` immediately.  The actual
    user interaction happens via the API (approve/override endpoints).

    Args:
        characters:    List of extracted :class:`~server.content.character_dedup.CharacterRef`
                       objects.
        project_id:    Optional project ID for DB gate tracking.
        session:       Optional active SQLModel session.  When provided
                       together with *project_id*, an EG1 gate record is
                       created in the database.
        timeout_hours: SLA timeout in hours (default 24h).

    Returns:
        :class:`EpubGateResult` with ``gate_id="EG1"`` and
        ``status="checking"`` (gate created, awaiting user review).
    """
    char_names = [c.name for c in characters] if characters else []
    logger.info(
        "EG1 Character Gate: %d character(s) extracted — %s",
        len(char_names),
        char_names,
    )

    # Persist gate record when DB session is available.
    if session is not None and project_id is not None:
        try:
            from server.pipeline.gates.epub_checkpoints import create_epub_character_gate

            create_epub_character_gate(
                session, project_id=project_id, timeout_hours=timeout_hours
            )
            logger.debug(
                "EG1 gate record created for project_id=%d", project_id
            )
        except Exception as exc:
            logger.warning(
                "EG1: failed to create gate record (non-fatal): %s", exc
            )

    return EpubGateResult(
        gate_id="EG1",
        status="checking",
        message=(
            f"Character Gate: {len(char_names)} character(s) extracted. "
            "Awaiting user review."
        ),
        payload={"characters": char_names},
    )


async def run_plot_gate(
    scene_list: "SceneList",
    *,
    project_id: int | None = None,
    session: Any = None,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
) -> EpubGateResult:
    """EG2 — Plot Gate.

    Called after chapter-to-scene mapping.  Logs the scene breakdown
    (scene count, chapter range, total duration) and, when a DB session
    and project_id are provided, creates an EG2 gate record.

    Args:
        scene_list:    The :class:`~server.content.base.SceneList` produced
                       by the tier processor.
        project_id:    Optional project ID for DB gate tracking.
        session:       Optional active SQLModel session.
        timeout_hours: SLA timeout in hours (default 24h).

    Returns:
        :class:`EpubGateResult` with ``gate_id="EG2"`` and
        ``status="checking"``.
    """
    scene_count = len(scene_list.scenes) if scene_list.scenes else 0
    total_duration = sum(s.duration for s in scene_list.scenes) if scene_list.scenes else 0.0

    logger.info(
        "EG2 Plot Gate: %d scene(s), total_duration=%.1fs, project_id=%r",
        scene_count,
        total_duration,
        scene_list.project_id,
    )

    # Persist gate record when DB session is available.
    if session is not None and project_id is not None:
        try:
            from server.pipeline.gates.epub_checkpoints import create_epub_plot_gate

            create_epub_plot_gate(
                session, project_id=project_id, timeout_hours=timeout_hours
            )
            logger.debug(
                "EG2 gate record created for project_id=%d", project_id
            )
        except Exception as exc:
            logger.warning(
                "EG2: failed to create gate record (non-fatal): %s", exc
            )

    return EpubGateResult(
        gate_id="EG2",
        status="checking",
        message=(
            f"Plot Gate: {scene_count} scene(s), "
            f"total duration {total_duration:.1f}s. "
            "Awaiting user review."
        ),
        payload={
            "scene_count": scene_count,
            "total_duration_sec": total_duration,
            "project_id": scene_list.project_id,
        },
    )


async def run_style_gate(
    style_info: dict,
    *,
    project_id: int | None = None,
    session: Any = None,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
) -> EpubGateResult:
    """EG3 — Style Gate.

    Called after skill application.  Logs the style configuration that
    will be injected into every Veo3 prompt and, when a DB session and
    project_id are provided, creates an EG3 gate record.

    Args:
        style_info:    Dict describing the applied style (e.g. skill name,
                       style prefix snippet, style.json keys).
        project_id:    Optional project ID for DB gate tracking.
        session:       Optional active SQLModel session.
        timeout_hours: SLA timeout in hours (default 24h).

    Returns:
        :class:`EpubGateResult` with ``gate_id="EG3"`` and
        ``status="checking"``.
    """
    skill_name = style_info.get("skill_name", "(unknown)")
    logger.info(
        "EG3 Style Gate: skill=%r, style_keys=%s",
        skill_name,
        list(style_info.keys()),
    )

    # Persist gate record when DB session is available.
    if session is not None and project_id is not None:
        try:
            from server.pipeline.gates.epub_checkpoints import create_epub_style_gate

            create_epub_style_gate(
                session, project_id=project_id, timeout_hours=timeout_hours
            )
            logger.debug(
                "EG3 gate record created for project_id=%d", project_id
            )
        except Exception as exc:
            logger.warning(
                "EG3: failed to create gate record (non-fatal): %s", exc
            )

    return EpubGateResult(
        gate_id="EG3",
        status="checking",
        message=(
            f"Style Gate: skill={skill_name!r}. "
            "Awaiting user review of style configuration."
        ),
        payload=style_info,
    )
