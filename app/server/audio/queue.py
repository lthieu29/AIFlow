"""Single-owner durable audio queue. All model inference happens on the remote worker."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select
from sqlalchemy import update

from server.audio.remote import AudioUnavailable, cached, combine, connection, download, make_segments, request
from server.db.models.audio_task import AudioTask
from server.db.models.job import Job
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.session import get_engine


def now():
    return datetime.now(timezone.utc)


def project_snapshot(session: Session, project: Project) -> list[dict]:
    return [{"scene_id": scene.id, "text": scene.narration, "order": scene.order}
            for scene in session.exec(select(Scene).where(Scene.project_id == project.id).order_by(Scene.order)).all()
            if scene.narration.strip()]


def prepare(task: AudioTask, data_dir: Path) -> None:
    """Freeze model revision and cache keys before submitting any segment."""
    if task.segments_json != "[]":
        return
    health = connection.public(data_dir)["health"]
    if not health.get("model_revision"):
        raise AudioUnavailable("Bật Colab, nhập URL và token rồi tiếp tục.", "not_configured")
    if task.language not in health.get("languages", []):
        raise AudioUnavailable("Model hiện tại không hỗ trợ ngôn ngữ đã chọn.", "incompatible")
    known_voices = connection.public(data_dir)["voices"]
    if task.voice not in {v["id"] for v in known_voices}:
        raise AudioUnavailable("Giọng đã chọn không có trên worker. Hãy chọn lại giọng.", "incompatible")
    segments = []
    for item in json.loads(task.snapshot_json):
        if item.get("locked_model") and item["locked_model"] != health["model_revision"]:
            raise AudioUnavailable("Worker khác model đã khóa cho tập này. Load đúng phiên bản giọng của series.", "incompatible")
        for segment in make_segments(item["text"], task.voice, task.language, task.speed, health["model_revision"]):
            segments.append({**segment, "scene_id": item.get("scene_id")})
    task.segments_json = json.dumps(segments, ensure_ascii=False)


def enqueue(session: Session, settings, *, text: str = "", title: str = "Giọng đọc",
            project: Project | None = None, generation_job_id: int | None = None,
            voice: str = "af_heart", language: str = "en", speed: float = 1.0) -> AudioTask:
    snapshot = project_snapshot(session, project) if project else [{"scene_id": None, "text": text}]
    if not snapshot:
        raise ValueError("Dự án không có lời đọc.")
    if project:
        series = json.loads(project.production_brief).get("series", {})
        if series:
            if series.get("voice") and (project.voice_id != series["voice"] or project.language != series["language"]):
                raise ValueError("Giọng/ngôn ngữ khác cấu hình series đã khóa. Tạo tập mới với phiên bản series mới để đổi.")
            speed = series["speed"]
            for item in snapshot:
                item["locked_model"] = series.get("model_revision", "")
    task = AudioTask(title=title, project_id=project.id if project else None, generation_job_id=generation_job_id,
                     voice=project.voice_id if project else voice, language=project.language if project else language,
                     speed=speed, snapshot_json=json.dumps(snapshot, ensure_ascii=False))
    try:
        prepare(task, settings.data_dir)
        segments = json.loads(task.segments_json)
        task.status = "queued" if (connection.token or all(cached(settings.data_dir, s["key"]) for s in segments)) else "waiting_resource"
    except AudioUnavailable as exc:
        task.error = exc.message
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def inputs_current(session: Session, task: AudioTask) -> bool:
    if task.project_id is None:
        return True
    project = session.get(Project, task.project_id)
    return bool(project and project.voice_id == task.voice and project.language == task.language
                and project_snapshot(session, project) == [{k: v for k, v in item.items() if k != "locked_model"} for item in json.loads(task.snapshot_json)])


class AudioQueue:
    def __init__(self, settings):
        self.settings = settings
        self.engine = get_engine(settings)
        self.stop_event = asyncio.Event()
        self.generation_tasks: set[asyncio.Task] = set()
        self.lock_file = None

    def acquire(self) -> None:
        """OS file lock excludes multiple schedulers; released automatically after a crash."""
        path = self.settings.data_dir / "audio-worker.lock"
        self.lock_file = path.open("a+b")
        self.lock_file.seek(0)
        if path.stat().st_size == 0:
            self.lock_file.write(b"0")
            self.lock_file.flush()
        self.lock_file.seek(0)
        try:
            import os
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise RuntimeError("Another AIFlow audio scheduler is running. Use one backend process.")
        with Session(self.engine) as session:
            for task in session.exec(select(AudioTask).where(AudioTask.status.in_(["running", "queued", "cancel_requested"]))):
                task.status = "waiting_resource" if task.status != "cancel_requested" else "cancel_requested"
                task.error = "Backend đã khởi động lại. Kết nối Colab rồi chọn Tiếp tục."
                session.add(task)
            # Video may already have consumed credits. Do not replay it on process restart.
            for task in session.exec(select(AudioTask).where(AudioTask.generation_job_id != None)):
                job = session.get(Job, task.generation_job_id)
                if job and job.status == "running":
                    job.status = "needs_attention"
                    session.add(job)
                    project = session.get(Project, task.project_id)
                    if project:
                        project.status = "ready"
                        session.add(project)
            session.commit()

    async def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.to_thread(self.tick)
                self.dispatch_generation()
            except Exception:
                from loguru import logger
                logger.exception("Audio queue tick failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass

    def tick(self) -> None:
        with Session(self.engine) as session:
            task = session.exec(select(AudioTask).where(AudioTask.status.in_(["queued", "running", "cancel_requested"]))
                                .order_by(AudioTask.id)).first()
            if task is None:
                return
            task_id = task.id
            cancel = task.status == "cancel_requested"
            retry = task.status == "queued"
            try:
                if cancel:
                    if task.active_key:
                        try:
                            url, token, _, _ = connection.snapshot()
                            state = request(url, token, "POST", f"/v1/jobs/{task.active_key}/cancel")
                            if state["status"] == "cancel_requested":
                                return
                        except AudioUnavailable:
                            task.error = "Đã hủy trên máy; chưa xác nhận dừng worker. Kiểm tra hoặc dừng runtime Colab nếu cần."
                    task.status = "cancelled"
                    self.stop_generation(session, task)
                elif not inputs_current(session, task):
                    task.status, task.error = "needs_attention", "Nội dung/giọng đã đổi. Tạo tác vụ mới cho phiên bản hiện tại."
                    self.stop_generation(session, task)
                else:
                    prepare(task, self.settings.data_dir)
                    segments = json.loads(task.segments_json)
                    missing = [s for s in segments if not cached(self.settings.data_dir, s["key"])]
                    task.completed_segments = len(segments) - len(missing)
                    if not missing:
                        self.finish(session, task, segments)
                    else:
                        segment = missing[0]
                        url, token, generation, health = connection.snapshot()
                        if health.get("model_revision") != segment["input"]["model_revision"]:
                            raise AudioUnavailable("Model của phiên mới khác tác vụ. Dùng lại model đã khóa hoặc tạo tác vụ mới.", "incompatible")
                        task.status = "running"
                        # Persist before submit, including ambiguous submit/network failures.
                        if task.active_key != segment["key"]:
                            task.active_key = segment["key"]
                            task.updated_at = now()
                            session.add(task)
                            session.commit()
                        elapsed = (now().replace(tzinfo=None) - task.updated_at.replace(tzinfo=None)).total_seconds()
                        if elapsed > 900:
                            raise AudioUnavailable("Đoạn âm thanh vượt thời gian chờ. Kiểm tra Colab rồi Tiếp tục.")
                        job = request(url, token, "POST", "/v1/tts/jobs", params={"retry": "true" if retry else "false"}, json=segment["input"],
                                      headers={"Idempotency-Key": segment["key"]})
                        if job["status"] == "succeeded":
                            download(url, token, self.settings.data_dir, segment["key"], job["checksum"])
                            task.completed_segments += 1
                            task.active_key = None
                            task.updated_at = now()
                        elif job["status"] in ("failed", "cancelled"):
                            raise AudioUnavailable("Worker không hoàn thành đoạn audio. Kiểm tra notebook rồi Tiếp tục.")
                        if connection.generation != generation:
                            raise AudioUnavailable("Kết nối đã đổi. Chọn Tiếp tục để nhận lại kết quả.")
                # A user may cancel while an HTTP request is in progress.
                with Session(self.engine) as latest:
                    row = latest.get(AudioTask, task_id)
                    if row and row.status == "cancel_requested" and not cancel:
                        task.status = "cancel_requested"
                session.add(task)
                session.commit()
            except AudioUnavailable as exc:
                with connection.lock:
                    connection.state = exc.state
                with Session(self.engine) as latest:
                    row = latest.get(AudioTask, task_id)
                    pending_cancel = row and row.status == "cancel_requested"
                task.status = "cancel_requested" if cancel or pending_cancel else "waiting_resource"
                task.error = exc.message
                session.add(task)
                session.commit()
            except Exception:
                with Session(self.engine) as latest:
                    row = latest.get(AudioTask, task_id)
                    pending_cancel = row and row.status == "cancel_requested"
                task.status = "cancel_requested" if cancel or pending_cancel else "needs_attention"
                task.error = "Không xử lý được audio. Kiểm tra dữ liệu và nhật ký backend."
                self.stop_generation(session, task)
                session.add(task)
                session.commit()

    def finish(self, session: Session, task: AudioTask, segments: list[dict]) -> None:
        # Claim the write transaction before attaching anything. A cancellation
        # committed first wins; later cancellation observes the completed task.
        claimed = session.execute(update(AudioTask).where(
            AudioTask.id == task.id, AudioTask.status.in_(["queued", "running"]),
        ).values(status="running"))
        if claimed.rowcount != 1:
            session.refresh(task)
            return
        if not inputs_current(session, task):
            raise AudioUnavailable("Nội dung đã thay đổi, cần tạo tác vụ mới.", "incompatible")
        output = self.settings.data_dir / "audio" / "tasks" / f"{task.id}.wav"
        task.duration_sec = combine(self.settings.data_dir, segments, output)
        task.output_path = str(output.resolve())
        if task.project_id:
            for item in json.loads(task.snapshot_json):
                scene = session.get(Scene, item["scene_id"])
                subset = [s for s in segments if s["scene_id"] == scene.id]
                destination = output.with_name(f"{task.id}-scene-{scene.id}.wav")
                combine(self.settings.data_dir, subset, destination)
                current_project = select(Project.id).where(Project.id == task.project_id,
                                                           Project.voice_id == task.voice,
                                                           Project.language == task.language)
                attached = session.execute(update(Scene).where(
                    Scene.id == item["scene_id"], Scene.narration == item["text"], Scene.order == item["order"],
                    Scene.project_id.in_(current_project),
                ).values(audio_path=str(destination.resolve())))
                if attached.rowcount != 1:
                    session.rollback()
                    raise AudioUnavailable("Nội dung đã đổi trong khi ghép audio. Tạo tác vụ mới.", "incompatible")
        task.status, task.error, task.active_key = "succeeded", "", None
        task.completed_segments = len(segments)
        task.updated_at = now()

    def stop_generation(self, session: Session, task: AudioTask) -> None:
        if task.generation_job_id:
            job = session.get(Job, task.generation_job_id)
            if job and job.status == "waiting_resource":
                job.status = "needs_attention"
                session.add(job)
                project = session.get(Project, task.project_id)
                if project:
                    project.status = "ready"
                    session.add(project)

    def dispatch_generation(self) -> None:
        if self.generation_tasks:
            return
        with Session(self.engine) as session:
            candidates = session.exec(select(AudioTask).where(AudioTask.status == "succeeded",
                                                              AudioTask.generation_job_id != None)).all()
            for task in candidates:
                job = session.get(Job, task.generation_job_id)
                if not job or job.status != "waiting_resource":
                    continue
                if not inputs_current(session, task):
                    self.stop_generation(session, task)
                    session.commit()
                    continue
                job.status = "running"
                session.add(job)
                session.commit()
                from server.api.routes.projects import _run_generation
                running = asyncio.create_task(asyncio.to_thread(_run_generation, task.project_id, job.id, self.settings, False))
                self.generation_tasks.add(running)
                running.add_done_callback(self.generation_tasks.discard)
                break

    async def close(self, runner: asyncio.Task) -> None:
        self.stop_event.set()
        await runner
        if self.generation_tasks:
            await asyncio.gather(*self.generation_tasks, return_exceptions=True)
        if self.lock_file:
            self.lock_file.close()
