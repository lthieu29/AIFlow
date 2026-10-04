"""Current Flow RPC regressions against sanitized live request/response structure."""
import base64
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.flow.rpc import FlowRPC, FlowRPCError, video_request
from server.flow.sdk import FlowSDK, extract_video_operations

PROJECT = "12345678-1234-4234-8234-123456789abc"
MEDIA = "22345678-1234-4234-8234-123456789abc"
OPERATION = f"rpc:{PROJECT}:{MEDIA}"


def media_payload(state=3, url=None):
    metadata = [None] * 9
    metadata[8] = [state]
    generated_video = [None] * 9
    generated_video[8] = url
    return [MEDIA, PROJECT, "workflow", None, None, metadata, None, [generated_video]]


def make_client(*responses):
    client = MagicMock()
    client.get_token.return_value = None
    client.flow_rpc_request = AsyncMock(side_effect=[{"status": 200, "data": response} for response in responses])
    return client


def test_lite_request_matches_observed_proto_fields():
    body = video_request("A paper boat", "veo_3_1_t2v_lite", "16:9", PROJECT)
    item = body[0][0]
    assert item[:4] == [[None, None, [[["A paper boat"]]]], "veo_3_1_t2v_lite", 2, None]
    assert len(item[4]) == 6
    assert body[1][:6] == [None, 22, None, None, None, PROJECT]
    assert body[1][10] == ["", 1]
    assert body[2][1] == 2


async def test_sdk_text_video_submits_lite_without_a_bearer():
    client = make_client()
    client.flow_ui_request = AsyncMock(return_value={"status": 200, "data": {"projectId": PROJECT, "mediaId": MEDIA}})
    sdk = FlowSDK(client=client)
    assert await sdk.gen_text_video("Paper boat", project_id=PROJECT) == OPERATION
    client.flow_ui_request.assert_awaited_once_with(PROJECT, "Paper boat", "16:9", allow_silent_video=False, reference_mode="ingredients")
    client.flow_rpc_request.assert_not_called()


async def test_sdk_silent_video_choice_reaches_ui_and_websocket(monkeypatch):
    client = make_client()
    client.flow_ui_request = AsyncMock(return_value={"status": 200, "data": {"projectId": PROJECT, "mediaId": MEDIA}})
    assert await FlowSDK(client=client).gen_text_video("Paper boat", project_id=PROJECT, allow_silent_video=True) == OPERATION
    client.flow_ui_request.assert_awaited_once_with(PROJECT, "Paper boat", "16:9", allow_silent_video=True, reference_mode="ingredients")
    from server.flow.client import FlowClient
    proxy = FlowClient()
    send = AsyncMock(return_value={"status": 200})
    monkeypatch.setattr(proxy, "_send", send)
    await proxy.flow_ui_request(PROJECT, "Boat", allow_silent_video=True)
    assert send.call_args.args[0] == "flow_ui_request"
    assert send.call_args.args[1]["allow_silent_video"] is True
    await proxy.flow_ui_request(PROJECT, "Boat")
    assert send.call_args.args[1]["allow_silent_video"] is False
    assert send.call_args.args[1]["reference_mode"] == "ingredients"
    await proxy.flow_ui_request(PROJECT, "Boat", reference_mode="first_frame", reference={"name": "fixture"})
    assert send.call_args.args[1]["reference_mode"] == "first_frame"


async def test_sdk_invalid_silent_video_choice_never_submits():
    client = make_client()
    client.flow_ui_request = AsyncMock()
    with pytest.raises(ValueError, match="boolean"):
        await FlowSDK(client=client).gen_text_video("Boat", project_id=PROJECT, allow_silent_video="true")
    client.flow_ui_request.assert_not_called()


async def test_sdk_preflight_uses_ui_capability_and_never_submits_video():
    client = make_client()
    client.flow_ui_request = AsyncMock(return_value={
        "error": "FLOW_UI_REFERENCES_PRESENT", "requestSent": False, "phase": "session",
    })
    with pytest.raises(FlowRPCError) as caught:
        await FlowSDK(client=client).preflight_text_video(PROJECT)
    assert caught.value.code == "FLOW_UI_REFERENCES_PRESENT"
    assert caught.value.request_sent is False
    client.flow_ui_request.assert_awaited_once_with(PROJECT, preflight_only=True)
    client.flow_rpc_request.assert_not_called()


async def test_rpc_error_keeps_only_safe_diagnostics():
    client = make_client()
    client.flow_rpc_request.side_effect = None
    client.flow_rpc_request.return_value = {
        "error": "FLOW_RPC_STATUS_3: secret response", "status": 200, "rpcStatus": 3,
        "requestSent": True, "phase": "decode", "errorType": "SyntaxError",
    }
    with pytest.raises(FlowRPCError) as caught:
        await FlowRPC(client).request("jwpduf", [], PROJECT)
    assert str(caught.value) == "FLOW_RPC_STATUS_3"
    assert caught.value.rpc_status_code == 3
    assert caught.value.request_sent is True
    assert caught.value.phase == "decode"


async def test_sdk_rpc_poll_success_uses_get_media_url_and_existing_operation_parser():
    url = f"https://flow-content.example/video/{MEDIA}"
    client = make_client([None, 1030, [media_payload(3)]], media_payload(3, url))
    response = await FlowSDK(client=client).check_async(OPERATION)
    operation = extract_video_operations(response, requested=[OPERATION])[0]
    assert operation["done"] is True
    assert operation["error"] is None
    assert operation["media_entries"][0]["url"] == url
    assert client.flow_rpc_request.call_args_list[0].args[:2] == ("jwpduf", [None, None, [[MEDIA]]])
    assert client.flow_rpc_request.call_args_list[1].args[:2] == ("as29s", [MEDIA])


@pytest.mark.parametrize("state", [1, 2, 6])
async def test_pending_poll_does_not_request_a_download(state):
    client = make_client([None, 1030, [media_payload(state)]])
    response = await FlowRPC(client).check_async(OPERATION)
    operation = extract_video_operations(response, requested=[OPERATION])[0]
    assert not operation["done"]
    client.flow_rpc_request.assert_awaited_once()


async def test_missing_poll_media_remains_pending():
    client = make_client([None, 1030, None])
    response = await FlowRPC(client).check_async(OPERATION)
    operation = extract_video_operations(response, requested=[OPERATION])[0]
    assert not operation["done"]
    assert not operation["media_entries"]


@pytest.mark.parametrize("state", [4, 5, 7])
async def test_failed_or_canceled_poll_is_terminal(state):
    client = make_client([None, 1030, [media_payload(state)]])
    response = await FlowRPC(client).check_async(OPERATION)
    operation = extract_video_operations(response, requested=[OPERATION])[0]
    assert operation["done"] and operation["error"]
    assert not operation["media_entries"]


async def test_terminal_success_without_download_url_is_an_error():
    client = make_client([None, 1030, [media_payload(3)]], media_payload(3))
    with pytest.raises(RuntimeError, match="no downloadable URL"):
        await FlowRPC(client).check_async(OPERATION)


async def test_rpc_transport_error_is_preserved():
    client = make_client()
    client.flow_ui_request = AsyncMock(return_value={"error": "FLOW_RPC_SESSION_MISSING"})
    with pytest.raises(RuntimeError, match="SESSION_MISSING"):
        await FlowSDK(client=client).gen_text_video("Boat", project_id=PROJECT)


async def test_ui_submission_requires_bound_media_result_and_preserves_ambiguity():
    client = make_client()
    client.flow_ui_request = AsyncMock(return_value={"status": 200, "data": {"projectId": "other", "mediaId": MEDIA}})
    with pytest.raises(FlowRPCError) as caught:
        await FlowSDK(client=client).gen_text_video("Boat", project_id=PROJECT)
    assert caught.value.code == "FLOW_UI_SUBMISSION_UNCONFIRMED"
    assert caught.value.request_sent is True


@pytest.mark.parametrize("mode", ["ingredients", "first_frame"])
async def test_ui_reference_payload_is_bounded_png_with_stable_sha_name(tmp_path, mode):
    image = tmp_path / "actor.png"
    data = b"\x89PNG\r\n\x1a\nfixture"
    image.write_bytes(data)
    client = make_client()
    client.flow_ui_request = AsyncMock(return_value={"status": 200, "data": {"projectId": PROJECT, "mediaId": MEDIA}})
    assert await FlowSDK(client=client).gen_text_video("Boat", project_id=PROJECT, reference_image=image, reference_mode=mode) == OPERATION
    assert client.flow_ui_request.call_args.kwargs["reference_mode"] == mode
    reference = client.flow_ui_request.call_args.kwargs["reference"]
    assert base64.b64decode(reference["base64"]) == data
    assert reference["sha256"] == hashlib.sha256(data).hexdigest()
    assert reference["name"] == f"aiflow-reference-{reference['sha256']}.png"
    image.write_bytes(b"not PNG")
    client.flow_ui_request.reset_mock()
    with pytest.raises(ValueError, match="PNG"):
        await FlowSDK(client=client).gen_text_video("Boat", project_id=PROJECT, reference_image=image)
    client.flow_ui_request.assert_not_called()


@pytest.mark.parametrize("mode", ["frames", "first_frame", None])
async def test_invalid_or_missing_first_frame_reference_never_submits(mode):
    client = make_client()
    client.flow_ui_request = AsyncMock()
    with pytest.raises(ValueError, match="reference_mode"):
        await FlowSDK(client=client).gen_text_video("Boat", project_id=PROJECT, reference_mode=mode)
    with pytest.raises(ValueError, match="reference_mode"):
        await FlowRPC(client).submit_ui("Boat", "16:9", PROJECT, reference_mode=mode)
    client.flow_ui_request.assert_not_called()


async def test_i2v_rpc_upload_keeps_image_and_generation_in_same_project(tmp_path: Path):
    image = tmp_path / "start.png"
    image.write_bytes(b"image-bytes")
    client = make_client([["uploaded-image"]], [None, 1000, [], [media_payload(6)]])
    assert await FlowSDK(client=client).gen_video(image, "Boat", model="VEO3_LITE", project_id=PROJECT) == OPERATION
    upload, video = client.flow_rpc_request.call_args_list
    assert upload.args[0] == "maseQ" and upload.kwargs["captcha_action"] == "UPLOAD_IMAGE"
    assert upload.args[1][0][5] == PROJECT
    assert video.args[0] == "eb1hJf"
    assert video.args[1][0][0][4] == [None, "uploaded-image"]
    assert video.args[1][0][0][1] == "veo_3_1_i2v_lite"


@pytest.mark.parametrize("duration", [4, 6, 10])
async def test_unsupported_duration_is_rejected_before_spending_credits(duration):
    client = make_client()
    with pytest.raises(ValueError, match="8-second"):
        await FlowSDK(client=client).gen_text_video("Boat", duration=duration, project_id=PROJECT)
    client.flow_rpc_request.assert_not_called()
