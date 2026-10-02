"""Add product kinds and immutable production media/output records."""

from alembic import op
from sqlalchemy import inspect, text

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    from server.db.models.production import ProductionMedia, ProductionOutput
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("project")}
    for name, default in [("kind", "legacy"), ("production_brief", "{}")]:
        if name not in columns:
            bind.execute(text(f"ALTER TABLE project ADD COLUMN {name} VARCHAR DEFAULT '{default}' NOT NULL"))
    ProductionMedia.__table__.create(bind, checkfirst=True)
    ProductionOutput.__table__.create(bind, checkfirst=True)


def downgrade():
    raise RuntimeError("Restore a compatible backup; production records must not be dropped automatically.")
