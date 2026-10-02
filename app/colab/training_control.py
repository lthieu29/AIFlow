"""Authenticated Colab control plane; model work shares the audio worker executor."""
import gc
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import audio_worker as worker
import voice_training as training

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
                     "epochs": training.read_json(path / "trainer-config.json")["epochs"] if (path / "trainer-config.json").exists() else 3,
                     "progress": training.read_json(path / "progress.json") if (path / "progress.json").exists() else None,
                     "can_resume": (path / "trainer-state.pt").exists() and not (path / "profile.json").exists(),
                     "has_sample": (path / "sample.wav").exists()})
    return {"job_id": job_id, "selection": training.read_json(job / "selection.json"),
            "actions": sorted(actions, key=lambda item: item["created_at"], reverse=True), "runs": runs,
            "has_dataset": (job / "review.json").exists(), "dataset_approved": (job / "dataset-approved.json").exists()}

class Action(BaseModel):
    request_id: uuid.UUID
    kind: Literal["download", "prepare", "train", "resume", "sample", "load"]
    run_id: str = ""
    epochs: int = Field(default=3, ge=1, le=20)
    text: str = Field(default="", max_length=1500)

def process(job, body, path):
    global ACTIVE
    try:
        unload()
        if body.kind == "load":
            training.configure_worker(run_path(job, body.run_id))
        else:
            log = path.with_suffix(".log")
            env = dict(os.environ)
            if body.kind == "download":
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
            if old["input"] != body.model_dump(mode="json"):
                raise HTTPException(409, "Request ID thuộc tác vụ khác.")
            return old
        idle()
        if body.kind in ("sample", "load", "resume"):
            run_path(job, body.run_id)
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
    path = job_path(job_id) / "review.json"
    return {"hash": training.sha256(path), "rows": training.read_json(path)} if path.exists() else {"hash": "", "rows": []}

class ReviewEdit(BaseModel):
    hash: str
    file: str
    text: str = Field(max_length=4000)
    include: bool
    reviewed: bool

@router.put("/jobs/{job_id}/review")
def edit_review(job_id: str, body: ReviewEdit):
    job = job_path(job_id)
    with worker.LOCK:
        idle()
        path = job / "review.json"
        if not path.exists() or training.sha256(path) != body.hash:
            raise HTTPException(409, "Dataset đã thay đổi; tải lại.")
        rows = training.read_json(path)
        row = next((r for r in rows if r["file"] == body.file), None)
        if not row:
            raise HTTPException(404, "Không có đoạn này.")
        row.update(text=" ".join(body.text.replace("|", " ").split()), include=body.include, reviewed=body.reviewed)
        training.write_json(path, rows)
        (job / "dataset-approved.json").unlink(missing_ok=True)
        return review(job_id)

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
        if value["hash"] != body.hash or len(rows) < 20 or any(not r["reviewed"] or not r["text"] for r in rows):
            raise HTTPException(422, "Cần tối thiểu 20 đoạn đã nghe/sửa, bản dữ liệu phải khớp.")
        training.write_json(job / "dataset-approved.json", {"review_sha256": value["hash"]})
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
        training.approve_voice(run_path(job_path(job_id), run_id))
        return {"approved": True}

worker.app.include_router(router)

if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--execute":
    record = training.read_json(sys.argv[2])
    job = job_path(record["job_id"])
    body = Action.model_validate(record["input"])
    if body.kind == "download":
        training.download_selected(job)
    elif body.kind == "prepare":
        training.prepare_clips(job)
    elif body.kind in ("train", "resume"):
        training.train(job, body.epochs, body.run_id if body.kind == "resume" else None)
    elif body.kind == "sample":
        training.sample_voice(run_path(job, body.run_id), body.text)
