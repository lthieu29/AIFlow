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
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from server.config import Settings, load_settings
from server.db.models.job import Job
from server.db.models.project import Project, _new_short_id, _utcnow
from server.db.models.scene import Scene
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


class ProjectSummary(BaseModel):
    """Minimal project representation for list responses."""

    id: int
    short_id: str
    name: str
    adapter: str
    skill: str
    status: str
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
        List of project summaries (id, name, adapter, skill, created_at, status).
    """
    logger.debug("[projects] GET /api/projects")
    projects = session.exec(select(Project).order_by(Project.created_at.desc())).all()
    return [
        ProjectSummary(
            id=p.id,
            short_id=p.short_id,
            name=p.title,
            adapter=p.adapter,
            skill=p.skill,
            status=p.status,
            created_at=p.created_at,
        )
        for p in projects
    ]


@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest,
    session: Session = Depends(get_session),
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
) -> tuple[int, Optional[str]]:
    """Run the adapter for *project* and persist the resulting scenes.

    Returns ``(scene_count, error_message)``. On any adapter error the scenes
    are not persisted and a human-readable message is returned.
    """
    from server.content.base import AdapterError, AdapterInput
    from server.content.registry import REGISTRY

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


@router.delete("/{project_id}", response_model=DeleteResponse)
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
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

    # Hard delete: cascade scenes → jobs → project
    scenes = session.exec(select(Scene).where(Scene.project_id == project.id)).all()
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

    job = create_job(session, project_id=project.id, job_type="generate")
    mode = "dry-run (placeholder)" if body.dry_run else "Veo3"
    add_job_log(session, job.id, "INFO", f"Bắt đầu tạo video cho {scene_count} cảnh — chế độ {mode}.")

    project.status = "generating"
    project.updated_at = _utcnow()
    session.add(project)
    session.commit()

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
            update_job_status(session, job_id, "running", started_at=_now())

        if dry_run:
            _run_dry_run(project_id, job_id, settings)
        else:
            # Run the async orchestrator from this sync background task.
            asyncio.run(_orchestrate(project_id, job_id, settings))

        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is not None:
                project.status = "done"
                project.updated_at = _now()
                session.add(project)
                session.commit()
            update_job_status(session, job_id, "success", finished_at=_now())
            add_job_log(session, job_id, "INFO", "Tạo video hoàn tất.")
        logger.info("[projects] generation done project_id=%d job_id=%d", project_id, job_id)

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
        "-f", "lavfi", "-i", f"color=c=0x1E3A8A:s=720x1280:d={total_dur:.1f}",
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


async def _orchestrate(project_id: int, job_id: int, settings: Settings) -> None:
    """Build the orchestrator inputs from the DB and run the full pipeline."""
    from server.db.models.asset import Asset
    from server.flow.sdk import FlowSDK
    from server.pipeline.event_bus import EventBus
    from server.pipeline.orchestrator import PipelineOrchestrator

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

    style_json = _resolve_style_json(skill_name)

    sdk = FlowSDK()
    orch = PipelineOrchestrator(settings=settings, flow_sdk=sdk, event_bus=EventBus())
    await orch.run(
        project_id=project_id,
        scenes=scenes,
        style_json=style_json,
        assets=assets,
    )


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
    filename = f"{project.title or project.short_id}.mp4"
    return FileResponse(
        path=str(out_path),
        media_type="video/mp4",
        filename=filename if download else None,
    )


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
