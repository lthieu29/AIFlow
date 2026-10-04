"""Client selects an existing project through BE/extension, then guarded preflight."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.api.routes import production
from server.flow.client import FlowClient
from server.flow.rpc import FlowRPCError
from server.tests.test_production_flow_video import REMOTE_ID
from server.tests.test_production_flow_video import client as client


@pytest.fixture
def bridge(client, monkeypatch):
    proxy = SimpleNamespace(open_flow_project=AsyncMock(return_value={
        "status": 200, "data": {"projectId": REMOTE_ID},
    }))
    monkeypatch.setattr(production, "FlowClient", lambda: proxy)
    return proxy


@pytest.mark.parametrize("url", [
    f"https://flow.google.com/project/{REMOTE_ID}",
    f"https://flow.google.com:443/project/{REMOTE_ID.upper()}/",
    f"https://labs.google/fx/tools/flow/project/{REMOTE_ID}",
    f"https://labs.google/fx/vi/tools/flow/project/{REMOTE_ID}",
])
def test_open_project_normalizes_url_and_preflights_without_generation(client, bridge, url):
    response = client.post("/api/production/flow-project", json={"url": url})
    assert response.status_code == 200, response.text
    assert response.json()["available"]
    bridge.open_flow_project.assert_awaited_once_with(f"https://flow.google.com/project/{REMOTE_ID}")
    client.sdk.preflight_text_video.assert_awaited_once_with(REMOTE_ID)
    client.sdk.gen_text_video.assert_not_awaited()


@pytest.mark.parametrize("url", [
    "https://flow.google.com/", "https://flow.google.com/project/5",
    f"http://flow.google.com/project/{REMOTE_ID}",
    f"https://evil.example/project/{REMOTE_ID}",
    f"https://flow.google.com.evil.example/project/{REMOTE_ID}",
    f"https://user:password@flow.google.com/project/{REMOTE_ID}",
    f"https://flow.google.com:9443/project/{REMOTE_ID}",
    f"https://flow.google.com/project/{REMOTE_ID}?token=anything",
    f"https://flow.google.com/project/{REMOTE_ID}#fragment",
    f"https://flow.google.com/project/{REMOTE_ID}/other", "https://[",
])
def test_untrusted_project_url_never_reaches_extension(client, bridge, url):
    assert client.post("/api/production/flow-project", json={"url": url}).status_code == 422
    bridge.open_flow_project.assert_not_awaited()
    client.sdk.preflight_text_video.assert_not_awaited()


def test_guarded_project_open_does_not_bypass_flow_generation_policy(client, bridge):
    client.sdk.preflight_text_video.side_effect = FlowRPCError({
        "error": "FLOW_UI_GENERATION_REQUIRED", "requestSent": False, "phase": "captcha",
    })
    response = client.post("/api/production/flow-project", json={
        "url": f"https://flow.google.com/project/{REMOTE_ID}",
    })
    assert response.status_code == 200 and not response.json()["available"]
    assert response.json()["project_url"].endswith(REMOTE_ID)
    client.sdk.gen_text_video.assert_not_awaited()


def test_extension_failure_returns_recoverable_error_without_preflight(client, bridge):
    bridge.open_flow_project.return_value = {"error": "extension_disconnected"}
    assert client.post("/api/production/flow-project", json={
        "url": f"https://flow.google.com/project/{REMOTE_ID}",
    }).status_code == 503
    client.sdk.preflight_text_video.assert_not_awaited()


def test_wrong_tab_response_does_not_preflight_another_project(client, bridge):
    bridge.open_flow_project.return_value = {"status": 200, "data": {"projectId": "different"}}
    assert client.post("/api/production/flow-project", json={
        "url": f"https://flow.google.com/project/{REMOTE_ID}",
    }).status_code == 409
    client.sdk.preflight_text_video.assert_not_awaited()


async def test_flow_client_sends_project_selection_method(monkeypatch):
    proxy = FlowClient()
    send = AsyncMock(return_value={"status": 200})
    monkeypatch.setattr(proxy, "_send", send)
    url = f"https://flow.google.com/project/{REMOTE_ID}"
    assert await proxy.open_flow_project(url) == {"status": 200}
    send.assert_awaited_once_with("open_flow_project", {"url": url}, timeout=30.0)
