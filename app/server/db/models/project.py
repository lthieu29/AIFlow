"""Project model — top-level container for a video generation project.

Indexes (per spec 02):
    short_id  UNIQUE  — lookup by public id (Field index=True, unique=True)
    ix_project_status — filter list of active projects
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_short_id() -> str:
    return "p_" + uuid.uuid4().hex[:4]


class Project(SQLModel, table=True):
    """Top-level project entity.

    Phase 0 subset — full schema (with adapter_input JSON, scenes, etc.)
    will be added in Phase 1-2 migrations.
    """

    __table_args__ = (
        Index("ix_project_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    short_id: str = Field(index=True, unique=True)  # e.g. "p_a3f9"
    title: str
    aspect: str = "9:16"
    skill: str = ""
    adapter: str = ""
    status: str = "draft"

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
