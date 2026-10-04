"""Offline control-plane regression: invalid steps never unload or enqueue model work."""
import hashlib
import importlib.util
import io
import json
import os
import runpy
import subprocess
import sys
import threading
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def control(tmp_path, monkeypatch):
    from server.audio import youtube_source
    monkeypatch.setitem(sys.modules, "youtube_source", youtube_source)
    base = Path(__file__).resolve().parents[2] / "colab"
    spec = importlib.util.spec_from_file_location("voice_training", base / "voice_training.py")
    training = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "voice_training", training)
    spec.loader.exec_module(training)
    training.ROOT = tmp_path
    queued = []
    worker = SimpleNamespace(
        app=FastAPI(), LOCK=threading.RLock(), ACTIVE=set(), CONTROL_BUSY=False,
        RUNTIME_ID="test-runtime", EXECUTOR=SimpleNamespace(submit=lambda *args: queued.append(args)),
        health=lambda: {}, voices=lambda: [], PIPELINE=object(),
    )
    monkeypatch.setitem(sys.modules, "audio_worker", worker)
    spec = importlib.util.spec_from_file_location("test_training_control", base / "training_control.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    job = tmp_path / ("a" * 32)
    training.write_json(job / "selection.json", {"voice_name": "Test", "files": [{"id": "file", "size": 3}]})
    with TestClient(worker.app) as client:
        yield module, training, worker, queued, client, job


def approval(training, job):
    training.write_json(job / "review.json", [{"file": "clip.wav", "text": "hello", "include": True, "reviewed": True}])
    training.write_json(job / "dataset-approved.json", {"review_sha256": training.sha256(job / "review.json")})


@pytest.mark.parametrize("kind", ["prepare", "train", "resume"])
def test_out_of_order_action_rejected_before_worker_is_claimed(control, kind):
    _, _, worker, queued, client, job = control
    response = client.post(f"/v1/training/jobs/{job.name}/actions", json={"request_id": str(uuid4()), "kind": kind})
    assert response.status_code == 409
    assert not worker.CONTROL_BUSY
    assert not queued
    assert not (job / "actions").exists()


def test_partial_download_does_not_enable_preparation(control):
    _, training, _, queued, client, job = control
    training.write_json(job / "downloads.json", {"file": {"file": "source.wav"}})
    (job / "source").mkdir()
    (job / "source/source.wav").write_bytes(b"ab")
    assert client.get(f"/v1/training/jobs/{job.name}").json()["has_downloads"] is False
    response = client.post(f"/v1/training/jobs/{job.name}/actions", json={"request_id": str(uuid4()), "kind": "prepare"})
    assert response.status_code == 409
    assert not queued


def test_complete_download_enables_preparation(control):
    _, training, worker, queued, client, job = control
    training.write_json(job / "downloads.json", {"file": {"file": "source.wav"}})
    (job / "source").mkdir()
    (job / "source/source.wav").write_bytes(b"abc")
    assert client.get(f"/v1/training/jobs/{job.name}").json()["has_downloads"] is True
    response = client.post(f"/v1/training/jobs/{job.name}/actions", json={"request_id": str(uuid4()), "kind": "prepare"})
    assert response.status_code == 202
    assert worker.CONTROL_BUSY
    assert len(queued) == 1


def test_stale_dataset_approval_is_not_reported_or_trained(control):
    _, training, _, queued, client, job = control
    approval(training, job)
    training.write_json(job / "review.json", [])
    assert client.get(f"/v1/training/jobs/{job.name}").json()["dataset_approved"] is False
    response = client.post(f"/v1/training/jobs/{job.name}/actions", json={"request_id": str(uuid4()), "kind": "train"})
    assert response.status_code == 409
    assert not queued


def test_resume_rejects_changed_epochs_before_enqueue(control):
    _, training, _, queued, client, job = control
    approval(training, job)
    run = job / "runs" / ("b" * 32)
    training.write_json(run / "trainer-config.json", {"epochs": 3})
    (run / "trainer-state.pt").write_bytes(b"checkpoint")
    (run / "review.json").write_bytes((job / "review.json").read_bytes())
    body = {"request_id": str(uuid4()), "kind": "resume", "run_id": run.name, "epochs": 4}
    assert client.post(f"/v1/training/jobs/{job.name}/actions", json=body).status_code == 409
    assert not queued
    body.update(epochs=3)
    assert client.post(f"/v1/training/jobs/{job.name}/actions", json=body).status_code == 202
    assert len(queued) == 1


def test_download_does_not_unload_existing_tts_model(control, monkeypatch):
    module, training, worker, _, _, job = control
    path = job / "actions/action.json"
    training.write_json(path, {"status": "running"})
    monkeypatch.setattr(module, "unload", lambda: pytest.fail("Download must preserve the loaded model"))
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "google.colab", SimpleNamespace(userdata=SimpleNamespace(get=lambda _: "secret")))
    pipeline = worker.PIPELINE
    module.process(job, module.Action(request_id=uuid4(), kind="download"), path)
    assert training.read_json(path)["status"] == "succeeded"
    assert worker.PIPELINE is pipeline


def test_action_logging_is_unbuffered_in_python_descendants(control, monkeypatch):
    module, training, _, _, _, job = control
    path = job / "actions/action.json"
    training.write_json(path, {"status": "running"})
    monkeypatch.setattr(module, "unload", lambda: None)
    original_run = module.subprocess.run
    def run_descendant(*args, **kwargs):
        assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
        code = "import subprocess,sys; subprocess.run([sys.executable,'-c','import sys; print(sys.stdout.write_through)'],check=True)"
        return original_run([sys.executable, "-c", code], env=kwargs["env"], stdout=kwargs["stdout"],
                            stderr=kwargs["stderr"], check=True)
    monkeypatch.setattr(module.subprocess, "run", run_descendant)
    module.process(job, module.Action(request_id=uuid4(), kind="prepare"), path)
    assert training.read_json(path)["status"] == "succeeded"
    assert path.with_suffix(".log").read_text(encoding="utf-8").strip() == "True"


@pytest.mark.parametrize("script", ["prepare_dataset.py", "make_voice.py"])
def test_pinned_onnx_cli_uses_local_graphs_and_restores_factory(control, monkeypatch, tmp_path, script):
    _, training, _, _, _, _ = control
    upstream = tmp_path / "upstream"
    (upstream / "finetune").mkdir(parents=True)
    base = tmp_path / "base"
    (base / "onnx_update").mkdir(parents=True)
    (upstream / "finetune" / script).write_text(
        "import sys\nfrom vieneu import Vieneu\nVieneu(mode='v3turbo',backend='onnx',backbone_repo=sys.argv[1])\n",
    )
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
    module = SimpleNamespace(Vieneu=factory)
    monkeypatch.setitem(sys.modules, "vieneu", module)
    monkeypatch.setattr(training, "UPSTREAM", upstream)
    original_argv = sys.argv
    training.onnx_cli(script, [str(base)])
    assert calls[0]["onnx_dir"] == str(base / "onnx_update")
    assert module.Vieneu is factory
    assert sys.argv is original_argv


def test_malformed_proxy_json_rejected_before_remote_call(monkeypatch):
    from server.api.routes import training_control as local
    monkeypatch.setattr(local, "remote", lambda *args, **kwargs: pytest.fail("No remote request expected"))
    app = FastAPI()
    app.include_router(local.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        path = "/api/training-control/remote/jobs/" + "a" * 32 + "/actions"
        for body in ["{", "[]"]:
            assert client.post(path, content=body).status_code == 422


def source_wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 2400)
    return buffer.getvalue()


def test_local_ingest_matches_locked_manifest_and_resumes_idempotently(control):
    module, training, _, _, client, job = control
    content = source_wav()
    key = "podcast.wav"
    file_id = hashlib.sha256(key.encode()).hexdigest()
    manifest = {"schema_version": 1, "mode": "finetune", "source_type": "local", "job_id": job.name,
                "language": "vi", "voice_name": "Podcast", "same_speaker_confirmed": True,
                "files": [{"key": key, "id": file_id, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}]}
    path = job / "selection.json"
    training.write_json(path, manifest)
    assert training.open_selection(path) == job
    endpoint = f"/v1/training/jobs/{job.name}/sources/{file_id}"
    assert client.post(endpoint, files={"file": (key, content)}).json()["stored"] is True
    assert client.post(endpoint, files={"file": (key, content)}).json()["stored"] is True
    status = client.get(f"/v1/training/jobs/{job.name}").json()
    assert status["has_downloads"] is True
    assert status["has_dataset"] is False
    assert client.get("/v1/training/health").json()["local_dataset_upload"] is True
    assert client.post(endpoint, files={"file": (key, b"changed")}).status_code == 422
    assert client.post(endpoint.replace(file_id, "b" * 64), files={"file": (key, content)}).status_code == 422
    assert training.sha256(job / "source" / (file_id + ".wav")) == hashlib.sha256(content).hexdigest()


def test_local_client_to_backend_to_worker_transfer_verifies_checksum(monkeypatch):
    from server.api.routes import training_control as local
    content = source_wav()
    calls = []

    def transport(path, method="GET", body=None, **kwargs):
        calls.append((path, method, body))
        if path == "health":
            return {"local_dataset_upload": True}
        if path == "selections":
            return {"job_id": body["job_id"]}
        uploaded = kwargs["upload"].read()
        assert uploaded == content
        return {"stored": True, "checksum": hashlib.sha256(uploaded).hexdigest()}

    monkeypatch.setattr(local, "remote", transport)
    monkeypatch.setattr(local, "CONNECTION", {"url": "https://session.trycloudflare.com", "token": "t" * 32})
    app = FastAPI()
    app.include_router(local.router)
    request_id = str(uuid4())
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        for _ in range(2):
            response = client.post("/api/training-control/local-selection", data={
                "request_id": request_id, "voice_name": "Podcast", "language": "vi", "same_speaker_confirmed": "true",
            }, files={"files": ("podcast.wav", content, "audio/wav")})
            assert response.status_code == 200
            assert response.json()["uploaded_files"] == 1
    first, second = calls[1][2], calls[4][2]
    assert first == second
    assert first["source_type"] == "local"
    assert first["job_id"] == request_id.replace("-", "")
    assert first["files"][0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert not any(call[0].endswith("actions") for call in calls)


@pytest.mark.parametrize("filename,content,confirmed", [("../outside.wav", source_wav(), "true"),
    ("audio.wav", b"invalid", "true"), ("audio.wav", source_wav(), "false")])
def test_bad_local_upload_never_contacts_worker(monkeypatch, filename, content, confirmed):
    from server.api.routes import training_control as local
    monkeypatch.setattr(local, "remote", lambda *args, **kwargs: pytest.fail("No remote call expected"))
    app = FastAPI()
    app.include_router(local.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        response = client.post("/api/training-control/local-selection", data={
            "request_id": str(uuid4()), "voice_name": "Podcast", "same_speaker_confirmed": confirmed,
        }, files={"files": (filename, content, "audio/wav")})
        assert response.status_code == 422


def test_real_multipart_parser_accepts_868_dataset_files(monkeypatch):
    from server.api.routes import training_control as local
    content = source_wav()
    uploaded = []
    def transport(path, method="GET", body=None, **kwargs):
        if path == "health":
            return {"local_dataset_upload": True}
        if path == "selections":
            assert len(body["files"]) == 868
            return {"job_id": body["job_id"]}
        uploaded.append(path)
        assert kwargs["upload"].read() == content
        return {"stored": True, "checksum": hashlib.sha256(content).hexdigest()}
    monkeypatch.setattr(local, "remote", transport)
    monkeypatch.setattr(local, "CONNECTION", {"url": "https://session.trycloudflare.com", "token": "t" * 32})
    app = FastAPI()
    app.include_router(local.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        response = client.post("/api/training-control/local-selection", data={
            "request_id": str(uuid4()), "voice_name": "Podcast", "same_speaker_confirmed": "true",
        }, files=[("files", (f"clip-{index}.wav", content, "audio/wav")) for index in range(868)])
        assert response.status_code == 200
        assert response.json()["uploaded_files"] == 868
    assert len(uploaded) == 868


def test_asr_preparation_retains_confidence_signal_and_unreviewed_state(control, monkeypatch):
    _, training, _, _, _, job = control
    content = source_wav()
    training.write_json(job / "selection.json", {"language": "vi", "files": [{"id": "file", "key": "source.wav"}]})
    training.write_json(job / "downloads.json", {"file": {"file": "source.wav", "sha256": hashlib.sha256(content).hexdigest()}})
    (job / "source").mkdir()
    (job / "source/source.wav").write_bytes(content)
    segment = SimpleNamespace(words=[SimpleNamespace(word="Xin chào", start=0, end=2, probability=0.91)],
                              avg_logprob=-0.15, no_speech_prob=0.001, compression_ratio=1.2)
    model = SimpleNamespace(transcribe=lambda *args, **kwargs: ([segment], SimpleNamespace(language_probability=0.98)))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *args, **kwargs: model))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        HfApi=lambda: SimpleNamespace(model_info=lambda _: SimpleNamespace(sha="revision")),
        snapshot_download=lambda *args, **kwargs: "model",
    ))
    monkeypatch.setattr(training, "gpu", lambda: SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    monkeypatch.setattr(training, "probe_media", lambda _: {"duration": 3, "sample_rate": 24000, "channels": 1})
    monkeypatch.setattr(training, "run", lambda *args: Path(args[-1]).write_bytes(content))
    training.prepare_clips(job)
    row = training.read_json(job / "review.json")[0]
    assert row["asr"]["mean_word_probability"] == 0.91
    assert row["asr"]["no_speech_prob"] == 0.001
    assert row["signal"]["near_silence_fraction"] == 1
    assert row["signal"]["clipped_fraction"] == 0
    assert row["reviewed"] is False
    assert row["review_method"] == "manual_listening"


def checkpoint_preparer(control, monkeypatch):
    _, training, _, _, _, job = control
    content = source_wav()
    training.write_json(job / "selection.json", {"language": "vi", "files": [
        {"id": f"file-{index}", "key": f"source-{index}.wav"} for index in range(2)]})
    training.write_json(job / "downloads.json", {f"file-{index}": {
        "file": f"source-{index}.wav", "sha256": hashlib.sha256(content).hexdigest()} for index in range(2)})
    (job / "source").mkdir()
    for index in range(2):
        (job / "source" / f"source-{index}.wav").write_bytes(content)
    calls = []
    segment = SimpleNamespace(words=[SimpleNamespace(word="Hello", start=0, end=2, probability=0.9)])
    def transcribe(path, **kwargs):
        calls.append(Path(path).name)
        return [segment], SimpleNamespace()
    model = SimpleNamespace(transcribe=transcribe)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *args, **kwargs: model))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        HfApi=lambda: SimpleNamespace(model_info=lambda _: SimpleNamespace(sha="revision")),
        snapshot_download=lambda *args, **kwargs: "model"))
    monkeypatch.setattr(training, "gpu", lambda: SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    monkeypatch.setattr(training, "probe_media", lambda _: {"duration": 3, "sample_rate": 24000, "channels": 1})
    def write_clip(*args):
        Path(args[-1]).write_bytes(content)
        if len(calls) == 1 and Path(args[-1]).parent.name == "raw_audio":
            (job / "cancel.request").touch()
    monkeypatch.setattr(training, "run", write_clip)
    return training, job, calls


def test_prepare_cancel_at_file_boundary_resumes_verified_checkpoint_without_duplicate_asr(control, monkeypatch):
    training, job, calls = checkpoint_preparer(control, monkeypatch)
    with pytest.raises(RuntimeError, match="checkpoint"):
        training.prepare_clips(job)
    checkpoint = job / "prepare-checkpoints/file-0_c00000.json"
    assert checkpoint.is_file() and checkpoint.stat().st_size < 2 * 1024**2
    assert not (job / "review.json").exists()
    assert calls == ["file-0_normalized.wav"]
    (job / "cancel.request").unlink()
    training.prepare_clips(job)
    assert calls == ["file-0_normalized.wav", "file-1_normalized.wav"]
    rows = training.read_json(job / "review.json")
    assert len(rows) == 2
    assert len({row["file"] for row in rows}) == 2
    assert all(row["reviewed"] is False for row in rows)


@pytest.mark.parametrize("changed", ["source", "asr"])
def test_prepare_checkpoint_rejects_changed_source_or_asr_revision(control, monkeypatch, changed):
    training, job, calls = checkpoint_preparer(control, monkeypatch)
    with pytest.raises(RuntimeError):
        training.prepare_clips(job)
    (job / "cancel.request").unlink()
    if changed == "source":
        source = job / "source/source-0.wav"
        source.write_bytes(source.read_bytes() + b"changed")
        receipts = training.read_json(job / "downloads.json")
        receipts["file-0"]["sha256"] = training.sha256(source)
        training.write_json(job / "downloads.json", receipts)
    else:
        training.write_json(job / "asr-revision.json", {"repo": "model", "revision": "changed"})
    with pytest.raises(RuntimeError, match="ASR"):
        training.prepare_clips(job)
    assert calls == ["file-0_normalized.wav"]
    assert not (job / "review.json").exists()


def test_prepare_cancel_before_first_file_never_runs_asr(control, monkeypatch):
    training, job, calls = checkpoint_preparer(control, monkeypatch)
    (job / "cancel.request").touch()
    with pytest.raises(RuntimeError, match="checkpoint"):
        training.prepare_clips(job)
    assert not calls
    assert not (job / "review.json").exists()


def test_declared_text_signal_review_is_preserved_without_listening_attestation(control):
    _, training, _, _, client, job = control
    rows = [{"file": f"clip-{index}.wav", "text": "Xin chào", "include": True, "reviewed": True,
             "review_method": "text_acoustic_review", "asr": {"avg_logprob": -0.2}, "signal": {"rms_dbfs": -18}}
            for index in range(20)]
    training.write_json(job / "review.json", rows)
    endpoint = f"/v1/training/jobs/{job.name}"
    before = client.get(endpoint + "/review").json()
    response = client.put(endpoint + "/review", json={"hash": before["hash"], "file": rows[0]["file"],
        "text": "Xin chào", "include": True, "reviewed": True, "review_method": "text_acoustic_review"})
    assert response.status_code == 200
    assert response.json()["rows"][0]["review_method"] == "text_acoustic_review"
    assert client.post(endpoint + "/approve-dataset", json={"hash": response.json()["hash"]}).status_code == 200
    approval = training.read_json(job / "dataset-approved.json")
    assert approval["review_methods"] == {"manual_listening": 0, "text_acoustic_review": 20}


def test_text_signal_review_requires_metrics_but_legacy_manual_review_remains_supported(control):
    _, training, _, _, client, job = control
    training.write_json(job / "review.json", [{"file": "clip.wav", "text": "hello", "include": True, "reviewed": False}])
    endpoint = f"/v1/training/jobs/{job.name}/review"
    hash_value = client.get(endpoint).json()["hash"]
    body = {"hash": hash_value, "file": "clip.wav", "text": "hello", "include": True, "reviewed": True,
            "review_method": "text_acoustic_review"}
    assert client.put(endpoint, json=body).status_code == 409
    body.pop("review_method")
    response = client.put(endpoint, json=body)
    assert response.status_code == 200
    assert response.json()["rows"][0]["review_method"] == "manual_listening"


def test_bulk_review_writes_once_and_preserves_declared_review_methods(control, monkeypatch):
    _, training, _, _, client, job = control
    rows = [{"file": f"clip-{index}.wav", "text": "old", "include": True, "reviewed": False,
             "asr": {"avg_logprob": -0.2}, "signal": {"rms_dbfs": -18}} for index in range(2)]
    training.write_json(job / "review.json", rows)
    training.write_json(job / "dataset-approved.json", {"review_sha256": "previous"})
    writes = []
    original = training.write_json
    def record_write(path, value):
        writes.append(path)
        original(path, value)
    monkeypatch.setattr(training, "write_json", record_write)
    endpoint = f"/v1/training/jobs/{job.name}/review"
    value = client.get(endpoint).json()
    response = client.put(endpoint + "/bulk", json={"hash": value["hash"], "edits": [
        {"file": "clip-0.wav", "text": "new | text", "include": True, "reviewed": True, "review_method": "text_acoustic_review"},
        {"file": "clip-1.wav", "text": "other", "include": False, "reviewed": False},
    ]})
    assert response.status_code == 200
    assert writes == [job / "review.json"]
    assert response.json()["hash"] != value["hash"]
    assert response.json()["rows"][0]["text"] == "new text"
    assert response.json()["rows"][0]["review_method"] == "text_acoustic_review"
    assert not (job / "dataset-approved.json").exists()


@pytest.mark.parametrize("invalid", ["foreign", "duplicate", "stale", "missing_metrics"])
def test_bulk_review_is_atomic_on_invalid_foreign_duplicate_hash_or_provenance(control, invalid):
    _, training, _, _, client, job = control
    training.write_json(job / "review.json", [{"file": f"clip-{index}.wav", "text": "old", "include": True,
                                              "reviewed": False} for index in range(2)])
    training.write_json(job / "dataset-approved.json", {"review_sha256": "keep"})
    before = (job / "review.json").read_bytes()
    valid = {"file": "clip-0.wav", "text": "changed", "include": True, "reviewed": True}
    second = {**valid, "file": "clip-1.wav"}
    expected = 409
    if invalid == "foreign":
        second["file"] = "foreign.wav"
        expected = 404
    elif invalid == "duplicate":
        second["file"] = "clip-0.wav"
        expected = 422
    elif invalid == "missing_metrics":
        second["review_method"] = "text_acoustic_review"
    value = training.sha256(job / "review.json") if invalid != "stale" else "stale"
    response = client.put(f"/v1/training/jobs/{job.name}/review/bulk", json={"hash": value, "edits": [valid, second]})
    assert response.status_code == expected
    assert (job / "review.json").read_bytes() == before
    assert training.read_json(job / "dataset-approved.json")["review_sha256"] == "keep"


def test_backend_bulk_review_supports_explicit_plan_above_single_row_limit(monkeypatch):
    from server.api.routes import training_control as local
    calls = []
    def transport(path, method, body, **kwargs):
        calls.append((path, method, body))
        return {"hash": "new", "rows": []}
    monkeypatch.setattr(local, "remote", transport)
    app = FastAPI()
    app.include_router(local.router)
    endpoint = "/api/training-control/remote/jobs/" + "a" * 32 + "/review/bulk"
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        plan = {"hash": "old", "edits": [{"file": f"{index}.wav", "text": "a" * 3000} for index in range(30)]}
        response = client.put(endpoint, json=plan)
        assert response.status_code == 200
        assert calls[0][1] == "PUT"
        assert calls[0][2] == plan
        assert client.put(endpoint + "/other", json=plan).status_code == 404


@pytest.mark.parametrize("invalid", ["missing", "excluded", "changed"])
def test_verification_rejects_invalid_dataset_before_claiming_worker(control, invalid):
    _, training, worker, queued, client, job = control
    if invalid != "missing":
        clip = job / "dataset/raw_audio/clip.wav"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"audio")
        training.write_json(job / "review.json", [{"file": clip.name, "include": invalid != "excluded",
                                                  "sha256": "wrong" if invalid == "changed" else training.sha256(clip)}])
    response = client.post(f"/v1/training/jobs/{job.name}/actions",
                           json={"request_id": str(uuid4()), "kind": "verify-transcripts"})
    assert response.status_code == 409
    assert not worker.CONTROL_BUSY
    assert not queued
    assert not (job / "actions").exists()


def test_verification_preserves_original_text_exclusions_and_resumes_per_clip(control, monkeypatch):
    _, training, _, _, client, job = control
    training.write_json(job / "selection.json", {"language": "vi"})
    rows = []
    for index in range(3):
        clip = job / f"dataset/raw_audio/{index}.wav"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(str(index).encode())
        rows.append({"file": clip.name, "text": "original", "include": index < 2, "reviewed": True,
                     "sha256": training.sha256(clip), "review_method": "text_acoustic_review"})
    training.write_json(job / "review.json", rows)
    training.write_json(job / "dataset-approved.json", {"review_sha256": training.sha256(job / "review.json")})
    calls, models, downloads = [], [], []
    def transcribe(path, **kwargs):
        calls.append(Path(path).name)
        assert kwargs["language"] == "vi" and kwargs["condition_on_previous_text"] is False
        segment = SimpleNamespace(text="alternative", words=[SimpleNamespace(probability=0.9)],
                                  avg_logprob=-0.2, no_speech_prob=0.01, compression_ratio=1.1)
        return iter([segment]), SimpleNamespace(language_probability=1.0)
    def create_model(*args, **kwargs):
        models.append(kwargs)
        return SimpleNamespace(transcribe=transcribe)
    def snapshot(repo, **kwargs):
        downloads.append((repo, kwargs["revision"]))
        return "pinned-model"
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=create_model))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        HfApi=lambda: SimpleNamespace(model_info=lambda repo: SimpleNamespace(sha="immutable-sha")),
        snapshot_download=snapshot))
    monkeypatch.setattr(training, "gpu", lambda: SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    write = training.write_json
    def cancel_after_save(path, value):
        write(path, value)
        if path.name == "review.json":
            (job / "cancel.request").touch()
    monkeypatch.setattr(training, "write_json", cancel_after_save)
    with pytest.raises(RuntimeError):
        training.verify_transcripts(job)
    assert calls == ["0.wav"]
    assert not (job / "dataset-approved.json").exists()
    monkeypatch.setattr(training, "write_json", write)
    (job / "cancel.request").unlink()
    training.verify_transcripts(job)
    assert calls == ["0.wav", "1.wav"]
    saved = training.read_json(job / "review.json")
    assert all(row["text"] == "original" for row in saved)
    for row in saved[:2]:
        assert not row["reviewed"]
        assert row["verification"]["text"] == "alternative"
        assert row["verification"]["clip_sha256"] == row["sha256"]
        assert row["verification"]["asr"]["mean_word_probability"] == 0.9
    assert saved[2] == rows[2]
    assert downloads == [("Systran/faster-whisper-large-v3", "immutable-sha")] * 2
    assert all(config == {"device": "cuda", "compute_type": "int8_float16"} for config in models)
    response = client.post(f"/v1/training/jobs/{job.name}/actions",
                           json={"request_id": str(uuid4()), "kind": "verify-transcripts"})
    assert response.status_code == 202


def raw_selection(training, job, name, content):
    file_id = hashlib.sha256(name.encode()).hexdigest()
    manifest = {"schema_version": 1, "mode": "finetune", "source_type": "local", "upload_protocol": "chunks-v1",
                "job_id": job.name, "language": "vi", "voice_name": "Podcast", "same_speaker_confirmed": True,
                "files": [{"key": name, "id": file_id, "size": len(content), "last_modified": 1000}]}
    training.write_json(job / "selection.json", manifest)
    training.open_selection(job / "selection.json")
    return file_id


def ffmpeg_tools(monkeypatch):
    vendor = Path(__file__).resolve().parents[2] / "vendor"
    monkeypatch.setenv("PATH", str(vendor) + os.pathsep + os.environ["PATH"])
    return str(vendor / "ffmpeg.exe")


@pytest.mark.parametrize("extension", [".mp3", ".mp4", ".wav"])
def test_real_raw_media_chunk_retry_checksum_and_normalization(control, monkeypatch, tmp_path, extension):
    _, training, _, _, client, job = control
    ffmpeg = ffmpeg_tools(monkeypatch)
    source = tmp_path / ("stereo" + extension)
    args = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2"]
    if extension == ".mp4":
        args += ["-f", "lavfi", "-i", "color=s=16x16:r=1", "-map", "0:a:0", "-map", "1:v:0", "-c:v", "libx264", "-c:a", "aac"]
    args += ["-t", "2", "-ac", "2", str(source)]
    subprocess.run(args, check=True, capture_output=True)
    content = source.read_bytes()
    file_id = raw_selection(training, job, source.name, content)
    endpoint = f"/v1/training/jobs/{job.name}/sources/{file_id}"
    first, last = content[:100], content[100:]
    def send(offset, data, checksum=None):
        return client.post(endpoint + "/chunks", data={"offset": offset, "checksum": checksum or hashlib.sha256(data).hexdigest()},
                           files={"file": ("chunk", data)})
    assert send(0, first, "a" * 64).status_code == 422
    assert client.get(endpoint + "/status").json()["offset"] == 0
    assert send(0, first).json() == {"offset": 100, "stored": False}
    assert send(0, first).json()["offset"] == 100  # exact duplicate does not append
    assert send(0, b"changed").status_code == 409
    assert send(101, last).status_code == 409
    assert client.get(endpoint + "/status").json()["offset"] == 100
    result = send(100, last)
    assert result.status_code == 200
    assert result.json() == {"offset": len(content), "stored": True, "checksum": hashlib.sha256(content).hexdigest()}
    assert send(100, last).json()["stored"] is True
    receipt = training.read_json(job / "downloads.json")[file_id]
    stored = job / "source" / receipt["file"]
    assert stored.suffix == extension and stored.read_bytes() == content
    assert receipt["media"]["sample_rate"] == 44100 and receipt["media"]["channels"] == 2
    normalized = tmp_path / "normalized.wav"
    training.normalize_audio(stored, normalized, 0, receipt["media"]["duration"])
    with wave.open(str(normalized)) as audio:
        assert (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) == (1, 24000, 2)
        assert 1.9 < audio.getnframes() / audio.getframerate() < 2.2
    assert client.get(f"/v1/training/jobs/{job.name}").json()["has_downloads"] is True


@pytest.mark.parametrize("kind", ["no-audio", "corrupt"])
def test_raw_invalid_media_is_not_receipted_or_enabled_for_asr(control, monkeypatch, tmp_path, kind):
    _, training, _, queued, client, job = control
    ffmpeg = ffmpeg_tools(monkeypatch)
    source = tmp_path / "invalid.mp4"
    if kind == "no-audio":
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=16x16:r=1", "-t", "1",
                        "-c:v", "libx264", str(source)], check=True, capture_output=True)
        content = source.read_bytes()
    else:
        content = b"not media"
    file_id = raw_selection(training, job, source.name, content)
    response = client.post(f"/v1/training/jobs/{job.name}/sources/{file_id}/chunks",
                           data={"offset": 0, "checksum": hashlib.sha256(content).hexdigest()}, files={"file": ("chunk", content)})
    assert response.status_code == 422
    assert not (job / "downloads.json").exists()
    assert not list((job / "source").glob("*"))
    assert client.post(f"/v1/training/jobs/{job.name}/actions", json={"request_id": str(uuid4()), "kind": "prepare"}).status_code == 409
    assert not queued


def test_backend_raw_manifest_accepts_five_hour_pcm_size_and_only_bounded_chunks(monkeypatch):
    from server.api.routes import training_control as local
    calls = []
    def transport(path, method="GET", body=None, **kwargs):
        calls.append((path, body, kwargs))
        if path == "health":
            return {"local_media_upload": "chunks-v1"}
        if path == "selections":
            return {"job_id": body["job_id"]}
        data = kwargs["upload"].read()
        assert kwargs["upload_fields"] == {"offset": "0", "checksum": hashlib.sha256(data).hexdigest()}
        return {"offset": len(data), "stored": False}
    monkeypatch.setattr(local, "remote", transport)
    app = FastAPI()
    app.include_router(local.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        response = client.post("/api/training-control/local-media", json={"request_id": str(uuid4()), "voice_name": "Podcast",
            "same_speaker_confirmed": True, "files": [{"name": "long.wav", "size": 5 * 3600 * 24000 * 2 + 44, "last_modified": 1}]})
        assert response.status_code == 200
        selection = response.json()
        endpoint = f"/api/training-control/local-media/{selection['job_id']}/sources/{selection['files'][0]['id']}"
        assert client.post(endpoint, data={"offset": 0}, files={"file": ("part", b"abc")}).json()["offset"] == 3
        count = len(calls)
        assert client.post(endpoint, data={"offset": 0}, files={"file": ("part", b"x" * (8 * 1024**2 + 1))}).status_code == 413
        assert len(calls) == count


def test_probe_media_uses_container_duration_when_audio_duration_is_unavailable(control, monkeypatch):
    _, training, _, _, _, _ = control
    monkeypatch.setattr(training.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=
        '{"streams":[{"duration":"N/A","sample_rate":"44100","channels":2}],"format":{"duration":"8.5"}}'))
    assert training.probe_media("source.mp4") == {"duration": 8.5, "sample_rate": 44100, "channels": 2}


@pytest.mark.parametrize("files", [
    [{"name": "oversize.mp4", "size": 2 * 1024**3 + 1}],
    [{"name": f"source-{index}.mp4", "size": 2 * 1024**3} for index in range(11)],
    [{"name": "unsupported.txt", "size": 1}],
    [{"name": "duplicate.wav", "size": 1}, {"name": "duplicate.wav", "size": 1}],
])
def test_invalid_raw_selection_never_contacts_colab(monkeypatch, files):
    from server.api.routes import training_control as local
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid local selection must not contact Colab")
    monkeypatch.setattr(local, "remote", forbidden)
    app = FastAPI()
    app.include_router(local.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        response = client.post("/api/training-control/local-media", json={"request_id": str(uuid4()),
            "voice_name": "Podcast", "same_speaker_confirmed": True, "files": files})
    assert response.status_code in (413, 422)


def test_long_source_preparation_resumes_per_chunk_and_keeps_global_provenance(control, monkeypatch):
    training, job, calls = checkpoint_preparer(control, monkeypatch)
    selection = training.read_json(job / "selection.json")
    selection["files"] = selection["files"][:1]
    training.write_json(job / "selection.json", selection)
    monkeypatch.setattr(training, "probe_media", lambda _: {"duration": 1201, "sample_rate": 44100, "channels": 2})
    segment = SimpleNamespace(words=[SimpleNamespace(word="Hello", start=1.1, end=3.1, probability=0.9)])
    def transcribe(path, **kwargs):
        calls.append(Path(path).name)
        return [segment], SimpleNamespace()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *args, **kwargs: SimpleNamespace(transcribe=transcribe)))
    with pytest.raises(RuntimeError, match="checkpoint"):
        training.prepare_clips(job)
    assert len(calls) == 1
    (job / "cancel.request").unlink()
    # Third one-second tail cannot contain the fake two-second sentence: safely rejected.
    training.prepare_clips(job)
    assert len(calls) == 3
    rows = training.read_json(job / "review.json")
    assert len(rows) == 2 and len({row["file"] for row in rows}) == 2
    assert [row["start"] for row in rows] == pytest.approx([1.02, 601.02])
    assert [row["chunk_start"] for row in rows] == [0, 600]
    assert all(row["source_sha256"] == training.read_json(job / "downloads.json")["file-0"]["sha256"] for row in rows)
    assert all(row["text"] == "Hello" and not row["reviewed"] for row in rows)
    assert len(list((job / "prepare-checkpoints").glob("*_c*.json"))) == 3


def test_artificial_chunk_boundary_groups_are_excluded_without_guessed_text(control, monkeypatch, tmp_path):
    _, training, _, _, _, _ = control
    content = source_wav()
    monkeypatch.setattr(training, "run", lambda *args: Path(args[-1]).write_bytes(content))
    groups = [SimpleNamespace(words=[SimpleNamespace(word=text, start=start, end=end)])
              for text,start,end in [("cut start", 0.1, 2), ("safe", 2, 4), ("cut end", 598, 599.9)]]
    model = SimpleNamespace(transcribe=lambda *args, **kwargs: (groups, SimpleNamespace()))
    rows, skipped, boundaries = training.prepare_audio_chunk(model, "normalized.wav", tmp_path,
        {"id": "a" * 64, "key": "raw.mp4"}, "source-checksum", 1, 600, 600, True, "vi")
    assert [row["text"] for row in rows] == ["safe"]
    assert rows[0]["start"] == pytest.approx(601.92)
    assert skipped == 2
    assert [row["text"] for row in boundaries] == ["cut start", "cut end"]


@pytest.mark.parametrize("stage", ["full-part", "rename-before-receipt"])
def test_chunk_finalization_recovers_interruption_without_reuploading_file(control, monkeypatch, stage):
    _, training, _, _, client, job = control
    ffmpeg_tools(monkeypatch)
    content = source_wav()
    file_id = raw_selection(training, job, "source.wav", content)
    source = job / "source" / (file_id + ".wav")
    source.parent.mkdir()
    staged = source if stage == "rename-before-receipt" else source.with_suffix(".wav.part")
    staged.write_bytes(content)
    endpoint = f"/v1/training/jobs/{job.name}/sources/{file_id}"
    assert client.get(endpoint + "/status").json() == {"offset": len(content), "stored": False}
    tail = content[-100:]
    response = client.post(endpoint + "/chunks", data={"offset": len(content)-100, "checksum": hashlib.sha256(tail).hexdigest()},
                           files={"file": ("part", tail)})
    assert response.status_code == 200 and response.json()["stored"]
    assert source.read_bytes() == content
    assert client.get(endpoint + "/status").json()["stored"]


@pytest.mark.parametrize("url", ["http://www.youtube.com/watch?v=iaPiJZeJwQk", "https://youtube.com.evil/watch?v=iaPiJZeJwQk",
    "https://127.0.0.1/watch?v=iaPiJZeJwQk", "https://www.youtube.com/watch?v=iaPiJZeJwQk&list=abc",
    "https://user@www.youtube.com/watch?v=iaPiJZeJwQk", "https://www.youtube.com:443/watch?v=iaPiJZeJwQk",
    "https://youtu.be/iaPiJZeJwQk/extra", "https://www.youtube.com/watch?v=iaPiJZeJwQk&v=abcdefghijk"])
def test_youtube_import_rejects_non_single_public_url_before_remote(monkeypatch, url):
    from server.api.routes import training_control as local
    monkeypatch.setattr(local, "remote", lambda *args, **kwargs: pytest.fail("Must not contact remote for invalid URL"))
    app = FastAPI()
    app.include_router(local.router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        response = client.post("/api/training-control/youtube", json={"request_id": str(uuid4()), "voice_name": "Podcast",
                               "language": "vi", "same_speaker_confirmed": True, "url": url})
        assert response.status_code == 422


def test_youtube_import_manifest_is_canonical_isolated_and_capability_gated(monkeypatch):
    from server.api.routes import training_control as local
    calls = []
    def remote(path, method="GET", body=None, **kwargs):
        calls.append((path, body))
        return {"youtube_source": "single-video-v1"} if path == "health" else {"job_id": body["job_id"]}
    monkeypatch.setattr(local, "remote", remote)
    request_id = uuid4()
    body = local.YouTubeSelection(request_id=request_id, voice_name=" Podcast ", language="vi",
                                  same_speaker_confirmed=True, url="https://youtu.be/iaPiJZeJwQk?t=10")
    result = local.begin_youtube(body)
    assert result == {"job_id": request_id.hex, "source_url": "https://www.youtube.com/watch?v=iaPiJZeJwQk"}
    manifest = calls[-1][1]
    assert manifest["source_type"] == "youtube" and manifest["voice_name"] == "Podcast"
    assert manifest["files"][0] == {"id": hashlib.sha256(result["source_url"].encode()).hexdigest(),
                                    "key": result["source_url"], "size": 0}
    monkeypatch.setattr(local, "remote", lambda *args, **kwargs: {})
    with pytest.raises(Exception) as exc:
        local.begin_youtube(body)
    assert exc.value.status_code == 409


def youtube_selection(training, job):
    url = "https://www.youtube.com/watch?v=iaPiJZeJwQk"
    file_id = hashlib.sha256(url.encode()).hexdigest()
    training.write_json(job / "selection.json", {"schema_version": 1, "mode": "finetune", "source_type": "youtube",
        "source_url": url, "job_id": job.name, "voice_name": "Podcast", "language": "vi", "same_speaker_confirmed": True,
        "files": [{"id": file_id, "key": url, "size": 0}]})
    return file_id, url


def test_youtube_download_preserves_provenance_resumes_and_requires_review(control, monkeypatch):
    module, training, worker, queued, client, job = control
    file_id, url = youtube_selection(training, job)
    assert training.open_selection(job / "selection.json") == job
    calls = []
    def download(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 600 and kwargs["check"] is True and not kwargs.get("shell")
        assert args[-3] == url
        scratch = Path(args[-2])
        (scratch / "audio.webm").write_bytes(b"audio")
        training.write_json(scratch / "receipt.json", {"file": "audio.webm", "source_url": url,
            "video_id": "iaPiJZeJwQk", "title": "Podcast", "duration": 15, "extractor": "youtube", "download_bytes": 5})
    monkeypatch.setattr(training.subprocess, "run", download)
    monkeypatch.setattr(training, "probe_media", lambda _: {"duration": 15, "sample_rate": 48000, "channels": 2})
    monkeypatch.setattr(training.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    assert not module.downloads_complete(job)
    receipts = training.download_selected(job)
    assert module.downloads_complete(job)
    assert receipts[file_id]["sha256"] == hashlib.sha256(b"audio").hexdigest()
    assert receipts[file_id]["source_url"] == url
    assert client.get(f"/v1/training/jobs/{job.name}").json()["source_provenance"][0]["video_id"] == "iaPiJZeJwQk"
    assert training.download_selected(job) == receipts and len(calls) == 1
    assert not (job / "review.json").exists() and not (job / "dataset-approved.json").exists()
    assert client.post(f"/v1/training/jobs/{job.name}/actions", json={"request_id": str(uuid4()), "kind": "train"}).status_code == 409
    assert not queued and not worker.CONTROL_BUSY


def test_youtube_download_timeout_has_no_success_receipt(control, monkeypatch):
    _, training, _, _, _, job = control
    youtube_selection(training, job)
    monkeypatch.setattr(training.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 600)
    monkeypatch.setattr(training.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="10 phút"):
        training.download_selected(job)
    assert not (job / "downloads.json").exists()
    assert not list((job / "source").glob("*"))


def test_youtube_download_needs_no_r2_secrets_and_reports_public_failure(control, monkeypatch):
    module, training, _, _, _, job = control
    youtube_selection(training, job)
    path = job / "actions/action.json"
    training.write_json(path, {"status": "running"})
    monkeypatch.setitem(sys.modules, "google.colab", None)
    monkeypatch.setattr(module, "unload", lambda: pytest.fail("Download must retain TTS"))
    def failed(*args, **kwargs):
        training.write_json(job / "download-error.json", {"error": "Không tải được audio YouTube công khai."})
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(module.subprocess, "run", failed)
    module.process(job, module.Action(request_id=uuid4(), kind="download"), path)
    result = training.read_json(path)
    assert result["status"] == "failed" and "YouTube" in result["error"]


def test_youtube_prepare_review_and_train_dispatch_reaches_isolated_run(control, monkeypatch):
    """Run real orchestration; external media/model/GPU CLIs are CPU fixtures, never a real train."""
    module, training, worker, queued, client, job = control
    file_id, url = youtube_selection(training, job)
    training.open_selection(job / "selection.json")
    base = job.parent / "fixture-model"
    base.mkdir()
    monkeypatch.setattr(training, "gpu", lambda: SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: None)))
    monkeypatch.setattr(module, "unload", lambda: None)
    monkeypatch.setattr(training.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    monkeypatch.setattr(training, "probe_media", lambda _: {"duration": 90, "sample_rate": 48000, "channels": 2})
    monkeypatch.setitem(sys.modules, "google.colab", None)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        HfApi=lambda: SimpleNamespace(model_info=lambda _: SimpleNamespace(sha="fixture-revision")),
        snapshot_download=lambda *args, **kwargs: str(base)))
    words = [SimpleNamespace(start=index * 4 + 1, end=index * 4 + 4, word=f" Sentence {index + 1}.", probability=0.98)
             for index in range(20)]
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=lambda *args, **kwargs:
        SimpleNamespace(transcribe=lambda *args, **kwargs: ([SimpleNamespace(words=[word]) for word in words],
                                                         SimpleNamespace(language_probability=0.99)))))
    parquet = SimpleNamespace(read_table=lambda path: SimpleNamespace(num_rows=20 if Path(path).is_file() else 0))
    monkeypatch.setitem(sys.modules, "pyarrow", SimpleNamespace(parquet=parquet))
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", parquet)
    commands = []
    def external_cli(*args):
        commands.append(args)
        if args[0] == "ffmpeg":
            output = Path(args[-1])
            with wave.open(str(output), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x01\x00" * 2400)
        elif "prepare_dataset.py" in args:
            (job / "dataset/train.parquet").write_bytes(b"fixture encoded rows")
        elif Path(args[1]).name == "train_resumable.py":
            run = Path(args[args.index("--run-dir") + 1])
            (run / "merged/update").mkdir(parents=True)
            (run / "merged/update/model.safetensors").write_bytes(b"fixture weights")
        elif "make_voice.py" in args:
            Path(args[args.index("--out") + 1]).write_text("{}", encoding="utf-8")
        else:
            pytest.fail(f"Unexpected external CLI: {args[0]}")
    monkeypatch.setattr(training, "run", external_cli)
    def subprocess_fixture(args, **kwargs):
        if "--execute" in args:
            monkeypatch.setattr(sys, "argv", [args[2], "--execute", args[-1]])
            runpy.run_path(args[2], run_name="__main__")
        else:
            assert args[-3] == url and not kwargs.get("shell")
            scratch = Path(args[-2])
            (scratch / "audio.webm").write_bytes(b"fixture youtube audio")
            training.write_json(scratch / "receipt.json", {"file": "audio.webm", "source_url": url,
                "video_id": "iaPiJZeJwQk", "download_bytes": 21})
    monkeypatch.setattr(training.subprocess, "run", subprocess_fixture)
    training.download_selected(job)
    assert module.downloads_complete(job)
    training.prepare_clips(job)
    rows = training.read_json(job / "review.json")
    assert len(rows) == 20 and all(row["source"] == url and not row["reviewed"] for row in rows)
    assert all(row["source_sha256"] == training.sha256(job / "source" / (file_id + ".webm")) for row in rows)
    endpoint = f"/v1/training/jobs/{job.name}"
    request = {"request_id": str(uuid4()), "kind": "train", "epochs": 2}
    assert client.post(endpoint + "/actions", json=request).status_code == 409
    review = client.get(endpoint + "/review").json()
    assert client.post(endpoint + "/approve-dataset", json={"hash": review["hash"]}).status_code == 422
    edits = [{"file": row["file"], "text": row["text"], "include": True, "reviewed": True} for row in rows]
    revised = client.put(endpoint + "/review/bulk", json={"hash": review["hash"], "edits": edits})
    assert revised.status_code == 200
    assert client.post(endpoint + "/approve-dataset", json={"hash": revised.json()["hash"]}).status_code == 200
    assert client.post(endpoint + "/actions", json=request).status_code == 202
    assert client.post(endpoint + "/actions", json=request).status_code == 202
    assert len(queued) == 1
    function, *arguments = queued[0]
    function(*arguments)
    assert training.read_json(job / "actions" / f"{request['request_id']}.json")["status"] == "succeeded"
    assert not worker.CONTROL_BUSY
    runs = client.get(endpoint).json()["runs"]
    assert len(runs) == 1 and runs[0]["profile"]["status"] == "awaiting_review"
    assert runs[0]["profile"]["job_id"] == job.name and runs[0]["profile"]["name"] == "Podcast"
    run_dir = job / "runs" / runs[0]["run_id"]
    assert training.read_json(run_dir / "review.json") == training.read_json(job / "review.json")
    assert training.read_json(job / "selection.json")["source_type"] == "youtube"
    assert any("prepare_dataset.py" in args for args in commands)
    assert any(Path(args[1]).name == "train_resumable.py" and args[-1] == 2 for args in commands if args[0] != "ffmpeg")
    assert client.post(endpoint + "/actions", json={"request_id": str(uuid4()), "kind": "load",
                                                   "run_id": runs[0]["run_id"]}).status_code == 409


def test_youtube_worker_bundle_and_control_notebook_include_downloader_dependencies():
    from server.api.routes import training_control as local
    base = Path(__file__).resolve().parents[2]
    with zipfile.ZipFile(io.BytesIO(local.worker_bundle().body)) as bundle:
        required = {"voice_training.py", "train_resumable.py", "training_control.py", "audio_worker.py", "youtube_source.py"}
        assert required <= set(bundle.namelist())
        for name in required:
            compile(bundle.read(name), name, "exec")
        assert bundle.read("youtube_source.py") == (base / "server/audio/youtube_source.py").read_bytes()
    notebook = json.loads((base / "colab/control_voice_training.ipynb").read_text(encoding="utf-8"))
    bootstrap = next("".join(cell["source"]) for cell in notebook["cells"]
                     if cell["cell_type"] == "code" and "required =" in "".join(cell["source"]))
    compile(bootstrap, "control_voice_training bootstrap", "exec")
    assert "'youtube_source.py'" in bootstrap and "'yt-dlp>=2025.1,<2027'" in bootstrap
    assert "'ffmpeg'" in bootstrap and "'[finetune]'" in bootstrap and "'faster-whisper==1.1.1'" in bootstrap
