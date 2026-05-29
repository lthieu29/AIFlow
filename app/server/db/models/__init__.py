"""Models package — re-export all SQLModel classes.

CRITICAL: bootstrap_schema() depends on every class being imported when
`from server.db import models` is called. If you add a new model (Phase 2+),
you MUST add it to __all__ and the import statements below, otherwise
create_all() will skip that table.
"""

from server.db.models.asset import Asset
from server.db.models.config import Config
from server.db.models.job import Job, JobLog
from server.db.models.project import Project
from server.db.models.quality_gate import QualityGate
from server.db.models.scene import Scene
from server.db.models.scene_asset import SceneAsset
from server.db.models.style import Style

__all__ = [
    "Project",
    "Job",
    "JobLog",
    "Config",
    # Phase 2 models
    "Scene",
    "Asset",
    "SceneAsset",
    "Style",
    "QualityGate",
]

# Phase 4.5+ add:
# from server.db.models.cookie import Cookie
# __all__ += ["Cookie"]
