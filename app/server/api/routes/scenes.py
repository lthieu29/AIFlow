"""Scenes API routes.

Endpoints:
    GET   /api/scenes/{id}   — scene detail (prompt, duration, status, assets)
    PATCH /api/scenes/{id}   — update scene fields (prompt, duration, status)

Task 5.3 — Phase 5.3
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlmodel import Session, select

from server.config import Settings, load_settings
from server.db.models.asset import Asset
from server.db.models.scene import Scene
from server.db.models.scene_asset import SceneAsset
from server.db.session import get_engine

router = APIRouter(prefix="/api/scenes", tags=["scenes"])


# ─── Dependency ───────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    return load_settings()


def get_session(settings: Settings = Depends(get_settings)):
    engine = get_engine(settings)
    with Session(engine) as session:
        yield session


# ─── Request / Response models ────────────────────────────────────────────────


class AssetRef(BaseModel):
    """Asset reference nested inside scene detail."""

    id: int
    name: str
    type: str
    ref_url: Optional[str]
    role: Optional[str]


class SceneDetail(BaseModel):
    """Full scene representation including asset refs."""

    id: int
    project_id: int
    order: int
    duration: float
    status: str
    location_hint: str
    created_at: datetime
    updated_at: datetime
    assets: list[AssetRef]


class ScenePatchRequest(BaseModel):
    """Request body for PATCH /api/scenes/{id}.

    All fields are optional — only provided fields are updated.
    """

    duration: Optional[float] = None
    status: Optional[str] = None
    location_hint: Optional[str] = None


class ScenePatchResponse(BaseModel):
    """Response body for PATCH /api/scenes/{id}."""

    id: int
    duration: float
    status: str
    location_hint: str
    updated_at: datetime


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("/{scene_id}", response_model=SceneDetail)
def get_scene(
    scene_id: int,
    session: Session = Depends(get_session),
) -> SceneDetail:
    """Get scene detail including associated assets.

    Args:
        scene_id: Integer primary key of the scene.

    Returns:
        Full scene detail with assets list.

    Raises:
        HTTPException 404: If the scene is not found.
    """
    logger.debug("[scenes] GET /api/scenes/%d", scene_id)
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "SCENE_NOT_FOUND",
                    "message": f"Scene {scene_id} not found.",
                }
            },
        )

    # Load associated assets via SceneAsset join
    asset_refs = _load_scene_assets(session, scene_id)

    return SceneDetail(
        id=scene.id,
        project_id=scene.project_id,
        order=scene.order,
        duration=scene.duration,
        status=scene.status,
        location_hint=scene.location_hint,
        created_at=scene.created_at,
        updated_at=scene.updated_at,
        assets=asset_refs,
    )


@router.patch("/{scene_id}", response_model=ScenePatchResponse)
def patch_scene(
    scene_id: int,
    body: ScenePatchRequest,
    session: Session = Depends(get_session),
) -> ScenePatchResponse:
    """Update scene fields.

    Only the fields provided in the request body are updated.
    Attempting to edit a scene that is currently generating raises 409.

    Args:
        scene_id: Integer primary key of the scene.
        body: Partial update payload.

    Returns:
        Updated scene fields.

    Raises:
        HTTPException 404: If the scene is not found.
        HTTPException 409: If the scene is currently generating.
        HTTPException 400: If duration is out of the valid range [3, 30].
    """
    logger.info("[scenes] PATCH /api/scenes/%d body=%s", scene_id, body.model_dump(exclude_none=True))
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "SCENE_NOT_FOUND",
                    "message": f"Scene {scene_id} not found.",
                }
            },
        )

    if scene.status == "generating":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "STATE_CONFLICT",
                    "message": "Cannot edit a scene that is currently generating.",
                }
            },
        )

    if body.duration is not None:
        if not (3.0 <= body.duration <= 30.0):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "INVALID_DURATION",
                        "message": f"duration must be between 3 and 30 seconds, got {body.duration}.",
                    }
                },
            )
        scene.duration = body.duration

    if body.status is not None:
        scene.status = body.status

    if body.location_hint is not None:
        scene.location_hint = body.location_hint

    scene.updated_at = datetime.now(timezone.utc)
    session.add(scene)
    session.commit()
    session.refresh(scene)

    logger.info("[scenes] updated scene id=%d status=%s duration=%.1f", scene.id, scene.status, scene.duration)
    return ScenePatchResponse(
        id=scene.id,
        duration=scene.duration,
        status=scene.status,
        location_hint=scene.location_hint,
        updated_at=scene.updated_at,
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _load_scene_assets(session: Session, scene_id: int) -> list[AssetRef]:
    """Load assets associated with a scene via the SceneAsset join table.

    Args:
        session: Active SQLModel session.
        scene_id: Scene primary key.

    Returns:
        List of AssetRef objects.
    """
    scene_assets = session.exec(
        select(SceneAsset).where(SceneAsset.scene_id == scene_id)
    ).all()

    result: list[AssetRef] = []
    for sa in scene_assets:
        asset = session.get(Asset, sa.asset_id)
        if asset is not None:
            result.append(
                AssetRef(
                    id=asset.id,
                    name=asset.name,
                    type=asset.type,
                    ref_url=asset.ref_url,
                    role=getattr(sa, "role", None),
                )
            )
    return result
