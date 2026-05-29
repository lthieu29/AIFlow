"""Config model — runtime mutable key/value store."""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Config(SQLModel, table=True):
    """Runtime mutable config (not .env). E.g. Veo3 daily credits used.

    Important keys:
    - "veo3_credits_used_today" : "37"
    - "veo3_credits_reset_at"   : "2026-05-27T00:00:00Z"
    - "extension_callback_secret" : "abc..." (regenerated each restart)
    - "schema_version" : "0.1.0"
    """

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=_utcnow)
