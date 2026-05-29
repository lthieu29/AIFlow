"""Background polling loop for async video generation operations.

VideoPoller watches pending video operations submitted to Google Flow and
downloads completed videos to disk. It runs as a single asyncio background
task and polls every 5 seconds.

Usage::

    from server.pipeline.poller import VideoPoller

    poller = VideoPoller(settings=settings)
    poller.start()

    # Register an operation for polling after gen_video() returns:
    poller.submit(
        operation_name="operations/abc123",
        project_id="proj-uuid",
        job_id=42,
        storage_dir=Path("storage/media"),
    )

    # On shutdown:
    await poller.stop()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:
    from server.config import Settings

# How often to poll each pending operation (seconds)
POLL_INTERVAL_SECONDS = 5

# Maximum number of poll attempts before giving up (120 × 5s = 10 minutes)
MAX_POLL_ATTEMPTS = 120


@dataclass
class _PendingOp:
    """Internal record for a single pending video operation."""

    operation_name: str
    project_id: str
    job_id: int
    storage_dir: Path
    attempts: int = 0
    submitted_at: float = field(default_factory=time.monotonic)


class VideoPoller:
    """Background task that polls pending video generation operations.

    Attributes:
        _settings: Application settings (used to open DB sessions).
        _pending: Dict mapping operation_name → _PendingOp.
        _task: The asyncio.Task running _poll_loop(), or None.
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._pending: dict[str, _PendingOp] = {}
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(
        self,
        operation_name: str,
        project_id: str,
        job_id: int,
        storage_dir: Path,
    ) -> None:
        """Register a pending operation for polling.

        Safe to call from any coroutine or thread (dict mutation is GIL-safe
        in CPython). Duplicate submissions are silently ignored.

        Args:
            operation_name: The async operation ID returned by FlowSDK.gen_video().
            project_id: Flow project UUID (used to build the output path).
            job_id: DB primary key of the associated Job row.
            storage_dir: Base directory for media storage (e.g. Path("storage/media")).
        """
        if operation_name in self._pending:
            logger.debug(f"VideoPoller.submit: already tracking {operation_name!r}")
            return
        self._pending[operation_name] = _PendingOp(
            operation_name=operation_name,
            project_id=project_id,
            job_id=job_id,
            storage_dir=storage_dir,
        )
        logger.info(
            f"VideoPoller: registered operation {operation_name!r} "
            f"(job_id={job_id}, project_id={project_id})"
        )

    def start(self) -> None:
        """Start the background polling loop as an asyncio task.

        Must be called from within a running event loop (e.g. inside a
        FastAPI lifespan handler). Calling start() twice is a no-op if the
        task is still running.
        """
        if self._task is not None and not self._task.done():
            logger.debug("VideoPoller.start: already running")
            return
        self._task = asyncio.create_task(self._poll_loop(), name="video_poller")
        logger.info("VideoPoller: background polling loop started")

    async def stop(self) -> None:
        """Cancel the polling task and wait for it to finish.

        Safe to call even if start() was never called.
        """
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info("VideoPoller: polling loop stopped")

    # ── Internal polling loop ─────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Async loop: every POLL_INTERVAL_SECONDS, check all pending operations.

        For each pending operation:
        - Call FlowSDK.check_async() to get the current status.
        - If done (successful): download video, update Job to success.
        - If failed: update Job to failed.
        - If still pending: increment attempt counter; mark failed after MAX_POLL_ATTEMPTS.
        """
        from server.flow.sdk import get_flow_sdk

        logger.info("VideoPoller._poll_loop: entering poll loop")
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                if not self._pending:
                    continue
                await self._check_all()
            except asyncio.CancelledError:
                logger.info("VideoPoller._poll_loop: cancelled")
                raise
            except Exception as exc:
                # Log unexpected errors but keep the loop alive
                logger.exception(f"VideoPoller._poll_loop: unexpected error: {exc}")

    async def _check_all(self) -> None:
        """Check all pending operations in a single pass."""
        from server.flow.sdk import extract_video_operations, get_flow_sdk

        sdk = get_flow_sdk()
        op_names = list(self._pending.keys())
        if not op_names:
            return

        logger.debug(f"VideoPoller: checking {len(op_names)} pending operation(s)")

        for op_name in op_names:
            pending = self._pending.get(op_name)
            if pending is None:
                continue
            await self._check_one(sdk, pending)

    async def _check_one(self, sdk: object, pending: _PendingOp) -> None:
        """Poll a single operation and handle the result."""
        from server.flow.sdk import FlowSDK, extract_video_operations

        assert isinstance(sdk, FlowSDK)

        pending.attempts += 1
        op_name = pending.operation_name

        # Timeout guard: exceeded max attempts
        if pending.attempts > MAX_POLL_ATTEMPTS:
            logger.warning(
                f"VideoPoller: operation {op_name!r} exceeded max attempts "
                f"({MAX_POLL_ATTEMPTS}), marking as failed"
            )
            self._pending.pop(op_name, None)
            await self._mark_failed(
                pending,
                reason=f"Polling timeout: exceeded {MAX_POLL_ATTEMPTS} attempts "
                       f"({MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS}s)",
            )
            return

        try:
            resp = await sdk.check_async(op_name)
        except Exception as exc:
            logger.warning(
                f"VideoPoller: check_async error for {op_name!r} "
                f"(attempt {pending.attempts}): {exc}"
            )
            return  # Transient error — retry next cycle

        # Parse the response using the existing helper
        ops = extract_video_operations(resp, requested=[op_name])
        if not ops:
            logger.debug(f"VideoPoller: no ops in response for {op_name!r}")
            return

        op_result = ops[0]
        done = op_result.get("done", False)
        error = op_result.get("error")
        media_entries = op_result.get("media_entries", [])

        if not done:
            logger.debug(
                f"VideoPoller: {op_name!r} still pending "
                f"(attempt {pending.attempts}/{MAX_POLL_ATTEMPTS})"
            )
            return

        # Operation is done — remove from pending dict first
        self._pending.pop(op_name, None)

        if error:
            logger.error(f"VideoPoller: operation {op_name!r} failed: {error}")
            await self._mark_failed(pending, reason=error)
            return

        # Success — download the video
        if not media_entries:
            logger.error(
                f"VideoPoller: operation {op_name!r} done but no media entries"
            )
            await self._mark_failed(
                pending, reason="Operation completed but no media entries returned"
            )
            return

        entry = media_entries[0]
        signed_url = entry.get("url")
        if not signed_url:
            logger.error(
                f"VideoPoller: operation {op_name!r} done but no signed URL"
            )
            await self._mark_failed(
                pending, reason="Operation completed but no signed URL in media entry"
            )
            return

        await self._download_and_complete(pending, signed_url)

    async def _download_and_complete(
        self, pending: _PendingOp, signed_url: str
    ) -> None:
        """Download the completed video and update the Job to success."""
        from server.flow.downloader import download_video

        timestamp = int(time.time())
        out_dir = pending.storage_dir / pending.project_id
        out_path = out_dir / f"video_{timestamp}.mp4"

        try:
            saved_path = await download_video(signed_url, out_path)
        except RuntimeError as exc:
            logger.error(
                f"VideoPoller: download failed for job {pending.job_id}: {exc}"
            )
            await self._mark_failed(pending, reason=str(exc))
            return

        logger.info(
            f"VideoPoller: video saved to {saved_path} "
            f"(job_id={pending.job_id})"
        )

        # Update DB: job → success
        await asyncio.get_event_loop().run_in_executor(
            None,
            self._db_mark_success,
            pending.job_id,
            str(saved_path),
        )

    def _db_mark_success(self, job_id: int, video_path: str) -> None:
        """Synchronous DB update: mark job as success and add log entry."""
        from sqlmodel import Session

        from server.db.session import get_engine
        from server.pipeline.job_manager import add_job_log, update_job_status

        engine = get_engine(self._settings)
        with Session(engine) as session:
            update_job_status(
                session,
                job_id,
                "success",
                finished_at=datetime.now(timezone.utc),
            )
            add_job_log(
                session,
                job_id,
                "INFO",
                f"Video generation completed. Saved to: {video_path}",
            )

    async def _mark_failed(self, pending: _PendingOp, reason: str) -> None:
        """Update the Job to failed status with a log entry."""
        await asyncio.get_event_loop().run_in_executor(
            None,
            self._db_mark_failed,
            pending.job_id,
            reason,
        )

    def _db_mark_failed(self, job_id: int, reason: str) -> None:
        """Synchronous DB update: mark job as failed and add log entry."""
        from sqlmodel import Session

        from server.db.session import get_engine
        from server.pipeline.job_manager import add_job_log, update_job_status

        engine = get_engine(self._settings)
        with Session(engine) as session:
            update_job_status(
                session,
                job_id,
                "failed",
                finished_at=datetime.now(timezone.utc),
            )
            add_job_log(
                session,
                job_id,
                "ERROR",
                f"Video generation failed: {reason}",
            )
