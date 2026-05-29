"""QualityGate model — track G1-G6 gate results per project/scene.

Gates:
    G1 — Validate SceneList structure (auto)
    G2 — User approve asset refs (manual)
    G3 — Per-scene quality check (auto, max 2 retries)
    G4 — Audio quality check (auto)
    G5 — Subtitle quality check (auto)
    G6 — Final video quality check (auto/manual)

Indexes (per spec 02):
    ix_quality_gate_project_id — list gates per project
    ix_quality_gate_status     — filter by gate status
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QualityGate(SQLModel, table=True):
    """One quality gate evaluation record.

    gate_id values: "G1" | "G2" | "G3" | "G4" | "G5" | "G6"
    status values:  "pending" | "checking" | "passed" | "failed" | "expired" | "overridden"

    scene_id is nullable — project-level gates (G1, G2, G4, G5, G6) have no
    specific scene; scene-level gates (G3) reference a scene.

    score is reserved for future use (LLM judge confidence, face similarity, etc.)
    expired_at is set for manual gates that have an SLA deadline.
    """

    __tablename__ = "quality_gate"  # type: ignore[assignment]

    __table_args__ = (
        Index("ix_quality_gate_project_id", "project_id"),
        Index("ix_quality_gate_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    gate_id: str  # G1 | G2 | G3 | G4 | G5 | G6
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id")
    project_id: int = Field(foreign_key="project.id")

    status: str = Field(default="pending")  # pending | checking | passed | failed | expired | overridden

    # Reserved for future LLM judge / face confidence score (REVIEW-02 #8)
    score: Optional[float] = Field(default=None)

    # SLA deadline for manual gates (REVIEW-01 #7)
    expired_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
