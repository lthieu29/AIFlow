"""Add human editorial approval records; preserve all existing scripts."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from server.db.models.script_approval import ScriptApproval
    ScriptApproval.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("Restore a backup; automatic downgrade would discard editorial approvals.")
