"""Add series, shared library and production operation records."""
from alembic import op
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

def upgrade():
    from server.db.models.studio import StorySeries, SeriesEpisode, StudioLibrary, StudioOperation
    for model in (StorySeries, SeriesEpisode, StudioLibrary, StudioOperation):
        model.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError("Restore a compatible backup; studio history is not deleted automatically.")
