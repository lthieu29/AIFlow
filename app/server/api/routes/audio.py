"""Connection setup and persistent audio jobs for the personal local UI."""

import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import update
from sqlmodel import Session, select

from server.audio.queue import enqueue, inputs_current, now, prepare
from server.audio.remote import AudioUnavailable, cached, connection, store_audio
from server.config import load_settings
from server.db.models.audio_task import AudioTask
from server.db.models.project import Project
from server.db.session import get_engine


def local_client(request: Request, x_aiflow_client: str = Header(default="")):
    if request.method in ("POST", "PUT", "DELETE"):
        if x_aiflow_client != "1":
            raise HTTPException(403, "Local UI header required")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise HTTPException(403, "Local origin required")


router = APIRouter(prefix="/api", tags=["remote-audio"], dependencies=[Depends(local_client)])


class ConnectionInput(BaseModel):
    url: str = Field(max_length=512)
    token: SecretStr
    fingerprint: str = ""


class TaskInput(BaseModel):
    title: str = Field(default="Giọng đọc", max_length=200)
    text: str = Field(default="", max_length=50000)
    project_id: int | None = None
    voice: str = Field(default="af_heart", max_length=100)
    language: str = Field(default="en", max_length=16)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def public_task(task: AudioTask) -> dict:
    segments = json.loads(task.segments_json)
    return {"id": task.id, "title": task.title, "project_id": task.project_id,
            "generation_job_id": task.generation_job_id, "status": task.status,
            "voice": task.voice, "language": task.language,
            "completed_segments": task.completed_segments, "total_segments": len(segments),
            "duration_sec": task.duration_sec, "error": task.error,
            "created_at": task.created_at.isoformat(),
            "audio_path": f"audio/tasks/{task.id}.wav" if task.status == "succeeded" else None,
            "audio_url": f"/api/audio/tasks/{task.id}/result" if task.status == "succeeded" else None}


def get_task(session: Session, task_id: int) -> AudioTask:
    task = session.get(AudioTask, task_id)
    if not task:
        raise HTTPException(404, "Không tìm thấy tác vụ audio.")
    return task


@router.get("/connections/audio")
def get_connection():
    settings = load_settings()
    return connection.public(settings.data_dir)


@router.post("/connections/audio/check")
def check_connection(body: ConnectionInput):
    try:
        return connection.check(body.url, body.token.get_secret_value())
    except AudioUnavailable as exc:
        raise HTTPException(422, {"state": exc.state, "message": exc.message}) from exc


@router.put("/connections/audio")
def save_connection(body: ConnectionInput):
    checked = check_connection(body)  # Revalidate on save; never trust a browser-supplied health result.
    if checked["fingerprint"] != body.fingerprint:
        raise HTTPException(409, "URL/token đã đổi. Kiểm tra lại trước khi lưu.")
    settings = load_settings()
    connection.save(checked, body.token.get_secret_value(), settings.data_dir)
    return connection.public(settings.data_dir)


@router.post("/connections/audio/disconnect")
def disconnect():
    connection.disconnect()
    return {"state": "not_configured", "message": "Đã ngắt API. Hãy tự Disconnect and delete runtime trên Colab."}


@router.get("/audio/tasks")
def list_tasks():
    with Session(get_engine(load_settings())) as session:
        return [public_task(t) for t in session.exec(select(AudioTask).order_by(AudioTask.id.desc()).limit(100)).all()]


@router.post("/audio/tasks", status_code=202)
def create_task(body: TaskInput):
    settings = load_settings()
    with Session(get_engine(settings)) as session:
        if body.project_id:
            # Claim the write transaction before checking ownership so two
            # concurrent requests cannot both clear and replace scene audio.
            session.execute(update(Project).where(Project.id == body.project_id).values(updated_at=Project.updated_at))
        project = session.get(Project, body.project_id) if body.project_id else None
        if body.project_id and not project:
            raise HTTPException(404, "Dự án không tồn tại.")
        if not project and not body.text.strip():
            raise HTTPException(422, "Nhập nội dung cần tạo giọng đọc.")
        if project:
            if project.status == "generating":
                raise HTTPException(409, "Dự án đang chạy; hãy xử lý tác vụ hiện tại.")
            existing = session.exec(select(AudioTask).where(
                AudioTask.project_id == project.id,
                AudioTask.status.notin_(["succeeded", "cancelled"]),
            )).first()
            if existing:
                raise HTTPException(409, f"Dự án đang có tác vụ audio #{existing.id}. Tiếp tục hoặc hủy và chờ xác nhận đã hủy trước khi tạo tác vụ mới.")
            series = json.loads(project.production_brief).get("series", {})
            if series.get("voice") and (body.voice != series["voice"] or body.language != series["language"]):
                raise HTTPException(409, "Tập này đã khóa giọng theo series. Tạo tập mới với phiên bản series mới để đổi.")
            project.voice_id, project.language = body.voice, body.language
            session.add(project)
            from server.db.models.scene import Scene
            for scene in session.exec(select(Scene).where(Scene.project_id == project.id)).all():
                scene.audio_path = None
                session.add(scene)
        try:
            task = enqueue(session, settings, text=body.text, title=body.title, project=project,
                           voice=body.voice, language=body.language, speed=body.speed)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return public_task(task)


@router.get("/audio/tasks/{task_id}")
def read_task(task_id: int):
    with Session(get_engine(load_settings())) as session:
        return public_task(get_task(session, task_id))


@router.post("/audio/tasks/{task_id}/resume")
def resume(task_id: int):
    settings = load_settings()
    with Session(get_engine(settings)) as session:
        task = get_task(session, task_id)
        if task.status in ("succeeded", "cancelled", "cancel_requested", "running"):
            raise HTTPException(409, "Trạng thái hiện tại không cho phép tiếp tục.")
        if not inputs_current(session, task):
            raise HTTPException(409, "Nội dung/giọng đã đổi. Hãy tạo tác vụ mới.")
        try:
            prepare(task, settings.data_dir)
            if not all(cached(settings.data_dir, s["key"]) for s in json.loads(task.segments_json)):
                connection.snapshot()
        except AudioUnavailable as exc:
            raise HTTPException(422, exc.message) from exc
        task.status, task.error, task.updated_at = "queued", "", now()
        session.add(task)
        session.commit()
        return public_task(task)


@router.post("/audio/tasks/{task_id}/cancel")
def cancel(task_id: int):
    with Session(get_engine(load_settings())) as session:
        task = get_task(session, task_id)
        if task.status not in ("succeeded", "cancelled"):
            task.status = "cancel_requested"
            session.add(task)
            session.commit()
        return public_task(task)


@router.get("/audio/tasks/{task_id}/result")
def result(task_id: int):
    settings = load_settings()
    with Session(get_engine(settings)) as session:
        task = get_task(session, task_id)
        path = settings.data_dir / "audio" / "tasks" / f"{task.id}.wav"
        if task.status != "succeeded" or not path.is_file():
            raise HTTPException(409, "Audio chưa sẵn sàng.")
        return FileResponse(path, media_type="audio/wav", filename=f"audio-{task.id}.wav")


@router.get("/audio/tasks/{task_id}/batch")
def export_batch(task_id: int):
    settings = load_settings()
    with Session(get_engine(settings)) as session:
        task = get_task(session, task_id)
        try:
            prepare(task, settings.data_dir)
        except AudioUnavailable as exc:
            raise HTTPException(422, "Nhập cấu hình model từ notebook trước khi xuất batch: " + exc.message) from exc
        session.add(task)
        session.commit()
        return JSONResponse({"api_version": "1", "task_id": task.id, "segments": json.loads(task.segments_json)},
                            headers={"Content-Disposition": f'attachment; filename="audio-{task.id}.json"'})


@router.post("/connections/audio/batch-profile")
def import_batch_profile(profile: dict):
    """No tunnel required: paste the non-secret worker profile displayed in the notebook."""
    health, voices = profile.get("health", {}), profile.get("voices", [])
    import re
    if (not isinstance(health, dict) or health.get("api_version") != "1"
            or health.get("engine") not in ("kokoro", "vieneu-v3turbo-finetune")
            or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", str(health.get("model_revision", "")))
            or not isinstance(health.get("languages"), list) or not health["languages"]
            or any(lang not in ("en", "vi") for lang in health["languages"])
            or not isinstance(voices, list) or not 1 <= len(voices) <= 100
            or any(not isinstance(v, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", str(v.get("id", "")))
                   or v.get("language") not in health["languages"] for v in voices)):
        raise HTTPException(422, "Profile notebook không hợp lệ.")
    settings = load_settings()
    connection.disconnect()
    with connection.lock:
        connection.health, connection.voices = health, voices
        (settings.data_dir / "audio-connection.json").write_text(json.dumps({"health": health, "voices": voices}), encoding="utf-8")
    return connection.public(settings.data_dir)


@router.post("/audio/tasks/{task_id}/import")
async def import_batch(task_id: int, file: UploadFile = File(...)):
    raw = await file.read(128 * 1024 * 1024 + 1)
    if len(raw) > 128 * 1024 * 1024:
        raise HTTPException(413, "ZIP tối đa 128 MiB; chia batch nhỏ hơn.")
    settings = load_settings()
    with Session(get_engine(settings)) as session:
        task = get_task(session, task_id)
        if task.status in ("running", "cancel_requested", "cancelled", "succeeded") or not inputs_current(session, task):
            raise HTTPException(409, "Tác vụ không còn chấp nhận kết quả batch.")
        expected = {s["key"] for s in json.loads(task.segments_json)}
        if not expected:
            raise HTTPException(409, "Xuất batch JSON trước khi nhập kết quả để khóa model và các đoạn audio.")
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 256 * 1024 * 1024:
                    raise ValueError("ZIP giải nén quá lớn")
                manifest = json.loads(archive.read("manifest.json"))
                results = manifest["results"]
                if not isinstance(results, list) or not results or any(not isinstance(job, dict) for job in results):
                    raise ValueError("Manifest không có kết quả audio")
                for job in results:
                    key = job["job_id"]
                    if key not in expected or job["status"] != "succeeded":
                        raise ValueError("Kết quả không thuộc tác vụ")
                    store_audio(settings.data_dir, key, archive.read(f"{key}.wav"), job["checksum"])
        except (ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile, AudioUnavailable) as exc:
            raise HTTPException(422, "ZIP/manifest/checksum không hợp lệ.") from exc
        task.status, task.error = "queued", ""
        session.add(task)
        session.commit()
        return public_task(task)


@router.get("/audio/notebook")
def notebook():
    path = Path(__file__).resolve().parents[3] / "colab" / "serve_audio_api.ipynb"
    return FileResponse(path, filename=path.name)


@router.get("/audio/worker-bundle")
def worker_bundle():
    from fastapi.responses import Response
    base = Path(__file__).resolve().parents[3] / "colab" / "audio_worker"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("app.py", "requirements.txt"):
            archive.write(base / name, f"audio_worker/{name}")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="aiflow-audio-worker.zip"'})
