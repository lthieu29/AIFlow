"""Offline full-clip ASR recovery and read-only review projections."""
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from server.tests import test_training_control

checkpoint_preparer = test_training_control.checkpoint_preparer


@pytest.fixture
def control(request):
    return request.getfixturevalue("shared_control")


shared_control = test_training_control.control


def recovery_dataset(training, job, count=2):
    source = job / "source/source.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original source")
    checksum = training.sha256(source)
    training.write_json(job / "selection.json", {"language": "vi", "files": [{"id": "source", "key": "video"}]})
    training.write_json(job / "downloads.json", {"source": {"file": source.name, "sha256": checksum}})
    rows = []
    for index in range(count):
        clip = job / f"dataset/raw_audio/{index}.wav"
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(f"audio {index}".encode())
        rows.append({"file": clip.name, "source": "video", "source_sha256": checksum,
                     "sha256": training.sha256(clip), "text": "saved original", "start": 10 + index * 5,
                     "duration": 3, "include": False, "reviewed": True, "review_method": "text_acoustic_review",
                     "asr": {"mean_word_probability": 0.1}, "signal": {"rms_dbfs": -18}})
    training.write_json(job / "review.json", rows)
    training.write_json(job / "dataset-approved.json", {"review_sha256": training.sha256(job / "review.json")})
    return rows, source


def fake_asr(training, monkeypatch, segments=None):
    calls, downloads, releases, normalizations = [], [], [], []
    segments = segments if segments is not None else [SimpleNamespace(start=0, end=3, words=None, text="đúng 42 English")]
    def transcribe(path, **kwargs):
        calls.append(Path(path).name)
        assert kwargs == {"language": "vi", **training.RECOVERY_POLICY["decode"]}
        return iter(segments), SimpleNamespace()
    def create_model(*args, **kwargs):
        assert kwargs == {"device": "cuda", "compute_type": training.RECOVERY_POLICY["compute_type"]}
        return SimpleNamespace(transcribe=transcribe)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(
        WhisperModel=create_model))
    def download(repo, **kwargs):
        downloads.append((repo, kwargs["revision"]))
        return "immutable-model"
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        HfApi=lambda: SimpleNamespace(model_info=lambda repo: SimpleNamespace(sha="immutable-sha")),
        snapshot_download=download))
    monkeypatch.setattr(training, "gpu", lambda: SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: releases.append(True))))
    monkeypatch.setattr(training, "probe_media", lambda source: {"duration": 60})
    monkeypatch.setattr(training, "normalize_audio", lambda *args: normalizations.append(args))
    return calls, downloads, releases, normalizations


def test_excluded_recovery_uses_original_clips_and_preserves_dataset_and_approval(control, monkeypatch):
    _, training, _, _, client, job = control
    rows, _ = recovery_dataset(training, job)
    review_bytes, approval_bytes = (job / "review.json").read_bytes(), (job / "dataset-approved.json").read_bytes()
    calls, downloads, releases, normalizations = fake_asr(training, monkeypatch)
    training.recover_transcripts(job)
    assert len(calls) == 2 and len(downloads) == 1 and len(releases) == 1
    assert calls == ["0.wav", "1.wav"] and not normalizations
    assert (job / "review.json").read_bytes() == review_bytes
    assert (job / "dataset-approved.json").read_bytes() == approval_bytes
    proposals = training.read_json(job / "recovery-proposals.json")
    assert proposals["progress"] == {"total": 2, "completed": 2}
    assert all(proposal["text"] == "đúng 42 English" and proposal["complete"] for proposal in proposals["rows"].values())
    result = client.get(f"/v1/training/jobs/{job.name}/review").json()
    assert result["hash"] == training.sha256(job / "review.json")
    assert result["rows"][0]["review_assessment"]["candidate_text"] == "đúng 42 English"
    assert result["rows"][0]["review_assessment"]["status"] == "transcript_disagreement"
    assert result["review_summary"]["excluded_count"] == 2
    assert result["review_summary"]["included_seconds"] == 0
    assert training.read_json(job / "review.json") == rows


def test_cancelled_recovery_resumes_only_fresh_proposals(control, monkeypatch):
    _, training, _, _, _, job = control
    recovery_dataset(training, job)
    calls, _, releases, _ = fake_asr(training, monkeypatch)
    write = training.write_json
    def cancel_after_proposal(path, value):
        write(path, value)
        if path.name == "recovery-proposals.json" and value["progress"]["completed"]:
            (job / "cancel.request").touch()
    monkeypatch.setattr(training, "write_json", cancel_after_proposal)
    with pytest.raises(RuntimeError, match="Đã dừng"):
        training.recover_transcripts(job)
    assert len(calls) == 1 and len(releases) == 1
    assert training.read_json(job / "recovery-proposals.json")["progress"]["completed"] == 1
    (job / "cancel.request").unlink()
    monkeypatch.setattr(training, "write_json", write)
    training.recover_transcripts(job)
    assert len(calls) == 2
    training.recover_transcripts(job)
    assert len(calls) == 2


def test_wrong_model_pin_does_not_expose_or_reuse_proposal(control, monkeypatch):
    _, training, _, _, client, job = control
    recovery_dataset(training, job, 1)
    fake_asr(training, monkeypatch)
    training.recover_transcripts(job)
    training.write_json(job / "recovery-revision.json", {"repo": "wrong-repo", "revision": "immutable-sha"})
    result = client.get(f"/v1/training/jobs/{job.name}/review").json()
    assert result["rows"][0]["review_assessment"]["candidate_text"] is None
    with pytest.raises(RuntimeError, match="Phiên bản model"):
        training.recover_transcripts(job)


def test_changed_text_clip_and_source_invalidate_recovery_cache(control, monkeypatch):
    _, training, _, _, client, job = control
    rows, source = recovery_dataset(training, job, 1)
    calls, _, _, _ = fake_asr(training, monkeypatch)
    training.recover_transcripts(job)
    rows[0]["text"] = "new label"
    training.write_json(job / "review.json", rows)
    assert client.get(f"/v1/training/jobs/{job.name}/review").json()["rows"][0]["review_assessment"]["candidate_text"] is None
    training.recover_transcripts(job)
    clip = job / "dataset/raw_audio" / rows[0]["file"]
    clip.write_bytes(b"different clip")
    with pytest.raises(RuntimeError, match="Clip đã đổi"):
        training.recover_transcripts(job)
    rows[0]["sha256"] = training.sha256(clip)
    training.write_json(job / "review.json", rows)
    training.recover_transcripts(job)
    source.write_bytes(b"different source")
    with pytest.raises(RuntimeError, match="Checksum nguồn đã đổi"):
        training.recover_transcripts(job)
    rows[0]["source_sha256"] = training.sha256(source)
    training.write_json(job / "downloads.json", {"source": {"file": source.name, "sha256": rows[0]["source_sha256"]}})
    training.write_json(job / "review.json", rows)
    training.recover_transcripts(job)
    assert len(calls) == 4


def test_phantom_segment_end_preserves_all_text_but_marks_incomplete(control, monkeypatch):
    _, training, _, _, _, job = control
    rows, _ = recovery_dataset(training, job, 1)
    rows[0]["duration"] = 2.14
    training.write_json(job / "review.json", rows)
    fake_asr(training, monkeypatch, [SimpleNamespace(start=0, end=29.98, text="Đăng ký kênh Ghiền Mì Gõ")])
    training.recover_transcripts(job)
    proposal = training.read_json(job / "recovery-proposals.json")["rows"]["0.wav"]
    assert proposal["text"] == "Đăng ký kênh Ghiền Mì Gõ" and not proposal["complete"]
    assert proposal["issues"] == ["invalid_segment_timestamps"]
    assert proposal["segments"] == [{"start": 0, "end": 29.98, "text": "Đăng ký kênh Ghiền Mì Gõ"}]


def test_missing_or_zero_duration_word_alignment_does_not_remove_first_word(control, monkeypatch):
    _, training, _, _, _, job = control
    recovery_dataset(training, job, 1)
    fake_asr(training, monkeypatch, [SimpleNamespace(start=0, end=1.5, text="Đúng lời đầu", words=[
        SimpleNamespace(start=0, end=0, word="Đúng")]),
        SimpleNamespace(start=1.5, end=3, text="và lời cuối", words=None)])
    training.recover_transcripts(job)
    proposal = training.read_json(job / "recovery-proposals.json")["rows"]["0.wav"]
    assert proposal["text"] == "Đúng lời đầu và lời cuối" and proposal["complete"]


@pytest.mark.parametrize("segments,issue", [
    ([SimpleNamespace(start=float("nan"), end=3, text="kept")], "invalid_segment_timestamps"),
    ([SimpleNamespace(start=0, end=0, text="kept")], "invalid_segment_timestamps"),
    ([SimpleNamespace(start=0, end=2, text="first"), SimpleNamespace(start=1, end=3, text="second")], "invalid_segment_timestamps"),
    ([SimpleNamespace(start=0, end=3, text="Xin chào xin chào xin chào")], "repeated_text"),
    ([SimpleNamespace(start=0, end=3, text="")], "empty_segment"),
])
def test_segment_anomalies_are_retained_and_advisory(control, monkeypatch, segments, issue):
    _, training, _, _, _, job = control
    recovery_dataset(training, job, 1)
    fake_asr(training, monkeypatch, segments)
    training.recover_transcripts(job)
    proposal = training.read_json(job / "recovery-proposals.json")["rows"]["0.wav"]
    assert proposal["text"] == " ".join(segment.text for segment in segments).strip()
    assert not proposal["complete"] and issue in proposal["issues"]


def test_policy_and_compute_type_change_archives_previous_sidecar_before_rerun(control, monkeypatch):
    _, training, _, _, _, job = control
    rows, _ = recovery_dataset(training, job, 1)
    old_identity = training.recovery_identity(rows[0], "vi")
    old_identity["policy"] = {"version": 1, "mode": "source_context"}
    path = job / "recovery-proposals.json"
    training.write_json(path, {"rows": {"0.wav": {"identity": old_identity, "text": "old context proposal"}}})
    old_bytes, old_hash = path.read_bytes(), training.sha256(path)
    calls, _, _, _ = fake_asr(training, monkeypatch)
    training.recover_transcripts(job)
    assert (job / f"recovery-proposals-{old_hash}.json").read_bytes() == old_bytes
    assert training.read_json(path)["rows"]["0.wav"]["method"] == "recovered_full_clip"
    first_bytes, first_hash = path.read_bytes(), training.sha256(path)
    monkeypatch.setattr(training, "RECOVERY_POLICY", {**training.RECOVERY_POLICY, "compute_type": "int8_float16"})
    training.recover_transcripts(job)
    assert (job / f"recovery-proposals-{first_hash}.json").read_bytes() == first_bytes
    assert len(calls) == 2


def test_mixed_language_numbers_and_low_confidence_are_advisory(control):
    _, training, _, _, _, job = control
    rows, _ = recovery_dataset(training, job, 1)
    rows[0].update(text="Năm 2026 English 42", include=True, reviewed=True)
    result, summary = training.review_assessments(job, rows)
    assert result[0]["review_assessment"]["status"] == "ready"
    assert not result[0]["review_assessment"]["recoverable"]
    assert summary["status_counts"]["acoustic_issue"] == 0
    rows[0]["signal"]["clipped_fraction"] = 0.1
    assert training.review_assessments(job, rows)[0][0]["review_assessment"]["status"] == "acoustic_issue"
    assert training.transcript_key("Đúng 42!") == training.transcript_key(unicodedata.normalize("NFD", "đúng 42"))
    assert training.transcript_key("đúng") != training.transcript_key("dung")


@pytest.mark.parametrize("mode", ["new", "legacy_small", "legacy_large"])
def test_new_prepare_uses_float16_and_legacy_pins_preserve_dtype_and_resume(control, monkeypatch, mode):
    training, job, calls = checkpoint_preparer(control, monkeypatch)
    if mode == "legacy_small":
        training.write_json(job / "asr-revision.json", {"revision": "revision"})
    elif mode == "legacy_large":
        training.write_json(job / "asr-revision.json", {"repo": training.RECOVERY_REPO, "revision": "revision"})
    downloads = []
    dtypes = []
    create_model = sys.modules["faster_whisper"].WhisperModel
    def factory(*args, **kwargs):
        dtypes.append(kwargs["compute_type"])
        return create_model(*args, **kwargs)
    monkeypatch.setattr(sys.modules["faster_whisper"], "WhisperModel", factory)
    monkeypatch.setattr(sys.modules["huggingface_hub"], "snapshot_download",
                        lambda repo, **kwargs: downloads.append(repo) or "pinned-model")
    with pytest.raises(RuntimeError, match="checkpoint"):
        training.prepare_clips(job)
    config = training.read_json(job / "prepare-checkpoints/file-0_c00000.json")["config"]
    if mode == "legacy_small":
        assert "asr_repo" not in config
    else:
        assert config["asr_repo"] == training.RECOVERY_REPO
    if mode == "new":
        assert config["compute_type"] == "float16"
    else:
        assert "compute_type" not in config
    (job / "cancel.request").unlink()
    training.prepare_clips(job)
    assert calls == ["file-0_normalized.wav", "file-1_normalized.wav"]
    assert downloads == ["Systran/faster-whisper-small" if mode == "legacy_small" else training.RECOVERY_REPO] * 2
    assert dtypes == ["float16" if mode == "new" else "int8_float16"] * 2


def test_recovery_action_accepts_excluded_and_rejects_invalid_before_unload(control):
    _, training, worker, queued, client, job = control
    rows, _ = recovery_dataset(training, job, 1)
    body = {"request_id": str(uuid4()), "kind": "recover-transcripts"}
    assert client.post(f"/v1/training/jobs/{job.name}/actions", json=body).status_code == 202
    assert len(queued) == 1
    worker.CONTROL_BUSY = False
    rows[0]["duration"] = 0
    training.write_json(job / "review.json", rows)
    body["request_id"] = str(uuid4())
    assert client.post(f"/v1/training/jobs/{job.name}/actions", json=body).status_code == 409
    assert len(queued) == 1 and not worker.CONTROL_BUSY
    assert client.get("/v1/training/health").json()["transcript_recovery"] is True
