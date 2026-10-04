"""Remote Flow UUID resolution must not use local database IDs or random UUIDs."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.flow.sdk import FlowSDK

PROJECT_ID = "dafc6eda-c82e-4864-ba19-2140a20e2f9e"


async def test_explicit_remote_uuid_does_not_contact_extension():
    client = MagicMock()
    sdk = FlowSDK(client=client)
    assert await sdk.resolve_project_id(PROJECT_ID) == PROJECT_ID
    client.get_flow_project.assert_not_called()


async def test_missing_remote_uuid_reads_open_flow_project_tab():
    client = MagicMock()
    client.get_flow_project = AsyncMock(return_value={"status": 200, "data": {"projectId": PROJECT_ID}})
    assert await FlowSDK(client=client).resolve_project_id() == PROJECT_ID
    client.get_flow_project.assert_awaited_once()


@pytest.mark.parametrize("value", ["1", "local-db-project", "not-a-uuid"])
async def test_local_project_identifiers_are_rejected(value):
    with pytest.raises(RuntimeError, match="remote project UUID is required"):
        await FlowSDK(client=MagicMock()).resolve_project_id(value)


async def test_landing_page_response_cannot_create_fake_remote_project():
    client = MagicMock()
    client.get_flow_project = AsyncMock(return_value={"status": 200, "data": {}})
    with pytest.raises(RuntimeError, match="remote project UUID is required"):
        await FlowSDK(client=client).resolve_project_id()


async def test_extension_unavailable_error_is_preserved():
    client = MagicMock()
    client.get_flow_project = AsyncMock(return_value={"error": "extension_disconnected"})
    with pytest.raises(RuntimeError, match="extension_disconnected"):
        await FlowSDK(client=client).resolve_project_id()
