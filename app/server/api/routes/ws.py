"""WebSocket route for UI live event stream.

Endpoint:
    WS /ws/{project_id} — subscribe to pipeline EventBus and forward events
                          to connected UI clients.

Task 5.3 — Phase 5.3
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

router = APIRouter(tags=["websocket"])

# Heartbeat interval in seconds
_HEARTBEAT_INTERVAL = 25.0


# ─── Route ────────────────────────────────────────────────────────────────────


@router.websocket("/ws/{project_id}")
async def ws_project_events(
    websocket: WebSocket,
    project_id: str,
) -> None:
    """WebSocket endpoint for UI live event stream.

    Accepts a WebSocket connection from the UI, subscribes to the shared
    ``EventBus`` on ``app.state.event_bus``, and forwards all pipeline events
    for the given project to the connected client.

    Message format (server → client):
    ```json
    {
        "type": "scene_started" | "scene_completed" | "scene_failed" |
                "pipeline_completed" | "pipeline_failed" | "gate_status_changed",
        "project_id": "...",
        "data": { ... }
    }
    ```

    Heartbeat (server → client every 25s):
    ```json
    {"type": "ping"}
    ```

    Client can send ``{"type": "pong"}`` in response (ignored by server).

    Args:
        websocket: The WebSocket connection.
        project_id: The project short_id or integer id to subscribe to.
    """
    await websocket.accept()
    logger.info("[ws] client connected for project_id=%s", project_id)

    # Resolve event_bus from app state
    event_bus = None
    try:
        event_bus = websocket.app.state.event_bus
    except AttributeError:
        logger.warning("[ws] event_bus not found on app.state — events will not be forwarded")

    # Queue for thread-safe event delivery from EventBus callbacks
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def _on_event(data: dict) -> None:
        """EventBus callback — enqueue event for async delivery."""
        # Only forward events for this project (if project_id is in data)
        event_project = str(data.get("project_id", ""))
        if event_project and event_project != str(project_id):
            return
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("[ws] event queue full for project_id=%s — dropping event", project_id)

    # Subscribe to all known event types
    _EVENT_TYPES = [
        "scene_started",
        "scene_completed",
        "scene_failed",
        "pipeline_completed",
        "pipeline_failed",
        "gate_status_changed",
    ]

    if event_bus is not None:
        for event_type in _EVENT_TYPES:
            event_bus.subscribe(event_type, _on_event)
        logger.debug("[ws] subscribed to %d event types for project_id=%s", len(_EVENT_TYPES), project_id)

    try:
        # Send initial connection acknowledgement
        await websocket.send_text(
            json.dumps({"type": "connected", "project_id": project_id})
        )

        heartbeat_task = asyncio.create_task(_heartbeat(websocket))

        try:
            while True:
                # Wait for either an event from the bus or a message from the client
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(_receive_message(websocket)),
                        asyncio.create_task(_next_event(queue)),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

                for task in done:
                    result = task.result()
                    if result is None:
                        # WebSocket disconnected
                        return
                    if isinstance(result, dict):
                        # Event from EventBus — forward to client
                        event_type = result.get("_event_type", "event")
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": event_type,
                                    "project_id": project_id,
                                    "data": result,
                                },
                                ensure_ascii=False,
                            )
                        )
                    # str result = client message (pong, etc.) — ignore

        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info("[ws] client disconnected for project_id=%s", project_id)
    except Exception as exc:
        logger.error("[ws] error for project_id=%s: %s", project_id, exc)
    finally:
        # Unsubscribe from all event types
        if event_bus is not None:
            for event_type in _EVENT_TYPES:
                event_bus.unsubscribe(event_type, _on_event)
            logger.debug("[ws] unsubscribed from event bus for project_id=%s", project_id)


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _heartbeat(websocket: WebSocket) -> None:
    """Send periodic ping messages to keep the connection alive."""
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL)
        try:
            await websocket.send_text(json.dumps({"type": "ping"}))
        except Exception:
            return


async def _receive_message(websocket: WebSocket) -> str | None:
    """Receive a single message from the WebSocket client.

    Returns:
        The message text, or None if the connection was closed.
    """
    try:
        return await websocket.receive_text()
    except WebSocketDisconnect:
        return None
    except Exception:
        return None


async def _next_event(queue: asyncio.Queue) -> dict:
    """Wait for the next event from the queue."""
    return await queue.get()
