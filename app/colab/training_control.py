"""Authenticated Colab control plane; model work shares the audio worker executor."""
import gc
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Literal

import audio_worker as worker
import voice_training as training
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/training")
ACTIVE = ""

def job_path(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(422, "Job ID không hợp lệ.")
    job = training.ROOT / job_id
    if not (job / "selection.json").exists():
        raise HTTPException(404, "Chưa có lựa chọn này trên Drive.")
    return job

def run_path(job, run_id):
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise HTTPException(422, "Run ID không hợp lệ.")
    path = job / "runs" / run_id
    if not path.is_dir():
        raise HTTPException(404, "Không có lượt train.")
    return path

def idle():
    if worker.ACTIVE or worker.CONTROL_BUSY:
        raise HTTPException(409, "Colab đang chạy tác vụ. Chờ hoàn tất hoặc hủy trước.")

def downloads_complete(job):
    path = job / "downloads.json"
    if not path.exists():
        return False
    receipts = training.read_json(path)
    manifest = training.read_json(job / "selection.json")
    for item in manifest["files"]:
        receipt = receipts.get(item["id"])
        if not receipt or Path(receipt["file"]).name != receipt["file"]:
            return False
        source = job / "source" / receipt["file"]
        size = receipt.get("download_bytes", 0) if manifest.get("source_type") == "youtube" else item["size"]
        if not source.is_file() or size <= 0 or source.stat().st_size != size:
            return False
    return True

def dataset_approved(job):
    review, approval = job / "review.json", job / "dataset-approved.json"
    return (review.exists() and approval.exists()
            and training.read_json(approval).get("review_sha256") == training.sha256(review))

def unload():
    worker.PIPELINE = None
    worker.STT_MODEL = None
    worker.STT_REVISION = ""
    worker.REVISION = ""
    worker.VOICES = ()
    worker.VOICE_FILES = {}
    worker.VOICE_METADATA = []
    gc.collect()
    import torch
    torch.cuda.empty_cache()

@router.get("/health")
def control_health():
    return {"api_version": "1", "training_version": "2", "runtime_id": worker.RUNTIME_ID,
            "local_dataset_upload": True,
            "local_media_upload": "chunks-v1", "upload_chunk_bytes": training.UPLOAD_CHUNK_BYTES,
            "youtube_source": "single-video-v1",
            "transcript_recovery": True,
            "busy": bool(worker.CONTROL_BUSY or worker.ACTIVE), "active_action": ACTIVE,
            "tts": worker.health(), "voices": worker.voices()}

@router.post("/selections")
def selection(manifest: dict):
    with worker.LOCK:
        idle()
        if len(json.dumps(manifest)) > 8 * 1024**2:
            raise HTTPException(413, "Manifest quá lớn.")
        path = Path("/content") / f"selection-{uuid.uuid4().hex}.json"
        try:
            training.write_json(path, manifest)
            job = training.open_selection(path)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "Manifest lựa chọn không hợp lệ.") from exc
        finally:
            path.unlink(missing_ok=True)
        return {"job_id": job.name}

@router.post("/jobs/{job_id}/sources/{file_id}")
async def upload_source(job_id: str, file_id: str, file: UploadFile = File(...)):
    content = await file.read(32 * 1024**2 + 1)
    if len(content) > 32 * 1024**2:
        raise HTTPException(413, "Mỗi WAV local tối đa 32 MiB.")
    with worker.LOCK:
        idle()
        job = job_path(job_id)
        manifest = training.read_json(job / "selection.json")
        item = next((item for item in manifest["files"] if item["id"] == file_id), None)
        checksum = hashlib.sha256(content).hexdigest()
        if (manifest.get("source_type") != "local" or item is None
                or len(content) != item["size"] or checksum != item["sha256"]):
            raise HTTPException(422, "WAV không khớp lựa chọn/checksum đã khóa.")
        source = job / "source" / f"{file_id}.wav"
        source.parent.mkdir(exist_ok=True)
        if not source.is_file() or training.sha256(source) != checksum:
            temporary = source.with_suffix(".part")
            temporary.write_bytes(content)
            temporary.replace(source)
        receipts_path = job / "downloads.json"
        receipts = training.read_json(receipts_path) if receipts_path.exists() else {}
        receipts[file_id] = {"file": source.name, "sha256": checksum}
        training.write_json(receipts_path, receipts)
        return {"file_id": file_id, "stored": True, "checksum": checksum}


def local_source(job_id, file_id):
    job = job_path(job_id)
    manifest = training.read_json(job / "selection.json")
    item = next((item for item in manifest["files"] if item["id"] == file_id), None)
    if manifest.get("source_type") != "local" or manifest.get("upload_protocol") != "chunks-v1" or item is None:
        raise HTTPException(422, "Không có nguồn media local trong lựa chọn này.")
    return job, item, job / "source" / (file_id + Path(item["key"]).suffix.lower())


@router.get("/jobs/{job_id}/sources/{file_id}/status")
def source_status(job_id: str, file_id: str):
    with worker.LOCK:
        job, item, source = local_source(job_id, file_id)
        receipts = training.read_json(job / "downloads.json") if (job / "downloads.json").exists() else {}
        receipt = receipts.get(file_id)
        if receipt and source.is_file() and source.stat().st_size == item["size"]:
            return {"offset": item["size"], "stored": True, "checksum": receipt["sha256"]}
        if source.is_file() and source.stat().st_size == item["size"]:
            return {"offset": item["size"], "stored": False}  # Recover a rename before receipt persistence.
        part = source.with_suffix(source.suffix + ".part")
        return {"offset": part.stat().st_size if part.is_file() else 0, "stored": False}


@router.post("/jobs/{job_id}/sources/{file_id}/chunks")
async def upload_source_chunk(job_id: str, file_id: str, offset: int = Form(...), checksum: str = Form(...),
                              file: UploadFile = File(...)):
    content = await file.read(training.UPLOAD_CHUNK_BYTES + 1)
    if not 0 < len(content) <= training.UPLOAD_CHUNK_BYTES:
        raise HTTPException(413, "Mỗi phần upload phải có 1 byte–8 MiB.")
    if offset < 0 or not re.fullmatch(r"[a-f0-9]{64}", checksum) or hashlib.sha256(content).hexdigest() != checksum:
        raise HTTPException(422, "Offset/checksum phần upload không hợp lệ.")
    with worker.LOCK:
        idle()
        job, item, source = local_source(job_id, file_id)
        status = source_status(job_id, file_id)
        if status["stored"]:
            if offset + len(content) > item["size"]:
                raise HTTPException(422, "Phần upload vượt kích thước lựa chọn.")
            with source.open("rb") as saved:
                saved.seek(offset)
                if saved.read(len(content)) != content:
                    raise HTTPException(409, "Phần upload khác bản đã lưu. Tạo lựa chọn mới.")
            return status
        source.parent.mkdir(exist_ok=True)
        part = source.with_suffix(source.suffix + ".part")
        staged = source if source.is_file() and source.stat().st_size == item["size"] else part
        current = status["offset"]
        if offset < current and offset + len(content) <= current:
            with staged.open("rb") as saved:
                saved.seek(offset)
                if saved.read(len(content)) != content:
                    raise HTTPException(409, "Phần upload khác checkpoint. Tạo lựa chọn mới.")
        elif offset != current:
            raise HTTPException(409, "Offset upload khác checkpoint. Đọc trạng thái và gửi lại.")
        else:
            if current + len(content) > item["size"]:
                raise HTTPException(422, "Phần upload vượt kích thước lựa chọn.")
            if training.shutil.disk_usage(source.parent).free < len(content) + 1024**3:
                raise HTTPException(413, "Drive không đủ dung lượng ghi phần media tiếp theo.")
            with part.open("ab") as output:
                output.write(content)
        current = staged.stat().st_size
        if current < item["size"]:
            return {"offset": current, "stored": False}
        try:
            media = training.probe_media(staged)
        except (ValueError, KeyError, subprocess.SubprocessError) as exc:
            staged.unlink(missing_ok=True)
            raise HTTPException(422, "Media không có âm thanh/thời lượng hợp lệ. Kiểm tra file và tạo lại lựa chọn.") from exc
        final_checksum = training.sha256(staged)
        if staged != source:
            part.replace(source)
        path = job / "downloads.json"
        receipts = training.read_json(path) if path.exists() else {}
        receipts[file_id] = {"file": source.name, "sha256": final_checksum, "media": media}
        training.write_json(path, receipts)
        return {"offset": current, "stored": True, "checksum": final_checksum}

@router.get("/jobs")
def jobs():
    return [{"job_id": path.parent.name, "voice_name": training.read_json(path)["voice_name"]}
            for path in training.ROOT.glob("*/selection.json")]

@router.get("/jobs/{job_id}")
def status(job_id: str):
    job = job_path(job_id)
    actions = []
    for path in (job / "actions").glob("*.json"):
        item = training.read_json(path)
        if item["status"] == "running" and (item.get("runtime_id") != worker.RUNTIME_ID or item["request_id"] != ACTIVE):
            item["status"] = "interrupted"
        actions.append(item)
    runs = []
    for path in (job / "runs").glob("*"):
        if not path.is_dir():
            continue
        runs.append({"run_id": path.name, "profile": training.read_json(path / "profile.json") if (path / "profile.json").exists() else None,
                     "sample_options": training.read_json(path / "sample.json").get("inference_options") if (path / "sample.json").exists() else None,
                     "sample_revision": training.sha256(path / "sample.json") if (path / "sample.json").exists() else "",
                     "epochs": training.read_json(path / "trainer-config.json")["epochs"] if (path / "trainer-config.json").exists() else 3,
                     "progress": training.read_json(path / "progress.json") if (path / "progress.json").exists() else None,
                     "can_resume": (path / "trainer-state.pt").exists() and not (path / "profile.json").exists(),
                     "has_sample": (path / "sample.wav").exists()})
    return {"job_id": job_id, "selection": training.read_json(job / "selection.json"),
            "source_provenance": list(training.read_json(job / "downloads.json").values()) if (job / "downloads.json").exists() else [],
            "actions": sorted(actions, key=lambda item: item["created_at"], reverse=True), "runs": runs,
            "has_downloads": downloads_complete(job),
            "recovery_progress": training.read_json(job / "recovery-proposals.json").get("progress") if (job / "recovery-proposals.json").exists() else None,
            "has_dataset": (job / "review.json").exists(), "dataset_approved": dataset_approved(job)}

class Action(BaseModel):
    request_id: uuid.UUID
    kind: Literal["download", "prepare", "verify-transcripts", "recover-transcripts", "train", "resume", "sample", "load"]
    run_id: str = ""
    epochs: int = Field(default=3, ge=1, le=20)
    text: str = Field(default="", max_length=1500)
    temperature: float = Field(default=0.8, ge=0.1, le=1.5, allow_inf_nan=False, strict=True)
    seed: int = Field(default=42, ge=0, le=4294967295, strict=True)

def process(job, body, path):
    global ACTIVE
    try:
        if body.kind != "download":
            unload()
        if body.kind == "load":
            training.configure_worker(run_path(job, body.run_id))
        else:
            log = path.with_suffix(".log")
            env = dict(os.environ)
            env["PYTHONUNBUFFERED"] = "1"
            if body.kind == "download" and training.read_json(job / "selection.json").get("source_type", "r2") == "r2":
                from google.colab import userdata
                env["R2_ACCESS_KEY_ID"] = userdata.get("R2_ACCESS_KEY_ID")
                env["R2_SECRET_ACCESS_KEY"] = userdata.get("R2_SECRET_ACCESS_KEY")
            with log.open("w", encoding="utf-8") as output:
                subprocess.run([sys.executable, "-u", str(Path(__file__).resolve()), "--execute", str(path)],
                               cwd="/content", env=env, stdout=output, stderr=subprocess.STDOUT, check=True)
        record = training.read_json(path)
        record["status"] = "cancelled" if (job / "cancel.request").exists() else "succeeded"
        training.write_json(path, record)
    except Exception:
        record = training.read_json(path)
        record.update(status="cancelled" if (job / "cancel.request").exists() else "failed",
                      error="Bước chưa hoàn tất. Xem log Colab; có thể tiếp tục từ file/checkpoint đã lưu.")
        failure = job / "download-error.json"
        if body.kind == "download" and failure.exists():
            record["error"] = training.read_json(failure)["error"]
        training.write_json(path, record)
    finally:
        with worker.LOCK:
            ACTIVE = ""
            worker.CONTROL_BUSY = False

@router.post("/jobs/{job_id}/actions", status_code=202)
def action(job_id: str, body: Action):
    global ACTIVE
    job = job_path(job_id)
    path = job / "actions" / f"{body.request_id}.json"
    with worker.LOCK:
        if path.exists():
            old = training.read_json(path)
            if Action.model_validate(old["input"]).model_dump(mode="json") != body.model_dump(mode="json"):
                raise HTTPException(409, "Request ID thuộc tác vụ khác.")
            return old
        idle()
        if body.kind == "prepare" and not downloads_complete(job):
            raise HTTPException(409, "Tải đủ các file đã chọn trước khi tách audio / chép lời.")
        if body.kind == "verify-transcripts":
            try:
                training.verification_inputs(job)
            except (RuntimeError, KeyError, FileNotFoundError) as exc:
                raise HTTPException(409, "Chọn các clip hợp lệ trong dataset trước khi đối chiếu transcript.") from exc
        if body.kind == "recover-transcripts":
            try:
                training.recovery_inputs(job)
            except (RuntimeError, KeyError, FileNotFoundError) as exc:
                raise HTTPException(409, "Cần clip và nguồn gốc hợp lệ trước khi khôi phục transcript.") from exc
        if body.kind in ("train", "resume") and not dataset_approved(job):
            raise HTTPException(409, "Duyệt dataset hiện tại trước khi huấn luyện.")
        if body.kind in ("sample", "load", "resume"):
            run_path(job, body.run_id)
        if body.kind == "resume":
            run = run_path(job, body.run_id)
            config = run / "trainer-config.json"
            if (not (run / "trainer-state.pt").exists() or (run / "profile.json").exists()
                    or not config.exists() or training.read_json(config).get("epochs") != body.epochs
                    or not (run / "review.json").exists()
                    or training.sha256(run / "review.json") != training.sha256(job / "review.json")):
                raise HTTPException(409, "Checkpoint, dataset hoặc epochs không khớp. Dùng đúng lượt cũ hoặc train phiên bản mới.")
        if body.kind == "sample" and not (run_path(job, body.run_id) / "profile.json").exists():
            raise HTTPException(409, "Lượt train chưa đóng gói model để nghe thử.")
        if body.kind == "sample" and not body.text.strip():
            raise HTTPException(422, "Nhập câu nghe thử.")
        if body.kind == "load":
            profile = run_path(job, body.run_id) / "profile.json"
            if not profile.exists() or training.read_json(profile)["status"] != "approved":
                raise HTTPException(409, "Duyệt giọng trước khi load.")
        (job / "cancel.request").unlink(missing_ok=True)
        record = {"request_id": str(body.request_id), "job_id": job_id, "input": body.model_dump(mode="json"),
                  "status": "running", "runtime_id": worker.RUNTIME_ID, "created_at": time.time()}
        training.write_json(path, record)
        worker.CONTROL_BUSY = True
        ACTIVE = str(body.request_id)
        worker.EXECUTOR.submit(process, job, body, path)
        return record

@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    job = job_path(job_id)
    with worker.LOCK:
        if not ACTIVE or not (job / "actions" / f"{ACTIVE}.json").exists():
            raise HTTPException(409, "Không có tác vụ đang chạy của bộ dữ liệu này.")
        (job / "cancel.request").touch()
    return {"status": "cancel_requested", "message": "Dừng ở ranh giới file/bước optimizer hoặc sau công đoạn hiện tại."}

@router.get("/jobs/{job_id}/review")
def review(job_id: str):
    job = job_path(job_id)
    path = job / "review.json"
    rows, summary = training.review_assessments(job, training.read_json(path) if path.exists() else [])
    return {"hash": training.sha256(path) if path.exists() else "", "rows": rows, "review_summary": summary}

class ReviewRowEdit(BaseModel):
    file: str
    text: str = Field(max_length=4000)
    include: bool
    reviewed: bool
    review_method: Literal["manual_listening", "text_acoustic_review"] = "manual_listening"

class ReviewEdit(ReviewRowEdit):
    hash: str

class ReviewBulk(BaseModel):
    hash: str
    edits: list[ReviewRowEdit] = Field(min_length=1, max_length=5000)

def apply_review_edits(job, expected_hash, edits):
    with worker.LOCK:
        idle()
        path = job / "review.json"
        if not path.exists() or training.sha256(path) != expected_hash:
            raise HTTPException(409, "Dataset đã thay đổi; tải lại.")
        rows = training.read_json(path)
        indexed = {row["file"]: row for row in rows}
        if len({edit.file for edit in edits}) != len(edits):
            raise HTTPException(422, "Không được sửa cùng đoạn nhiều lần trong một lượt.")
        for edit in edits:
            row = indexed.get(edit.file)
            if row is None:
                raise HTTPException(404, "Không có đoạn này.")
            if edit.reviewed and edit.review_method == "text_acoustic_review" and (not row.get("asr") or not row.get("signal")):
                raise HTTPException(409, "Cần metadata ASR và kiểm tra tín hiệu trước khi khai báo duyệt văn bản/tín hiệu.")
        for edit in edits:
            indexed[edit.file].update(text=" ".join(edit.text.replace("|", " ").split()), include=edit.include,
                                      reviewed=edit.reviewed, review_method=edit.review_method)
        training.write_json(path, rows)
        (job / "dataset-approved.json").unlink(missing_ok=True)
        return review(job.name)

@router.put("/jobs/{job_id}/review")
def edit_review(job_id: str, body: ReviewEdit):
    return apply_review_edits(job_path(job_id), body.hash, [body])

@router.put("/jobs/{job_id}/review/bulk")
def edit_review_bulk(job_id: str, body: ReviewBulk):
    return apply_review_edits(job_path(job_id), body.hash, body.edits)

class Approval(BaseModel):
    hash: str = ""
    heard: bool = False

@router.post("/jobs/{job_id}/approve-dataset")
def approve_dataset(job_id: str, body: Approval):
    job = job_path(job_id)
    with worker.LOCK:
        idle()
        value = review(job_id)
        rows = [r for r in value["rows"] if r["include"]]
        if value["hash"] != body.hash or len(rows) < 20 or any(not r["reviewed"] or not r["text"]
                or r.get("review_method", "manual_listening") not in ("manual_listening", "text_acoustic_review") for r in rows):
            raise HTTPException(422, "Cần tối thiểu 20 đoạn đã duyệt với cách kiểm tra được khai báo; bản dữ liệu phải khớp.")
        counts = {method: sum(row.get("review_method", "manual_listening") == method for row in rows)
                  for method in ("manual_listening", "text_acoustic_review")}
        training.write_json(job / "dataset-approved.json", {"review_sha256": value["hash"], "review_methods": counts})
        return {"approved": True}

@router.get("/jobs/{job_id}/clips/{file}")
def clip(job_id: str, file: str):
    job = job_path(job_id)
    if not any(row["file"] == file for row in review(job_id)["rows"]) or Path(file).name != file:
        raise HTTPException(404, "Không có đoạn audio.")
    return FileResponse(job / "dataset/raw_audio" / file, media_type="audio/wav")

@router.get("/jobs/{job_id}/runs/{run_id}/sample")
def sample(job_id: str, run_id: str):
    path = run_path(job_path(job_id), run_id) / "sample.wav"
    if not path.exists():
        raise HTTPException(404, "Chưa sinh mẫu.")
    return FileResponse(path, media_type="audio/wav")

@router.post("/jobs/{job_id}/runs/{run_id}/approve")
def approve_voice(job_id: str, run_id: str, body: Approval):
    with worker.LOCK:
        idle()
        if not body.heard:
            raise HTTPException(422, "Nghe mẫu và xác nhận trước.")
        sample_metadata = run_path(job_path(job_id), run_id) / "sample.json"
        if body.hash and (not sample_metadata.exists() or training.sha256(sample_metadata) != body.hash):
            raise HTTPException(409, "Mẫu đã thay đổi. Nghe mẫu hiện tại trước khi duyệt.")
        try:
            training.approve_voice(run_path(job_path(job_id), run_id))
        except (RuntimeError, FileNotFoundError) as exc:
            raise HTTPException(409, "Sinh và nghe mẫu của lượt train hiện tại trước khi duyệt giọng.") from exc
        return {"approved": True}

worker.app.include_router(router)

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--execute":
    record = training.read_json(sys.argv[2])
    job = job_path(record["job_id"])
    body = Action.model_validate(record["input"])
    if body.kind == "download":
        (job / "download-error.json").unlink(missing_ok=True)
        try:
            training.download_selected(job)
        except RuntimeError as exc:
            if training.read_json(job / "selection.json").get("source_type") == "youtube":
                training.write_json(job / "download-error.json", {"error": str(exc)})
            raise
    elif body.kind == "prepare":
        training.prepare_clips(job)
    elif body.kind == "verify-transcripts":
        training.verify_transcripts(job)
    elif body.kind == "recover-transcripts":
        training.recover_transcripts(job)
    elif body.kind in ("train", "resume"):
        training.train(job, body.epochs, body.run_id if body.kind == "resume" else None)
    elif body.kind == "sample":
        training.sample_voice(run_path(job, body.run_id), body.text, temperature=body.temperature, seed=body.seed)
