"""Production inputs and reviewed outputs for both personal content workflows."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class ProductionMedia(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    scene_id: int | None = Field(default=None, index=True)
    role: str  # reference | portrait | visual
    path: str
    sha256: str
    mime: str
    width: int
    height: int
    duration: float = 0
    approved: bool = False
    review_json: str = "{}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProductionOutput(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    job_id: int = Field(index=True, unique=True)
    kind: str
    status: str = "awaiting_review"
    manifest_json: str
    folder: str
    review_json: str = "{}"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
