"""A project cannot replace audio while a resumable task still owns it."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from server.api.routes import audio
from server.audio import queue
from server.audio.remote import AudioConnection
from server.config import Settings
from server.db.models.audio_task import AudioTask
from server.db.models.project import Project
from server.db.models.scene import Scene


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'audio.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(audio, "get_engine", lambda _: engine)
    monkeypatch.setattr(audio, "load_settings", lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr(queue, "connection", AudioConnection())
    with Session(engine) as db:
        project = Project(title="Audio ownership", short_id="ownership", status="ready")
        db.add(project)
        db.flush()
        db.add(Scene(project_id=project.id, order=0, narration="Hello", audio_path="preserved.wav"))
        db.commit()
        project_id = project.id
    app = FastAPI()
    app.include_router(audio.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        browser.engine, browser.project_id = engine, project_id
        yield browser
    engine.dispose()


@pytest.mark.parametrize("status", ["queued", "running", "waiting_resource", "needs_attention", "cancel_requested"])
def test_resumable_audio_blocks_replacement_without_mutating_saved_inputs(client, status):
    with Session(client.engine) as db:
        db.add(AudioTask(project_id=client.project_id, title="Existing", snapshot_json="[]", status=status))
        db.commit()
        project = db.get(Project, client.project_id)
        before = project.model_dump()
        task_before = db.exec(select(AudioTask)).one().model_dump()
    result = client.post("/api/audio/tasks", json={"project_id": client.project_id, "voice": "af_bella", "speed": 0.8})
    assert result.status_code == 409, result.text
    with Session(client.engine) as db:
        assert db.get(Project, client.project_id).model_dump() == before
        assert db.exec(select(Scene)).one().audio_path == "preserved.wav"
        assert db.exec(select(AudioTask)).one().model_dump() == task_before


@pytest.mark.parametrize("status", ["succeeded", "cancelled"])
def test_terminal_audio_allows_explicit_new_task(client, status):
    with Session(client.engine) as db:
        db.add(AudioTask(project_id=client.project_id, title="Previous", snapshot_json="[]", status=status))
        db.commit()
    result = client.post("/api/audio/tasks", json={"project_id": client.project_id, "voice": "af_bella"})
    assert result.status_code == 202, result.text
    with Session(client.engine) as db:
        assert len(db.exec(select(AudioTask)).all()) == 2
        assert db.get(Project, client.project_id).voice_id == "af_bella"
        assert db.exec(select(Scene)).one().audio_path is None


def test_concurrent_project_audio_requests_create_only_one_owner(client):
    start = Barrier(2)
    def submit(speed):
        start.wait(timeout=5)
        return client.post("/api/audio/tasks", json={"project_id": client.project_id, "speed": speed}).status_code
    with ThreadPoolExecutor(max_workers=2) as workers:
        codes = list(workers.map(submit, [0.8, 1.2]))
    assert sorted(codes) == [202, 409]
    with Session(client.engine) as db:
        assert len(db.exec(select(AudioTask)).all()) == 1
