"""Durable audio requests with immutable inputs and per-segment cache keys."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class AudioTask(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, index=True)
    generation_job_id: Optional[int] = Field(default=None, index=True)
    title: str
    voice: str = "af_heart"
    language: str = "en"
    speed: float = 1.0
    snapshot_json: str
    segments_json: str = "[]"
    status: str = Field(default="waiting_resource", index=True)
    completed_segments: int = 0
    output_path: Optional[str] = None
    duration_sec: float = 0.0
    error: str = ""
    active_key: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
