"""Style model — Layer 1 continuity: one visual identity per project.

One project = one Style row. The style_json stores camera, lighting, and
color palette settings loaded from skills/{skill_id}/style.json and
optionally overridden per project.

The project_id column has a UNIQUE constraint (enforced via Field unique=True)
so that the 1-project-1-style invariant is maintained at the DB level.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Style(SQLModel, table=True):
    """Layer 1 style lock — one row per project.

    style_json stores the full style.json blob as a TEXT column (JSON string).
    The pipeline reads this and prepends the generated prefix_text to every
    Veo3 prompt.
    """

    id: Optional[int] = Field(default=None, primary_key=True)

    # UNIQUE: one style per project (enforced at DB level)
    project_id: int = Field(foreign_key="project.id", index=True, unique=True)

    # Full style.json blob serialised as a JSON string
    style_json: str  # JSON blob: camera, lighting, color palette, etc.

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
