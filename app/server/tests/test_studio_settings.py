"""Settings/series/library roundtrips with isolated SQLite and no external providers."""

import base64
import io
import json
import uuid

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine, select

from server.api.routes import production, scripts, studio
from server.config import Settings
from server.db.models.asset import Asset
from server.db.models.production import ProductionMedia
from server.db.models.project import Project
from server.db.models.studio import SeriesEpisode, StudioOperation
from server.production.media import sha256
from server.text.approval import CHECKLIST


def rid():
    return str(uuid.uuid4())


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'studio.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    settings = Settings(_env_file=None, data_dir=tmp_path)
    app = FastAPI()
    app.include_router(studio.router)
    app.include_router(scripts.router)
    app.include_router(production.router)
    def sessions():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[studio.get_session] = sessions
    app.dependency_overrides[studio.get_settings] = lambda: settings
    monkeypatch.setattr(studio, "IMAGE_CONFIG", {"key": "", "model": "", "billing_confirmed": False})
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        browser.engine = engine
        browser.root = tmp_path
        yield browser
    engine.dispose()


def series(client, **values):
    response = client.post("/api/studio/series", json={"name": "The boat", "bible": "Keep the red boat.", "voice": "voice-a", "speed": 1.2, "model_revision": "test-revision", **values})
    assert response.status_code == 200, response.text
    return response.json()


def episode_payload(series):
    return {"request_id": rid(), "series_id": series["id"], "series_version": series["version"], "content": {
        "title": "The first journey", "idea": "A boat travels downstream.", "language": "en",
        "series_bible": "Ignored user override", "target_seconds": 8}}


@pytest.mark.parametrize("path,body", [
    ("/api/studio/series", {"name": "   "}),
    ("/api/studio/series", {"name": "Boat", "version": 0}),
    ("/api/studio/library", {"name": "   ", "kind": "character"}),
    ("/api/studio/library", {"name": "Boat", "kind": "reference", "media_id": 0}),
    ("/api/studio/library", {"name": "Boat", "kind": "reference", "media_id": -1}),
])
def test_invalid_settings_do_not_create_rows(client, path, body):
    assert client.post(path, json=body).status_code == 422
    assert client.get("/api/studio/series").json() == []
    assert client.get("/api/studio/library").json() == []


def test_series_version_conflict_and_episode_retry_keeps_frozen_snapshot(client):
    first = series(client, language="vi")
    payload = episode_payload(first)
    created = client.post("/api/scripts/brief", json=payload)
    assert created.status_code == 201, created.text
    brief = created.json()
    assert brief["content"]["language"] == "vi" and brief["content"]["series_bible"] == first["bible"]
    updated = client.put(f"/api/studio/series/{first['id']}", json={**first, "bible": "A blue boat now.", "language": "en"})
    assert updated.status_code == 200 and updated.json()["version"] == 2
    assert client.put(f"/api/studio/series/{first['id']}", json=first).status_code == 409
    retry = client.post("/api/scripts/brief", json=payload)
    assert retry.status_code == 201 and retry.json()["id"] == brief["id"]
    collision = {**payload, "content": {**payload["content"], "idea": "Different idea"}}
    assert client.post("/api/scripts/brief", json=collision).status_code == 409
    assert client.post("/api/scripts/brief", json={**payload, "request_id": rid()}).status_code == 409
    with Session(client.engine) as db:
        snapshots = db.exec(select(SeriesEpisode)).all()
        assert len(snapshots) == 1 and json.loads(snapshots[0].snapshot_json)["bible"] == first["bible"]


def test_series_episode_approval_project_and_canon_roundtrip(client):
    original = series(client)
    root = client.post("/api/scripts/brief", json=episode_payload(original)).json()
    manuscript = {"title": "The first journey", "continuity_notes": "Keep the red boat.", "scenes": [{
        "visual_prompt": "A red paper boat floats gently through a quiet forest stream at sunrise.",
        "narration": "", "duration": 8, "location_hint": "outdoor"}]}
    draft = client.post("/api/scripts/import", json={"request_id": rid(), "parent_id": root["id"], "content": manuscript}).json()
    canon = f"/api/studio/series/{original['id']}/canon"
    assert client.post(canon, json={"revision_id": draft["id"], "version": 1, "bible": "The boat reached the bridge."}).status_code == 409
    assert client.post(f"/api/scripts/{draft['id']}/approve", json={"checklist": sorted(CHECKLIST), "acknowledge_warnings": True}).status_code == 200
    result = client.post(f"/api/scripts/{draft['id']}/project", json={"aspect": "9:16"})
    assert result.status_code == 200
    detail = client.get(f"/api/scripts/{draft['id']}").json()
    assert detail["project_aspect"] == "9:16"
    with Session(client.engine) as db:
        project = db.get(Project, result.json()["id"])
        assert project.voice_id == original["voice"]
        snapshot = json.loads(project.production_brief)["series"]
        assert snapshot["speed"] == 1.2 and snapshot["model_revision"] == "test-revision"
    changed = client.post(canon, json={"revision_id": draft["id"], "version": 1, "bible": "The boat reached the bridge."})
    assert changed.status_code == 200 and changed.json()["version"] == 2
    assert client.post(canon, json={"revision_id": draft["id"], "version": 1, "bible": "Stale update"}).status_code == 409
    second = series(client, name="Another series")
    assert client.post(f"/api/studio/series/{second['id']}/canon", json={"revision_id": draft["id"], "version": 1, "bible": "Wrong series"}).status_code == 422


def library_fixture(client):
    source = client.root / "reference.png"
    source.write_bytes(image_bytes())
    with Session(client.engine) as db:
        project = Project(short_id="test-lib", title="Fixture", kind="video", adapter="storyboard_manual", skill="cinematic-thriller")
        db.add(project)
        db.flush()
        media = ProductionMedia(project_id=project.id, role="reference", path=str(source), sha256=sha256(source), mime="image/png", width=64, height=64)
        db.add(media)
        db.commit()
        project_id, media_id = project.id, media.id
    item = client.post("/api/studio/library", json={"name": " Red boat ", "kind": "reference", "media_id": media_id}).json()
    return project_id, item["id"], source


def test_library_apply_copies_once_and_preserves_independent_file(client):
    project, item, source = library_fixture(client)
    path = f"/api/studio/library/{item}/apply"
    assert client.post(path, json={"project_id": project}).status_code == 200
    assert client.post(path, json={"project_id": project}).status_code == 200
    with Session(client.engine) as db:
        assets = db.exec(select(Asset)).all()
        assert len(assets) == 1 and assets[0].name == "Red boat"
        from pathlib import Path
        copy = Path(assets[0].file_path)
        assert copy != source and copy.read_bytes() == source.read_bytes()
        assert len(json.loads(db.get(Project, project).production_brief)["library"]) == 1


def test_missing_library_source_is_actionable_and_does_not_change_project(client):
    project, item, source = library_fixture(client)
    source.unlink()
    response = client.post(f"/api/studio/library/{item}/apply", json={"project_id": project})
    assert response.status_code == 409 and "Nhập lại ảnh" in response.json()["detail"]
    with Session(client.engine) as db:
        assert json.loads(db.get(Project, project).production_brief) == {}
        assert db.exec(select(Asset)).all() == []


def test_image_connection_requires_model_and_disconnect_has_no_generation(client):
    assert client.put("/api/studio/connections/image", json={"key": "test-key", "billing_confirmed": True}).status_code == 422
    assert client.put("/api/studio/connections/image", json={"key": "test-key", "model": "bad/model", "billing_confirmed": True}).status_code == 422
    response = client.put("/api/studio/connections/image", json={"key": "test-key", "model": " gemini-test-image ", "billing_confirmed": True})
    assert response.status_code == 200 and response.json()["configured"]
    assert client.put("/api/studio/connections/image", json={"key": ""}).json()["configured"] is False


def test_image_receipt_remains_idempotent_after_disconnect(client, monkeypatch):
    project = client.post("/api/production/portraits", json={"title": "Fixture", "species": "cat", "identity": "Green eyes", "style": "watercolor"}).json()["id"]
    upload = client.post(f"/api/production/projects/{project}/media", data={"role": "reference"}, files={"file": ("ref.png", image_bytes(), "image/png")})
    assert upload.status_code == 201
    client.put("/api/studio/connections/image", json={"key": "test-key", "model": "gemini-test-image", "billing_confirmed": True})
    calls = []
    real_client = httpx.Client
    def response(request):
        calls.append(request)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(image_bytes()).decode()}}]}}]})
    monkeypatch.setattr(studio.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(response), **kwargs))
    payload = {"request_id": rid()}
    route = f"/api/studio/projects/{project}/generate-image"
    first = client.post(route, json=payload)
    assert first.status_code == 200 and first.json()["status"] == "succeeded"
    client.put("/api/studio/connections/image", json={"key": ""})
    repeated = client.post(route, json=payload)
    assert repeated.status_code == 200 and repeated.json()["request_id"] == first.json()["request_id"]
    assert client.post(route, json={**payload, "prompt": "Different input"}).status_code == 409
    assert len(calls) == 1
    with Session(client.engine) as db:
        assert len(db.exec(select(StudioOperation)).all()) == 1
