"""Extension discovery endpoint.

GET /api/ext/discovery — public endpoint (no auth) that tells the extension
which WebSocket port to connect to and what version the agent is running.

This is the bootstrap endpoint: the extension fetches this URL first (before
it has a callback_secret), then uses ws_url to open the WebSocket connection.
"""

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/ext/discovery")
async def ext_discovery(request: Request) -> dict[str, Any]:
    """Return WebSocket connection info for the Chrome extension.

    No authentication required — the extension calls this before it has
    a callback_secret.

    Response:
        ws_port: WebSocket server port.
        ws_url: Full WebSocket URL.
        version: Agent version string.
        callback_url: HTTP callback URL for the extension to POST results.
        supported_modules: List of supported extension modules.
        min_extension_version: Minimum compatible extension version.
    """
    from server.config import load_settings

    settings = load_settings()
    ws_port = settings.ws_port

    return {
        "agent_version": "0.1.0",
        "ws_port": ws_port,
        "ws_url": f"ws://127.0.0.1:{ws_port}",
        "callback_url": "http://127.0.0.1:8101/api/ext/callback",
        "supported_modules": ["flow_proxy", "cookie_sniffer"],
        "min_extension_version": "0.1.0",
    }
