"""Offline approved-script -> one Flow submission -> unapproved production clip."""

import io
import json
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from server.api.routes import production, scripts
from server.config import Settings
from server.db.models.production import ProductionMedia
from server.db.models.studio import StudioOperation
from server.flow.rpc import FlowRPCError
from server.production import flow_video
from server.text.approval import CHECKLIST

REMOTE_ID = "12345678-1234-4234-8234-123456789abc"
OPERATION = f"rpc:{REMOTE_ID}:22345678-1234-4234-8234-123456789abc"


def success():
    return {"data": {"operations": [{"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "operation": {
        "name": OPERATION, "done": True, "metadata": {"video": {"mediaId": "22345678-1234-4234-8234-123456789abc",
        "fifeUrl": "https://example.com/video.mp4"}}}}]}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'flow.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    settings = Settings(_env_file=None, data_dir=tmp_path)
    app = FastAPI()
    app.include_router(production.router)
    app.include_router(scripts.router)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[production.get_session] = sessions
    app.dependency_overrides[production.get_settings] = lambda: settings
    monkeypatch.setattr(production, "get_engine", lambda _: engine)
    sdk = AsyncMock()
    sdk.resolve_project_id.return_value = REMOTE_ID
    sdk.gen_text_video.return_value = OPERATION
    sdk.check_async.return_value = success()
    monkeypatch.setattr(flow_video, "get_flow_sdk", lambda: sdk)
    monkeypatch.setattr("server.flow.sdk.get_flow_sdk", lambda: sdk)
    async def download(url, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"isolated fixture; decoding is stubbed")
        return path
    monkeypatch.setattr(flow_video, "download_video", download)
    monkeypatch.setattr(flow_video, "probe", lambda _: {"duration": 8, "streams": [{"codec_type": "video", "width": 1280, "height": 720}]})
    monkeypatch.setattr(flow_video, "POLL_INTERVAL", 0)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        browser.engine = engine
        browser.sdk = sdk
        yield browser
    flow_video.ACTIVE_VIDEOS.clear()
    engine.dispose()


def create_project(client, approved=True, scene_count=1):
    draft = client.post("/api/scripts/manual", json={"request_id": str(uuid.uuid4()), "language": "en", "content": {
        "title": "A paper boat", "continuity_notes": "Keep the red boat.", "scenes": [{"visual_prompt": "A red paper boat floats gently on a calm stream at sunrise.",
        "narration": "", "duration": 8, "location_hint": "outdoor"} for _ in range(scene_count)]}}).json()
    if not approved:
        return draft
    assert client.post(f"/api/scripts/{draft['id']}/approve", json={"checklist": sorted(CHECKLIST), "acknowledge_warnings": True}).status_code == 200
    project = client.post(f"/api/scripts/{draft['id']}/project", json={}).json()["id"]
    scene = client.get(f"/api/production/projects/{project}").json()["scenes"][0]["id"]
    return project, scene


def test_single_submission_download_and_unapproved_media(client):
    project, scene = create_project(client)
    prompt = client.get(f"/api/production/projects/{project}/scenes/{scene}/flow-prompt")
    assert prompt.status_code == 200 and prompt.json()["model"] == "Veo 3.1 Lite"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    route = f"/api/production/projects/{project}/generate-video"
    assert client.post(route, json=payload).status_code == 202
    detail = client.get(f"/api/production/projects/{project}").json()
    assert detail["video_operations"][0]["status"] == "succeeded"
    media = detail["media"][0]
    assert media["scene_id"] == scene and media["role"] == "visual" and media["mime"] == "video/mp4"
    assert not media["approved"] and media["width"] == 1280
    assert client.post(route, json=payload).status_code == 202
    client.sdk.gen_text_video.assert_awaited_once_with(prompt="A red paper boat floats gently on a calm stream at sunrise.",
        model="VEO3_LITE", duration=8, aspect="16:9", project_id=REMOTE_ID, allow_silent_video=False, reference_mode="ingredients")
    assert client.sdk.resolve_project_id.await_count == 1
    with Session(client.engine) as db:
        assert len(db.exec(select(StudioOperation)).all()) == 1
        assert len(db.exec(select(ProductionMedia)).all()) == 1
    payload["scene_id"] = scene + 999
    assert client.post(route, json=payload).status_code == 409


@pytest.mark.parametrize("enabled", [False, True])
def test_silent_video_option_is_frozen_forwarded_and_part_of_request_identity(client, enabled):
    project, scene = create_project(client)
    route = f"/api/production/projects/{project}/generate-video"
    identity = str(uuid.uuid4())
    payload = {"request_id": identity, "scene_id": scene, "allow_silent_video": enabled}
    assert client.post(route, json=payload).status_code == 202
    operation = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert operation["status"] == "succeeded" and operation["allow_silent_video"] is enabled
    assert client.sdk.gen_text_video.call_args.kwargs["allow_silent_video"] is enabled
    with Session(client.engine) as db:
        row = db.get(StudioOperation, identity)
        assert json.loads(row.input_json)["snapshot"]["allow_silent_video"] is enabled
        media = db.exec(select(ProductionMedia)).one()
        assert media.role == "visual" and not media.approved
        assert json.loads(media.review_json)["allow_silent_video"] is enabled
    assert client.post(route, json=payload).status_code == 202
    assert client.post(route, json={**payload, "allow_silent_video": not enabled}).status_code == 409
    client.sdk.gen_text_video.assert_awaited_once()


def test_legacy_video_request_defaults_to_false_and_cannot_be_changed(client):
    project, scene = create_project(client)
    route = f"/api/production/projects/{project}/generate-video"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    assert client.post(route, json=payload).status_code == 202
    with Session(client.engine) as db:
        row = db.get(StudioOperation, payload["request_id"])
        stored = json.loads(row.input_json)
        del stored["snapshot"]["allow_silent_video"]
        row.input_json = json.dumps(stored)
        db.add(row)
        db.commit()
    assert client.post(route, json=payload).json()["allow_silent_video"] is False
    assert client.post(route, json={**payload, "allow_silent_video": True}).status_code == 409
    client.sdk.gen_text_video.assert_awaited_once()


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_silent_video_requires_explicit_boolean_before_submission(client, invalid):
    project, scene = create_project(client)
    assert client.post(f"/api/production/projects/{project}/generate-video", json={
        "request_id": str(uuid.uuid4()), "scene_id": scene, "allow_silent_video": invalid}).status_code == 422
    client.sdk.gen_text_video.assert_not_called()


def video_reference(client, project, approve=True):
    data = io.BytesIO()
    Image.new("RGB", (128, 96), "olive").save(data, "PNG")
    response = client.post(f"/api/production/projects/{project}/media",
        data={"role": "reference", "provenance_note": "Scene 1, frame at 2 seconds; declared source."},
        files={"file": ("actor.png", data.getvalue(), "image/png")})
    assert response.status_code == 201
    media = response.json()
    if approve:
        assert client.post(f"/api/production/media/{media['id']}/review",
                           json={"checklist": ["identity", "clothing", "rights"]}).status_code == 200
    return media


@pytest.mark.parametrize("mode", ["ingredients", "first_frame"])
def test_video_reference_is_frozen_and_forwarded_after_explicit_approval(client, mode):
    project, scene = create_project(client)
    media = video_reference(client, project)
    identity = str(uuid.uuid4())
    payload = {"request_id": identity, "scene_id": scene, "reference_media_id": media["id"], "reference_mode": mode}
    route = f"/api/production/projects/{project}/generate-video"
    assert client.post(route, json=payload).status_code == 202
    assert client.sdk.gen_text_video.call_args.kwargs["reference_image"].is_file()
    assert client.sdk.gen_text_video.call_args.kwargs["reference_mode"] == mode
    operation = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert operation["status"] == "succeeded" and operation["reference_mode"] == mode
    with Session(client.engine) as db:
        row = db.get(StudioOperation, identity)
        reference = json.loads(row.input_json)["snapshot"]["reference"]
        assert json.loads(row.input_json)["snapshot"]["reference_mode"] == mode
        generated = db.get(ProductionMedia, json.loads(row.result_json)["media_id"])
        assert json.loads(generated.review_json)["reference_mode"] == mode
        assert reference["sha256"] == media["sha256"]
        assert reference["provenance"]["origin"]["kind"] == "client_uploaded_png"
        assert reference["provenance"]["origin"]["user_note"].startswith("Scene 1")
        assert json.loads(row.result_json)["media_id"]
    assert client.post(route, json=payload).status_code == 202
    assert client.post(route, json={**payload, "reference_mode": "ingredients" if mode == "first_frame" else "first_frame"}).status_code == 409
    payload["reference_media_id"] = None
    assert client.post(route, json=payload).status_code == 409
    client.sdk.gen_text_video.assert_awaited_once()


@pytest.mark.parametrize("mode", ["first_frame", "frames", None])
def test_first_frame_requires_valid_mode_and_approved_png_before_remote_call(client, mode):
    project, scene = create_project(client)
    response = client.post(f"/api/production/projects/{project}/generate-video", json={
        "request_id": str(uuid.uuid4()), "scene_id": scene, "reference_mode": mode})
    assert response.status_code == 422
    client.sdk.gen_text_video.assert_not_called()


def test_legacy_reference_mode_defaults_to_ingredients(client):
    project, scene = create_project(client)
    reference = video_reference(client, project)
    route = f"/api/production/projects/{project}/generate-video"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene, "reference_media_id": reference["id"]}
    assert client.post(route, json=payload).status_code == 202
    with Session(client.engine) as db:
        row = db.get(StudioOperation, payload["request_id"])
        stored = json.loads(row.input_json)
        del stored["snapshot"]["reference_mode"]
        row.input_json = json.dumps(stored)
        db.add(row)
        db.commit()
    assert client.post(route, json=payload).json()["reference_mode"] == "ingredients"
    assert client.post(route, json={**payload, "reference_mode": "first_frame"}).status_code == 409
    client.sdk.gen_text_video.assert_awaited_once()


@pytest.mark.parametrize("invalid", ["unapproved", "foreign", "changed", "archived"])
def test_invalid_reference_is_rejected_before_any_remote_generation(client, invalid):
    project, scene = create_project(client)
    other, _ = create_project(client) if invalid == "foreign" else (project, scene)
    media = video_reference(client, other, approve=invalid != "unapproved")
    with Session(client.engine) as db:
        row = db.get(ProductionMedia, media["id"])
        if invalid == "changed":
            from pathlib import Path
            Path(row.path).write_bytes(b"changed")
        elif invalid == "archived":
            row.role = "archived"
            db.add(row)
            db.commit()
    response = client.post(f"/api/production/projects/{project}/generate-video",
        json={"request_id": str(uuid.uuid4()), "scene_id": scene, "reference_media_id": media["id"]})
    assert response.status_code == 422
    client.sdk.gen_text_video.assert_not_called()


def test_video_reference_rejects_non_png_and_mislabelled_png(client):
    project, _ = create_project(client)
    route = f"/api/production/projects/{project}/media"
    data = io.BytesIO()
    Image.new("RGB", (128, 96), "olive").save(data, "JPEG")
    for name in ["actor.jpg", "actor.png"]:
        assert client.post(route, data={"role": "reference"}, files={"file": (name, data.getvalue())}).status_code == 422


def test_lost_poll_resumes_without_second_generation(client):
    project, scene = create_project(client)
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    client.sdk.check_async.side_effect = RuntimeError("sensitive URL must not leak")
    assert client.post(f"/api/production/projects/{project}/generate-video", json=payload).status_code == 202
    task = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert task["status"] == "needs_attention" and task["can_resume"]
    assert client.post(f"/api/production/video-operations/{payload['request_id']}/resolve", json={"checked_flow": True}).status_code == 409
    assert "sensitive" not in task["error"]
    with Session(client.engine) as db:
        stored = db.get(StudioOperation, payload["request_id"]).result_json
        assert '"stage": "poll"' in stored and '"type": "RuntimeError"' in stored
        assert "sensitive" not in stored and "https://" not in stored
    client.sdk.check_async.side_effect = None
    assert client.post(f"/api/production/video-operations/{payload['request_id']}/resume").status_code == 202
    detail = client.get(f"/api/production/projects/{project}").json()
    assert detail["video_operations"][0]["status"] == "succeeded"
    assert client.sdk.gen_text_video.await_count == 1 and client.sdk.check_async.await_count == 2
    assert client.post(f"/api/production/video-operations/{payload['request_id']}/resume").status_code == 409


def test_uncertain_submission_blocks_replay(client):
    project, scene = create_project(client)
    client.sdk.gen_text_video.side_effect = RuntimeError("lost response")
    route = f"/api/production/projects/{project}/generate-video"
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    assert client.post(route, json=payload).status_code == 202
    task = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert task["status"] == "needs_attention" and not task["can_resume"]
    assert client.post(route, json=payload).status_code == 202
    assert client.post(route, json={**payload, "request_id": str(uuid.uuid4())}).status_code == 409
    assert client.sdk.gen_text_video.await_count == 1


def test_pending_scene_cannot_submit_twice(client, monkeypatch):
    project, scene = create_project(client)
    monkeypatch.setattr(flow_video, "generate", AsyncMock())
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    route = f"/api/production/projects/{project}/generate-video"
    assert client.post(route, json=payload).status_code == 202
    assert client.post(route, json=payload).status_code == 202
    assert client.post(route, json={**payload, "request_id": str(uuid.uuid4())}).status_code == 409
    assert flow_video.generate.await_count == 1
    flow_video.ACTIVE_VIDEOS.clear()
    flow_video.reconcile_interrupted(client.engine)
    task = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert task["status"] == "interrupted" and client.sdk.gen_text_video.await_count == 0


def test_running_clip_blocks_other_scenes_in_same_project_without_auto_submission(client, monkeypatch):
    project, first = create_project(client, scene_count=2)
    second = client.get(f"/api/production/projects/{project}").json()["scenes"][1]["id"]
    monkeypatch.setattr(flow_video, "generate", AsyncMock())
    payload = {"request_id": str(uuid.uuid4()), "scene_id": first}
    route = f"/api/production/projects/{project}/generate-video"
    assert client.post(route, json=payload).status_code == 202
    assert client.post(route, json=payload).status_code == 202
    denied = client.post(route, json={"request_id": str(uuid.uuid4()), "scene_id": second})
    assert denied.status_code == 409 and "Chờ tác vụ" in denied.json()["detail"]
    assert flow_video.generate.await_count == 1
    with Session(client.engine) as db:
        row = db.get(StudioOperation, payload["request_id"])
        row.status = "succeeded"
        db.add(row)
        db.commit()
    assert client.post(route, json={"request_id": str(uuid.uuid4()), "scene_id": second}).status_code == 202
    assert flow_video.generate.await_count == 2


def test_busy_preflight_guidance_reports_wait_without_submission(client):
    project, scene = create_project(client)
    client.sdk.preflight_text_video.side_effect = FlowRPCError({"error": "FLOW_UI_BUSY", "requestSent": False, "phase": "session"})
    response = client.post(f"/api/production/projects/{project}/generate-video",
                           json={"request_id": str(uuid.uuid4()), "scene_id": scene})
    assert response.status_code == 202
    row = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert row["status"] == "failed" and not row["can_resume"]
    assert "Chờ thao tác hiện tại" in row["error"] and "AIFlow chưa gửi" in row["error"]
    client.sdk.gen_text_video.assert_not_awaited()


def test_tampered_script_scene_is_not_submitted(client):
    from server.db.models.scene import Scene
    project, scene = create_project(client)
    with Session(client.engine) as db:
        row = db.get(Scene, scene)
        row.prompt = "Different from approved script"
        db.add(row)
        db.commit()
    response = client.post(f"/api/production/projects/{project}/generate-video", json={"request_id": str(uuid.uuid4()), "scene_id": scene})
    assert response.status_code == 409
    assert client.get(f"/api/production/projects/{project}/scenes/{scene}/flow-prompt").status_code == 409
    assert client.sdk.gen_text_video.await_count == 0


def test_guarded_flow_preflight_requires_native_ui_without_submission(client):
    project, scene = create_project(client)
    client.sdk.preflight_text_video.side_effect = FlowRPCError({"error": "FLOW_UI_GENERATION_REQUIRED", "requestSent": False, "phase": "captcha"})
    capability = client.get("/api/production/flow-capability").json()
    assert not capability["available"] and capability["project_url"].endswith(REMOTE_ID)
    assert "kiểm tra Bridge" in capability["message"] and "AIFlow chưa gửi" in capability["message"]
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    assert client.post(f"/api/production/projects/{project}/generate-video", json=payload).status_code == 202
    operation = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert operation["status"] == "failed" and not operation["can_resume"]
    assert "AIFlow chưa gửi" in operation["error"]
    client.sdk.gen_text_video.assert_not_awaited()
    with Session(client.engine) as db:
        result = db.get(StudioOperation, payload["request_id"]).result_json
        assert "submission_started" not in result and "FLOW_UI_GENERATION_REQUIRED" in result


def test_uncertain_operation_requires_explicit_flow_check_to_close(client):
    project, scene = create_project(client)
    client.sdk.gen_text_video.side_effect = RuntimeError("response lost")
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    route = f"/api/production/projects/{project}/generate-video"
    assert client.post(route, json=payload).status_code == 202
    resolve = f"/api/production/video-operations/{payload['request_id']}/resolve"
    assert client.post(resolve, json={}).status_code == 409
    result = client.post(resolve, json={"checked_flow": True})
    assert result.status_code == 200 and result.json()["status"] == "resolved"
    assert client.post(resolve, json={"checked_flow": True}).status_code == 200
    assert client.post(route, json=payload).json()["status"] == "resolved"
    client.sdk.gen_text_video.assert_awaited_once()


def test_stale_downloaded_clip_can_be_closed_without_replaying_generation(client):
    from server.db.models.scene import Scene

    project, scene = create_project(client)
    async def stale_poll(name):
        with Session(client.engine) as db:
            row = db.get(Scene, scene)
            row.prompt = "Edited while waiting for Flow"
            db.add(row)
            db.commit()
        return success()
    client.sdk.check_async.side_effect = stale_poll
    payload = {"request_id": str(uuid.uuid4()), "scene_id": scene}
    route = f"/api/production/projects/{project}/generate-video"
    assert client.post(route, json=payload).status_code == 202
    task = client.get(f"/api/production/projects/{project}").json()["video_operations"][0]
    assert task["status"] == "needs_attention" and not task["can_resume"]
    resolve = f"/api/production/video-operations/{payload['request_id']}/resolve"
    assert client.post(resolve, json={}).status_code == 409
    response = client.post(resolve, json={"checked_flow": True})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    with Session(client.engine) as db:
        media = db.exec(select(ProductionMedia)).one()
        assert media.role == "archived" and not media.approved
    client.sdk.gen_text_video.assert_awaited_once()
