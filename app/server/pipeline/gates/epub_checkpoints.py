"""EPUB quality checkpoints — Task 6.3.

Three manual gates specific to EPUB novel processing:

    EG1 — Character gate
        Pause after character extraction.  User reviews extracted characters
        (names, roles, descriptions) before the pipeline proceeds to scene
        generation.  Prevents mis-identified characters from propagating into
        all downstream prompts.

    EG2 — Plot gate
        Pause after chapter-to-scene mapping.  User reviews the episode/scene
        breakdown (chapter boundaries, scene count, narration snippets) and
        can request re-chunking before expensive Veo3 calls begin.

    EG3 — Style gate
        Pause after skill application.  User reviews the merged style prefix
        and style.json that will be injected into every Veo3 prompt.  Allows
        last-minute style adjustments without re-parsing the EPUB.

Skill restriction:
    Only the ``kdrama-romance`` skill is permitted for EPUB novel processing.
    Attempting to use any other skill raises :class:`EpubSkillRestrictionError`.

Usage::

    from server.pipeline.gates.epub_checkpoints import (
        EPUB_ALLOWED_SKILL,
        EpubSkillRestrictionError,
        validate_epub_skill,
        create_epub_character_gate,
        create_epub_plot_gate,
        create_epub_style_gate,
        check_epub_gate_status,
        approve_epub_gate,
        override_epub_gate,
    )
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlmodel import Session

from server.db.models.quality_gate import QualityGate

# ─── Constants ────────────────────────────────────────────────────────────────

#: The only skill permitted for EPUB novel processing.
EPUB_ALLOWED_SKILL: str = "kdrama-romance"

#: Gate IDs for the three EPUB checkpoints.
EpubGateId = Literal["EG1", "EG2", "EG3"]

#: Human-readable names for each EPUB gate.
EPUB_GATE_NAMES: dict[str, str] = {
    "EG1": "Character Gate",
    "EG2": "Plot Gate",
    "EG3": "Style Gate",
}

#: Default SLA timeout in hours for EPUB manual gates.
EPUB_GATE_DEFAULT_TIMEOUT_HOURS: int = 24


# ─── Exceptions ───────────────────────────────────────────────────────────────


class EpubSkillRestrictionError(Exception):
    """Raised when an unsupported skill is used with the EPUB novel adapter.

    Attributes:
        requested_skill: The skill name that was requested.
        allowed_skill:   The only permitted skill.
    """

    def __init__(self, requested_skill: str) -> None:
        self.requested_skill = requested_skill
        self.allowed_skill = EPUB_ALLOWED_SKILL
        super().__init__(
            f"EPUB novel processing only supports the '{EPUB_ALLOWED_SKILL}' skill. "
            f"Requested skill '{requested_skill}' is not allowed. "
            f"Please set skill_name='{EPUB_ALLOWED_SKILL}' in your AdapterInput."
        )


# ─── Skill restriction ────────────────────────────────────────────────────────


def validate_epub_skill(skill_name: str | None) -> None:
    """Validate that *skill_name* is permitted for EPUB novel processing.

    EPUB novel processing is restricted to the ``kdrama-romance`` skill.
    Passing ``None`` (no skill) is also rejected — a skill must be specified.

    Args:
        skill_name: The skill name to validate.  May be ``None``.

    Raises:
        :class:`EpubSkillRestrictionError`: If *skill_name* is not
            ``"kdrama-romance"``.
    """
    if skill_name != EPUB_ALLOWED_SKILL:
        raise EpubSkillRestrictionError(requested_skill=skill_name or "(none)")


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_epub_gate(
    session: "Session",
    gate_id: EpubGateId,
    project_id: int,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
    metadata: dict | None = None,
) -> QualityGate:
    """Create an EPUB checkpoint gate record.

    Args:
        session:       Active SQLModel session.
        gate_id:       One of ``"EG1"``, ``"EG2"``, ``"EG3"``.
        project_id:    ID of the project this gate belongs to.
        timeout_hours: Hours until the gate expires (default 24h).
        metadata:      Optional free-form metadata to attach to the gate.

    Returns:
        The newly created and committed :class:`QualityGate` record.
    """
    now = _utcnow()
    gate = QualityGate(
        gate_id=gate_id,
        project_id=project_id,
        status="checking",
        expired_at=(now + timedelta(hours=timeout_hours)).replace(tzinfo=None),
        score=None,
    )
    session.add(gate)
    session.commit()
    session.refresh(gate)
    return gate


def _get_active_epub_gate(
    session: "Session",
    gate_id: EpubGateId,
    project_id: int,
) -> QualityGate:
    """Fetch the most recent EPUB gate record for a project.

    Args:
        session:    Active SQLModel session.
        gate_id:    Gate identifier (``"EG1"``, ``"EG2"``, or ``"EG3"``).
        project_id: Project ID to look up.

    Returns:
        The most recent :class:`QualityGate` record for the given gate.

    Raises:
        ValueError: If no gate record exists for the project.
    """
    from sqlmodel import select

    statement = (
        select(QualityGate)
        .where(QualityGate.gate_id == gate_id)
        .where(QualityGate.project_id == project_id)
        .order_by(QualityGate.created_at.desc())  # type: ignore[attr-defined]
    )
    gate = session.exec(statement).first()
    if gate is None:
        gate_name = EPUB_GATE_NAMES.get(gate_id, gate_id)
        raise ValueError(
            f"No {gate_name} ({gate_id}) gate found for project_id={project_id}. "
            f"Call create_epub_{gate_id.lower()}_gate() first."
        )
    return gate


# ─── EG1 — Character gate ─────────────────────────────────────────────────────


def create_epub_character_gate(
    session: "Session",
    project_id: int,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
) -> QualityGate:
    """Create an EG1 (Character Gate) record.

    The Character Gate pauses the pipeline after character extraction.
    The user must review the extracted character list (names, roles,
    descriptions) before scene generation begins.

    Args:
        session:       Active SQLModel session.
        project_id:    ID of the project.
        timeout_hours: SLA timeout in hours (default 24h).

    Returns:
        The newly created :class:`QualityGate` record with ``gate_id="EG1"``.
    """
    return _create_epub_gate(
        session,
        gate_id="EG1",
        project_id=project_id,
        timeout_hours=timeout_hours,
    )


# ─── EG2 — Plot gate ──────────────────────────────────────────────────────────


def create_epub_plot_gate(
    session: "Session",
    project_id: int,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
) -> QualityGate:
    """Create an EG2 (Plot Gate) record.

    The Plot Gate pauses the pipeline after chapter-to-scene mapping.
    The user reviews the episode/scene breakdown and can request
    re-chunking before expensive Veo3 calls begin.

    Args:
        session:       Active SQLModel session.
        project_id:    ID of the project.
        timeout_hours: SLA timeout in hours (default 24h).

    Returns:
        The newly created :class:`QualityGate` record with ``gate_id="EG2"``.
    """
    return _create_epub_gate(
        session,
        gate_id="EG2",
        project_id=project_id,
        timeout_hours=timeout_hours,
    )


# ─── EG3 — Style gate ─────────────────────────────────────────────────────────


def create_epub_style_gate(
    session: "Session",
    project_id: int,
    timeout_hours: int = EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
) -> QualityGate:
    """Create an EG3 (Style Gate) record.

    The Style Gate pauses the pipeline after skill application.
    The user reviews the merged style prefix and style.json before
    they are injected into every Veo3 prompt.

    Args:
        session:       Active SQLModel session.
        project_id:    ID of the project.
        timeout_hours: SLA timeout in hours (default 24h).

    Returns:
        The newly created :class:`QualityGate` record with ``gate_id="EG3"``.
    """
    return _create_epub_gate(
        session,
        gate_id="EG3",
        project_id=project_id,
        timeout_hours=timeout_hours,
    )


# ─── Status / approve / override (shared) ────────────────────────────────────


def check_epub_gate_status(
    session: "Session",
    gate_id: EpubGateId,
    project_id: int,
) -> str:
    """Return the current status of an EPUB checkpoint gate.

    Args:
        session:    Active SQLModel session.
        gate_id:    Gate identifier (``"EG1"``, ``"EG2"``, or ``"EG3"``).
        project_id: ID of the project to check.

    Returns:
        Status string: ``"pending"`` | ``"checking"`` | ``"passed"`` |
        ``"failed"`` | ``"expired"`` | ``"overridden"``, or
        ``"not_found"`` if no gate record exists.
    """
    from sqlmodel import select

    statement = (
        select(QualityGate)
        .where(QualityGate.gate_id == gate_id)
        .where(QualityGate.project_id == project_id)
        .order_by(QualityGate.created_at.desc())  # type: ignore[attr-defined]
    )
    gate = session.exec(statement).first()
    if gate is None:
        return "not_found"
    return gate.status


def approve_epub_gate(
    session: "Session",
    gate_id: EpubGateId,
    project_id: int,
) -> None:
    """Mark an EPUB checkpoint gate as passed (user approved).

    Args:
        session:    Active SQLModel session.
        gate_id:    Gate identifier (``"EG1"``, ``"EG2"``, or ``"EG3"``).
        project_id: ID of the project.

    Raises:
        ValueError: If no gate record exists for the project.
    """
    gate = _get_active_epub_gate(session, gate_id, project_id)
    gate.status = "passed"
    gate.updated_at = _utcnow().replace(tzinfo=None)
    session.add(gate)
    session.commit()


def override_epub_gate(
    session: "Session",
    gate_id: EpubGateId,
    project_id: int,
) -> None:
    """Mark an EPUB checkpoint gate as overridden (user skips review).

    The pipeline will continue without explicit user approval.

    Args:
        session:    Active SQLModel session.
        gate_id:    Gate identifier (``"EG1"``, ``"EG2"``, or ``"EG3"``).
        project_id: ID of the project.

    Raises:
        ValueError: If no gate record exists for the project.
    """
    gate = _get_active_epub_gate(session, gate_id, project_id)
    gate.status = "overridden"
    gate.updated_at = _utcnow().replace(tzinfo=None)
    session.add(gate)
    session.commit()
