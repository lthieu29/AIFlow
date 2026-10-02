"""Non-destructive backup for existing installations before the audio schema is added."""

import sqlite3
from datetime import datetime, timezone


def backup_before_audio_upgrade(settings) -> None:
    path = settings.data_dir / "projects.db"
    if not path.is_file():
        return
    with sqlite3.connect(str(path)) as source:
        columns = {row[1] for row in source.execute("PRAGMA table_info(project)")}
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if ({"voice_id", "language", "kind", "production_brief"}.issubset(columns)
                and {"storyseries", "seriesepisode", "studiolibrary", "studiooperation"}.issubset(tables)):
            return
        folder = settings.data_dir / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        with sqlite3.connect(str(folder / f"before-remote-audio-{timestamp}.db")) as backup:
            source.backup(backup)
