"""Scene model — 1 scene = 1 Veo3 clip (8s).

Indexes (per spec 02):
    ix_scene_project_id — list scenes per project
    ix_scene_status     — filter by generation status
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

# REVIEW-02 #6 — location_hint MUST be a Literal enum, NOT a free string.
LocationHint = Literal["indoor", "outdoor", "transition", "unspecified"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Scene(SQLModel, table=True):
    """One scene in a project — maps to one Veo3 8s clip.

    location_hint uses a Literal type (REVIEW-02 #6) to constrain values
    to: "indoor" | "outdoor" | "transition" | "unspecified".
    The scene chain logic in Layer 3 uses this to detect location changes
    and reset the start-frame chain accordingly.
    """

    __table_args__ = (
        Index("ix_scene_project_id", "project_id"),
        Index("ix_scene_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    order: int  # 0-based position in the scene list
    duration: float = 8.0  # seconds; Veo3 fixed at 8s, may be adjusted by audio

    # Status state machine: draft → queued → generating → quality_check → approved/rejected
    status: str = Field(default="draft")

    # REVIEW-02 #6 — constrained Literal, stored as VARCHAR in SQLite
    location_hint: str = Field(default="unspecified")

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
