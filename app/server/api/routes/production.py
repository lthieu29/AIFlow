"""Portrait import/review, scene visual approval and local delivery production."""

import json
import re
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from server.api.routes.audio import local_client
from server.api.routes.projects import get_session, get_settings
from server.config import Settings
from server.db.models.audio_task import AudioTask
from server.db.models.job import Job
from server.db.models.production import ProductionMedia, ProductionOutput
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.models.studio import StudioOperation
from server.db.session import get_engine
from server.flow.client import FlowClient
from server.production import flow_video
from server.production.media import contained, image_info, probe, sha256
from server.production.render import output_file_path, package, public_manifest, render, snapshot

router = APIRouter(prefix="/api/production", tags=["production"], dependencies=[Depends(local_client)])


class PortraitInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    species: str = Field(min_length=1, max_length=100)
    identity: str = Field(min_length=1, max_length=5000)
    style: str = Field(min_length=1, max_length=1000)
    requirements: str = Field(default="", max_length=5000)
    channel: str = Field(default="", max_length=100)


class ConfigureInput(BaseModel):
    kind: Literal["portrait", "video"]
    channel: str = Field(default="", max_length=100)


class ReviewInput(BaseModel):
    checklist: list[str] = Field(max_length=10)
    notes: str = Field(default="", max_length=3000)


class RenderInput(BaseModel):
    allow_loop: bool = False
    subtitle_mode: Literal["scene", "remote_stt"] = "scene"
    still_motion: bool = False


class GenerateVideoInput(BaseModel):
    request_id: uuid.UUID
    scene_id: int
    reference_media_id: int | None = Field(default=None, gt=0)
    reference_mode: Literal["ingredients", "first_frame"] = "ingredients"
    allow_silent_video: bool = Field(default=False, strict=True)


class ResolveVideoInput(BaseModel):
    checked_flow: bool = False


class FlowProjectInput(BaseModel):
    url: str = Field(min_length=1, max_length=512)


def project_or_404(session, project_id):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án.")
    return project


def media_public(item):
    return {key: getattr(item, key) for key in ("id", "project_id", "scene_id", "role", "sha256", "mime", "width", "height", "duration", "approved")}


@router.get("/overview")
def overview(session: Session = Depends(get_session)):
    projects = session.exec(select(Project).order_by(Project.updated_at.desc())).all()
    jobs = session.exec(select(Job).order_by(Job.id.desc()).limit(100)).all()
    audio = session.exec(select(AudioTask).order_by(AudioTask.id.desc()).limit(100)).all()
    outputs = session.exec(select(ProductionOutput).order_by(ProductionOutput.id.desc()).limit(100)).all()
    return {"projects": [{"id": p.id, "title": p.title, "kind": p.kind, "status": p.status,
                           "channel": json.loads(p.production_brief).get("channel", "")} for p in projects],
            "jobs": [{"id": j.id, "project_id": j.project_id, "type": j.type, "status": j.status} for j in jobs],
            "audio": [{"id": a.id, "project_id": a.project_id, "title": a.title, "status": a.status} for a in audio],
            "outputs": [{"id": o.id, "project_id": o.project_id, "job_id": o.job_id, "kind": o.kind, "status": o.status,
                         "error": json.loads(o.manifest_json).get("error")} for o in outputs],
            "capabilities": {"portrait_generation": "configured_gemini_or_import", "local_ai": False,
                             "render": "FFmpeg", "subtitle": "scene-level timing"}}


@router.post("/portraits", status_code=201)
def create_portrait(body: PortraitInput, session: Session = Depends(get_session)):
    project = Project(short_id="p_" + uuid.uuid4().hex[:12], title=body.title, kind="portrait",
                      adapter="portrait_import", status="ready", production_brief=body.model_dump_json())
    session.add(project)
    session.commit()
    session.refresh(project)
    return {"id": project.id}


@router.put("/projects/{project_id}/kind")
def configure(project_id: int, body: ConfigureInput, session: Session = Depends(get_session)):
    project = project_or_404(session, project_id)
    if project.status == "generating" or (project.kind != "legacy" and project.kind != body.kind):
        raise HTTPException(409, "Không đổi loại khi đang chạy hoặc khi dự án đã được phân loại.")
    if body.kind == "portrait" and session.exec(select(Scene).where(Scene.project_id == project_id)).first():
        raise HTTPException(409, "Dự án có cảnh video; tạo dự án chân dung mới để giữ dữ liệu cũ.")
    project.kind = body.kind
    project.production_brief = json.dumps({**json.loads(project.production_brief), "channel": body.channel})
    session.add(project)
    session.commit()
    return {"kind": project.kind}


@router.get("/projects/{project_id}")
def detail(project_id: int, session: Session = Depends(get_session)):
    project = project_or_404(session, project_id)
    media = session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id).order_by(ProductionMedia.id.desc())).all()
    scenes = session.exec(select(Scene).where(Scene.project_id == project_id).order_by(Scene.order)).all()
    return {"id": project.id, "title": project.title, "kind": project.kind, "status": project.status,
            "aspect": project.aspect, "brief": json.loads(project.production_brief),
            "scenes": [{"id": s.id, "order": s.order, "prompt": s.prompt, "narration": s.narration,
                        "duration": s.duration, "has_audio": bool(s.audio_path)} for s in scenes],
            "media": [media_public(item) for item in media if item.role != "archived"],
            "video_operations": [flow_video.operation_public(row) for row in session.exec(select(StudioOperation).where(
                StudioOperation.project_id == project_id, StudioOperation.kind == "flow_video")).all()],
            "prompt": f"Create a personalized pet portrait using the attached reference images. Preserve identity exactly.\n{project.production_brief}" if project.kind == "portrait" else ""}


@router.get("/flow-capability")
async def flow_capability():
    return await _flow_capability()


async def _flow_capability(remote_id=None):
    from server.flow.sdk import get_flow_sdk
    try:
        sdk = get_flow_sdk()
        if not remote_id:
            remote_id = await sdk.resolve_project_id()
        await sdk.preflight_text_video(remote_id)
        return {"available": True, "project_url": f"https://flow.google.com/project/{remote_id}", "message": ""}
    except Exception as exc:
        return {"available": False, "project_url": f"https://flow.google.com/project/{remote_id}" if remote_id else "https://flow.google.com/",
                "message": flow_video.failure_guidance(getattr(exc, "code", None)) or
                "Chọn URL dự án Google Flow đã đăng nhập và bấm Mở dự án qua Bridge & kiểm tra. Kiểm tra extension đã kết nối AIFlow."}


@router.post("/flow-project")
async def open_flow_project(body: FlowProjectInput):
    try:
        url = urlsplit(body.url.strip())
        if (url.scheme != "https" or url.hostname not in {"flow.google.com", "labs.google"}
                or url.username or url.password or url.port not in (None, 443) or url.query or url.fragment):
            raise ValueError("Invalid Flow project URL")
        prefix = r"/project/" if url.hostname == "flow.google.com" else r"/fx/(?:[a-z]{2}(?:-[A-Za-z]{2})?/)?tools/flow/project/"
        match = re.fullmatch(prefix + r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})/?", url.path)
        if not match:
            raise ValueError("Missing project UUID")
        remote_id = str(uuid.UUID(match[1]))
    except ValueError as exc:
        raise HTTPException(422, "Nhập URL HTTPS của dự án Google Flow có UUID; không dùng URL landing hoặc tham số khác.") from exc
    canonical_url = f"https://flow.google.com/project/{remote_id}"
    result = await FlowClient().open_flow_project(canonical_url)
    if result.get("error") or result.get("status") != 200:
        raise HTTPException(503, "Bridge chưa mở được dự án Flow. Kiểm tra extension đã kết nối và thử lại.")
    if result.get("data", {}).get("projectId") != remote_id:
        raise HTTPException(409, "Tab Flow chưa vào đúng dự án đã chọn; kiểm tra và thử lại.")
    return await _flow_capability(remote_id)


@router.get("/projects/{project_id}/scenes/{scene_id}/flow-prompt")
def approved_flow_prompt(project_id: int, scene_id: int, session: Session = Depends(get_session)):
    project = project_or_404(session, project_id)
    scene = session.get(Scene, scene_id)
    if project.kind != "video" or not scene or scene.project_id != project_id:
        raise HTTPException(422, "Chọn cảnh thuộc dự án video.")
    from server.text.workflow import assert_project_approved
    assert_project_approved(session, project_id)
    return {"prompt": scene.prompt, "aspect": project.aspect, "model": "Veo 3.1 Lite", "duration": 8}


@router.post("/projects/{project_id}/generate-video", status_code=202)
def generate_scene_video(project_id: int, body: GenerateVideoInput, background: BackgroundTasks,
                         session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    request_id = str(body.request_id)
    old = session.get(StudioOperation, request_id)
    if old:
        old_input = json.loads(old.input_json)
        if (old.kind != "flow_video" or old.project_id != project_id or old_input["scene_id"] != body.scene_id
                or old_input.get("snapshot", {}).get("reference", {}).get("id") != body.reference_media_id
                or old_input.get("snapshot", {}).get("reference_mode", "ingredients") != body.reference_mode
                or old_input.get("snapshot", {}).get("allow_silent_video", False) != body.allow_silent_video):
            raise HTTPException(409, "Request ID đã dùng cho đầu vào khác.")
        return flow_video.operation_public(old)
    project = project_or_404(session, project_id)
    scene = session.get(Scene, body.scene_id)
    if project.kind != "video" or not scene or scene.project_id != project_id:
        raise HTTPException(422, "Chọn cảnh thuộc dự án video.")
    if project.status == "generating":
        raise HTTPException(409, "Dự án đang chạy.")
    from server.text.workflow import assert_project_approved
    assert_project_approved(session, project_id)
    if project.aspect not in ("16:9", "9:16") or not scene.prompt.strip():
        raise HTTPException(422, "Veo Lite cần prompt hình ảnh và khung hình 16:9 hoặc 9:16.")
    if body.reference_mode == "first_frame" and body.reference_media_id is None:
        raise HTTPException(422, "Chế độ khung hình đầu cần một ảnh PNG tham chiếu đã duyệt.")
    frozen = flow_video.scene_snapshot(project, scene)
    frozen["allow_silent_video"] = body.allow_silent_video
    frozen["reference_mode"] = body.reference_mode
    if body.reference_media_id:
        reference = session.get(ProductionMedia, body.reference_media_id)
        try:
            flow_video.reference_path(reference, project_id, settings.data_dir)
        except ValueError as exc:
            raise HTTPException(422, "Chọn ảnh PNG tham chiếu đã duyệt, không đổi, thuộc dự án này (tối đa 5 MiB).") from exc
        frozen["reference"] = {"id": reference.id, "sha256": reference.sha256,
                               "provenance": json.loads(reference.review_json)}
    # Serialize competing submissions for this project across HTTP requests.
    session.execute(update(Project).where(Project.id == project_id).values(updated_at=Project.updated_at))
    for active in session.exec(select(StudioOperation).where(StudioOperation.project_id == project_id,
            StudioOperation.kind == "flow_video", StudioOperation.status.in_(["running", "interrupted", "needs_attention"]))).all():
        if active.status == "running" and active.request_id != request_id:
            raise HTTPException(409, "Dự án đang tạo / nhận một clip Flow. Chờ tác vụ hiện tại hoàn tất rồi tạo cảnh tiếp theo.")
        if json.loads(active.input_json)["scene_id"] == body.scene_id:
            if active.request_id == request_id:
                return flow_video.operation_public(active)
            raise HTTPException(409, "Cảnh còn tác vụ Flow chưa xử lý. Tiếp tục nhận kết quả trước khi tạo lượt mới.")
    row = StudioOperation(request_id=request_id, project_id=project_id, kind="flow_video",
        input_json=json.dumps({"scene_id": body.scene_id, "snapshot": frozen}))
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Request ID đã được dùng; tải lại trạng thái trước khi gửi mới.")
    flow_video.ACTIVE_VIDEOS.add(request_id)
    background.add_task(flow_video.generate, get_engine(settings), settings, request_id)
    return flow_video.operation_public(row)


@router.post("/video-operations/{request_id}/resume", status_code=202)
def resume_video(request_id: uuid.UUID, background: BackgroundTasks, session: Session = Depends(get_session),
                 settings: Settings = Depends(get_settings)):
    identity = str(request_id)
    row = session.get(StudioOperation, identity)
    if not row or row.kind != "flow_video":
        raise HTTPException(404, "Không tìm thấy tác vụ video.")
    if identity in flow_video.ACTIVE_VIDEOS:
        return flow_video.operation_public(row)
    if row.status not in ("interrupted", "needs_attention") or not flow_video.operation_public(row)["can_resume"]:
        raise HTTPException(409, "Chưa có mã Flow để tiếp tục, hoặc kết quả đã được nhận. Kiểm tra tab Flow.")
    claimed = session.execute(update(StudioOperation).where(StudioOperation.request_id == identity,
        StudioOperation.status.in_(["interrupted", "needs_attention"])).values(status="running", error=""))
    session.commit()
    session.refresh(row)
    if claimed.rowcount != 1:
        return flow_video.operation_public(row)
    flow_video.ACTIVE_VIDEOS.add(identity)
    background.add_task(flow_video.generate, get_engine(settings), settings, identity)
    return flow_video.operation_public(row)


@router.post("/video-operations/{request_id}/resolve")
def resolve_video(request_id: uuid.UUID, body: ResolveVideoInput, session: Session = Depends(get_session)):
    identity = str(request_id)
    row = session.get(StudioOperation, identity)
    if not row or row.kind != "flow_video":
        raise HTTPException(404, "Không tìm thấy tác vụ video.")
    if row.status == "resolved":
        return flow_video.operation_public(row)
    result = json.loads(row.result_json)
    if (not body.checked_flow or identity in flow_video.ACTIVE_VIDEOS
            or row.status not in ("needs_attention", "interrupted")
            or (result.get("operation_name") and not result.get("media_id"))):
        raise HTTPException(409, "Chỉ khép lại lượt chưa có mã kết quả hoặc clip đã nhận sau khi kiểm tra trong Google Flow.")
    row.status = "resolved"
    row.error = "Đã xác nhận kiểm tra và xử lý lượt này trong Google Flow. Không tự tạo lại."
    result["manually_resolved"] = True
    row.result_json = json.dumps(result)
    session.add(row)
    session.commit()
    return flow_video.operation_public(row)


@router.post("/projects/{project_id}/media", status_code=201)
async def upload(project_id: int, role: Literal["reference", "portrait", "visual"] = Form(...),
                 scene_id: int | None = Form(default=None), file: UploadFile = File(...),
                 provenance_note: str = Form(default="", max_length=1000),
                 session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    project = project_or_404(session, project_id)
    if project.status == "generating":
        raise HTTPException(409, "Chờ tác vụ hiện tại kết thúc trước khi thay tài nguyên.")
    if role == "visual":
        scene = session.get(Scene, scene_id) if scene_id else None
        if project.kind != "video" or not scene or scene.project_id != project_id:
            raise HTTPException(422, "Chọn đúng cảnh của dự án video.")
    elif not (project.kind == "portrait" or (project.kind == "video" and role == "reference")) or scene_id is not None:
        raise HTTPException(422, "Ảnh tham chiếu/thành phẩm chỉ dành cho dự án chân dung.")
    if role == "reference":
        refs = session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id, ProductionMedia.role == "reference")).all()
        if len(refs) >= 3:
            raise HTTPException(422, "Tối đa 3 ảnh tham chiếu; lưu trữ ảnh cũ trước khi thay.")
    suffix = Path(file.filename or "").suffix.lower()
    video_reference = project.kind == "video" and role == "reference"
    if video_reference and suffix != ".png":
        raise HTTPException(422, "Ảnh tham chiếu video cần PNG tối đa 5 MiB.")
    if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".mp4") or (suffix == ".mp4" and role != "visual"):
        raise HTTPException(422, "Dùng PNG/JPEG/WebP; clip cảnh có thể dùng MP4.")
    folder = settings.data_dir / "production" / "inputs" / str(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{suffix}"
    limit = 5 * 1024**2 if video_reference else 100 * 1024 * 1024 if suffix == ".mp4" else 10 * 1024 * 1024
    size = 0
    try:
        with path.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Tham chiếu video tối đa 5 MiB; ảnh khác tối đa 10MB; MP4 tối đa 100MB.")
                stream.write(chunk)
        duration = 0.0
        if suffix == ".mp4":
            info = probe(path)
            video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
            if not video:
                raise ValueError("File không có video stream.")
            width, height, duration, mime = video["width"], video["height"], info["duration"], "video/mp4"
        else:
            width, height = image_info(path)
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[suffix]
        media = ProductionMedia(project_id=project_id, scene_id=scene_id, role=role, path=str(path.resolve()),
                                sha256=sha256(path), mime=mime, width=width, height=height, duration=duration)
        if video_reference:
            if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Ảnh tham chiếu phải chứa dữ liệu PNG thực.")
            media.review_json = json.dumps({"origin": {"kind": "client_uploaded_png", "filename": Path(file.filename or "").name,
                "sha256": media.sha256, "user_note": provenance_note}}, ensure_ascii=False)
        if role == "reference":
            for portrait in session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id, ProductionMedia.role == "portrait")).all():
                portrait.approved = False
                session.add(portrait)
        session.add(media)
        session.commit()
        session.refresh(media)
        return media_public(media)
    except Exception as exc:
        path.unlink(missing_ok=True)
        session.rollback()
        raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else "Không đọc được file ảnh/video hợp lệ.") from exc


@router.get("/media/{media_id}")
def get_media(media_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    item = session.get(ProductionMedia, media_id)
    if not item:
        raise HTTPException(404, "Không có tài nguyên.")
    try:
        path = contained(settings.data_dir, item.path)
    except ValueError as exc:
        raise HTTPException(404, "File tài nguyên không còn trong storage; nhập lại file.") from exc
    return FileResponse(path, media_type=item.mime)


@router.post("/media/{media_id}/review")
def review_media(media_id: int, body: ReviewInput, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    item = session.get(ProductionMedia, media_id)
    project = session.get(Project, item.project_id) if item else None
    video_reference = item and item.role == "reference" and project and project.kind == "video"
    if not item or (item.role not in ("portrait", "visual") and not video_reference):
        raise HTTPException(404, "Không có ảnh/clip cần duyệt.")
    required = {"identity", "clothing", "rights"} if video_reference else {"likeness", "anatomy", "crop", "artifacts"} if item.role == "portrait" else {"content", "continuity", "framing"}
    try:
        unchanged = sha256(contained(settings.data_dir, item.path)) == item.sha256
    except ValueError as exc:
        raise HTTPException(422, "File tài nguyên không còn trong storage; nhập lại file.") from exc
    if set(body.checklist) != required or not unchanged:
        raise HTTPException(422, "Xác nhận đủ checklist; file phải khớp bản đã nhập.")
    item.approved = True
    review = {**json.loads(item.review_json), **body.model_dump()}
    if item.role == "visual":
        scene = session.get(Scene, item.scene_id)
        if not scene:
            raise HTTPException(409, "Cảnh không còn tồn tại.")
        review["scene_content"] = {"prompt": scene.prompt, "narration": scene.narration}
    item.review_json = json.dumps(review, ensure_ascii=False)
    session.add(item)
    session.commit()
    return media_public(item)


@router.delete("/media/{media_id}")
def archive_media(media_id: int, session: Session = Depends(get_session)):
    item = session.get(ProductionMedia, media_id)
    if not item:
        raise HTTPException(404, "Không có tài nguyên.")
    project = project_or_404(session, item.project_id)
    if project.status == "generating":
        raise HTTPException(409, "Đang sản xuất; chờ hoàn tất trước khi thay tài nguyên.")
    if item.role == "reference":
        for portrait in session.exec(select(ProductionMedia).where(ProductionMedia.project_id == item.project_id, ProductionMedia.role == "portrait")).all():
            portrait.approved = False
            session.add(portrait)
    item.role = "archived"
    session.add(item)
    session.commit()
    return {"archived": True}


@router.post("/projects/{project_id}/render", status_code=202)
def start_render(project_id: int, body: RenderInput, background: BackgroundTasks,
                 session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    project = project_or_404(session, project_id)
    try:
        data = snapshot(session, project, settings.data_dir, body.allow_loop)
        data["subtitle_mode"] = body.subtitle_mode
        data["still_motion"] = body.still_motion
        data["language"] = project.language
        if body.subtitle_mode == "remote_stt" and project.kind == "video":
            from server.audio.remote import AudioUnavailable, connection
            try:
                health = connection.snapshot()[3]
            except AudioUnavailable as exc:
                raise ValueError("Bật Colab và lưu kết nối STT trước khi xuất.") from exc
            if "stt" not in health.get("capabilities", []):
                raise ValueError("Colab chưa bật STT; nạp model rồi kiểm tra và lưu lại kết nối.")
            if project.language not in ("en", "vi"):
                raise ValueError("STT hiện hỗ trợ tiếng Anh và tiếng Việt.")
            data["subtitle_alignment"] = "remote STT segments; review recognition before publishing"
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    claim = session.execute(update(Project).where(Project.id == project_id, Project.status != "generating").values(status="generating"))
    if claim.rowcount != 1:
        raise HTTPException(409, "Dự án đang chạy tác vụ khác.")
    job = Job(project_id=project_id, type="production_render")
    session.add(job)
    session.flush()
    folder = settings.data_dir / "production" / "outputs" / str(job.id)
    output = ProductionOutput(project_id=project_id, job_id=job.id, kind=project.kind, status="rendering",
                              manifest_json=json.dumps(data, ensure_ascii=False), folder=str(folder.resolve()))
    session.add(output)
    session.commit()
    session.refresh(output)
    background.add_task(render, get_engine(settings), settings.data_dir, output.id)
    return {"output_id": output.id, "job_id": job.id}


@router.post("/jobs/{job_id}/cancel")
def cancel_render(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job or job.type != "production_render":
        raise HTTPException(404, "Không có tác vụ xuất file.")
    if job.status in ("pending", "running"):
        job.status = "cancel_requested"
        session.add(job)
        session.commit()
    return {"status": job.status}


@router.get("/outputs/{output_id}")
def output_detail(output_id: int, session: Session = Depends(get_session)):
    output = session.get(ProductionOutput, output_id)
    if not output:
        raise HTTPException(404, "Không có thành phẩm.")
    return {"id": output.id, "project_id": output.project_id, "status": output.status,
            "job_id": output.job_id, "kind": output.kind, "manifest": public_manifest(json.loads(output.manifest_json))}


@router.get("/outputs/{output_id}/file/{name}")
def output_file(output_id: int, name: str, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    output = session.get(ProductionOutput, output_id)
    if not output or name not in json.loads(output.manifest_json).get("files", {}):
        raise HTTPException(404, "Không có file thành phẩm.")
    try:
        return FileResponse(output_file_path(output, name, settings.data_dir))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/outputs/{output_id}/review")
def review_output(output_id: int, body: ReviewInput, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    output = session.get(ProductionOutput, output_id)
    if not output or output.status not in ("awaiting_review", "approved"):
        raise HTTPException(409, "Thành phẩm chưa sẵn sàng để duyệt.")
    if set(body.checklist) != {"quality", "rights", "delivery"}:
        raise HTTPException(422, "Xác nhận chất lượng, quyền sử dụng và bộ file giao hàng.")
    try:
        for name in json.loads(output.manifest_json)["files"]:
            output_file_path(output, name, settings.data_dir)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    output.review_json = body.model_dump_json()
    output.status = "approved"
    session.add(output)
    session.commit()
    return {"approved": True}


@router.get("/outputs/{output_id}/download")
def download(output_id: int, session: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    output = session.get(ProductionOutput, output_id)
    if not output:
        raise HTTPException(404, "Không có thành phẩm.")
    try:
        return FileResponse(package(output, settings.data_dir), filename=f"aiflow-{output.id}.zip")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
