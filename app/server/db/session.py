"""Database session management — engine factory, schema bootstrap, and migrations.

Usage:
    from server.db.session import get_engine, bootstrap_schema, run_migrations
    from server.config import load_settings

    settings = load_settings()

    # Phase 0-1 (tests / first boot):
    bootstrap_schema(settings)

    # Phase 1+ (production startup):
    run_migrations(settings)

    engine = get_engine(settings)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import SQLModel, create_engine

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from server.config import Settings

_engine: "Engine | None" = None


def get_engine(settings: "Settings") -> "Engine":
    """SQLite engine factory — singleton per process.

    Args:
        settings: Loaded Settings instance.

    Returns:
        SQLAlchemy Engine connected to storage/projects.db.
    """
    global _engine
    if _engine is None:
        db_path = settings.data_dir / "projects.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
            echo=settings.debug,
        )
    return _engine


def bootstrap_schema(settings: "Settings") -> None:
    """Idempotent schema creation for Phase 0 / tests.

    Creates all tables registered in SQLModel.metadata. Safe to call on
    every startup — create_all() is a no-op if tables already exist.

    After create_all, sets the ``schema_version`` key in the Config table.

    IMPORTANT: Import order matters. ``from server.db import models`` must
    happen before create_all() so that all SQLModel table classes are
    registered in SQLModel.metadata.tables.

    Args:
        settings: Loaded Settings instance.
    """
    # CRITICAL: import the models package (not individual files) so that
    # __init__.py re-exports trigger registration of ALL table classes.
    from server.db import models  # noqa: F401

    engine = get_engine(settings)
    SQLModel.metadata.create_all(engine)

    # Set schema_version in Config table
    from sqlmodel import Session, select

    with Session(engine) as session:
        existing = session.exec(
            select(models.Config).where(models.Config.key == "schema_version")
        ).first()
        if existing is None:
            session.add(models.Config(key="schema_version", value="0.1.0"))
            session.commit()


def run_migrations(settings: "Settings") -> None:
    """Run Alembic migrations programmatically to bring DB to latest revision.

    This is the Phase 1+ replacement for bootstrap_schema() in production
    startup. It runs ``alembic upgrade head`` against the DB path derived
    from *settings*.

    The function sets the ``AIFLOW_DB_URL`` environment variable so that
    Alembic's env.py picks up the correct SQLite path without needing a
    .env file to be present at the alembic.ini location.

    Args:
        settings: Loaded Settings instance.
    """
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config as AlembicConfig

    db_path = settings.data_dir / "projects.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Tell env.py which DB to use (overrides alembic.ini fallback)
    os.environ["AIFLOW_DB_URL"] = f"sqlite:///{db_path}"

    # Locate alembic.ini relative to this file: app/alembic.ini
    ini_path = Path(__file__).resolve().parent.parent.parent / "alembic.ini"

    alembic_cfg = AlembicConfig(str(ini_path))
    command.upgrade(alembic_cfg, "head")
