"""Job and JobLog models — async work tracking.

State machine:
    pending → running → success
                  │
                  ↓
                failed
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    """Job state machine values.

    Transitions:
        pending  → running
        running  → success | failed
        failed   → pending  (retry, reset by worker)
    """

    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class Job(SQLModel, table=True):
    """In-process worker queue, persistent across restarts.

    Indexes (per spec 02):
        ix_job_project_id  — list jobs per project
        ix_job_status      — worker queue pull by status
    """

    __table_args__ = (
        Index("ix_job_project_id", "project_id"),
        Index("ix_job_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")
    type: str  # gen_image | gen_video | tts | transcribe | compose | ...
    status: str = Field(default=JobStatus.pending.value)

    # Timing
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)


class JobLog(SQLModel, table=True):
    """Per-job detailed log. Append-only.

    Indexes (per spec 02):
        ix_joblog_job_id — time-ordered logs per job
    """

    __table_args__ = (
        Index("ix_joblog_job_id", "job_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id")
    level: str = "INFO"  # DEBUG | INFO | WARN | ERROR
    message: str
    created_at: datetime = Field(default_factory=_utcnow)
