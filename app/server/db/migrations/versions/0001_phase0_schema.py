"""Phase 0 schema — project, job, joblog, config tables.

This is a "stamp" migration that documents the initial state created by
bootstrap_schema() (SQLModel.metadata.create_all) during Phase 0.

Running ``alembic upgrade head`` on a fresh DB will create all four tables
with the correct columns and indexes. On an existing Phase 0 DB that was
bootstrapped via create_all(), use ``alembic stamp 0001`` to mark it as
already at this revision without re-running DDL.

Revision ID: 0001
Revises:     (none — initial migration)
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create Phase 0 tables: project, job, joblog, config."""

    # ── project ───────────────────────────────────────────────────────────────
    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("short_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("aspect", sa.String(), nullable=False, server_default="9:16"),
        sa.Column("skill", sa.String(), nullable=False, server_default=""),
        sa.Column("adapter", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("short_id"),
    )
    op.create_index("ix_project_short_id", "project", ["short_id"], unique=True)
    op.create_index("ix_project_status", "project", ["status"], unique=False)

    # ── job ───────────────────────────────────────────────────────────────────
    op.create_table(
        "job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_project_id", "job", ["project_id"], unique=False)
    op.create_index("ix_job_status", "job", ["status"], unique=False)

    # ── joblog ────────────────────────────────────────────────────────────────
    op.create_table(
        "joblog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(), nullable=False, server_default="INFO"),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_joblog_job_id", "joblog", ["job_id"], unique=False)

    # ── config ────────────────────────────────────────────────────────────────
    op.create_table(
        "config",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Drop all Phase 0 tables in reverse dependency order."""
    op.drop_table("config")
    op.drop_index("ix_joblog_job_id", table_name="joblog")
    op.drop_table("joblog")
    op.drop_index("ix_job_status", table_name="job")
    op.drop_index("ix_job_project_id", table_name="job")
    op.drop_table("job")
    op.drop_index("ix_project_status", table_name="project")
    op.drop_index("ix_project_short_id", table_name="project")
    op.drop_table("project")
