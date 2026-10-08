"""Projects API routes.

Endpoints:
    GET    /api/projects          — list all projects
    POST   /api/projects          — create a new project
    GET    /api/projects/{id}     — project detail + scene list
    DELETE /api/projects/{id}     — delete project (hard delete)

Task 5.3 — Phase 5.3
"""

from __future__ import annotations

from datetime import datetime, timezone
import subprocess
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from server.config import Settings, load_settings
from server.db.models.job import Job
from server.db.models.project import Project, _new_short_id, _utcnow
from server.db.models.scene import Scene, LocationHint
from server.db.session import get_engine

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ─── Dependency ───────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    return load_settings()


def get_session(settings: Settings = Depends(get_settings)):
    engine = get_engine(settings)
    with Session(engine) as session:
        yield session


# ─── Request / Response models ────────────────────────────────────────────────


class ProjectCreateRequest(BaseModel):
    """Request body for POST /api/projects.

    Accepts both the short field names (``name``/``adapter``/``skill``/``aspect``)
    and the UI's descriptive aliases (``title``/``adapter_name``/``skill_id``/
    ``aspect_ratio``) so the React client and CLI/tests share one endpoint.
    The optional ``adapter_input`` carries the raw input the adapter will parse
    (stored for the generate step; not required to create a draft project).
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str = Field(validation_alias="title", serialization_alias="name")
    adapter: str = Field(validation_alias="adapter_name")
    skill: str = Field(validation_alias="skill_id")
    description: Optional[str] = None
    aspect: str = Field(default="9:16", validation_alias="aspect_ratio")
    adapter_input: Optional[dict[str, Any]] = None
    voice_id: Optional[str] = None
    language: str = "en"


class ProjectSummary(BaseModel):
    """Minimal project representation for list responses."""

    id: int
    short_id: str
    name: str
    adapter: str
    skill: str
    status: str
    scene_count: int = 0
    created_at: datetime


class SceneSummary(BaseModel):
    """Minimal scene representation nested inside project detail."""

    id: int
    order: int
    duration: float
    status: str
    location_hint: str
    prompt: str = ""
    narration: str = ""
    created_at: datetime


class ProjectDetail(BaseModel):
    """Full project representation including scenes."""

    id: int
    short_id: str
    name: str
    adapter: str
    skill: str
    aspect: str
    status: str
    partial_failure: bool = False
    voice_id: str = "af_heart"
    language: str = "en"
    created_at: datetime
    updated_at: datetime
    scenes: list[SceneSummary]


class ProjectCreateResponse(BaseModel):
    """Response body for POST /api/projects."""

    short_id: str
    status: str
    created_at: datetime
    scene_count: int = 0
    parse_error: Optional[str] = None


class DeleteResponse(BaseModel):
    deleted: bool


class SceneEdit(BaseModel):
    id: int | None = Field(default=None, gt=0)
    duration: float = Field(default=8, ge=3, le=30, allow_inf_nan=False)
    prompt: str = ""
    narration: str = ""
    location_hint: LocationHint = "unspecified"


class SceneListEdit(BaseModel):
    scenes: list[SceneEdit] = Field(min_length=1, max_length=500)


class GenerateResponse(BaseModel):
    """Response body for POST /api/projects/{id}/generate."""

    job_id: int
    status: str
    message: str


class GenerateRequest(BaseModel):
    """Optional request body for POST /api/projects/{id}/generate.

    Attributes:
        dry_run: When True, skip Veo3 generation entirely and produce a local
                 placeholder video (no API credits used). Useful for testing
                 the full create → generate → output UI flow offline.
    """

    dry_run: bool = False


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProjectSummary])
def list_projects(
    session: Session = Depends(get_session),
) -> list[ProjectSummary]:
    """List all projects ordered by creation date (newest first).

    Returns:
        List of project summaries (id, name, adapter, skill, scene_count, created_at, status).
    """
    logger.debug("[projects] GET /api/projects")
    projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    results: list[ProjectSummary] = []
    for p in projects:
        scene_count = len(
            session.exec(select(Scene).where(Scene.project_id == p.id)).all()
        )
        results.append(
            ProjectSummary(
                id=p.id,
                short_id=p.short_id,
                name=p.title,
                adapter=p.adapter,
                skill=p.skill,
                status=p.status,
                scene_count=scene_count,
                created_at=p.created_at,
            )
        )
    return results


@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProjectCreateResponse:
    """Create a new project and parse its input into scenes.

    Steps:
      1. Create the Project row (status="draft").
      2. If ``adapter_input`` is provided, run the matching ContentAdapter to
         produce a SceneList, then persist each scene to the DB. The project
         status becomes ``"ready"`` (scenes ready to generate). If parsing
         fails, the project is still created (status="draft") and the error is
         returned in ``parse_error`` so the UI can show it.

    Args:
        body: Project creation payload (accepts UI or legacy field names).

    Returns:
        ProjectCreateResponse with short_id, status, created_at, scene_count.
    """
    logger.info(
        "[projects] POST /api/projects — name=%r adapter=%r skill=%r has_input=%s",
        body.name,
        body.adapter,
        body.skill,
        body.adapter_input is not None,
    )
    project = Project(
        short_id=_new_short_id(),
        title=body.name,
        adapter=body.adapter,
        skill=body.skill,
        aspect=body.aspect,
        voice_id=body.voice_id or "af_heart",
        language=body.language,
        status="draft",
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    logger.info("[projects] created project short_id=%s id=%d", project.short_id, project.id)

    scene_count = 0
    parse_error: Optional[str] = None

    if body.adapter_input:
        scene_count, parse_error = await _parse_and_persist_scenes(
            session=session,
            project=project,
            adapter_name=body.adapter,
            skill_name=body.skill,
            adapter_input=body.adapter_input,
            settings=settings,
        )
        if parse_error is None:
            project.status = "ready"
            project.updated_at = _utcnow()
            session.add(project)
            session.commit()
            session.refresh(project)

    return ProjectCreateResponse(
        short_id=project.short_id,
        status=project.status,
        created_at=project.created_at,
        scene_count=scene_count,
        parse_error=parse_error,
    )


async def _parse_and_persist_scenes(
    session: Session,
    project: Project,
    adapter_name: str,
    skill_name: str,
    adapter_input: dict[str, Any],
    settings: Settings,
) -> tuple[int, Optional[str]]:
    """Run the adapter for *project* and persist the resulting scenes.

    Returns ``(scene_count, error_message)``. On any adapter error the scenes
    are not persisted and a human-readable message is returned.
    """
    from server.content.base import AdapterError, AdapterInput
    from server.content.registry import REGISTRY
    from server.content.adapters.epub_novel.tiers import EpisodeList

    # Build AdapterInput from the UI payload.
    raw_content = adapter_input.get("raw_content")
    if raw_content is None:
        # Common UI keys mapped to raw_content for convenience.
        for key in ("script", "url", "text", "content"):
            if adapter_input.get(key):
                raw_content = adapter_input[key]
                break
    if raw_content is None:
        # storyboard_manual etc. may pass the whole dict as JSON.
        import json as _json
        raw_content = _json.dumps(adapter_input)

    ai = AdapterInput(
        source_type=adapter_name,
        raw_content=str(raw_content),
        skill_name=skill_name or None,
        assets={"product_image": Path(str(adapter_input["product_image_path"]))}
        if adapter_name == "ecommerce_product" and adapter_input.get("product_image_path") else {},
        options={k: v for k, v in adapter_input.items() if k != "raw_content"},
    )

    try:
        adapter = REGISTRY.get(adapter_name)
    except AdapterError as exc:
        logger.warning("[projects] adapter not found: %s", exc.message)
        return 0, f"Adapter '{adapter_name}' không khả dụng: {exc.message}"

    try:
        scene_list = await adapter.adapt(ai)
    except AdapterError as exc:
        logger.warning("[projects] adapter error: %s", exc.message)
        return 0, exc.message
    except Exception as exc:  # noqa: BLE001
        logger.error("[projects] unexpected adapter error: %s", exc)
        return 0, f"Lỗi phân tích đầu vào: {exc}"

    if isinstance(scene_list, EpisodeList):
        return 0, "EPUB có nhiều tập. Chọn tier='manual' cùng chapter_start và chapter_end để tạo một dự án cho khoảng chương đã chọn."

    product_asset = None
    if ai.assets.get("product_image"):
        import shutil
        from uuid import uuid4
        from server.db.models.asset import Asset

        source = ai.assets["product_image"]
        folder = Path(settings.data_dir) / "media" / str(project.id) / "assets"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            copied = folder / f"{uuid4().hex}{source.suffix.lower()}"
            shutil.copyfile(source, copied)
        except OSError:
            return 0, "Không lưu được ảnh sản phẩm. Kiểm tra file nguồn và dung lượng storage."
        product_asset = Asset(project_id=project.id, name=scene_list.metadata.get("product_name", "Product"),
                              type="product", file_path=str(copied), source="uploaded")
        session.add(product_asset)
        session.flush()

    # Persist scenes.
    valid_hints = {"indoor", "outdoor", "transition", "unspecified"}
    count = 0
    for spec in scene_list.scenes:
        hint = spec.location_hint if spec.location_hint in valid_hints else "unspecified"
        scene = Scene(
            project_id=project.id,
            order=spec.order,
            duration=spec.duration,
            prompt=spec.prompt or "",
            narration=spec.narration or "",
            location_hint=hint,
            status="draft",
        )
        session.add(scene)
        if product_asset is not None and spec.start_image is not None:
            from server.db.models.scene_asset import SceneAsset

            session.flush()
            session.add(SceneAsset(scene_id=scene.id, asset_id=product_asset.id))
        count += 1
    session.commit()
    logger.info("[projects] persisted %d scene(s) for project id=%d", count, project.id)
    return count, None


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: str,
    session: Session = Depends(get_session),
) -> ProjectDetail:
    """Get project detail including its scene list.

    Args:
        project_id: The project's short_id (e.g. "p_a3f9") or integer id.

    Returns:
        Full project detail with scenes list.

    Raises:
        HTTPException 404: If the project is not found.
    """
    logger.debug("[projects] GET /api/projects/%s", project_id)
    project = _find_project(session, project_id)

    scenes = session.exec(
        select(Scene)
        .where(Scene.project_id == project.id)
        .order_by(Scene.order)
    ).all()

    return ProjectDetail(
        id=project.id,
        short_id=project.short_id,
        name=project.title,
        adapter=project.adapter,
        skill=project.skill,
        aspect=project.aspect,
        status=project.status,
        partial_failure=bool(getattr(project, "partial_failure", False)),
        voice_id=project.voice_id,
        language=project.language,
        created_at=project.created_at,
        updated_at=project.updated_at,
        scenes=[
            SceneSummary(
                id=s.id,
                order=s.order,
                duration=s.duration,
                status=s.status,
                location_hint=s.location_hint,
                prompt=getattr(s, "prompt", "") or "",
                narration=getattr(s, "narration", "") or "",
                created_at=s.created_at,
            )
            for s in scenes
        ],
    )


@router.put("/{project_id}/scenes", response_model=ProjectDetail)
def save_project_scenes(
    project_id: str,
    body: SceneListEdit,
    session: Session = Depends(get_session),
) -> ProjectDetail:
    """Save additions, removals, ordering and scene content in one transaction."""
    from server.db.models.audio_task import AudioTask
    from server.db.models.production import ProductionMedia
    from server.db.models.quality_gate import QualityGate
    from server.db.models.scene_asset import SceneAsset
    from server.db.models.studio import StudioOperation
    import json

    project = _find_project(session, project_id)
    existing = session.exec(select(Scene).where(Scene.project_id == project.id).order_by(Scene.order)).all()
    if project.status == "generating" or any(s.status in {"queued", "generating"} for s in existing):
        raise HTTPException(409, "Dự án đang tạo video; chờ tác vụ hoàn tất trước khi sửa cảnh.")
    active_audio = session.exec(select(AudioTask).where(
        AudioTask.project_id == project.id,
        AudioTask.status.in_(["queued", "running", "waiting_resource", "retrying", "cancel_requested"]),
    )).first()
    if active_audio:
        raise HTTPException(409, "Dự án đang có tác vụ audio; hủy hoặc hoàn tất trước khi sửa cảnh.")
    ids = [item.id for item in body.scenes if item.id is not None]
    by_id = {row.id: row for row in existing}
    if len(ids) != len(set(ids)) or any(scene_id not in by_id for scene_id in ids):
        raise HTTPException(422, "Danh sách có cảnh trùng hoặc cảnh không thuộc dự án.")
    removed = [row for row in existing if row.id not in ids]
    # Keep immutable media and audio history attached to its original scene IDs.
    if removed and session.exec(select(AudioTask.id).where(AudioTask.project_id == project.id)).first():
        raise HTTPException(409, "Cảnh có lịch sử audio; tạo dự án mới để giữ bản gốc.")
    removed_ids = {row.id for row in removed}
    for operation in session.exec(select(StudioOperation).where(StudioOperation.project_id == project.id)).all() if removed else []:
        if json.loads(operation.input_json).get("scene_id") in removed_ids:
            raise HTTPException(409, "Cảnh có tác vụ sản xuất đã lưu; giữ cảnh để theo dõi hoặc xử lý tác vụ.")
    for row in removed:
        if (session.exec(select(ProductionMedia.id).where(ProductionMedia.scene_id == row.id)).first()
                or session.exec(select(QualityGate.id).where(QualityGate.scene_id == row.id)).first()):
            raise HTTPException(409, "Cảnh có lịch sử sản xuất; tạo dự án mới để giữ bản gốc.")

    changed = bool(removed)
    for order, item in enumerate(body.scenes):
        row = by_id.get(item.id)
        if row is None:
            row = Scene(project_id=project.id, order=order)
            changed = True
        content_changed = (row.prompt, row.narration, row.duration, row.location_hint) != (
            item.prompt, item.narration, item.duration, item.location_hint)
        changed = changed or content_changed or row.order != order
        if content_changed:
            if row.narration != item.narration:
                row.audio_path = None
            row.video_path = None
            row.last_frame_path = None
            row.status = "draft"
            for media in session.exec(select(ProductionMedia).where(
                ProductionMedia.scene_id == row.id, ProductionMedia.role == "visual",
            )).all() if row.id else []:
                media.approved = False
                session.add(media)
        row.order = order
        row.duration = item.duration
        row.prompt = item.prompt
        row.narration = item.narration
        row.location_hint = item.location_hint
        row.updated_at = _utcnow()
        session.add(row)
    # Allocate new IDs before deleting rows, avoiding ID reuse in this edit.
    session.flush()
    for row in removed:
        for link in session.exec(select(SceneAsset).where(SceneAsset.scene_id == row.id)).all():
            session.delete(link)
        session.delete(row)
    if changed:
        project.status = "ready"
        project.updated_at = _utcnow()
        session.add(project)
    session.commit()
    return get_project(project_id, session)


@router.delete("/{project_id}", response_model=DeleteResponse)
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DeleteResponse:
    """Delete a project and all its associated scenes and jobs.

    Performs a hard delete: removes scenes and jobs belonging to the project,
    then removes the project itself.

    Args:
        project_id: The project's short_id or integer id.

    Returns:
        {"deleted": true}

    Raises:
        HTTPException 404: If the project is not found.
        HTTPException 409: If the project is currently generating (status="generating").
    """
    logger.info("[projects] DELETE /api/projects/%s", project_id)
    project = _find_project(session, project_id)

    if project.status == "generating":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "STATE_CONFLICT",
                    "message": "Cannot delete a project that is currently generating. Cancel the job first.",
                }
            },
        )

    scenes = session.exec(select(Scene).where(Scene.project_id == project.id)).all()
    output_dir = settings.data_dir / "output" / str(project.id)
    if (any(scene.video_path or scene.audio_path or scene.last_frame_path for scene in scenes)
            or (output_dir.is_dir() and any(output_dir.iterdir()))):
        raise HTTPException(409, "Dự án có file audio/video đã tạo. Giữ dự án để bảo toàn file và tránh tái sử dụng thư mục đầu ra.")

    # Preserve delivery/audit history and prevent recycled SQLite IDs from
    # binding old media or audio work to a newly created project.
    from server.db.models.production import ProductionMedia, ProductionOutput
    from server.db.models.audio_task import AudioTask
    from server.db.models.studio import StudioOperation
    from server.db.models.script_revision import ScriptRevision
    if (session.exec(select(ProductionMedia.id).where(ProductionMedia.project_id == project.id)).first()
            or session.exec(select(ProductionOutput.id).where(ProductionOutput.project_id == project.id)).first()
            or session.exec(select(AudioTask.id).where(AudioTask.project_id == project.id)).first()
            or session.exec(select(StudioOperation.request_id).where(StudioOperation.project_id == project.id)).first()
            or session.exec(select(ScriptRevision.id).where(
                (ScriptRevision.project_id == project.id) | (ScriptRevision.project_short_id == project.short_id))).first()):
        raise HTTPException(409, "Dự án có lịch sử kịch bản/audio/thành phẩm. Giữ dự án để bảo toàn tham chiếu và bộ file đã duyệt.")

    # Remove relational dependents before their parents; user files stay on disk.
    from sqlalchemy import delete
    from server.db.models.asset import Asset
    from server.db.models.job import JobLog
    from server.db.models.quality_gate import QualityGate
    from server.db.models.scene_asset import SceneAsset
    from server.db.models.style import Style
    scene_ids = select(Scene.id).where(Scene.project_id == project.id)
    asset_ids = select(Asset.id).where(Asset.project_id == project.id)
    job_ids = select(Job.id).where(Job.project_id == project.id)
    session.execute(delete(SceneAsset).where(
        SceneAsset.scene_id.in_(scene_ids) | SceneAsset.asset_id.in_(asset_ids)))
    session.execute(delete(QualityGate).where(
        (QualityGate.project_id == project.id) | QualityGate.scene_id.in_(scene_ids)))
    session.execute(delete(JobLog).where(JobLog.job_id.in_(job_ids)))
    session.execute(delete(Style).where(Style.project_id == project.id))
    session.execute(delete(Asset).where(Asset.project_id == project.id))
    for scene in scenes:
        session.delete(scene)

    jobs = session.exec(select(Job).where(Job.project_id == project.id)).all()
    for job in jobs:
        session.delete(job)

    session.delete(project)
    session.commit()
    logger.info("[projects] deleted project id=%d short_id=%s", project.id, project.short_id)
    return DeleteResponse(deleted=True)


# ─── Generation ───────────────────────────────────────────────────────────────


@router.post("/{project_id}/generate", response_model=GenerateResponse, status_code=202)
def generate_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    body: GenerateRequest = GenerateRequest(),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
) -> GenerateResponse:
    """Kick off video generation for a project (runs in the background).

    Creates a ``Job`` row, sets the project to ``generating``, and schedules
    the orchestrator to run via FastAPI background tasks. The client tracks
    progress via ``GET /api/jobs/{job_id}/stream`` (SSE) and polls
    ``GET /api/projects/{id}`` for the final status.

    When ``body.dry_run`` is True, generation produces a local placeholder
    video instead of calling Veo3 (no API credits used).

    Returns 202 Accepted immediately. Requires the project to have scenes.

    Raises:
        HTTPException 404: project not found.
        HTTPException 409: project already generating.
        HTTPException 422: project has no scenes.
    """
    from server.pipeline.job_manager import add_job_log, create_job

    project = _find_project(session, project_id)

    if project.status == "generating":
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "STATE_CONFLICT", "message": "Dự án đang được tạo video."}},
        )

    scene_count = len(
        session.exec(select(Scene).where(Scene.project_id == project.id)).all()
    )
    if scene_count == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "NO_SCENES",
                    "message": "Dự án chưa có cảnh nào. Hãy phân tích đầu vào trước.",
                }
            },
        )

    from server.text.workflow import assert_project_approved
    assert_project_approved(session, project.id)

    job = create_job(session, project_id=project.id, job_type="generate")
    mode = "dry-run (placeholder)" if body.dry_run else "Veo3"
    add_job_log(session, job.id, "INFO", f"Bắt đầu tạo video cho {scene_count} cảnh — chế độ {mode}.")

    project.status = "generating"
    project.updated_at = _utcnow()
    session.add(project)
    session.commit()

    from server.audio.queue import enqueue, project_snapshot
    if not body.dry_run and project_snapshot(session, project):
        audio_task = enqueue(session, settings, project=project, title=f"Giọng đọc: {project.title}", generation_job_id=job.id)
        job.status = "waiting_resource"
        session.add(job)
        session.commit()
        add_job_log(session, job.id, "INFO", f"Chờ audio #{audio_task.id}. Mở Kết nối Colab để tiếp tục.")
        return GenerateResponse(job_id=job.id, status="waiting_resource", message="Đang chuẩn bị giọng đọc; mở Kết nối Colab nếu cần.")
    background_tasks.add_task(_run_generation, project.id, job.id, settings, body.dry_run)

    logger.info(
        "[projects] generation scheduled project_id=%d job_id=%d dry_run=%s",
        project.id, job.id, body.dry_run,
    )
    return GenerateResponse(
        job_id=job.id,
        status="generating",
        message=f"Đã lên lịch tạo video cho {scene_count} cảnh ({mode}).",
    )


def _run_generation(project_id: int, job_id: int, settings: Settings, dry_run: bool = False) -> None:
    """Background worker: run the pipeline orchestrator for *project_id*.

    Runs synchronously inside a FastAPI background task. Updates Job + Project
    status and logs progress to JobLog. Any failure marks the job failed and
    the project back to ``ready`` so the user can retry.
    """
    import asyncio

    from server.pipeline.job_manager import add_job_log, update_job_status

    engine = get_engine(settings)

    def _now():
        return datetime.now(timezone.utc)

    try:
        with Session(engine) as session:
            from server.text.workflow import assert_project_approved
            assert_project_approved(session, project_id)
            update_job_status(session, job_id, "running", started_at=_now())

        if dry_run:
            _run_dry_run(project_id, job_id, settings)
            with Session(engine) as session:
                project = session.get(Project, project_id)
                if project is not None:
                    project.status = "done"
                    project.updated_at = _now()
                    session.add(project)
                    session.commit()
                update_job_status(session, job_id, "success", finished_at=_now())
                add_job_log(session, job_id, "INFO", "Tạo video hoàn tất.")
            logger.info("[projects] dry-run done project_id=%d job_id=%d", project_id, job_id)
            return

        # Real Veo3 generation: orchestrator returns (all_passed, final_path).
        # If no scene succeeded, _orchestrate() raises so we mark the job
        # failed and the project back to "ready" for retry.
        all_passed, final_path = asyncio.run(
            _orchestrate(project_id, job_id, settings)
        )

        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "done"
                project.partial_failure = not all_passed  # type: ignore[attr-defined]
                project.updated_at = _now()
                session.add(project)
                session.commit()
            update_job_status(session, job_id, "success", finished_at=_now())
            if all_passed:
                add_job_log(session, job_id, "INFO", f"Tạo video hoàn tất → {final_path.name}")
            else:
                add_job_log(
                    session,
                    job_id,
                    "WARNING",
                    f"Tạo video hoàn tất với một số cảnh bị bỏ qua → {final_path.name}",
                )
        logger.info(
            "[projects] generation done project_id=%d job_id=%d all_passed=%s final=%s",
            project_id, job_id, all_passed, final_path,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("[projects] generation failed project_id=%d: %s", project_id, exc)
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "ready"
                project.updated_at = _now()
                session.add(project)
                session.commit()
            update_job_status(session, job_id, "failed", finished_at=_now())
            add_job_log(session, job_id, "ERROR", f"Tạo video thất bại: {exc}")


def _run_dry_run(project_id: int, job_id: int, settings: Settings) -> None:
    """Produce a local placeholder ``final.mp4`` without calling Veo3.

    Uses FFmpeg's ``lavfi`` test source to synthesise a short colour clip whose
    total duration matches the sum of scene durations. No external API is used,
    so this is safe for testing the full UI flow without spending credits.

    Raises:
        RuntimeError: If FFmpeg is unavailable or the encode fails.
    """
    import subprocess

    from server.audio.ffmpeg_utils import find_ffmpeg
    from server.pipeline.job_manager import add_job_log

    engine = get_engine(settings)
    with Session(engine) as session:
        project = session.get(Project, project_id)
        size = {"16:9": "1280x720", "1:1": "720x720"}.get(project.aspect if project else "9:16", "720x1280")
        scenes = list(
            session.exec(
                select(Scene).where(Scene.project_id == project_id).order_by(Scene.order)
            ).all()
        )
    total_dur = max(2.0, min(60.0, sum(float(s.duration or 8.0) for s in scenes)))

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg không khả dụng — không thể tạo video dry-run.")

    out_dir = Path(settings.data_dir) / "output" / str(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "final.mp4"

    # Colour test source + silent audio, encoded to a web-friendly MP4.
    cmd = [
        str(ffmpeg), "-y",
        "-f", "lavfi", "-i", f"color=c=0x1E3A8A:s={size}:d={total_dur:.1f}",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    with Session(engine) as session:
        add_job_log(session, job_id, "INFO", f"Dry-run: dựng video placeholder {total_dur:.1f}s.")

    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0 or not out_path.is_file():
        stderr = result.stderr.decode(errors="replace")[-500:]
        raise RuntimeError(f"FFmpeg dry-run thất bại: {stderr}")

    logger.info("[projects] dry-run placeholder written → %s", out_path)


async def _orchestrate(
    project_id: int, job_id: int, settings: Settings
) -> tuple[bool, Path]:
    """Build orchestrator inputs from the DB, run the full pipeline, then
    compose ``final.mp4`` with the G6 quality gate.

    Returns:
        ``(all_passed, final_path)`` — ``all_passed=False`` means at least one
        scene was skipped/failed but the remaining clips were still composed.
        Raises ``RuntimeError`` if no scene produced a usable clip.
    """
    from server.db.models.asset import Asset
    from server.flow.sdk import FlowSDK
    from server.pipeline.event_bus import get_event_bus
    from server.pipeline.event_bus_bridge import EventBusJobLogBridge
    from server.pipeline.job_manager import add_job_log
    from server.pipeline.orchestrator import PipelineOrchestrator
    from server.render.composer import (
        AspectRatio,
        ClipInput,
        ComposeConfig,
        SubtitleConfig,
        SubtitleSegment,
    )

    engine = get_engine(settings)
    with Session(engine) as session:
        scenes = list(
            session.exec(
                select(Scene).where(Scene.project_id == project_id).order_by(Scene.order)
            ).all()
        )
        assets = list(session.exec(select(Asset).where(Asset.project_id == project_id)).all())
        project = session.get(Project, project_id)
        skill_name = project.skill if project else ""
        aspect = (project.aspect if project else "9:16") or "9:16"

    style_json = _resolve_style_json(skill_name)

    sdk = FlowSDK()
    bus = get_event_bus()
    bridge = EventBusJobLogBridge(bus, engine, job_id, project_id=project_id)
    orch = PipelineOrchestrator(settings=settings, flow_sdk=sdk, event_bus=bus)
    def persist_scene(scene):
        with Session(engine) as session:
            row = session.get(Scene, scene.id)
            if row is None or (row.prompt, row.narration) != (scene.prompt, scene.narration):
                raise RuntimeError("Scene changed while generating; output was not attached.")
            row.video_path, row.audio_path, row.last_frame_path = scene.video_path, scene.audio_path, scene.last_frame_path
            row.status = "quality_check" if scene.video_path else "failed"
            session.add(row)
            session.commit()
    try:
        all_passed = await orch.run(
            project_id=project_id,
            scenes=scenes,
            style_json=style_json,
            assets=assets,
            aspect=aspect,
            persist_scene=persist_scene,
        )

        # ── Persist scene generation outputs (orchestrator only mutates ORM) ──
        with Session(engine) as session:
            for s in scenes:
                row = session.get(Scene, s.id)
                if row is None:
                    continue
                row.video_path = getattr(s, "video_path", None)
                row.audio_path = getattr(s, "audio_path", None)
                row.last_frame_path = getattr(s, "last_frame_path", None)
                session.add(row)
            session.commit()

        # ── Filter scenes that actually produced a clip ───────────────────────
        successful: list[Scene] = [
            s for s in sorted(scenes, key=lambda x: x.order)
            if s.video_path and Path(s.video_path).is_file()
        ]
        if not successful:
            with Session(engine) as session:
                add_job_log(
                    session,
                    job_id,
                    "ERROR",
                    f"Không cảnh nào tạo được clip (0/{len(scenes)}) — bỏ qua compose.",
                )
            raise RuntimeError(
                f"Pipeline produced no usable clips for project {project_id}."
            )

        skipped = len(scenes) - len(successful)
        if skipped:
            with Session(engine) as session:
                add_job_log(
                    session,
                    job_id,
                    "WARNING",
                    f"Compose chỉ với {len(successful)}/{len(scenes)} cảnh — "
                    f"{skipped} cảnh bị bỏ qua do fail.",
                )

        # Scene-level subtitle timing and narration gaps use measured audio durations.
        from server.production.media import align_narration
        out_dir = Path(settings.data_dir) / "output" / str(project_id)
        merged_audio, measured_subtitles = align_narration(successful, out_dir)
        subtitle_segments = [SubtitleSegment(**item) for item in measured_subtitles]

        # ── Build ComposeConfig ────────────────────────────────────────────────
        clips = [
            ClipInput(
                file_path=Path(s.video_path),
                duration=float(s.duration or 8.0),
                transition="direct_concat",
                has_audio=False,
            )
            for s in successful
        ]
        aspect_value: AspectRatio = aspect if aspect in ("9:16", "16:9", "1:1") else "9:16"  # type: ignore[assignment]
        compose_config = ComposeConfig(
            project_id=str(project_id),
            clips=clips,
            tts_path=merged_audio,
            output_dir=out_dir,
            aspect_ratio=aspect_value,
            subtitle=SubtitleConfig(segments=subtitle_segments),
        )

        expected_dur = sum(c.duration for c in clips)
        final_path = orch.compose_with_g6(
            project_id=project_id,
            compose_config=compose_config,
            expected_duration=expected_dur,
            aspect_ratio=aspect_value,
        )
        logger.info("[orchestrate] final.mp4 generated → %s", final_path)
        with Session(engine) as session:
            add_job_log(
                session,
                job_id,
                "INFO",
                f"Đã ghép xong final.mp4 ({len(clips)} clip, ~{expected_dur:.1f}s).",
            )
        return all_passed, final_path
    finally:
        bridge.close()


def _try_transcribe_subtitle(
    merged_audio: Optional[Path],
    out_dir: Path,
    job_id: int,
    engine,
) -> list:
    """Best-effort Whisper transcription for subtitle burn-in.

    Runs Whisper against the merged narration MP3 and returns a list of
    ``SubtitleSegment`` for the composer (burn-in via drawtext).  The SRT
    file is also written to ``{out_dir}/subtitle.srt`` so the export route
    can serve it standalone.

    Failures (no audio, faster-whisper not installed, runtime error) are
    swallowed and logged — subtitle is non-essential and must never block
    the compose stage.

    Args:
        merged_audio: Path to the merged narration MP3 (or None when there
                      is no narration at all).
        out_dir:      Project output directory (where ``subtitle.srt`` is
                      written).
        job_id:       Job id used for JobLog warnings.
        engine:       SQLAlchemy engine for JobLog session.

    Returns:
        List of ``SubtitleSegment`` ready for ``ComposeConfig.subtitle``.
        Empty list when transcription is skipped or fails.
    """
    from server.pipeline.job_manager import add_job_log
    from server.render.composer import SubtitleSegment

    if merged_audio is None or not Path(merged_audio).is_file():
        return []

    try:
        from server.audio.transcribe import transcribe_to_srt, transcribe
    except ImportError as exc:  # pragma: no cover — module always exists
        logger.warning("[orchestrate] transcribe module unavailable: %s", exc)
        return []

    srt_path = out_dir / "subtitle.srt"
    try:
        # Write the SRT file once (so /export/srt can serve it) and reuse
        # the same segments for in-video burn-in to avoid double work.
        segments = transcribe(
            audio_path=Path(merged_audio),
            language="vi",
            model_size="base",
        )
        if not segments:
            logger.info("[orchestrate] subtitle: 0 segments (silent audio?) — skip burn-in")
            return []

        srt_path.parent.mkdir(parents=True, exist_ok=True)
        with srt_path.open("w", encoding="utf-8") as fh:
            for seg in segments:
                fh.write(seg.to_srt_block())
                fh.write("\n")

        with Session(engine) as session:
            add_job_log(
                session,
                job_id,
                "INFO",
                f"Tạo phụ đề: {len(segments)} đoạn → {srt_path.name}",
            )
        return [
            SubtitleSegment(
                text=seg.text,
                start_sec=float(seg.start_time),
                end_sec=float(seg.end_time),
            )
            for seg in segments
        ]
    except ImportError as exc:
        logger.warning("[orchestrate] faster-whisper not installed — skip subtitle: %s", exc)
        with Session(engine) as session:
            add_job_log(
                session,
                job_id,
                "WARNING",
                "Bỏ qua phụ đề: chưa cài faster-whisper.",
            )
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[orchestrate] subtitle transcription failed: %s", exc)
        with Session(engine) as session:
            add_job_log(
                session,
                job_id,
                "WARNING",
                f"Bỏ qua phụ đề: lỗi transcribe ({exc}).",
            )
        return []


def _merge_narrations_to_mp3(
    audio_paths: list[Path], project_id: int, settings: Settings
) -> Optional[Path]:
    """Concatenate narration MP3 files into a single track for the composer.

    The composer's ``ComposeConfig.tts_path`` accepts only one audio file,
    so per-scene narrations must be merged into one track that anchors the
    full timeline.  Uses FFmpeg's ``concat`` demuxer for stream-copy when
    possible; falls back to re-encoding when streams are incompatible.

    Args:
        audio_paths: Per-scene narration MP3 paths (already exist on disk).
        project_id:  Project id (used to name the merged file).
        settings:    Application settings (data_dir, ffmpeg lookup).

    Returns:
        Path to the merged MP3, or ``None`` when ``audio_paths`` is empty.
    """
    import subprocess
    import tempfile

    from server.audio.ffmpeg_utils import find_ffmpeg

    if not audio_paths:
        return None
    if len(audio_paths) == 1:
        return audio_paths[0]

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        logger.warning("[orchestrate] ffmpeg not available — using first narration only.")
        return audio_paths[0]

    audio_dir = Path(settings.data_dir) / "audio" / str(project_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_path = audio_dir / "narration_merged.mp3"

    # Build a temporary concat list file (FFmpeg requires forward slashes
    # and quoting for paths with spaces).
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as fh:
        list_file = Path(fh.name)
        for p in audio_paths:
            fh.write(f"file '{str(p).replace(chr(92), '/')}'\n")

    try:
        cmd = [
            str(ffmpeg), "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:a", "libmp3lame", "-b:a", "192k",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=180)
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")[-400:]
            logger.warning(
                "[orchestrate] narration merge failed (rc=%s) — using first track: %s",
                result.returncode, stderr,
            )
            return audio_paths[0]
        logger.info(
            "[orchestrate] merged %d narration tracks → %s", len(audio_paths), out_path
        )
        return out_path
    finally:
        list_file.unlink(missing_ok=True)


def _resolve_style_json(skill_name: str) -> str:
    """Load the skill's ``style.json`` as a JSON string for Layer-1 Style Lock.

    Returns ``"{}"`` when the skill is unknown or has no style so the
    orchestrator's StyleLock degrades gracefully.
    """
    import json as _json

    if not skill_name:
        return "{}"
    try:
        from server.content.skill_loader import SkillLoader

        skills_dir = Path(__file__).resolve().parents[3] / "skills"
        loaded = SkillLoader(skills_dir).load(skill_name)
        return _json.dumps(loaded.style or {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[projects] could not load style for skill %r: %s", skill_name, exc)
        return "{}"


# ─── Output file ──────────────────────────────────────────────────────────────


@router.get("/{project_id}/output")
def get_project_output(
    project_id: str,
    download: int = 0,
    quality: Literal["original", "1080p", "720p", "480p"] = "original",
    format: Literal["mp4", "webm"] = "mp4",
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
):
    """Serve the final rendered video (``final.mp4``) for a project.

    Looks in ``{data_dir}/output/{project.id}/final.mp4``. Returns the file as
    a streaming ``FileResponse`` (inline by default, attachment when
    ``?download=1``).

    Raises:
        HTTPException 404: project not found or no rendered video yet.
    """
    project = _find_project(session, project_id)
    from server.api.safe_files import safe_resolve

    output_base = Path(settings.data_dir) / "output"
    # Path-traversal safe: str(project.id) is an int from the DB, but resolve
    # through the guard anyway as defence-in-depth.
    out_path = safe_resolve(output_base, str(project.id), "final.mp4")
    if not out_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "OUTPUT_NOT_READY",
                    "message": "Video chưa được tạo xong.",
                }
            },
        )
    from server.export.video import export_video
    try:
        out_path = export_video(out_path, quality, format)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, "Không thể chuyển định dạng video. Kiểm tra FFmpeg và thử lại.") from exc
    except subprocess.SubprocessError as exc:
        raise HTTPException(503, "Chuyển định dạng video thất bại hoặc quá thời gian; thử lại bản gốc.") from exc
    filename = f"{project.title or project.short_id}.{format}"
    return FileResponse(
        path=str(out_path),
        media_type=f"video/{format}",
        filename=filename if download else None,
    )


# ─── Quality gates ────────────────────────────────────────────────────────────


class GateInfo(BaseModel):
    """Minimal QualityGate representation for /gates routes."""

    id: int
    project_id: int
    gate_id: str
    status: str
    score: Optional[float] = None
    expired_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


def _gate_to_info(gate) -> GateInfo:
    return GateInfo(
        id=gate.id,
        project_id=gate.project_id,
        gate_id=gate.gate_id,
        status=gate.status,
        score=gate.score,
        expired_at=gate.expired_at,
        created_at=gate.created_at,
        updated_at=gate.updated_at,
    )


@router.get("/{project_id}/gates/pending", response_model=list[GateInfo])
def list_pending_gates(
    project_id: str,
    session: Session = Depends(get_session),
) -> list[GateInfo]:
    """List quality gates currently waiting for user input (status=checking).

    Used by the Timeline UI to drive the G2 Asset-Approval modal: the FE
    polls (or listens via SSE) and opens a modal whenever a G2 gate appears
    in this list.

    Args:
        project_id: short_id or integer id of the project.

    Returns:
        Zero or more gates in ``checking`` status, newest first.
    """
    from server.db.models.quality_gate import QualityGate

    project = _find_project(session, project_id)
    gates = session.exec(
        select(QualityGate)
        .where(QualityGate.project_id == project.id)
        .where(QualityGate.status == "checking")
        .order_by(QualityGate.created_at.desc())
    ).all()
    return [_gate_to_info(g) for g in gates]


@router.post("/{project_id}/gates/{gate_db_id}/approve", response_model=GateInfo)
def approve_gate(
    project_id: str,
    gate_db_id: int,
    session: Session = Depends(get_session),
) -> GateInfo:
    """Mark a checking gate as ``passed`` (user approved).

    The orchestrator's polling loop (``_wait_for_g2``) sees the status
    change and continues the pipeline.

    Args:
        project_id: short_id or integer id of the project.
        gate_db_id: ``QualityGate.id`` to approve.

    Raises:
        HTTPException 404: gate not found or doesn't belong to this project.
        HTTPException 409: gate already resolved (not in ``checking`` state).
    """
    from server.db.models.quality_gate import QualityGate

    project = _find_project(session, project_id)
    gate = session.get(QualityGate, gate_db_id)
    if gate is None or gate.project_id != project.id:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GATE_NOT_FOUND", "message": "Gate không tồn tại."}},
        )
    if gate.status != "checking":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "GATE_NOT_PENDING",
                    "message": f"Gate đã ở trạng thái {gate.status!r}, không thể duyệt.",
                }
            },
        )
    gate.status = "passed"
    gate.updated_at = datetime.now(timezone.utc)
    session.add(gate)
    session.commit()
    session.refresh(gate)
    logger.info(
        "[projects] gate %s (id=%d) approved for project %s",
        gate.gate_id, gate.id, project.short_id,
    )
    return _gate_to_info(gate)


@router.post("/{project_id}/gates/{gate_db_id}/override", response_model=GateInfo)
def override_gate(
    project_id: str,
    gate_db_id: int,
    session: Session = Depends(get_session),
) -> GateInfo:
    """Mark a checking gate as ``overridden`` (user skips approval).

    Same effect as approve for the orchestrator (it stops waiting), but the
    distinct status lets us audit which projects bypassed quality review.

    Args:
        project_id: short_id or integer id of the project.
        gate_db_id: ``QualityGate.id`` to override.

    Raises:
        HTTPException 404: gate not found.
        HTTPException 409: gate already resolved.
    """
    from server.db.models.quality_gate import QualityGate

    project = _find_project(session, project_id)
    gate = session.get(QualityGate, gate_db_id)
    if gate is None or gate.project_id != project.id:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "GATE_NOT_FOUND", "message": "Gate không tồn tại."}},
        )
    if gate.status != "checking":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "GATE_NOT_PENDING",
                    "message": f"Gate đã ở trạng thái {gate.status!r}, không thể override.",
                }
            },
        )
    gate.status = "overridden"
    gate.updated_at = datetime.now(timezone.utc)
    session.add(gate)
    session.commit()
    session.refresh(gate)
    logger.info(
        "[projects] gate %s (id=%d) overridden for project %s",
        gate.gate_id, gate.id, project.short_id,
    )
    return _gate_to_info(gate)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _find_project(session: Session, project_id: str) -> Project:
    """Look up a project by short_id or integer id.

    Args:
        session: Active SQLModel session.
        project_id: short_id string (e.g. "p_a3f9") or integer id as string.

    Returns:
        The Project instance.

    Raises:
        HTTPException 404: If not found.
    """
    # Try short_id first
    project = session.exec(
        select(Project).where(Project.short_id == project_id)
    ).first()

    if project is None:
        # Try integer id
        try:
            int_id = int(project_id)
            project = session.get(Project, int_id)
        except (ValueError, TypeError):
            pass

    if project is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "PROJECT_NOT_FOUND",
                    "message": f"Project '{project_id}' not found.",
                }
            },
        )
    return project
