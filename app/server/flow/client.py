"""FlowClient — singleton managing extension connection state and token.

The WebSocket server (ws_server.py) calls set_token() and set_connected()
when messages arrive from the extension. Other parts of the server call
wait_for_token() / wait_for_extension() to block until ready.

Bidirectional protocol (added for Task 0.5):
  - api_request() sends a JSON-RPC-style message to the extension over WS
    and awaits a response via the HTTP callback endpoint.
  - The extension POSTs the response to /api/ext/callback with the request id.
  - resolve_callback() is called by ext_callback.py to resolve the pending future.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

from loguru import logger


class FlowClient:
    """Singleton tracking extension WebSocket connection and Bearer token.

    Also handles bidirectional request/response with the extension via
    WS (outbound) + HTTP callback (inbound response).
    """

    _instance: Optional["FlowClient"] = None

    def __new__(cls) -> "FlowClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._token: Optional[str] = None
            cls._instance._connected: bool = False
            cls._instance._token_event: asyncio.Event = asyncio.Event()
            cls._instance._connected_event: asyncio.Event = asyncio.Event()
            # Pending futures keyed by request id — resolved via HTTP callback
            cls._instance._pending: dict[str, asyncio.Future] = {}
            # Reference to the active WS connection (set by ws_server)
            cls._instance._ws: Optional[Any] = None
        return cls._instance

    # ── WS reference (set by ws_server) ──────────────────────────────────────

    def set_ws(self, ws: Any) -> None:
        """Store reference to the active WebSocket connection."""
        self._ws = ws

    def clear_ws(self) -> None:
        """Clear WS reference and fail all pending futures on disconnect."""
        self._ws = None
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(ConnectionError("extension_disconnected"))
        self._pending.clear()

    # ── State setters (called by ws_server) ──────────────────────────────────

    def set_token(self, token: str) -> None:
        """Store captured Bearer token and signal waiters."""
        self._token = token
        self._token_event.set()
        logger.info("FlowClient: Bearer token captured")

    def set_connected(self, connected: bool) -> None:
        """Update extension connection state."""
        self._connected = connected
        if connected:
            self._connected_event.set()
            logger.info("FlowClient: extension connected")
        else:
            self._connected_event.clear()
            logger.info("FlowClient: extension disconnected")

    # ── State getters ─────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """Return True if extension is currently connected via WebSocket."""
        return self._connected

    def get_token(self) -> Optional[str]:
        """Return current Bearer token, or None if not yet captured."""
        return self._token

    # ── Async waiters ─────────────────────────────────────────────────────────

    async def wait_for_token(self, timeout: float = 60.0) -> str:
        """Wait until a Bearer token is captured from the extension.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            The captured Bearer token string.

        Raises:
            TimeoutError: If no token arrives within ``timeout`` seconds.
        """
        try:
            await asyncio.wait_for(self._token_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No Bearer token captured within {timeout}s. "
                "Make sure the extension is connected and you are logged in to labs.google."
            )
        assert self._token is not None
        return self._token

    async def wait_for_extension(self, timeout: float = 30.0) -> None:
        """Wait until the extension sends extension_ready.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If extension does not connect within ``timeout`` seconds.
        """
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Extension did not connect within {timeout}s. "
                "Make sure the AIFlow Bridge extension is installed and enabled."
            )

    # ── Bidirectional request/response ────────────────────────────────────────

    async def _send(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Send a request to the extension over WS and await the response.

        The extension responds via HTTP POST to /api/ext/callback, which calls
        resolve_callback() to resolve the pending future.

        Args:
            method: The method name (e.g. "api_request").
            params: Parameters dict for the method.
            timeout: Maximum seconds to wait for the response.

        Returns:
            The response dict from the extension.
        """
        if self._ws is None:
            return {"error": "extension_disconnected"}

        req_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut

        payload = {"id": req_id, "method": method, "params": params}
        try:
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            logger.warning(f"FlowClient: request {req_id[:8]} timed out after {timeout}s")
            return {"error": "timeout"}
        except ConnectionError as exc:
            self._pending.pop(req_id, None)
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(req_id, None)
            logger.warning(f"FlowClient: _send error: {exc}")
            return {"error": str(exc)}

    async def api_request(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[dict[str, Any]] = None,
        body: Any = None,
        captcha_action: Optional[str] = None,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Proxy an HTTP call through the extension's browser session.

        The extension performs the fetch with the user's Bearer token and
        reCAPTCHA token (if captcha_action is set), then POSTs the response
        back to /api/ext/callback.

        Args:
            url: Target URL (must be aisandbox-pa.googleapis.com).
            method: HTTP method.
            headers: Additional request headers.
            body: JSON-serialisable request body.
            captcha_action: reCAPTCHA action string (e.g. "IMAGE_GENERATION").
            timeout: Maximum seconds to wait.

        Returns:
            Response dict with ``status``, ``data``, or ``error`` keys.
        """
        params: dict[str, Any] = {
            "url": url,
            "method": method,
            "headers": headers or {},
            "body": body,
        }
        if captcha_action:
            params["captchaAction"] = captcha_action
        return await self._send("api_request", params, timeout=timeout)

    def resolve_callback(self, data: dict[str, Any]) -> bool:
        """Resolve a pending future from the HTTP callback endpoint.

        Called by ext_callback.py after validating the callback secret.

        Args:
            data: The callback payload (must contain ``id`` key).

        Returns:
            True if a matching pending future was found and resolved.
        """
        req_id = data.get("id")
        if not req_id or req_id not in self._pending:
            return False
        fut = self._pending.pop(req_id, None)
        if not fut or fut.done():
            return False
        fut.set_result(data)
        return True
