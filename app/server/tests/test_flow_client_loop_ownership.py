"""Sync background workers must proxy extension requests onto the WebSocket loop."""

import asyncio
import json

import pytest

from server.flow.client import FlowClient


async def test_worker_loop_uses_websocket_owner_loop(monkeypatch):
    monkeypatch.setattr(FlowClient, "_instance", None)
    client = FlowClient()
    owner = asyncio.get_running_loop()
    owner.set_debug(True)
    observed = []

    class Socket:
        async def send(self, message):
            observed.append(asyncio.get_running_loop())
            assert asyncio.get_running_loop() is owner, "WebSocket used from a worker loop"
            request = json.loads(message)
            owner.call_soon(client.resolve_callback, {"id": request["id"], "data": "ok"})

    client.set_ws(Socket())
    try:
        response = await asyncio.to_thread(lambda: asyncio.run(client._send("test", {}, timeout=1)))
        assert response.get("data") == "ok"
        assert observed == [owner]
        assert not client._pending
    finally:
        client.clear_ws()
        owner.set_debug(False)


async def test_cancelled_request_releases_pending_future(monkeypatch):
    monkeypatch.setattr(FlowClient, "_instance", None)
    client = FlowClient()
    sent = asyncio.Event()

    class Socket:
        async def send(self, message):
            sent.set()

    client.set_ws(Socket())
    request = asyncio.create_task(client._send("test", {}))
    await sent.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not client._pending
    client.clear_ws()
