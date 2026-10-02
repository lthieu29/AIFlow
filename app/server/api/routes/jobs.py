"""Jobs API routes.

Endpoints:
    GET /api/jobs/{id}/stream — SSE endpoint streaming live job progress
                                (status, log lines) from JobLog table;
                                polls DB every 1s using asyncio.

Task 5.3 — Phase 5.3
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlmodel import Session, select

from server.config import Settings, load_settings
from server.db.models.job import Job, JobLog
from server.db.session import get_engine
from server.pipeline.event_bus import (
    EVENT_GATE_STATUS_CHANGED,
    EVENT_PIPELINE_COMPLETED,
    EVENT_PIPELINE_FAILED,
    EVENT_SCENE_COMPLETED,
    EVENT_SCENE_FAILED,
    EVENT_SCENE_STARTED,
)
from server.pipeline.event_bus_bridge import parse_event_message

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# How often to poll the DB for new log lines (seconds)
_POLL_INTERVAL = 1.0

# Maximum number of seconds to stream before auto-closing (safety valve)
_MAX_STREAM_SECONDS = 3600

# Map EventBus event type → SSE event name emitted to the client.
# The FE listens to these directly (per-category) instead of parsing
# the legacy `job.log` firehose.
_SSE_EVENT_NAME: dict[str, str] = {
    EVENT_SCENE_STARTED: "job.scene_progress",
    EVENT_SCENE_COMPLETED: "job.scene_progress",
    EVENT_SCENE_FAILED: "job.scene_progress",
    EVENT_PIPELINE_COMPLETED: "job.pipeline",
    EVENT_PIPELINE_FAILED: "job.pipeline",
    EVENT_GATE_STATUS_CHANGED: "job.gate",
}


# ─── Dependency ───────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    return load_settings()


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("/{job_id}/stream")
async def stream_job(
    job_id: int,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Stream live job progress via Server-Sent Events (SSE).

    Polls the ``JobLog`` table every second and emits new log lines as SSE
    events.  Also emits a ``job.status`` event whenever the job status
    changes.  The stream closes automatically when the job reaches a
    terminal state (``success`` or ``failed``).

    SSE event types:
        ``job.status``  — emitted on status change, data: ``{"job_id": ..., "status": "..."}``
        ``job.log``     — emitted for each new log line, data: ``{"level": "...", "message": "...", "created_at": "..."}``
        ``job.done``    — emitted when job reaches terminal state, then stream closes

    Args:
        job_id: Integer primary key of the job.

    Returns:
        StreamingResponse with ``text/event-stream`` content type.

    Raises:
        HTTPException 404: If the job is not found.
    """
    logger.info("[jobs] GET /api/jobs/%d/stream", job_id)

    # Verify job exists before opening the stream
    engine = get_engine(settings)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "JOB_NOT_FOUND",
                        "message": f"Job {job_id} not found.",
                    }
                },
            )

    return StreamingResponse(
        _sse_generator(job_id, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ─── SSE generator ────────────────────────────────────────────────────────────


async def _sse_generator(
    job_id: int,
    settings: Settings,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted strings.

    Polls the DB every ``_POLL_INTERVAL`` seconds for new JobLog rows and
    job status changes.  Closes when the job reaches a terminal state.

    Args:
        job_id: Job primary key.
        settings: Loaded application settings.

    Yields:
        SSE-formatted strings (``event: ...\ndata: ...\n\n``).
    """
    engine = get_engine(settings)
    last_log_id: int = 0
    last_status: str = ""
    elapsed = 0.0

    # Send initial keep-alive comment
    yield ": keep-alive\n\n"

    while elapsed < _MAX_STREAM_SECONDS:
        await asyncio.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                # Job was deleted — close stream
                yield _sse_event("job.error", {"job_id": job_id, "message": "Job not found"})
                return

            # Emit status change event
            if job.status != last_status:
                last_status = job.status
                yield _sse_event(
                    "job.status",
                    {
                        "job_id": job_id,
                        "status": job.status,
                        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                    },
                )

            # Emit new log lines
            new_logs = session.exec(
                select(JobLog)
                .where(JobLog.job_id == job_id)
                .where(JobLog.id > last_log_id)
                .order_by(JobLog.id)
            ).all()

            for log in new_logs:
                last_log_id = log.id

                # Always emit the legacy `job.log` for back-compat / debug.
                yield _sse_event(
                    "job.log",
                    {
                        "level": log.level,
                        "message": log.message,
                        "created_at": log.created_at.isoformat(),
                    },
                )

                # If the log carries a structured EventBus payload, also
                # emit a typed event so the FE can subscribe per category.
                parsed = parse_event_message(log.message)
                if parsed is None:
                    continue
                evt_type, payload = parsed
                sse_event_name = _SSE_EVENT_NAME.get(evt_type)
                if sse_event_name is None:
                    continue
                yield _sse_event(
                    sse_event_name,
                    {
                        "event_type": evt_type,
                        "level": log.level,
                        "created_at": log.created_at.isoformat(),
                        **payload,
                    },
                )

            # Close stream on terminal state
            if job.status in ("success", "failed", "needs_attention", "cancelled"):
                yield _sse_event(
                    "job.done",
                    {
                        "job_id": job_id,
                        "status": job.status,
                        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    },
                )
                logger.info(
                    "[jobs] SSE stream closed for job %d — terminal status=%s",
                    job_id,
                    job.status,
                )
                return

    # Safety valve: stream timed out
    logger.warning("[jobs] SSE stream for job %d timed out after %ds", job_id, _MAX_STREAM_SECONDS)
    yield _sse_event("job.timeout", {"job_id": job_id, "message": "Stream timed out"})


def _sse_event(event_type: str, data: dict) -> str:
    """Format a single SSE event string.

    Args:
        event_type: SSE event name.
        data: Payload dict (will be JSON-serialised).

    Returns:
        SSE-formatted string ending with double newline.
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
