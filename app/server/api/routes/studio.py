"""Shared studio configuration, series, library and production handoffs."""
import base64
import json
import re
import shutil
import uuid
from typing import Literal
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from server.api.routes.audio import local_client
from server.api.routes.projects import get_session, get_settings
from server.api.routes.production import project_or_404, media_public
from server.db.models.studio import StorySeries, SeriesEpisode, StudioLibrary, StudioOperation
from server.db.models.production import ProductionMedia
from server.db.models.scene import Scene
from server.db.models.project import Project
from server.db.models.asset import Asset
from server.production.media import contained, sha256, image_info, probe

router = APIRouter(prefix="/api/studio", dependencies=[Depends(local_client)])
IMAGE_CONFIG = {"key": "", "model": "", "billing_confirmed": False}
ACTIVE_IMAGES: set[str] = set()

class SeriesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=200)
    bible: str = Field(default="", max_length=20000)
    voice: str = Field(default="", max_length=100)
    language: Literal["en", "vi"] = "en"
    model_revision: str = Field(default="", max_length=128)
    speed: float = Field(default=1, ge=0.5, le=2)
    version: int = Field(default=1, ge=1)

@router.get("/series")
def list_series(session: Session = Depends(get_session)):
    return session.exec(select(StorySeries).order_by(StorySeries.id.desc())).all()

@router.post("/series")
def new_series(body: SeriesInput, session: Session = Depends(get_session)):
    row = StorySeries(**body.model_dump(exclude={"version"}))
    session.add(row); session.commit(); session.refresh(row)
    return row

@router.put("/series/{series_id}")
def edit_series(series_id: int, body: SeriesInput, session: Session = Depends(get_session)):
    changed = session.execute(update(StorySeries).where(StorySeries.id == series_id, StorySeries.version == body.version)
        .values(**body.model_dump(exclude={"version"}), version=body.version + 1))
    if changed.rowcount != 1:
        raise HTTPException(409, "Series đã thay đổi. Tải lại trước khi lưu.")
    session.commit()
    return session.get(StorySeries, series_id)

@router.get("/series/{series_id}/episodes")
def episodes(series_id: int, session: Session = Depends(get_session)):
    return [{"root_revision_id": row.root_revision_id, "snapshot": json.loads(row.snapshot_json)}
            for row in session.exec(select(SeriesEpisode).where(SeriesEpisode.series_id == series_id)).all()]

class CanonInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    revision_id: int = Field(gt=0)
    version: int = Field(ge=1)
    bible: str = Field(min_length=1, max_length=20000)

@router.post("/series/{series_id}/canon")
def publish_canon(series_id: int, body: CanonInput, session: Session = Depends(get_session)):
    from server.text.approval import require_approval
    from server.text.workflow import ancestry, get_revision
    revision = get_revision(session, body.revision_id)
    require_approval(session, revision)
    root = ancestry(session, revision)[0]
    episode = session.get(SeriesEpisode, root.id)
    if not episode or episode.series_id != series_id:
        raise HTTPException(422, "Kịch bản không thuộc series này.")
    changed = session.execute(update(StorySeries).where(StorySeries.id == series_id, StorySeries.version == body.version)
                              .values(bible=body.bible, version=body.version + 1))
    if changed.rowcount != 1:
        raise HTTPException(409, "Series đã đổi. Đọc bản mới trước khi cập nhật diễn biến.")
    session.commit()
    return session.get(StorySeries, series_id)

class LibraryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["character", "style", "location", "reference"]
    description: str = Field(default="", max_length=10000)
    media_id: int | None = Field(default=None, gt=0)

@router.get("/library")
def library(session: Session = Depends(get_session)):
    return session.exec(select(StudioLibrary).order_by(StudioLibrary.id.desc())).all()

@router.post("/library")
def library_add(body: LibraryInput, session: Session = Depends(get_session)):
    if body.media_id:
        media = session.get(ProductionMedia, body.media_id)
        if not media or not media.mime.startswith("image/") or media.role == "archived":
            raise HTTPException(422, "Chọn ảnh đang hoạt động trong xưởng.")
    row = StudioLibrary(**body.model_dump())
    session.add(row); session.commit(); session.refresh(row)
    return row

class ApplyLibrary(BaseModel):
    project_id: int = Field(gt=0)

@router.post("/library/{item_id}/apply")
def library_apply(item_id: int, body: ApplyLibrary, session: Session = Depends(get_session), settings=Depends(get_settings)):
    item = session.get(StudioLibrary, item_id)
    project = project_or_404(session, body.project_id)
    if not item or project.status == "generating":
        raise HTTPException(409, "Tài nguyên không có hoặc dự án đang chạy.")
    session.execute(update(Project).where(Project.id == project.id).values(updated_at=Project.updated_at))
    session.refresh(project)
    if project.status == "generating":
        raise HTTPException(409, "Dự án đang chạy.")
    brief = json.loads(project.production_brief)
    entries = brief.setdefault("library", [])
    frozen = item.model_dump()
    if frozen not in entries:
        entries.append(frozen)
        project.production_brief = json.dumps(brief, ensure_ascii=False)
        session.add(project)
        if item.media_id:
            media = session.get(ProductionMedia, item.media_id)
            if not media or media.role == "archived":
                raise HTTPException(409, "Ảnh gốc không còn hoạt động.")
            try:
                source = contained(settings.data_dir, media.path)
                checksum = sha256(source)
            except (OSError, ValueError) as exc:
                raise HTTPException(409, "Ảnh gốc không còn đọc được. Nhập lại ảnh trước khi áp dụng.") from exc
            if checksum != media.sha256:
                raise HTTPException(409, "Ảnh gốc đã thay đổi.")
            folder = settings.data_dir / "studio-library" / str(project.id)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{uuid.uuid4().hex}{source.suffix}"
            shutil.copy2(source, target)
            session.add(Asset(project_id=project.id, name=item.name, type=item.kind,
                              file_path=str(target.resolve()), source="uploaded"))
    session.commit()
    return {"applied": True}

class ImageConnection(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    key: SecretStr = Field(max_length=512)
    model: str = Field(default="", max_length=160)
    billing_confirmed: bool = False

@router.get("/connections")
def connections(settings=Depends(get_settings)):
    from server.text.providers import gemini, openrouter
    from server.text.codex_tmux import public as codex_public
    from server.audio.remote import connection
    from server.flow.client import FlowClient
    codex = codex_public()
    return {"openrouter": bool(openrouter.key), "gemini": bool(gemini.key) and gemini.billing_confirmed,
            "flow": {"connected": FlowClient().is_connected()},
            "codex": {"enabled": codex["ready"] and codex["confirmed"], "reason": codex["message"]}, "audio": connection.public(settings.data_dir),
            "image": {"configured": bool(IMAGE_CONFIG["key"]) and IMAGE_CONFIG["billing_confirmed"], "model": IMAGE_CONFIG["model"]}}

@router.put("/connections/image")
def image_connection(body: ImageConnection):
    key = body.key.get_secret_value().strip()
    if key and not body.model:
        raise HTTPException(422, "Nhập model ảnh Gemini trước khi lưu API key.")
    if body.model and not re.fullmatch(r"gemini-[a-zA-Z0-9._-]+", body.model):
        raise HTTPException(422, "Tên model Gemini không hợp lệ.")
    IMAGE_CONFIG.update(key=key, model=body.model, billing_confirmed=body.billing_confirmed)
    return {"configured": bool(IMAGE_CONFIG["key"]) and IMAGE_CONFIG["billing_confirmed"]}

class GenerateImage(BaseModel):
    request_id: uuid.UUID
    scene_id: int | None = Field(default=None, gt=0)
    prompt: str = Field(default="", max_length=10000)

@router.post("/projects/{project_id}/generate-image")
def generate_image(project_id: int, body: GenerateImage, session: Session = Depends(get_session), settings=Depends(get_settings)):
    inputs = body.model_dump(mode="json")
    def existing_result():
        old = session.get(StudioOperation, str(body.request_id))
        if old:
            if old.kind != "image" or old.project_id != project_id or json.loads(old.input_json) != inputs:
                raise HTTPException(409, "Request ID đã được dùng cho đầu vào khác.")
            return old
        return None
    old = existing_result()
    if old:
        return old
    config = dict(IMAGE_CONFIG)
    if not config["key"] or not config["model"] or not config["billing_confirmed"]:
        raise HTTPException(409, "Cấu hình model ảnh và xác nhận quota/billing ở Kết nối trước.")
    project = project_or_404(session, project_id)
    if project.status == "generating":
        raise HTTPException(409, "Dự án đang chạy.")
    scene = session.get(Scene, body.scene_id) if body.scene_id else None
    if project.kind == "video" and (not scene or scene.project_id != project_id):
        raise HTTPException(422, "Chọn cảnh thuộc dự án.")
    if project.kind not in ("portrait", "video") or (project.kind == "portrait" and body.scene_id):
        raise HTTPException(422, "Loại dự án/cảnh không hợp lệ.")
    if project.kind == "video":
        from server.text.workflow import assert_project_approved
        assert_project_approved(session, project_id)
    references = session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id,
        ProductionMedia.role == "reference")).all() if project.kind == "portrait" else []
    if project.kind == "portrait" and not 1 <= len(references) <= 3:
        raise HTTPException(422, "Nhập 1–3 ảnh tham chiếu trước khi tạo chân dung.")
    parts = []
    asset_snapshot = []
    for ref in references:
        path = contained(settings.data_dir, ref.path)
        if sha256(path) != ref.sha256:
            raise HTTPException(409, "Ảnh tham chiếu đã đổi.")
        parts.append({"inlineData": {"mimeType": ref.mime, "data": base64.b64encode(path.read_bytes()).decode()}})
    for asset in session.exec(select(Asset).where(Asset.project_id == project_id)).all()[:3]:
        if asset.file_path:
            path = contained(settings.data_dir, asset.file_path)
            if path.stat().st_size <= 10 * 1024**2 and path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[path.suffix.lower()]
                parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(path.read_bytes()).decode()}})
                asset_snapshot.append((str(path), sha256(path)))
    if sum(len(part["inlineData"]["data"]) for part in parts) > 18 * 1024**2:
        raise HTTPException(422, "Tổng ảnh tham chiếu quá lớn. Giảm dung lượng ảnh trước khi tạo.")
    frozen = project.production_brief
    reference_snapshot = [(ref.id, ref.sha256) for ref in references]
    scene_prompt = scene.prompt if scene else ""
    parts.append({"text": f"Create one image. Preserve identities in the reference images. Aspect {project.aspect}.\n{frozen}\n{scene_prompt}\n{body.prompt}"})
    operation = StudioOperation(request_id=str(body.request_id), project_id=project_id, kind="image", input_json=json.dumps(inputs))
    session.add(operation)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        old = existing_result()
        if old:
            return old
        raise
    ACTIVE_IMAGES.add(str(body.request_id))
    try:
        with httpx.Client(timeout=180, trust_env=False) as client:
            response = client.post(f"https://generativelanguage.googleapis.com/v1beta/models/{config['model']}:generateContent",
                headers={"x-goog-api-key": config["key"]}, json={"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
            response.raise_for_status()
            data = response.json()
        image = next(p["inlineData"] for c in data.get("candidates", []) for p in c.get("content", {}).get("parts", []) if "inlineData" in p and p["inlineData"].get("mimeType", "").startswith("image/"))
        raw = base64.b64decode(image["data"], validate=True)
        if len(raw) > 10 * 1024**2:
            raise ValueError("Ảnh vượt 10 MiB.")
        suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[image["mimeType"]]
        folder = settings.data_dir / "production/inputs" / str(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(raw)
        width, height = image_info(path)
        session.refresh(project)
        if scene:
            session.refresh(scene)
        current_refs = session.exec(select(ProductionMedia).where(ProductionMedia.project_id == project_id,
            ProductionMedia.role == "reference")).all() if project.kind == "portrait" else []
        stale = (project.production_brief != frozen or (scene and scene.prompt != scene_prompt)
                 or [(ref.id, ref.sha256) for ref in current_refs] != reference_snapshot
                 or any(sha256(contained(settings.data_dir, path)) != checksum for path, checksum in asset_snapshot)
                 or any(sha256(contained(settings.data_dir, ref.path)) != ref.sha256 for ref in current_refs))
        item = ProductionMedia(project_id=project_id, scene_id=body.scene_id,
            role="archived" if stale else "visual" if scene else "portrait", path=str(path.resolve()),
            sha256=sha256(path), mime=image["mimeType"], width=width, height=height,
            review_json=json.dumps({"provider": "gemini", "model": data.get("modelVersion", config["model"]), "request_id": str(body.request_id), "references": reference_snapshot, "assets": asset_snapshot}))
        session.add(item); session.flush()
        operation.status = "needs_attention" if stale else "succeeded"
        operation.result_json = json.dumps(media_public(item))
    except Exception:
        operation.status = "failed"
        operation.error = "Không tạo/nhận được ảnh. Kiểm tra model ảnh, quota và dữ liệu; không tự gọi lại."
    finally:
        ACTIVE_IMAGES.discard(str(body.request_id))
    session.add(operation); session.commit(); session.refresh(operation)
    return operation

@router.get("/projects/{project_id}/operations")
def operations(project_id: int, session: Session = Depends(get_session)):
    from server.production.flow_video import ACTIVE_VIDEOS
    rows = session.exec(select(StudioOperation).where(StudioOperation.project_id == project_id)).all()
    return [{**row.model_dump(), "status": "interrupted" if row.status == "running" and row.request_id not in ACTIVE_IMAGES | ACTIVE_VIDEOS else row.status} for row in rows]

@router.post("/projects/{project_id}/collect-clips")
def collect_clips(project_id: int, session: Session = Depends(get_session), settings=Depends(get_settings)):
    project = project_or_404(session, project_id)
    if project.status == "generating" or project.kind != "video":
        raise HTTPException(409, "Chờ pipeline kết thúc trước khi lấy clip.")
    imported = 0
    for scene in session.exec(select(Scene).where(Scene.project_id == project_id)).all():
        if not scene.video_path:
            continue
        source = contained(settings.data_dir, scene.video_path)
        checksum = sha256(source)
        if session.exec(select(ProductionMedia).where(ProductionMedia.scene_id == scene.id,
                ProductionMedia.role == "visual", ProductionMedia.sha256 == checksum)).first():
            continue
        info = probe(source)
        stream = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
        if not stream:
            raise HTTPException(422, "Clip không có video stream.")
        folder = settings.data_dir / "production/inputs" / str(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{uuid.uuid4().hex}.mp4"
        shutil.copy2(source, target)
        session.add(ProductionMedia(project_id=project_id, scene_id=scene.id, role="visual", path=str(target.resolve()),
            sha256=checksum, mime="video/mp4", width=stream["width"], height=stream["height"], duration=info["duration"]))
        imported += 1
    session.commit()
    return {"imported": imported, "message": "Clip đã chuyển vào xưởng, cần duyệt trước xuất."}
