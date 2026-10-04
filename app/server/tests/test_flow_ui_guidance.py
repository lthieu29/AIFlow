"""Page-state errors guide recovery and preserve the no-replay submit contract."""

import uuid

import pytest

from server.flow.rpc import FlowRPCError
from server.tests.test_production_flow_video import client as client
from server.tests.test_production_flow_video import create_project


@pytest.mark.parametrize("code,needle", [
    ("FLOW_UI_REFERENCES_PRESENT", "tham chiếu"),
    ("FLOW_UI_DRAFT_PRESENT", "bản nháp"),
    ("FLOW_HUMAN_VERIFICATION_REQUIRED", "xác minh"),
])
def test_preflight_page_state_reports_specific_recovery_without_submission(client, code, needle):
    project, scene = create_project(client)
    client.sdk.preflight_text_video.side_effect = FlowRPCError({
        "error": code, "requestSent": False, "phase": "session",
    })
    capability = client.get("/api/production/flow-capability").json()
    assert not capability["available"]
    assert needle in capability["message"] and "AIFlow chưa gửi" in capability["message"]
    route = f"/api/production/projects/{project}/generate-video"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    assert client.post(route, json=payload).status_code == 202
    operation = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert operation["status"] == "failed" and not operation["can_resume"]
    assert needle in operation["error"] and "AIFlow chưa gửi" in operation["error"]
    client.sdk.gen_text_video.assert_not_awaited()
    client.sdk.check_async.assert_not_awaited()


@pytest.mark.parametrize("code,needle", [
    ("FLOW_UI_REFERENCES_PRESENT", "tham chiếu"),
    ("FLOW_UI_DRAFT_PRESENT", "bản nháp"),
    ("FLOW_HUMAN_VERIFICATION_REQUIRED", "xác minh"),
    ("FLOW_UI_SILENT_VIDEO_SETTING_REQUIRED", "âm thanh"),
])
def test_presubmit_page_change_is_failed_and_same_request_never_replays(client, code, needle):
    project, scene = create_project(client)
    client.sdk.gen_text_video.side_effect = FlowRPCError({
        "error": code, "requestSent": False, "phase": "session",
    })
    route = f"/api/production/projects/{project}/generate-video"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    assert client.post(route, json=payload).status_code == 202
    operation = client.post(route, json=payload).json()
    assert operation["status"] == "failed" and not operation["can_resume"]
    assert needle in operation["error"] and "AIFlow chưa gửi" in operation["error"]
    client.sdk.gen_text_video.assert_awaited_once()
    client.sdk.check_async.assert_not_awaited()


def test_postclick_human_check_needs_attention_and_blocks_new_submit(client):
    project, scene = create_project(client)
    client.sdk.gen_text_video.side_effect = FlowRPCError({
        "error": "FLOW_HUMAN_VERIFICATION_REQUIRED", "requestSent": True, "phase": "session",
    })
    route = f"/api/production/projects/{project}/generate-video"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    assert client.post(route, json=payload).status_code == 202
    operation = client.post(route, json=payload).json()
    assert operation["status"] == "needs_attention" and not operation["can_resume"]
    assert "Hoàn tất xác minh" in operation["error"] and "không bấm Tạo lại" in operation["error"]
    assert "AIFlow chưa gửi" not in operation["error"]
    assert client.post(route, json={**payload, "request_id": str(uuid.uuid4())}).status_code == 409
    assert client.post(f"/api/production/video-operations/{payload['request_id']}/resume").status_code == 409
    client.sdk.gen_text_video.assert_awaited_once()
    client.sdk.check_async.assert_not_awaited()
