"""WebSocket server for extension ↔ agent communication.

Listens on port 9223 (configurable via settings.ws_port).
Protocol:
  1. Extension connects.
  2. Server sends: {"type": "callback_secret", "secret": "<hex>"}
  3. Extension sends: {"type": "extension_ready", "version": "...", "modules": [...]}
  4. Extension may send: {"type": "token_captured", "token": "<bearer>"}
  5. Heartbeat: server ping → extension pong.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import TYPE_CHECKING, Optional

import websockets
from loguru import logger

if TYPE_CHECKING:
    from server.config import Settings
    from server.flow.client import FlowClient

# Module-level reference to the currently connected extension websocket
_extension_ws: Optional[websockets.WebSocketServerProtocol] = None  # type: ignore[name-defined]
_callback_secret: Optional[str] = None


def get_callback_secret() -> Optional[str]:
    """Return the current session callback secret (used by ext_callback route)."""
    return _callback_secret


async def _handle_connection(
    websocket: websockets.WebSocketServerProtocol,  # type: ignore[name-defined]
    flow_client: "FlowClient",
) -> None:
    """Handle a single extension WebSocket connection."""
    global _extension_ws, _callback_secret

    remote = websocket.remote_address
    logger.info(f"WS: extension connected from {remote}")

    # Generate a fresh callback secret for this session
    _callback_secret = secrets.token_hex(32)
    _extension_ws = websocket

    # Store WS reference in FlowClient for bidirectional communication
    flow_client.set_ws(websocket)

    # Send callback_secret immediately
    await websocket.send(
        json.dumps({"type": "callback_secret", "secret": _callback_secret})
    )
    logger.debug("WS: sent callback_secret to extension")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"WS: received non-JSON message: {raw!r}")
                continue

            msg_type = msg.get("type", "")
            logger.debug(f"WS: received message type={msg_type!r}")

            if msg_type == "extension_ready":
                version = msg.get("version", "unknown")
                modules = msg.get("modules", [])
                logger.info(f"WS: extension_ready version={version} modules={modules}")
                flow_client.set_connected(True)

            elif msg_type == "token_captured":
                # Extension sends flowKey (not token) per flow_proxy.js
                token = msg.get("flowKey") or msg.get("token", "")
                if token:
                    flow_client.set_token(token)
                else:
                    logger.warning("WS: token_captured message has empty token/flowKey")

            elif msg_type == "pong":
                logger.debug("WS: pong received")

            else:
                logger.debug(f"WS: unhandled message type={msg_type!r}")

    except websockets.exceptions.ConnectionClosed as exc:
        logger.info(f"WS: extension disconnected: {exc}")
    finally:
        flow_client.set_connected(False)
        flow_client.clear_ws()
        _extension_ws = None
        _callback_secret = None
        logger.info("WS: connection cleaned up")


async def start_ws_server(
    settings: "Settings",
    flow_client: "FlowClient",
) -> None:
    """Start the WebSocket server and run until cancelled.

    Args:
        settings: Loaded Settings instance (uses settings.ws_port).
        flow_client: Shared FlowClient singleton.
    """
    host = "127.0.0.1"
    port = settings.ws_port

    async def handler(ws: websockets.WebSocketServerProtocol) -> None:  # type: ignore[name-defined]
        await _handle_connection(ws, flow_client)

    logger.info(f"WS server starting on ws://{host}:{port}")
    async with websockets.serve(handler, host, port):  # type: ignore[attr-defined]
        logger.info(f"WS server listening on ws://{host}:{port}")
        await asyncio.Future()  # run forever until cancelled
