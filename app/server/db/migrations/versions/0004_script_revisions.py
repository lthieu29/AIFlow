"""Add immutable script checkpoints without changing existing tables."""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from server.db.models.script_revision import ScriptRevision
    ScriptRevision.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("Restore a backup; automatic downgrade would discard script history.")
