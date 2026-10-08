"""Asset management routes — upload, list, delete reference images.

Endpoints:
    POST   /api/assets/upload       — Upload a reference image (character/location/product)
    GET    /api/assets/{project_id} — List all assets for a project
    DELETE /api/assets/{asset_id}   — Delete an asset
    GET    /api/assets/file/{asset_id} — Serve the uploaded image file
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from server.api.routes.audio import local_client
from server.config import Settings, load_settings
from server.db.models.asset import Asset
from server.db.models.project import Project
from server.db.models.scene_asset import SceneAsset
from server.db.session import get_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"], dependencies=[Depends(local_client)])

# Allowed image extensions
_ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _asset_path(settings: Settings, value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(settings.data_dir.resolve()):
        raise HTTPException(status_code=409, detail="Asset file is outside managed storage")
    return path


# ─── Dependencies ────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    return load_settings()


def get_session(settings: Settings = Depends(get_settings)):
    engine = get_engine(settings)
    with Session(engine) as session:
        yield session


# ─── Response models ─────────────────────────────────────────────────────────


class AssetResponse(BaseModel):
    id: int
    project_id: int
    name: str
    type: str
    file_path: str | None
    ref_url: str | None
    source: str
    created_at: str


class AssetListResponse(BaseModel):
    assets: list[AssetResponse]
    count: int


# ─── POST /api/assets/upload ─────────────────────────────────────────────────


@router.post("/upload", response_model=AssetResponse)
async def upload_asset(
    file: UploadFile = File(...),
    project_id: int = Form(...),
    name: str = Form(...),
    asset_type: str = Form(..., alias="type"),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AssetResponse:
    """Upload a reference image (character, location, product, style).

    The image is saved to storage/media/{project_id}/assets/ and an Asset
    record is created in the database.

    Form fields:
        file:       Image file (jpg, png, webp, bmp). Max 10 MB.
        project_id: ID of the project this asset belongs to.
        name:       Human-readable name (e.g. "Nhân vật chính", "Quán cafe").
        type:       One of: character, product, location, style.
    """
    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate asset type
    valid_types = {"character", "product", "location", "style"}
    if asset_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"type must be one of {sorted(valid_types)}, got {asset_type!r}",
        )

    # Validate file extension
    if not file.filename:
        raise HTTPException(status_code=422, detail="File must have a filename")
    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"File extension {ext!r} not allowed. Use: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    # Read file bytes and check size
    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content):,} bytes). Max: {_MAX_FILE_SIZE:,} bytes.",
        )

    # Save to storage/media/{project_id}/assets/
    assets_dir = settings.data_dir / "media" / str(project_id) / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename to avoid collisions
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = assets_dir / unique_name
    file_path.write_bytes(content)

    logger.info(
        f"Asset uploaded: project={project_id} name={name!r} type={asset_type} "
        f"file={file_path} size={len(content):,} bytes"
    )

    # Create DB record
    asset = Asset(
        project_id=project_id,
        name=name,
        type=asset_type,
        file_path=str(file_path),
        source="uploaded",
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    return AssetResponse(
        id=asset.id,  # type: ignore[arg-type]
        project_id=asset.project_id,
        name=asset.name,
        type=asset.type,
        file_path=asset.file_path,
        ref_url=asset.ref_url,
        source=asset.source,
        created_at=asset.created_at.isoformat(),
    )


# ─── GET /api/assets/{project_id} ───────────────────────────────────────────


@router.get("/{project_id}", response_model=AssetListResponse)
async def list_assets(
    project_id: int,
    session: Session = Depends(get_session),
) -> AssetListResponse:
    """List all assets for a given project."""
    assets = session.exec(select(Asset).where(Asset.project_id == project_id)).all()

    items = [
        AssetResponse(
            id=a.id,  # type: ignore[arg-type]
            project_id=a.project_id,
            name=a.name,
            type=a.type,
            file_path=a.file_path,
            ref_url=a.ref_url,
            source=a.source,
            created_at=a.created_at.isoformat(),
        )
        for a in assets
    ]
    return AssetListResponse(assets=items, count=len(items))


# ─── DELETE /api/assets/{asset_id} ───────────────────────────────────────────


@router.delete("/item/{asset_id}")
async def delete_asset(
    asset_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Delete an asset by ID. Removes the file from disk and the DB record."""
    asset = session.exec(select(Asset).where(Asset.id == asset_id)).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    # Remove file from disk
    if asset.file_path:
        fp = _asset_path(settings, asset.file_path)
        if fp.exists():
            fp.unlink()
            logger.info(f"Asset file deleted: {fp}")

    for link in session.exec(select(SceneAsset).where(SceneAsset.asset_id == asset.id)).all():
        session.delete(link)
    session.flush()
    session.delete(asset)
    session.commit()

    return {"deleted": True, "id": asset_id}


# ─── GET /api/assets/file/{asset_id} ────────────────────────────────────────


@router.get("/file/{asset_id}")
async def serve_asset_file(
    asset_id: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve the uploaded asset image file."""
    asset = session.exec(select(Asset).where(Asset.id == asset_id)).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    if not asset.file_path:
        raise HTTPException(status_code=404, detail="Asset has no file")

    fp = _asset_path(settings, asset.file_path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="Asset file missing from disk")

    return FileResponse(fp)
