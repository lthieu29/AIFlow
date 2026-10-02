import json
from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import select
from server.db.models.studio import StorySeries, SeriesEpisode
from server.db.models.script_revision import ScriptRevision
from server.text.workflow import ancestry

def create_episode(session, body):
    series = session.get(StorySeries, body.series_id)
    if not series or body.series_version != series.version:
        raise HTTPException(409, "Series đã đổi hoặc không còn tồn tại. Tải lại rồi tạo tập.")
    existing = session.exec(select(ScriptRevision).where(ScriptRevision.request_id == str(body.request_id))).first()
    if existing:
        episode = session.get(SeriesEpisode, existing.id)
        expected = body.content.model_copy(update={"series_bible": series.bible, "language": series.language})
        if (not episode or episode.series_id != series.id
                or json.loads(existing.content_json) != expected.model_dump()):
            raise HTTPException(409, "Request ID đã được dùng.")
        return existing
    # Take the write lock and verify the version again before freezing the episode.
    locked = session.execute(update(StorySeries).where(StorySeries.id == series.id,
        StorySeries.version == body.series_version).values(version=body.series_version))
    if locked.rowcount != 1:
        raise HTTPException(409, "Series vừa được sửa. Tải lại.")
    session.refresh(series)
    content = body.content.model_copy(update={"series_bible": series.bible, "language": series.language})
    row = ScriptRevision(request_id=str(body.request_id), title=content.title, stage="brief", content_json=content.model_dump_json())
    session.add(row)
    session.flush()
    session.add(SeriesEpisode(root_revision_id=row.id, series_id=series.id, snapshot_json=series.model_dump_json()))
    session.commit()
    session.refresh(row)
    return row

def apply_episode(session, revision, project):
    root = ancestry(session, revision)[0]
    episode = session.get(SeriesEpisode, root.id)
    if episode:
        snapshot = json.loads(episode.snapshot_json)
        project.voice_id = snapshot["voice"] or project.voice_id
        project.language = snapshot["language"]
        project.production_brief = json.dumps({"channel": snapshot["name"], "series": snapshot}, ensure_ascii=False)
        session.add(project)
