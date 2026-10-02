"""Additive studio tables; old projects and script revisions remain readable."""
from sqlmodel import SQLModel, Field

class StorySeries(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    version: int = 1
    bible: str = ""
    voice: str = ""
    language: str = "en"
    model_revision: str = ""
    speed: float = 1.0

class SeriesEpisode(SQLModel, table=True):
    root_revision_id: int = Field(primary_key=True)
    series_id: int = Field(index=True)
    snapshot_json: str

class StudioLibrary(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    kind: str
    description: str = ""
    media_id: int | None = None
    version: int = 1

class StudioOperation(SQLModel, table=True):
    request_id: str = Field(primary_key=True)
    project_id: int = Field(index=True)
    kind: str
    status: str = "running"
    input_json: str
    result_json: str = "{}"
    error: str = ""
