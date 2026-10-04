"""Controlled preview metadata, approval and serving contract; no real TTS/quality claims."""

import hashlib
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from server.tests.test_training_control import control as control


@pytest.fixture
def preview(control, monkeypatch):
    module, training, worker, queued, client, job = control
    run = job / "runs" / ("b" * 32)
    profile = {"id": "ft_test", "name": "Test", "language": "vi", "status": "approved",
               "weights_sha256": "weights", "voices_sha256": "voices"}
    training.write_json(run / "profile.json", profile)
    torch = SimpleNamespace(manual_seed=Mock(), cuda=SimpleNamespace(
        is_available=lambda: True, manual_seed_all=Mock(), empty_cache=Mock()))
    numpy = SimpleNamespace(random=SimpleNamespace(seed=Mock()))
    monkeypatch.setitem(sys.modules, "vieneu_utils.phonemize_text", SimpleNamespace(
        normalize_to_chunks_v3_with_gaps=lambda text, **kw: ([text], [])))
    monkeypatch.setitem(sys.modules, "vieneu_utils.core_utils", SimpleNamespace(
        gaps_to_silence=Mock(), join_audio_chunks=Mock()))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "numpy", numpy)
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(
        write=lambda path, audio, rate: Path(path).write_bytes(audio)))
    monkeypatch.setitem(sys.modules, "IPython.display", SimpleNamespace(Audio=lambda *a, **k: None, display=lambda *a: None))
    monkeypatch.setattr(training, "gpu", lambda: torch)
    tts = SimpleNamespace(sample_rate=48000, infer=Mock(return_value=b"inference-test-marker"))
    monkeypatch.setattr(training, "load_voice", lambda path, **kw: (tts, training.read_json(Path(path) / "profile.json")))
    return module, training, worker, queued, client, run, tts, torch, numpy


@pytest.mark.parametrize("options", [
    {"temperature": 0.09}, {"temperature": 1.51}, {"temperature": float("nan")}, {"temperature": True},
    {"seed": -1}, {"seed": 4294967296}, {"seed": 1.5}, {"seed": True},
])
def test_invalid_options_never_enqueue_or_change_approval(preview, options):
    module, training, worker, queued, client, run, tts, _, _ = preview
    body = {"request_id": str(uuid4()), "kind": "sample", "run_id": run.name, "text": "Test", **options}
    if "temperature" in options and options["temperature"] != options["temperature"]:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            module.Action.model_validate(body)
    else:
        assert client.post(f"/v1/training/jobs/{run.parents[1].name}/actions", json=body).status_code == 422
    assert not queued and not worker.CONTROL_BUSY
    assert training.read_json(run / "profile.json")["status"] == "approved"
    tts.infer.assert_not_called()


def test_sample_seeds_inference_records_options_and_invalidates_approval(preview, monkeypatch):
    _, training, _, _, _, run, tts, torch, numpy = preview
    import random
    random_seed = Mock()
    monkeypatch.setattr(random, "seed", random_seed)
    training.sample_voice(run, "Test phrase", temperature=0.6, seed=73)
    tts.infer.assert_called_once_with("Test phrase", voice="Test", temperature=0.6, batch_size=1)
    random_seed.assert_called_once_with(73)
    numpy.random.seed.assert_called_once_with(73)
    torch.manual_seed.assert_called_once_with(73)
    torch.cuda.manual_seed_all.assert_called_once_with(73)
    assert training.read_json(run / "profile.json")["status"] == "awaiting_review"
    sample = training.read_json(run / "sample.json")
    assert sample["inference_options"] == {"temperature": 0.6, "seed": 73}
    assert sample["inference_policy"] == training.INFERENCE_POLICY
    assert sample["sample_sha256"] == training.sha256(run / "sample.wav")
    training.approve_voice(run)
    profile = training.read_json(run / "profile.json")
    assert profile["status"] == "approved" and profile["inference_options"] == sample["inference_options"]


@pytest.mark.parametrize("serving", [False, True], ids=["preview", "production"])
def test_multichunk_inference_preserves_text_order_anchor_and_request_seed(preview, monkeypatch, serving):
    _, training, worker, _, _, run, tts, torch, numpy = preview
    import random
    random_seed = Mock()
    monkeypatch.setattr(random, "seed", random_seed)
    chunks, gaps, pauses = ["long-first", "x", "middle"], ["sentence", "para"], [0.28, 0.5]
    normalizer = Mock(return_value=(chunks, gaps))
    join = Mock(return_value=b"joined-native-audio")
    gap_policy = Mock(return_value=pauses)
    monkeypatch.setitem(sys.modules, "vieneu_utils.phonemize_text", SimpleNamespace(
        normalize_to_chunks_v3_with_gaps=normalizer))
    monkeypatch.setitem(sys.modules, "vieneu_utils.core_utils", SimpleNamespace(
        gaps_to_silence=gap_policy, join_audio_chunks=join))

    def native_infer(text, voice=None, temperature=0.8, top_k=25, top_p=0.95,
                     max_new_frames=300, repetition_penalty=1.2, repetition_window=64, batch_size=None):
        pytest.fail("Multi-chunk synthesis must not use native length-sorted infer")

    tts.infer = native_infer
    speaker, reference = object(), object()
    tts._resolve_ref = Mock(return_value=(speaker, reference))
    tts._infer_chunks = Mock(side_effect=lambda parts, *args: [parts[0].encode()])
    tts._apply_watermark = Mock(return_value=b"watermarked-native-audio")
    before = (run / "profile.json").read_bytes()
    if serving:
        worker.PIPELINE = None
        worker.digest = Mock(return_value="policy-revision")
        stretch = Mock()
        monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace(effects=SimpleNamespace(time_stretch=stretch)))
        monkeypatch.setitem(sys.modules, "soxr", SimpleNamespace(resample=lambda audio, *args: audio))
        training.configure_worker(run)
        assert list(worker.PIPELINE("Complete narration", "Test")) == [(None, None, b"watermarked-native-audio")]
        stretch.assert_not_called()
        assert (run / "profile.json").read_bytes() == before
    else:
        training.sample_voice(run, "Complete narration")
        assert training.read_json(run / "sample.json")["inference_policy"] == training.INFERENCE_POLICY
    normalizer.assert_called_once_with("Complete narration", max_chars=256)
    random_seed.assert_called_once_with(42)
    numpy.random.seed.assert_called_once_with(42)
    torch.manual_seed.assert_called_once_with(42)
    torch.cuda.manual_seed_all.assert_called_once_with(42)
    tts._resolve_ref.assert_called_once_with("Test", None, True, True)
    sampling = {"top_k": 25, "top_p": 0.95, "max_new_frames": 300,
                "repetition_penalty": 1.2, "repetition_window": 64, "temperature": 0.8}
    assert [call.args for call in tts._infer_chunks.call_args_list] == [
        ([chunk], speaker, reference, True, 1, sampling) for chunk in chunks]
    gap_policy.assert_called_once_with(gaps)
    join.assert_called_once_with([chunk.encode() for chunk in chunks], 48000, silence_ps=pauses)
    tts._apply_watermark.assert_called_once_with(b"joined-native-audio")


def test_inference_policy_invalidates_cache_without_changing_approved_profile(preview, monkeypatch):
    _, training, worker, _, _, run, _, _, _ = preview
    from server.audio.remote import make_segments
    worker.PIPELINE = None
    worker.digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "soxr", SimpleNamespace())
    before = (run / "profile.json").read_bytes()
    legacy = worker.digest({"weights": "weights", "voices": "voices", "code": training.UPSTREAM_COMMIT,
                            "inference_options": {"temperature": 0.8, "seed": 42}})
    training.configure_worker(run)
    revision = worker.REVISION
    assert revision != legacy
    assert make_segments("Narration", "Test", "vi", 1.0, revision)[0]["key"] != make_segments(
        "Narration", "Test", "vi", 1.0, legacy)[0]["key"]
    worker.PIPELINE = None
    monkeypatch.setitem(training.INFERENCE_POLICY, "version", "different-policy")
    training.configure_worker(run)
    assert worker.REVISION != revision
    assert (run / "profile.json").read_bytes() == before


def test_approval_rejects_changed_audio_and_stale_listening_revision(preview):
    _, training, _, _, client, run, _, _, _ = preview
    training.sample_voice(run, "Test phrase")
    metadata_hash = training.sha256(run / "sample.json")
    route = f"/v1/training/jobs/{run.parents[1].name}/runs/{run.name}/approve"
    assert client.post(route, json={"heard": True, "hash": "old-preview"}).status_code == 409
    (run / "sample.wav").write_bytes(b"changed")
    assert client.post(route, json={"heard": True, "hash": metadata_hash}).status_code == 409
    assert training.read_json(run / "profile.json")["status"] == "awaiting_review"


def test_action_defaults_and_new_options_are_saved_without_replaying(preview):
    module, training, _, queued, client, run, _, _, _ = preview
    route = f"/v1/training/jobs/{run.parents[1].name}/actions"
    payload = {"request_id": str(uuid4()), "kind": "sample", "run_id": run.name,
               "text": "Test", "temperature": 0.6, "seed": 73}
    response = client.post(route, json=payload)
    assert response.status_code == 202, response.text
    assert response.json()["input"]["temperature"] == 0.6 and response.json()["input"]["seed"] == 73
    assert client.post(route, json=payload).status_code == 202 and len(queued) == 1
    assert client.post(route, json={**payload, "seed": 74}).status_code == 409
    old_id = str(uuid4())
    old_payload = {"request_id": old_id, "kind": "sample", "run_id": run.name, "text": "Old sample"}
    old_input = module.Action.model_validate(old_payload).model_dump(mode="json")
    old_input.pop("temperature")
    old_input.pop("seed")
    training.write_json(run.parents[1] / "actions" / f"{old_id}.json", {"input": old_input, "status": "succeeded"})
    assert client.post(route, json=old_payload).status_code == 202 and len(queued) == 1


def test_sample_child_dispatch_preserves_options(preview, monkeypatch):
    module, training, _, _, _, run, _, _, _ = preview
    path = run.parents[1] / "actions" / "sample-dispatch.json"
    training.write_json(path, {"job_id": run.parents[1].name, "input": {
        "request_id": str(uuid4()), "kind": "sample", "run_id": run.name,
        "text": "Controlled sample", "temperature": 0.6, "seed": 73,
    }})
    sample = Mock()
    monkeypatch.setattr(training, "sample_voice", sample)
    monkeypatch.setattr(sys, "argv", [module.__file__, "--execute", str(path)])
    runpy.run_path(module.__file__, run_name="__main__")
    sample.assert_called_once_with(run, "Controlled sample", temperature=0.6, seed=73)


def test_worker_uses_approved_options_and_changes_cache_revision(preview, monkeypatch):
    _, training, worker, _, _, run, tts, torch, numpy = preview
    worker.ACTIVE.clear()
    worker.PIPELINE = None
    worker.digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace(effects=SimpleNamespace(time_stretch=Mock())))
    monkeypatch.setitem(sys.modules, "soxr", SimpleNamespace(resample=lambda audio, *args: audio))
    training.sample_voice(run, "Test", temperature=0.6, seed=73)
    training.approve_voice(run)
    training.configure_worker(run)
    revision = worker.REVISION
    tts.infer.reset_mock()
    list(worker.PIPELINE("Production", "Test"))
    tts.infer.assert_called_once_with("Production", voice="Test", temperature=0.6, batch_size=1)
    assert torch.manual_seed.call_args.args == (73,) and numpy.random.seed.call_args.args == (73,)
    worker.PIPELINE = None
    training.sample_voice(run, "Test", temperature=0.8, seed=73)
    training.approve_voice(run)
    training.configure_worker(run)
    assert worker.REVISION != revision


def test_legacy_preview_and_profile_defaults_remain_readable(preview, monkeypatch):
    _, training, worker, _, _, run, _, _, _ = preview
    (run / "sample.wav").write_bytes(b"legacy")
    training.write_json(run / "sample.json", {"text": "Old", "weights_sha256": "weights"})
    training.approve_voice(run)
    assert training.read_json(run / "profile.json")["inference_options"] == {"temperature": 0.8, "seed": 42}


def test_sample_revision_query_preserves_binary_proxy_path(monkeypatch):
    from server.api.routes import training_control as local

    remote = Mock(return_value=Response(b"current-audio", media_type="audio/wav", headers={"Cache-Control": "no-store"}))
    monkeypatch.setattr(local, "remote", remote)
    app = FastAPI()
    app.include_router(local.router)
    path = "jobs/" + "a" * 32 + "/runs/" + "b" * 32 + "/sample"
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as client:
        response = client.get(f"/api/training-control/remote/{path}?revision={'c' * 64}")
    assert response.status_code == 200 and response.content == b"current-audio"
    assert response.headers["Cache-Control"] == "no-store"
    remote.assert_called_once_with(path, "GET", None, binary=True)
