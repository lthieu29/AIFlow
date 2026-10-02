"""Remote audio queue and persisted project voice/language (additive only)."""

from alembic import op
from sqlalchemy import inspect, text

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from server.db.models.audio_task import AudioTask

    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("project")}
    if "voice_id" not in columns:
        bind.execute(text("ALTER TABLE project ADD COLUMN voice_id VARCHAR DEFAULT 'af_heart' NOT NULL"))
    if "language" not in columns:
        bind.execute(text("ALTER TABLE project ADD COLUMN language VARCHAR DEFAULT 'en' NOT NULL"))
    AudioTask.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade database backup; automatic downgrade would discard audio jobs.")
