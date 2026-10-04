"""Extension connection ownership and callback fallback regressions."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from server.flow import ws_server


class FakeSocket:
    remote_address = ("127.0.0.1", 1234)

    def __init__(self):
        self.messages = asyncio.Queue()
        self.handshake = asyncio.Event()

    async def send(self, message):
        self.handshake.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.messages.get()
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)


@pytest.fixture(autouse=True)
def reset_server_state(monkeypatch):
    monkeypatch.setattr(ws_server, "_extension_ws", None)
    monkeypatch.setattr(ws_server, "_callback_secret", None)


async def test_http_callback_fallback_resolves_pending_request():
    socket = FakeSocket()
    client = MagicMock()
    response = {"id": "request-1", "status": 200, "data": {"operations": []}}
    await socket.messages.put(response)
    await socket.messages.put(None)
    await ws_server._handle_connection(socket, client)
    client.resolve_callback.assert_called_once_with(response)
    client.clear_ws.assert_called_once()


async def test_old_socket_disconnect_does_not_clear_replacement_connection():
    client = MagicMock()
    old_socket, new_socket = FakeSocket(), FakeSocket()
    old_task = asyncio.create_task(ws_server._handle_connection(old_socket, client))
    await old_socket.handshake.wait()
    new_task = asyncio.create_task(ws_server._handle_connection(new_socket, client))
    await new_socket.handshake.wait()
    replacement_secret = ws_server.get_callback_secret()
    await old_socket.messages.put(None)
    await old_task
    assert ws_server._extension_ws is new_socket
    assert ws_server.get_callback_secret() == replacement_secret
    client.clear_ws.assert_not_called()
    client.set_connected.assert_not_called()
    await new_socket.messages.put(None)
    await new_task
    client.clear_ws.assert_called_once()
    assert ws_server.get_callback_secret() is None
