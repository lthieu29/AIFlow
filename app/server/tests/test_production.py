"""Real local encoding and isolated API tests, without model calls or user storage."""
import io
import json
import wave
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, SQLModel, create_engine

from server.api.routes import production
from server.config import Settings
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.production.media import probe


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    settings = Settings(data_dir=tmp_path)
    app = FastAPI()
    app.include_router(production.router)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[production.get_session] = sessions
    app.dependency_overrides[production.get_settings] = lambda: settings
    monkeypatch.setattr(production, "get_engine", lambda _: engine)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        browser.engine = engine
        browser.root = tmp_path
        yield browser
    engine.dispose()


def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (96, 128), "#36664a").save(buffer, "PNG")
    return buffer.getvalue()


def upload(client, project, role, scene=None):
    data = {"role": role}
    if scene:
        data["scene_id"] = str(scene)
    result = client.post(f"/api/production/projects/{project}/media", data=data, files={"file": ("image.png", image_bytes(), "image/png")})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def portrait(client):
    response = client.post("/api/production/portraits", json={"title": "Fixture only", "species": "cat", "identity": "Green eyes", "style": "watercolor", "channel": "pets"})
    assert response.status_code == 201
    return response.json()["id"]


def test_portrait_review_native_pixels_delivery(client):
    project = portrait(client)
    upload(client, project, "reference")
    media = upload(client, project, "portrait")
    assert client.post(f"/api/production/projects/{project}/render", json={}).status_code == 409
    assert client.post(f"/api/production/media/{media}/review", json={"checklist": ["likeness"]}).status_code == 422
    client.post(f"/api/production/media/{media}/review", json={"checklist": ["likeness", "anatomy", "crop", "artifacts"]})
    response = client.post(f"/api/production/projects/{project}/render", json={})
    assert response.status_code == 202, response.text
    output = response.json()["output_id"]
    detail = client.get(f"/api/production/outputs/{output}").json()
    assert detail["status"] == "awaiting_review", detail
    assert detail["manifest"]["delivery_pixels"] == {"width": 96, "height": 128}
    assert detail["manifest"]["upscaled"] is False
    assert client.get(f"/api/production/outputs/{output}/download").status_code == 409
    client.post(f"/api/production/outputs/{output}/review", json={"checklist": ["quality", "rights", "delivery"]})
    downloaded = client.get(f"/api/production/outputs/{output}/download")
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert {"portrait.png", "portrait.jpg", "preview.jpg", "manifest.json"}.issubset(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert str(client.root) not in json.dumps(manifest)
    (client.root / "production" / "outputs" / str(response.json()["job_id"]) / "portrait.png").write_bytes(b"tampered")
    assert client.get(f"/api/production/outputs/{output}/download").status_code == 409


def test_bad_media_and_reference_limit(client):
    project = portrait(client)
    for _ in range(3):
        upload(client, project, "reference")
    response = client.post(f"/api/production/projects/{project}/media", data={"role": "reference"}, files={"file": ("test.png", image_bytes())})
    assert response.status_code == 422
    response = client.post(f"/api/production/projects/{project}/media", data={"role": "portrait"}, files={"file": ("../../invalid.png", b"not an image")})
    assert response.status_code == 422
    assert len(client.get(f"/api/production/projects/{project}").json()["media"]) == 3


def test_changed_reference_requires_portrait_review_again(client):
    project = portrait(client)
    reference = upload(client, project, "reference")
    media = upload(client, project, "portrait")
    client.post(f"/api/production/media/{media}/review", json={"checklist": ["likeness", "anatomy", "crop", "artifacts"]})
    client.delete(f"/api/production/media/{reference}")
    upload(client, project, "reference")
    detail = client.get(f"/api/production/projects/{project}").json()
    assert next(m for m in detail["media"] if m["id"] == media)["approved"] is False
    assert client.post(f"/api/production/projects/{project}/render", json={}).status_code == 409


def test_editing_scene_invalidates_audio_and_visual_review(client):
    from server.api.routes.scenes import ScenePatchRequest, patch_scene
    from server.db.models.production import ProductionMedia
    with Session(client.engine) as db:
        project = Project(title="Edit fixture", short_id="edit", kind="video")
        db.add(project)
        db.flush()
        scene = Scene(project_id=project.id, order=0, prompt="A clock", narration="Before", audio_path="old.wav")
        db.add(scene)
        db.flush()
        media = ProductionMedia(project_id=project.id, scene_id=scene.id, role="visual", path="old.png", sha256="old", mime="image/png", width=96, height=128, approved=True)
        db.add(media)
        db.commit()
        scene_id, media_id = scene.id, media.id
        patch_scene(scene_id, ScenePatchRequest(narration="After"), db)
        assert db.get(Scene, scene_id).audio_path is None
        assert db.get(ProductionMedia, media_id).approved is False


def test_new_voice_task_invalidates_old_audio(client, monkeypatch):
    from server.api.routes import audio
    from server.audio.remote import AudioConnection
    from server.audio import queue
    monkeypatch.setattr(audio, "get_engine", lambda _: client.engine)
    monkeypatch.setattr(audio, "load_settings", lambda: Settings(data_dir=client.root))
    monkeypatch.setattr(queue, "connection", AudioConnection())
    with Session(client.engine) as db:
        project = Project(title="Voice fixture", short_id="voice", kind="video", status="ready")
        db.add(project)
        db.flush()
        scene = Scene(project_id=project.id, order=0, narration="Hello", audio_path="old.wav")
        db.add(scene)
        db.commit()
        project_id, scene_id = project.id, scene.id
    result = audio.create_task(audio.TaskInput(project_id=project_id, voice="af_bella"))
    assert result["status"] == "waiting_resource"
    with Session(client.engine) as db:
        assert db.get(Scene, scene_id).audio_path is None
        assert db.get(Project, project_id).voice_id == "af_bella"


@pytest.mark.parametrize("motion", [False, True])
def test_video_measured_audio_silence_and_bundle(client, motion):
    audio = client.root / "speech.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(b"\0\0" * 36000)
    with Session(client.engine) as session:
        project = Project(title="Synthetic video fixture", short_id="fixture", kind="video", aspect="16:9")
        session.add(project)
        session.flush()
        project_id = project.id
        scenes = [Scene(project_id=project.id, order=0, prompt="Green", narration="Test narration", duration=1, audio_path=str(audio)), Scene(project_id=project.id, order=1, prompt="Silence", narration="", duration=1)]
        session.add_all(scenes)
        session.commit()
        scene_ids = [s.id for s in scenes]
    for scene_id in scene_ids:
        media = upload(client, project_id, "visual", scene_id)
        assert client.post(f"/api/production/media/{media}/review", json={"checklist": ["content", "continuity", "framing"]}).status_code == 200
    result = client.post(f"/api/production/projects/{project_id}/render", json={"still_motion": motion})
    assert result.status_code == 202, result.text
    output = client.get(f"/api/production/outputs/{result.json()['output_id']}").json()
    assert output["status"] == "awaiting_review", output
    assert abs(output["manifest"]["actual_duration"] - 2.5) < .15
    video = client.root / "production" / "outputs" / str(result.json()["job_id"]) / "video.mp4"
    stream = next(s for s in probe(video)["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (1280, 720)
    assert "00:00:00,000 --> 00:00:01,500" in video.with_name("subtitles.srt").read_text()
    assert "path" not in output["manifest"]["scenes"][0]["audio"]


def test_legacy_requires_explicit_kind_and_mutation_header(client):
    with Session(client.engine) as session:
        project = Project(title="Old", short_id="old")
        session.add(project)
        session.commit()
        project_id = project.id
    assert client.post(f"/api/production/projects/{project_id}/render", json={}).status_code == 409
    assert client.put(f"/api/production/projects/{project_id}/kind", json={"kind": "video", "channel": "stories"}).status_code == 200
    assert client.get("/api/production/overview").json()["projects"][0]["channel"] == "stories"
    client.headers.pop("X-AIFlow-Client")
    assert client.post("/api/production/portraits", json={"title": "x", "species": "x", "identity": "x", "style": "x"}).status_code == 403


def test_restart_and_cancel_do_not_replay_render(client):
    from server.db.models.job import Job
    from server.db.models.production import ProductionOutput
    from server.production.render import reconcile_interrupted, render
    project_id = portrait(client)
    with Session(client.engine) as db:
        job = Job(project_id=project_id, type="production_render", status="running")
        db.add(job)
        db.flush()
        output = ProductionOutput(project_id=project_id, job_id=job.id, kind="portrait", status="rendering", manifest_json="{}", folder=str(client.root / "not-created"))
        db.add(output)
        db.commit()
        job_id, output_id = job.id, output.id
    reconcile_interrupted(client.engine)
    with Session(client.engine) as db:
        assert db.get(ProductionOutput, output_id).status == "interrupted"
        assert db.get(Job, job_id).status == "needs_attention"
        job = db.get(Job, job_id)
        job.status = "cancel_requested"
        db.add(job)
        db.commit()
    render(client.engine, client.root, output_id)
    assert not (client.root / "not-created").exists()
    with Session(client.engine) as db:
        assert db.get(Job, job_id).status == "cancelled"


def test_full_app_starts_without_gemini_or_local_models(tmp_path, monkeypatch):
    from server import config, main
    from server.db import session as database
    monkeypatch.delenv("AIFLOW_GEMINI_API_KEY", raising=False)
    settings = Settings(_env_file=None, data_dir=tmp_path, ws_port=0)
    assert settings.gemini is None
    engine = create_engine(f"sqlite:///{tmp_path / 'startup.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(config, "load_settings", lambda: settings)
    monkeypatch.setattr(main, "setup_logging", lambda *_: None)
    app = main.create_app()
    app.dependency_overrides[production.get_settings] = lambda: settings
    with TestClient(app) as browser:
        result = browser.get("/api/production/overview")
        assert result.status_code == 200, result.text
        assert result.json()["projects"] == []
    engine.dispose()
