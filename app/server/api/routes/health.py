"""Health check endpoint.

GET /api/health — liveness check, returns extension connection status.
"""

import time
from typing import Any

from fastapi import APIRouter

router = APIRouter()

# Track server start time for uptime calculation
_start_time: float = time.time()


@router.get("/api/health")
async def health() -> dict[str, Any]:
    """Return server liveness status.

    Response:
        status: Always "ok" if server is running.
        extension_connected: Whether the Chrome extension is connected via WS.
        version: Agent version string.
        uptime_sec: Seconds since server started.
    """
    from server.flow.client import FlowClient

    client = FlowClient()
    return {
        "status": "ok",
        "extension_connected": client.is_connected(),
        "version": "0.1.0",
        "uptime_sec": int(time.time() - _start_time),
    }
