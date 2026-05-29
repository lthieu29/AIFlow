"""Asset model — character/product/location reference images.

Layer 2 continuity: one ref image generated once per asset, reused across
all scenes that reference that asset.

Indexes (per spec 02):
    ix_asset_project_id — list assets per project
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Asset(SQLModel, table=True):
    """Reusable reference asset (character, product, location, style).

    type values: "character" | "product" | "location" | "style"
    source values: "generated" | "uploaded" | "external"
    """

    __table_args__ = (
        Index("ix_asset_project_id", "project_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id")

    name: str  # e.g. "Hùng", "Áo trắng", "Quán cafe"
    type: str  # character | product | location | style
    ref_url: Optional[str] = Field(default=None)  # URL to reference image
    source: str = Field(default="generated")  # generated | uploaded | external

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
