"""Offline worker contracts, durable cache/queue and migration regression coverage."""
import hashlib
import importlib.util
import io
import sqlite3
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from server.audio import queue, remote
from server.audio.bootstrap import backup_before_audio_upgrade
from server.config import Settings
from server.db import session as database
from server.db.models.audio_task import AudioTask
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.production.transcribe import validate_segments


def wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 2400)
    return buffer.getvalue()


@pytest.mark.parametrize("url", ["http://x.trycloudflare.com", "https://localhost", "https://x.trycloudflare.com/path", "https://user:pass@x.trycloudflare.com", "https://x.trycloudflare.com?token=x"])
def test_worker_url_rejects_non_root_or_private(url):
    with pytest.raises(remote.AudioUnavailable):
        remote.validate_url(url)


@pytest.mark.parametrize("url", ["https://x.trycloudflare.com:bad", "https://x.trycloudflare.com:99999", "https://["])
def test_malformed_worker_url_is_a_user_error(url):
    with pytest.raises(remote.AudioUnavailable) as caught:
        remote.validate_url(url)
    assert caught.value.state == "invalid_url"


def test_token_never_persisted_and_generation_changes(tmp_path):
    c = remote.AudioConnection()
    c.save({"url": "https://example.trycloudflare.com", "health": {}, "voices": []}, "private-token", tmp_path)
    assert "private-token" not in (tmp_path / "audio-connection.json").read_text()
    generation = c.snapshot()[2]
    c.disconnect()
    assert c.generation > generation
    with pytest.raises(remote.AudioUnavailable):
        c.snapshot()


def test_verified_cache_and_canonical_keys(tmp_path):
    first = remote.make_segments("Hello world.", "af_heart", "en", 1, "revision")
    assert first == remote.make_segments("Hello world.", "af_heart", "en", 1.0, "revision")
    assert first != remote.make_segments("Hello world.", "af_bella", "en", 1, "revision")
    key, content = first[0]["key"], wav()
    with pytest.raises(remote.AudioUnavailable):
        remote.store_audio(tmp_path, key, content, "invalid")
    remote.store_audio(tmp_path, key, content, hashlib.sha256(content).hexdigest())
    assert remote.cached(tmp_path, key)
    remote.cache_path(tmp_path, key).write_bytes(b"bad")
    assert not remote.cached(tmp_path, key)


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(queue, "get_engine", lambda _: engine)
    c = remote.AudioConnection()
    c.health = {"model_revision": "rev", "languages": ["en"]}
    c.voices = [{"id": "af_heart"}]
    monkeypatch.setattr(queue, "connection", c)
    q = queue.AudioQueue(Settings(data_dir=tmp_path))
    yield q, c
    if q.lock_file:
        q.lock_file.close()
    engine.dispose()


def test_cancelled_queue_never_attaches_audio(isolated_queue):
    q, _ = isolated_queue
    with Session(q.engine) as db:
        project = Project(title="test", short_id="test")
        db.add(project)
        db.flush()
        scene = Scene(project_id=project.id, order=0, narration="Hello")
        db.add(scene)
        db.commit()
        task = queue.enqueue(db, q.settings, project=project)
        task.status = "cancel_requested"
        db.add(task)
        db.commit()
        task_id, scene_id = task.id, scene.id
    q.tick()
    with Session(q.engine) as db:
        assert db.get(AudioTask, task_id).status == "cancelled"
        assert db.get(Scene, scene_id).audio_path is None


def test_series_audio_snapshot_freezes_speed_and_model_revision(isolated_queue):
    import json
    q, _ = isolated_queue
    with Session(q.engine) as db:
        project = Project(title="Series", short_id="series", production_brief=json.dumps({
            "series": {"voice": "af_heart", "language": "en", "speed": 0.8, "model_revision": "other-model"},
        }))
        db.add(project)
        db.flush()
        db.add(Scene(project_id=project.id, order=0, narration="Hello"))
        db.commit()
        task = queue.enqueue(db, q.settings, project=project, speed=1.5)
        assert task.speed == 0.8
        assert json.loads(task.snapshot_json)[0]["locked_model"] == "other-model"
        assert task.status == "waiting_resource"
        assert task.segments_json == "[]"


def test_cancellation_wins_before_finish_claim(isolated_queue):
    q, _ = isolated_queue
    with Session(q.engine) as db:
        task = queue.enqueue(db, q.settings, text="Test")
        task.status = "queued"
        db.add(task)
        db.commit()
        task_id = task.id
        with Session(q.engine) as other:
            row = other.get(AudioTask, task_id)
            row.status = "cancel_requested"
            other.add(row)
            other.commit()
        q.finish(db, task, [])
        assert task.status == "cancel_requested"
        assert not (q.settings.data_dir / "audio" / "tasks" / f"{task_id}.wav").exists()


def test_cancel_with_lost_worker_session_finishes_locally_and_unblocks_queue(isolated_queue):
    q, _ = isolated_queue
    with Session(q.engine) as db:
        first = queue.enqueue(db, q.settings, text="First")
        first.status, first.active_key = "cancel_requested", "a" * 64
        db.add(first)
        db.commit()
        first_id = first.id
        second = queue.enqueue(db, q.settings, text="Second")
        second.status = "queued"
        db.add(second)
        db.commit()
        second_id = second.id
    q.tick()
    with Session(q.engine) as db:
        cancelled = db.get(AudioTask, first_id)
        assert cancelled.status == "cancelled"
        assert "Colab" in cancelled.error
    q.tick()
    with Session(q.engine) as db:
        assert db.get(AudioTask, second_id).status == "waiting_resource"


@pytest.mark.parametrize("failure", [remote.AudioUnavailable("offline"), RuntimeError("bad reply")])
def test_cancellation_wins_when_inflight_request_fails(isolated_queue, monkeypatch, failure):
    q, connection = isolated_queue
    connection.token, connection.url = "t" * 32, "https://test.trycloudflare.com"
    with Session(q.engine) as db:
        task = queue.enqueue(db, q.settings, text="Test")
        task_id = task.id

    def failing_request(*args, **kwargs):
        with Session(q.engine) as other:
            task = other.get(AudioTask, task_id)
            task.status = "cancel_requested"
            other.add(task)
            other.commit()
        raise failure

    monkeypatch.setattr(queue, "request", failing_request)
    q.tick()
    with Session(q.engine) as db:
        assert db.get(AudioTask, task_id).status == "cancel_requested"


@pytest.mark.parametrize("results", [None, [], [None], "invalid"])
async def test_invalid_batch_manifest_cannot_enqueue_new_audio(isolated_queue, monkeypatch, results):
    import json
    import zipfile

    from fastapi import HTTPException, UploadFile

    from server.api.routes import audio
    q, _ = isolated_queue
    monkeypatch.setattr(audio, "get_engine", lambda _: q.engine)
    monkeypatch.setattr(audio, "load_settings", lambda: q.settings)
    with Session(q.engine) as db:
        task = AudioTask(title="Batch test", snapshot_json="[]", segments_json=json.dumps([{"key": "a" * 64}]), status="waiting_resource")
        db.add(task)
        db.commit()
        task_id = task.id
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"results": results}))
    buffer.seek(0)
    with pytest.raises(HTTPException) as caught:
        await audio.import_batch(task_id, UploadFile(file=buffer, filename="results.zip"))
    assert caught.value.status_code == 422
    with Session(q.engine) as db:
        assert db.get(AudioTask, task_id).status == "waiting_resource"


async def test_batch_import_requires_exported_model_and_segments(isolated_queue, monkeypatch):
    from fastapi import HTTPException, UploadFile

    from server.api.routes import audio
    q, _ = isolated_queue
    monkeypatch.setattr(audio, "get_engine", lambda _: q.engine)
    monkeypatch.setattr(audio, "load_settings", lambda: q.settings)
    with Session(q.engine) as db:
        task = AudioTask(title="Batch test", snapshot_json="[]", status="waiting_resource")
        db.add(task)
        db.commit()
        task_id = task.id
    with pytest.raises(HTTPException) as caught:
        await audio.import_batch(task_id, UploadFile(file=io.BytesIO(b"not a zip")))
    assert caught.value.status_code == 409


def test_queue_restart_waits_and_stale_content_blocks(isolated_queue):
    q, _ = isolated_queue
    with Session(q.engine) as db:
        project = Project(title="test", short_id="test")
        db.add(project)
        db.flush()
        scene = Scene(project_id=project.id, order=0, narration="First")
        db.add(scene)
        db.commit()
        task = queue.enqueue(db, q.settings, project=project)
        task.status = "running"
        db.add(task)
        db.commit()
        task_id, scene_id = task.id, scene.id
    q.acquire()
    with Session(q.engine) as db:
        task = db.get(AudioTask, task_id)
        assert task.status == "waiting_resource"
        scene = db.get(Scene, scene_id)
        scene.narration = "Changed"
        db.add(scene)
        task.status = "queued"
        db.add(task)
        db.commit()
    q.tick()
    with Session(q.engine) as db:
        assert db.get(AudioTask, task_id).status == "needs_attention"


def test_additive_bootstrap_backs_up_and_keeps_legacy(tmp_path, monkeypatch):
    path = tmp_path / "projects.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE project (id INTEGER PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO project VALUES (1, 'Keep this')")
    settings = Settings(data_dir=tmp_path)
    backup_before_audio_upgrade(settings)
    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(database, "_engine", engine)
    database.bootstrap_schema(settings)
    database.bootstrap_schema(settings)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT title, kind, production_brief FROM project").fetchone() == ("Keep this", "legacy", "{}")
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("SELECT title FROM project").fetchone()[0] == "Keep this"
    engine.dispose()


@pytest.fixture
def worker(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("test_colab_worker", Path(__file__).resolve().parents[2] / "colab" / "audio_worker" / "app.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "TOKEN", "t" * 32)
    monkeypatch.setattr(module, "PIPELINE", object())
    monkeypatch.setattr(module, "REVISION", "rev")
    queued = []
    monkeypatch.setattr(module, "EXECUTOR", SimpleNamespace(submit=lambda fn, key: queued.append((fn, key))))
    with TestClient(module.app, headers={"Authorization": "Bearer " + "t" * 32}) as client:
        yield module, client, queued


def test_worker_idempotent_restart_and_auth(worker):
    module, client, queued = worker
    body = {"text": "Hello", "voice_id": "af_heart", "language": "en", "speed": 1.0, "model_revision": "rev", "output_format": "wav"}
    key = module.digest(body)
    for _ in range(2):
        assert client.post("/v1/tts/jobs", json=body, headers={"Idempotency-Key": key}).status_code == 202
    assert len(queued) == 1
    assert client.post("/v1/tts/jobs", json=body, headers={"Idempotency-Key": "bad"}).status_code == 409
    module.ACTIVE.clear()
    assert client.get(f"/v1/jobs/{key}").json()["status"] == "interrupted"
    assert client.get("/v1/health", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_worker_stt_shared_queue_and_result(worker, monkeypatch):
    module, client, queued = worker
    monkeypatch.setattr(module, "STT_REVISION", "stt-rev")
    segment = SimpleNamespace(start=0, end=.1, text="Hello", words=[SimpleNamespace(start=0, end=.1, word="Hello")])
    monkeypatch.setattr(module, "STT_MODEL", SimpleNamespace(transcribe=lambda *args, **kwargs: ([segment], SimpleNamespace(language="en"))))
    raw = wav()
    key = module.digest({"type": "stt", "audio_sha256": hashlib.sha256(raw).hexdigest(), "language": "en", "model_revision": "stt-rev"})
    for _ in range(2):
        response = client.post("/v1/stt/jobs", data={"language": "en", "model_revision": "stt-rev"}, files={"file": ("audio.wav", raw)}, headers={"Idempotency-Key": key})
        assert response.status_code == 202, response.text
    assert len(queued) == 1
    queued[0][0](key)
    response = client.get(f"/v1/jobs/{key}/result")
    assert response.status_code == 200
    assert response.json()["segments"][0]["text"] == "Hello"
    assert response.headers["X-Checksum-SHA256"] == hashlib.sha256(response.content).hexdigest()


def test_worker_stt_rejects_truncated_pcm_before_enqueue(worker, monkeypatch):
    module, client, queued = worker
    monkeypatch.setattr(module, "STT_MODEL", object())
    monkeypatch.setattr(module, "STT_REVISION", "stt-rev")
    raw = wav()[:-4]
    key = module.digest({"type": "stt", "audio_sha256": hashlib.sha256(raw).hexdigest(),
                         "language": "en", "model_revision": "stt-rev"})
    response = client.post("/v1/stt/jobs", data={"language": "en", "model_revision": "stt-rev"},
                           files={"file": ("audio.wav", raw)}, headers={"Idempotency-Key": key})
    assert response.status_code == 422
    assert not queued and not module.ACTIVE


def test_worker_stt_rebuilds_missing_persisted_result(worker, monkeypatch):
    module, client, queued = worker
    monkeypatch.setattr(module, "STT_MODEL", object())
    monkeypatch.setattr(module, "STT_REVISION", "stt-rev")
    raw = wav()
    payload = {"type": "stt", "audio_sha256": hashlib.sha256(raw).hexdigest(),
               "language": "en", "model_revision": "stt-rev"}
    key = module.digest(payload)
    module.save_job({"job_id": key, "input": payload, "type": "stt", "status": "succeeded"})
    response = client.post("/v1/stt/jobs", data={"language": "en", "model_revision": "stt-rev"},
                           files={"file": ("audio.wav", raw)}, headers={"Idempotency-Key": key})
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert len(queued) == 1


@pytest.mark.parametrize("segments", [[], [{"start": 2, "end": 1, "text": "bad"}], [{"start": 0, "end": float("nan"), "text": "bad"}]])
def test_invalid_stt_timestamps(segments):
    with pytest.raises(ValueError):
        validate_segments({"segments": segments})
