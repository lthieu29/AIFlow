"""Alembic migration environment.

Configured to:
- Use SQLModel.metadata (all registered table classes)
- Load DB URL from server.config.Settings (reads AIFLOW_DATA_DIR / projects.db)
- Fall back to alembic.ini sqlalchemy.url when Settings cannot be loaded
  (e.g. when running `alembic` CLI without a .env file)
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context

# ── Make sure the project root is on sys.path so `server.*` imports work ──────
_here = Path(__file__).resolve().parent          # server/db/migrations/
_project_root = _here.parent.parent.parent       # app/
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ── Alembic config object ──────────────────────────────────────────────────────
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import ALL models so SQLModel.metadata is fully populated ─────────────────
# CRITICAL: must import the models package (not individual files) so that
# __init__.py re-exports trigger registration of ALL table classes.
from server.db import models  # noqa: F401  # registers Project, Job, JobLog, Config

target_metadata = SQLModel.metadata


# ── Resolve DB URL ─────────────────────────────────────────────────────────────

def _get_db_url() -> str:
    """Return the SQLite URL, preferring Settings over alembic.ini."""
    # Allow override via env var (useful in CI / tests)
    env_url = os.environ.get("AIFLOW_DB_URL")
    if env_url:
        return env_url

    try:
        from server.config import load_settings
        settings = load_settings()
        db_path = settings.data_dir / "projects.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"
    except Exception:
        # Fall back to alembic.ini value (e.g. CLI without .env)
        return config.get_main_option("sqlalchemy.url")  # type: ignore[return-value]


# ── Migration runners ──────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection needed)."""
    url = _get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,   # Required for SQLite ALTER TABLE support
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (live DB connection)."""
    # Override the URL from Settings before creating the engine
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_db_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,   # Required for SQLite ALTER TABLE support
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
