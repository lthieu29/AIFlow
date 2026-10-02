"""SceneAsset model — many-to-many junction between Scene and Asset.

Each row records which asset is used in which scene and in what role.
Two single-column indexes allow fast queries in both directions:
    - "which assets are in scene X?" → ix_scene_asset_scene_id
    - "which scenes use asset Y?"    → ix_scene_asset_asset_id

Per spec 02 (REVIEW-01 #6): composite PK + 2 single-column indexes.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class SceneAsset(SQLModel, table=True):
    """Many-to-many junction: Scene ↔ Asset.

    role values: "character" | "product" | "location" | "background"
    """

    __tablename__ = "scene_asset"  # type: ignore[assignment]

    __table_args__ = (
        Index("ix_scene_asset_scene_id", "scene_id"),
        Index("ix_scene_asset_asset_id", "asset_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    scene_id: int = Field(foreign_key="scene.id")
    asset_id: int = Field(foreign_key="asset.id")

    # Role of this asset in the scene
    role: str = Field(default="character")  # character | product | location | background
