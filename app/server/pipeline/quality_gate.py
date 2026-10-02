"""Quality gate pipeline — Phase 2 implementation.

Provides:
    GateResult          — dataclass for gate evaluation results
    check_expired_gates — G2.8 SLA timeout: expire overdue checking gates
    periodic_gate_checker — async background loop (runs every 60s)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from server.config import Settings


@dataclass
class GateResult:
    """Result of a single quality gate evaluation.

    Attributes:
        gate_id:     Gate identifier, e.g. "G1", "G2", "G3".
        status:      Outcome: "passed" | "failed" | "expired" | "overridden".
        message:     Human-readable description (empty string on pass).
        retry_count: Number of retries consumed so far (used by G3 cascade).
    """

    gate_id: str
    status: str  # passed | failed | expired | overridden
    message: str = field(default="")
    retry_count: int = field(default=0)


def check_expired_gates(session: "object", settings: "Settings") -> int:
    """G2.8 SLA timeout: find and expire overdue G2 gates.

    Scans the quality_gate table for rows with:
        - status = "checking"  (gate is waiting for user action)
        - expired_at < now()   (SLA deadline has passed)

    Marks each such row as status="expired" and logs a warning.

    This function is called by `periodic_gate_checker()` every 60 seconds.
    It is also safe to call directly in tests.

    Args:
        session:  An active SQLModel Session instance.
        settings: Loaded Settings (used for logging context).

    Returns:
        Number of gates that were expired in this call.
    """
    from datetime import timezone

    from sqlmodel import select

    from server.db.models.quality_gate import QualityGate

    now = datetime.now(timezone.utc)

    # SQLite stores datetimes as naive UTC strings; compare against naive UTC.
    now_naive = now.replace(tzinfo=None)

    statement = select(QualityGate).where(
        QualityGate.status == "checking",
        QualityGate.expired_at.isnot(None),  # type: ignore[union-attr]
        QualityGate.expired_at < now_naive,  # type: ignore[operator]
    )
    expired_gates = session.exec(statement).all()  # type: ignore[attr-defined]

    count = 0
    for gate_row in expired_gates:
        gate_row.status = "expired"
        gate_row.updated_at = now_naive
        session.add(gate_row)  # type: ignore[attr-defined]
        logger.warning(
            "G2.8 SLA expired: gate id={} project_id={} gate_id={} "
            "expired_at={} — marking as expired",
            gate_row.id,
            gate_row.project_id,
            gate_row.gate_id,
            gate_row.expired_at,
        )
        count += 1

    if count > 0:
        session.commit()  # type: ignore[attr-defined]

    return count


async def periodic_gate_checker() -> None:
    """Background loop: check for expired gates every 60 seconds.

    Replaces the Phase 0 no-op skeleton. On each tick, opens a fresh DB
    session and calls `check_expired_gates()` to expire any G2 gates that
    have passed their SLA deadline.

    The loop runs indefinitely until the process exits (cancelled via
    asyncio task cancellation during FastAPI lifespan shutdown).
    """
    logger.info("Quality gate checker started (Phase 2 — G2.8 SLA enforcement)")

    while True:
        await asyncio.sleep(60)

        try:
            from sqlmodel import Session

            from server.config import load_settings
            from server.db.session import get_engine

            settings = load_settings()
            engine = get_engine(settings)

            with Session(engine) as session:
                expired_count = check_expired_gates(session, settings)
                if expired_count > 0:
                    logger.info(
                        "periodic_gate_checker: expired {} gate(s) this tick",
                        expired_count,
                    )
        except Exception as exc:
            # Never crash the background loop — log and continue
            logger.error(
                "periodic_gate_checker: error during gate check: {}", exc
            )
