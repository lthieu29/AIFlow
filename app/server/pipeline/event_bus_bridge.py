"""EventBus → JobLog bridge.

Subscribes to ``EventBus`` events and persists them as ``JobLog`` rows so
they show up in the ``/api/jobs/{id}/stream`` SSE feed in real time.

Each persisted log message uses a structured prefix (``[EVT:<type>] <json>``)
so the SSE generator can split events by type — ``job.scene_progress``,
``job.gate``, ``job.pipeline`` — instead of emitting a single ``job.log``
firehose.

The bridge keeps a reference to the engine and opens its own short-lived
session per event; do not share a long-running session with it.

Usage::

    bus = EventBus()
    bridge = EventBusJobLogBridge(bus, engine, job_id)
    orch = PipelineOrchestrator(settings, sdk, event_bus=bus)
    try:
        await orch.run(...)
    finally:
        bridge.close()
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from loguru import logger
from sqlmodel import Session

from server.pipeline.event_bus import (
    EVENT_GATE_STATUS_CHANGED,
    EVENT_PIPELINE_COMPLETED,
    EVENT_PIPELINE_FAILED,
    EVENT_SCENE_COMPLETED,
    EVENT_SCENE_FAILED,
    EVENT_SCENE_STARTED,
    EventBus,
)
from server.pipeline.job_manager import add_job_log

if TYPE_CHECKING:
    from sqlalchemy import Engine

# Structured prefix that the SSE generator parses to split events by type.
EVT_PREFIX = "[EVT:"


class EventBusJobLogBridge:
    """Persist EventBus events as JobLog rows for live SSE consumption."""

    def __init__(self, bus: EventBus, engine: "Engine", job_id: int, project_id: int | None = None) -> None:
        self._bus = bus
        self._engine = engine
        self._job_id = job_id
        self._project_id = project_id

        self._handlers: list[tuple[str, callable]] = [
            (EVENT_SCENE_STARTED, self._on_scene_started),
            (EVENT_SCENE_COMPLETED, self._on_scene_completed),
            (EVENT_SCENE_FAILED, self._on_scene_failed),
            (EVENT_PIPELINE_COMPLETED, self._on_pipeline_completed),
            (EVENT_PIPELINE_FAILED, self._on_pipeline_failed),
            (EVENT_GATE_STATUS_CHANGED, self._on_gate_status),
        ]
        for evt, fn in self._handlers:
            bus.subscribe(evt, fn)
        logger.debug(
            "EventBusJobLogBridge: subscribed to {} event types for job {}",
            len(self._handlers),
            job_id,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Unsubscribe all handlers — call from a ``finally`` block."""
        for evt, fn in self._handlers:
            self._bus.unsubscribe(evt, fn)
        self._handlers.clear()

    # ── Internal handlers ─────────────────────────────────────────────────────

    def _persist(self, level: str, evt_type: str, data: dict) -> None:
        if self._project_id is not None and str(data.get("project_id", "")) != str(self._project_id):
            return
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            payload = "{}"
        message = f"{EVT_PREFIX}{evt_type}] {payload}"
        try:
            with Session(self._engine) as session:
                add_job_log(session, self._job_id, level, message)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "EventBusJobLogBridge: failed to persist event {!r}: {}",
                evt_type,
                exc,
            )

    def _on_scene_started(self, data: dict) -> None:
        self._persist("INFO", EVENT_SCENE_STARTED, data)

    def _on_scene_completed(self, data: dict) -> None:
        self._persist("INFO", EVENT_SCENE_COMPLETED, data)

    def _on_scene_failed(self, data: dict) -> None:
        self._persist("ERROR", EVENT_SCENE_FAILED, data)

    def _on_pipeline_completed(self, data: dict) -> None:
        level = "INFO" if data.get("all_passed") else "WARNING"
        self._persist(level, EVENT_PIPELINE_COMPLETED, data)

    def _on_pipeline_failed(self, data: dict) -> None:
        self._persist("ERROR", EVENT_PIPELINE_FAILED, data)

    def _on_gate_status(self, data: dict) -> None:
        status = (data.get("status") or "").lower()
        level = {
            "passed": "INFO",
            "overridden": "INFO",
            "checking": "INFO",
            "expired": "WARNING",
            "failed": "ERROR",
        }.get(status, "INFO")
        self._persist(level, EVENT_GATE_STATUS_CHANGED, data)


def parse_event_message(message: str) -> tuple[str, dict] | None:
    """Inverse of the structured prefix used by ``_persist``.

    Returns ``(event_type, payload_dict)`` or ``None`` when the message
    does not start with the bridge prefix.  Used by the SSE generator to
    classify log entries into per-type events.
    """
    if not message or not message.startswith(EVT_PREFIX):
        return None
    end = message.find("]", len(EVT_PREFIX))
    if end == -1:
        return None
    evt_type = message[len(EVT_PREFIX):end]
    raw = message[end + 1:].strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"raw": raw}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    return evt_type, payload
