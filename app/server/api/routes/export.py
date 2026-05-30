"""Export API routes — CapCut draft export and SRT subtitle export.

Endpoints:
    POST /api/projects/{project_id}/export/capcut
        Triggers CapCut draft export for the given project.
        Returns {"draft_path": "...", "status": "ok"}.

    GET /api/projects/{project_id}/export/srt
        Exports the project's subtitles as a downloadable SRT file.
        Returns the SRT file as a FileResponse (attachment download).

Phase 7 — Task 7.2 / Task 7.3
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from loguru import logger
from pydantic import BaseModel

from server.config import Settings, load_settings

router = APIRouter(prefix="/api/projects", tags=["export"])


# ─── Dependency ───────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    """FastAPI dependency that returns the loaded Settings."""
    return load_settings()


# ─── Request / Response models ────────────────────────────────────────────────


class CapCutExportRequest(BaseModel):
    """Optional request body for POST /api/projects/{project_id}/export/capcut.

    All fields are optional — the exporter will auto-discover files from the
    project's storage directory when paths are not provided.
    """

    tts_audio_path: Optional[str] = None
    """Absolute path to the TTS narration MP3 file."""

    bgm_audio_path: Optional[str] = None
    """Absolute path to the BGM audio file (optional)."""

    srt_path: Optional[str] = None
    """Absolute path to the subtitle SRT file (optional)."""

    draft_name: Optional[str] = None
    """Override the draft folder name (optional)."""


class CapCutExportResponse(BaseModel):
    """Response body for POST /api/projects/{project_id}/export/capcut."""

    draft_path: str
    status: str = "ok"


# ─── Route ────────────────────────────────────────────────────────────────────


@router.post(
    "/{project_id}/export/capcut",
    response_model=CapCutExportResponse,
    summary="Export CapCut draft",
    description=(
        "Builds a CapCut / JianYing draft for the given project, including "
        "video clips for each scene, TTS narration, optional BGM, and subtitles. "
        "Returns the path to the created draft folder."
    ),
)
def export_capcut(
    project_id: int,
    body: CapCutExportRequest = CapCutExportRequest(),
    settings: Settings = Depends(get_settings),
) -> CapCutExportResponse:
    """Trigger CapCut draft export for a project.

    Loads the project and its scenes from the database, then calls
    :class:`~server.export.capcut_exporter.CapCutExporter` to build and
    write the draft.

    Args:
        project_id: DB primary key of the project to export.
        body: Optional export parameters (audio paths, SRT path, draft name).
        settings: Loaded application settings (injected via dependency).

    Returns:
        ``CapCutExportResponse`` with ``draft_path`` and ``status="ok"``.

    Raises:
        HTTPException 404: If the project is not found.
        HTTPException 422: If the project has no scenes.
        HTTPException 500: On unexpected export errors.
    """
    logger.info(
        "[export:routes] POST /api/projects/%d/export/capcut", project_id
    )

    # ── Load project and scenes from DB ──────────────────────────────────────
    try:
        from sqlmodel import Session, select

        from server.db.models.project import Project
        from server.db.models.scene import Scene
        from server.db.session import get_engine

        engine = get_engine(settings)
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Project {project_id} not found.",
                )

            scenes = session.exec(
                select(Scene)
                .where(Scene.project_id == project_id)
                .order_by(Scene.order)
            ).all()

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[export:routes] DB error loading project %d: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    if not scenes:
        raise HTTPException(
            status_code=422,
            detail=f"Project {project_id} has no scenes. Run the pipeline first.",
        )

    # ── Auto-discover audio / SRT paths if not provided ──────────────────────
    tts_audio_path = body.tts_audio_path
    bgm_audio_path = body.bgm_audio_path
    srt_path = body.srt_path

    if tts_audio_path is None:
        tts_audio_path = _discover_audio(settings, project_id, "narration")
    if bgm_audio_path is None:
        bgm_audio_path = _discover_audio(settings, project_id, "bgm")
    if srt_path is None:
        srt_path = _discover_srt(settings, project_id)

    # ── Run exporter ─────────────────────────────────────────────────────────
    try:
        from server.export.capcut_exporter import CapCutExporter

        exporter = CapCutExporter(settings)
        draft_path = exporter.export(
            project=project,
            scenes=list(scenes),
            tts_audio_path=tts_audio_path,
            bgm_audio_path=bgm_audio_path,
            srt_path=srt_path,
            draft_name=body.draft_name,
        )
    except ValueError as exc:
        logger.warning("[export:routes] export validation error: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("[export:routes] export failed for project %d: %s", project_id, exc)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

    logger.info(
        "[export:routes] CapCut draft exported: project_id=%d path=%s",
        project_id,
        draft_path,
    )
    return CapCutExportResponse(draft_path=draft_path, status="ok")


# ─── Discovery helpers ────────────────────────────────────────────────────────


def _discover_audio(
    settings: Settings,
    project_id: int,
    kind: str,
) -> Optional[str]:
    """Look for a TTS narration or BGM audio file in the project's audio dir.

    Searches ``{data_dir}/audio/{project_id}/`` for files whose name contains
    *kind* (e.g. ``"narration"`` or ``"bgm"``).

    Returns the first match as a string path, or None if not found.
    """
    audio_dir = Path(settings.data_dir) / "audio" / str(project_id)
    if not audio_dir.exists():
        return None

    for ext in ("*.mp3", "*.wav", "*.m4a"):
        for candidate in sorted(audio_dir.glob(ext)):
            if kind in candidate.name.lower():
                logger.debug(
                    "[export:routes] auto-discovered %s audio: %s", kind, candidate
                )
                return str(candidate)

    return None


def _discover_srt(settings: Settings, project_id: int) -> Optional[str]:
    """Look for a subtitle SRT file in the project's audio dir.

    Searches ``{data_dir}/audio/{project_id}/`` for ``*.srt`` files.

    Returns the first match as a string path, or None if not found.
    """
    audio_dir = Path(settings.data_dir) / "audio" / str(project_id)
    if not audio_dir.exists():
        return None

    candidates = sorted(audio_dir.glob("*.srt"))
    if candidates:
        logger.debug("[export:routes] auto-discovered SRT: %s", candidates[0])
        return str(candidates[0])

    return None


# ─── SRT export route ─────────────────────────────────────────────────────────


@router.get(
    "/{project_id}/export/srt",
    response_model=None,
    summary="Export SRT subtitles",
    description=(
        "Exports the project's subtitles as a downloadable SRT file. "
        "Looks for an existing SRT file in the project's audio directory first. "
        "If none is found, generates one from scene narrations using scene durations. "
        "Returns the SRT content as a file download attachment."
    ),
    responses={
        200: {"content": {"text/plain": {}, "application/octet-stream": {}}},
        404: {"description": "Project not found"},
        422: {"description": "Project has no scenes or narrations"},
    },
)
def export_srt(
    project_id: int,
    inline: bool = False,
    settings: Settings = Depends(get_settings),
):
    """Export the project's subtitles as an SRT file.

    Resolution order:
    1. If an SRT file already exists in ``{data_dir}/audio/{project_id}/``,
       return it directly as a :class:`~fastapi.responses.FileResponse`.
    2. Otherwise, generate an SRT from scene narrations (``scene.narration``
       field) using each scene's duration as the subtitle timing.

    Args:
        project_id: DB primary key of the project to export.
        inline:     When ``True``, return the SRT as ``text/plain`` (for
                    browser preview).  When ``False`` (default), return as
                    a file download attachment.
        settings:   Loaded application settings (injected via dependency).

    Returns:
        :class:`~fastapi.responses.FileResponse` (download) or
        :class:`~fastapi.responses.PlainTextResponse` (inline preview).

    Raises:
        HTTPException 404: If the project is not found.
        HTTPException 422: If the project has no scenes.
        HTTPException 500: On unexpected errors.
    """
    logger.info(
        "[export:routes] GET /api/projects/%d/export/srt (inline=%s)",
        project_id,
        inline,
    )

    # ── Load project and scenes from DB ──────────────────────────────────────
    try:
        from sqlmodel import Session, select

        from server.db.models.project import Project
        from server.db.models.scene import Scene
        from server.db.session import get_engine

        engine = get_engine(settings)
        with Session(engine) as session:
            project = session.get(Project, project_id)
            if project is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Project {project_id} not found.",
                )

            scenes = session.exec(
                select(Scene)
                .where(Scene.project_id == project_id)
                .order_by(Scene.order)
            ).all()

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[export:routes] DB error loading project %d: %s", project_id, exc
        )
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    if not scenes:
        raise HTTPException(
            status_code=422,
            detail=f"Project {project_id} has no scenes. Run the pipeline first.",
        )

    # ── Try to serve an existing SRT file ────────────────────────────────────
    existing_srt = _discover_srt(settings, project_id)
    if existing_srt and Path(existing_srt).exists():
        logger.info(
            "[export:routes] serving existing SRT for project %d: %s",
            project_id,
            existing_srt,
        )
        if inline:
            content = Path(existing_srt).read_text(encoding="utf-8")
            return PlainTextResponse(content=content, media_type="text/plain; charset=utf-8")

        filename = f"project_{project_id}_subtitles.srt"
        return FileResponse(
            path=existing_srt,
            media_type="application/octet-stream",
            filename=filename,
        )

    # ── Generate SRT from scene narrations ───────────────────────────────────
    try:
        from server.export.srt_exporter import SrtExporter, SubtitleSegment

        sorted_scenes = sorted(scenes, key=lambda s: s.order)
        narrations: list[str] = []
        durations: list[float] = []

        for scene in sorted_scenes:
            narration = getattr(scene, "narration", None) or ""
            duration = float(getattr(scene, "duration", 8.0) or 8.0)
            narrations.append(narration)
            durations.append(duration)

        segments = SrtExporter.from_scene_narrations(narrations, durations)

        if not segments:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Project {project_id} has no narration text on its scenes. "
                    "Add narrations or run Whisper transcription first."
                ),
            )

        exporter = SrtExporter()
        srt_content = exporter.generate(segments)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[export:routes] SRT generation failed for project %d: %s",
            project_id,
            exc,
        )
        raise HTTPException(
            status_code=500, detail=f"SRT generation failed: {exc}"
        ) from exc

    logger.info(
        "[export:routes] generated SRT for project %d (%d segment(s))",
        project_id,
        len(segments),
    )

    if inline:
        return PlainTextResponse(
            content=srt_content, media_type="text/plain; charset=utf-8"
        )

    # Return as a downloadable file without writing to disk
    filename = f"project_{project_id}_subtitles.srt"
    return PlainTextResponse(
        content=srt_content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
