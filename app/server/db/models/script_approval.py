"""Auditable human review, separate from immutable generated content."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class ScriptApproval(SQLModel, table=True):
    revision_id: int = Field(primary_key=True)
    content_hash: str
    quality_version: str
    checklist_json: str
    warnings_json: str
    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
