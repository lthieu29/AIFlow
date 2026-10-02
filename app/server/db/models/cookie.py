"""Cookie model — Phase 4.5 platform session cookies.

Stores captured cookies for Bilibili, Douyin, and TikTok so the
video-remaster adapter can authenticate download requests.

Per design.md §Cookie:
    platform: Literal["bilibili", "douyin", "tiktok"]
    name, value, domain, expires_at, created_at

Task 5.3 — Phase 5.3
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

# Supported platforms
Platform = Literal["bilibili", "douyin", "tiktok"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Cookie(SQLModel, table=True):
    """Platform session cookie stored for authenticated downloads.

    One row per cookie name per platform.  The cookie manager upserts rows
    when new cookies are captured by the extension's cookie_sniffer module.

    platform values: "bilibili" | "douyin" | "tiktok"
    """

    __table_args__ = (
        Index("ix_cookie_platform", "platform"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    # Platform this cookie belongs to.
    # NOTE: the index is declared explicitly in __table_args__ above as
    # "ix_cookie_platform". Do NOT also pass index=True here — SQLModel would
    # auto-generate a second index with the same name, causing
    # "index ix_cookie_platform already exists" on create_all().
    platform: str  # bilibili | douyin | tiktok

    # Cookie fields (standard HTTP cookie attributes)
    name: str
    value: str
    domain: str = ""

    # Optional expiry — None means session cookie
    expires_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
