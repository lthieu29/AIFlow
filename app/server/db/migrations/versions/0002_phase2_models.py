"""Phase 2 models — scene, asset, scene_asset, style, quality_gate tables.

Adds the five tables required by the continuity engine (Phase 2):
    - scene        : one Veo3 clip per row, with location_hint Literal enum
    - asset        : reusable character/product/location reference images
    - scene_asset  : many-to-many junction between scene and asset
    - style        : Layer 1 style lock (one row per project)
    - quality_gate : G1-G6 gate evaluation records

Revision ID: 0002
Revises:     0001
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create Phase 2 tables: scene, asset, scene_asset, style, quality_gate."""

    # ── scene ─────────────────────────────────────────────────────────────────
    # location_hint is stored as VARCHAR; constrained to the LocationHint Literal
    # values ("indoor" | "outdoor" | "transition" | "unspecified") at the
    # application layer (REVIEW-02 #6).
    op.create_table(
        "scene",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False, server_default="8.0"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("location_hint", sa.String(), nullable=False, server_default="unspecified"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scene_project_id", "scene", ["project_id"], unique=False)
    op.create_index("ix_scene_status", "scene", ["status"], unique=False)

    # ── asset ─────────────────────────────────────────────────────────────────
    op.create_table(
        "asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("ref_url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="generated"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_project_id", "asset", ["project_id"], unique=False)

    # ── scene_asset ───────────────────────────────────────────────────────────
    op.create_table(
        "scene_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="character"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["scene.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scene_asset_scene_id", "scene_asset", ["scene_id"], unique=False)
    op.create_index("ix_scene_asset_asset_id", "scene_asset", ["asset_id"], unique=False)

    # ── style ─────────────────────────────────────────────────────────────────
    # project_id is UNIQUE — one style per project (Layer 1 continuity invariant).
    op.create_table(
        "style",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("style_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id"),
    )
    op.create_index("ix_style_project_id", "style", ["project_id"], unique=True)

    # ── quality_gate ──────────────────────────────────────────────────────────
    # scene_id is nullable — project-level gates have no specific scene.
    op.create_table(
        "quality_gate",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gate_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("expired_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["scene.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_gate_project_id", "quality_gate", ["project_id"], unique=False)
    op.create_index("ix_quality_gate_status", "quality_gate", ["status"], unique=False)


def downgrade() -> None:
    """Drop Phase 2 tables in reverse dependency order."""
    # quality_gate references scene and project — drop first
    op.drop_index("ix_quality_gate_status", table_name="quality_gate")
    op.drop_index("ix_quality_gate_project_id", table_name="quality_gate")
    op.drop_table("quality_gate")

    # style references project
    op.drop_index("ix_style_project_id", table_name="style")
    op.drop_table("style")

    # scene_asset references scene and asset — drop before both
    op.drop_index("ix_scene_asset_asset_id", table_name="scene_asset")
    op.drop_index("ix_scene_asset_scene_id", table_name="scene_asset")
    op.drop_table("scene_asset")

    # asset references project
    op.drop_index("ix_asset_project_id", table_name="asset")
    op.drop_table("asset")

    # scene references project — drop last among Phase 2 tables
    op.drop_index("ix_scene_status", table_name="scene")
    op.drop_index("ix_scene_project_id", table_name="scene")
    op.drop_table("scene")
