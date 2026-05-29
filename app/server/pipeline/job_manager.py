"""Job CRUD helpers — create, update, and query Job/JobLog records.

These helpers wrap SQLModel sessions so callers don't need to know the
model internals. All functions are synchronous (SQLite is sync).

Usage::

    from sqlmodel import Session
    from server.db.session import get_engine
    from server.pipeline.job_manager import create_job, update_job_status, add_job_log

    engine = get_engine(settings)
    with Session(engine) as session:
        job = create_job(session, project_id=1, job_type="gen_video")
        update_job_status(session, job.id, "running", started_at=datetime.now(timezone.utc))
        add_job_log(session, job.id, "INFO", "Video generation started")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from server.db.models.job import Job, JobLog, JobStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_job(session: Session, project_id: int, job_type: str) -> Job:
    """Create a new Job with status=pending and persist it.

    Args:
        session: Active SQLModel session.
        project_id: ID of the owning Project row.
        job_type: Arbitrary type string, e.g. "gen_video", "gen_image", "tts".

    Returns:
        The newly created and refreshed Job instance (id is populated).
    """
    job = Job(
        project_id=project_id,
        type=job_type,
        status=JobStatus.pending.value,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def update_job_status(
    session: Session,
    job_id: int,
    status: str,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
) -> None:
    """Update a Job's status (and optional timing fields).

    Args:
        session: Active SQLModel session.
        job_id: Primary key of the Job to update.
        status: New status string — one of JobStatus enum values.
        started_at: Optional timestamp to set when transitioning to "running".
        finished_at: Optional timestamp to set when transitioning to terminal state.
    """
    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    job.status = status
    job.updated_at = _utcnow()
    if started_at is not None:
        job.started_at = started_at
    if finished_at is not None:
        job.finished_at = finished_at
    session.add(job)
    session.commit()


def add_job_log(session: Session, job_id: int, level: str, message: str) -> JobLog:
    """Append a JobLog entry for the given job.

    Args:
        session: Active SQLModel session.
        job_id: Foreign key referencing Job.id.
        level: Log level string — "DEBUG", "INFO", "WARN", or "ERROR".
        message: Human-readable log message.

    Returns:
        The newly created JobLog instance.
    """
    log = JobLog(
        job_id=job_id,
        level=level,
        message=message,
        created_at=_utcnow(),
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


def get_pending_jobs(session: Session, job_type: str) -> list[Job]:
    """Query all pending jobs of a given type.

    Args:
        session: Active SQLModel session.
        job_type: Type string to filter by (e.g. "gen_video").

    Returns:
        List of Job instances with status="pending" and matching type.
    """
    statement = select(Job).where(
        Job.status == JobStatus.pending.value,
        Job.type == job_type,
    )
    return list(session.exec(statement).all())
