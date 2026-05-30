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
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
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
    """Request body for POST /api/projects."""

    name: str
    adapter: str
    skill: str
    description: Optional[str] = None
    aspect: str = "9:16"


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


class DeleteResponse(BaseModel):
    deleted: bool


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
def create_project(
    body: ProjectCreateRequest,
    session: Session = Depends(get_session),
) -> ProjectCreateResponse:
    """Create a new project.

    Args:
        body: Project creation payload with name, adapter, skill, and optional description.

    Returns:
        ProjectCreateResponse with short_id, status, and created_at.
    """
    logger.info(
        "[projects] POST /api/projects — name=%r adapter=%r skill=%r",
        body.name,
        body.adapter,
        body.skill,
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
    return ProjectCreateResponse(
        short_id=project.short_id,
        status=project.status,
        created_at=project.created_at,
    )


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
