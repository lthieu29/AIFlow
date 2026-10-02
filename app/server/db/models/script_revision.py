"""Immutable script checkpoints; requests never overwrite a successful version."""

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class ScriptRevision(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("request_id"),)

    id: int | None = Field(default=None, primary_key=True)
    request_id: str
    parent_id: int | None = Field(default=None, index=True)
    title: str
    stage: str
    status: str = "succeeded"
    content_json: str = "{}"
    provider: str = "manual"
    model: str = ""
    usage_json: str = "null"
    error: str = ""
    approved: bool = False
    project_id: int | None = Field(default=None, index=True)
    project_short_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
