"""Extension callback endpoint.

POST /api/ext/callback — receives Flow API responses proxied by the extension.
Requires X-Callback-Secret header matching the current session secret.
"""

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter()


@router.post("/api/ext/callback")
async def ext_callback(
    request: Request,
    x_callback_secret: str = Header(default="", alias="X-Callback-Secret"),
) -> dict[str, Any]:
    """Receive a callback from the Chrome extension.

    The extension must include the ``X-Callback-Secret`` header with the
    secret received during the WebSocket handshake.

    For bidirectional requests (api_request), the body contains an ``id``
    field that matches a pending future in FlowClient. The future is resolved
    so the SDK can continue processing.

    Returns:
        {"status": "received"} on success.

    Raises:
        401: If the callback secret is missing or does not match.
    """
    from server.flow.ws_server import get_callback_secret
    from server.flow.client import FlowClient

    current_secret = get_callback_secret()

    if not x_callback_secret:
        raise HTTPException(status_code=401, detail="X-Callback-Secret header is required")

    if current_secret is None:
        raise HTTPException(
            status_code=401,
            detail="No active extension session — extension is not connected",
        )

    if x_callback_secret != current_secret:
        raise HTTPException(status_code=401, detail="Invalid callback secret")

    body = await request.json()

    # Resolve pending future if this is a response to an api_request
    flow_client = FlowClient()
    req_id = body.get("id")
    if req_id:
        resolved = flow_client.resolve_callback(body)
        if resolved:
            return {"status": "received", "request_id": req_id}

    return {"status": "received", "request_id": body.get("id")}
