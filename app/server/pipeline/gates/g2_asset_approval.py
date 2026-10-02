"""G2 — User approve asset refs gate.

This is a manual gate: the pipeline pauses and waits for the user to approve
(or override) the generated reference images before proceeding to scene gen.

G2.8 SLA: if the user does not act within `timeout_hours`, the background
`check_expired_gates()` in quality_gate.py auto-resolves the gate.

Functions:
    create_g2_gate  — create a G2 QualityGate record with SLA deadline
    check_g2_status — return current gate status string
    approve_g2      — mark gate as passed (user approved)
    override_g2     — mark gate as overridden (user skips approval)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session

from server.db.models.quality_gate import QualityGate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_g2_gate(
    session: "Session",
    project_id: int,
    timeout_hours: int = 24,
) -> QualityGate:
    """Create a G2 gate record with an SLA deadline.

    The gate starts in "checking" status (pipeline is waiting for user action).
    The `expired_at` field is set to now + timeout_hours so that
    `check_expired_gates()` can auto-resolve it if the user does not act.

    Args:
        session:       Active SQLModel session.
        project_id:    ID of the project this gate belongs to.
        timeout_hours: Hours until the gate expires (default 24h, per G2.8 SLA).

    Returns:
        The newly created and committed QualityGate record.
    """
    gate = QualityGate(
        gate_id="G2",
        project_id=project_id,
        status="checking",
        expired_at=_utcnow() + timedelta(hours=timeout_hours),
    )
    session.add(gate)
    session.commit()
    session.refresh(gate)
    return gate


def check_g2_status(session: "Session", project_id: int) -> str:
    """Return the current status of the G2 gate for a project.

    Looks for the most recently created G2 gate for the given project.

    Args:
        session:    Active SQLModel session.
        project_id: ID of the project to check.

    Returns:
        Status string: "pending" | "checking" | "passed" | "failed" |
        "expired" | "overridden", or "not_found" if no G2 gate exists.
    """
    from sqlmodel import select

    statement = (
        select(QualityGate)
        .where(QualityGate.gate_id == "G2")
        .where(QualityGate.project_id == project_id)
        .order_by(QualityGate.created_at.desc())  # type: ignore[attr-defined]
    )
    gate = session.exec(statement).first()
    if gate is None:
        return "not_found"
    return gate.status


def approve_g2(session: "Session", project_id: int) -> None:
    """Mark the G2 gate as passed (user approved all asset refs).

    Updates the most recent G2 gate for the project to status="passed".

    Args:
        session:    Active SQLModel session.
        project_id: ID of the project whose G2 gate to approve.

    Raises:
        ValueError: If no G2 gate exists for the project.
    """
    gate = _get_active_g2_gate(session, project_id)
    gate.status = "passed"
    gate.updated_at = _utcnow()
    session.add(gate)
    session.commit()


def override_g2(session: "Session", project_id: int) -> None:
    """Mark the G2 gate as overridden (user skips approval).

    The pipeline will continue without explicit user approval of asset refs.
    This is the "Override G2 — accept all refs" action from the UI.

    Args:
        session:    Active SQLModel session.
        project_id: ID of the project whose G2 gate to override.

    Raises:
        ValueError: If no G2 gate exists for the project.
    """
    gate = _get_active_g2_gate(session, project_id)
    gate.status = "overridden"
    gate.updated_at = _utcnow()
    session.add(gate)
    session.commit()


def _get_active_g2_gate(session: "Session", project_id: int) -> QualityGate:
    """Fetch the most recent G2 gate for a project.

    Args:
        session:    Active SQLModel session.
        project_id: Project ID to look up.

    Returns:
        The most recent QualityGate record with gate_id="G2".

    Raises:
        ValueError: If no G2 gate exists for the project.
    """
    from sqlmodel import select

    statement = (
        select(QualityGate)
        .where(QualityGate.gate_id == "G2")
        .where(QualityGate.project_id == project_id)
        .order_by(QualityGate.created_at.desc())  # type: ignore[attr-defined]
    )
    gate = session.exec(statement).first()
    if gate is None:
        raise ValueError(
            f"No G2 gate found for project_id={project_id}. "
            "Call create_g2_gate() first."
        )
    return gate
