"""Single-scene edits respect active work and invalidate generated content."""

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from server.api.routes.scenes import ScenePatchRequest, patch_scene
from server.db.models import AudioTask, ProductionMedia, Project, Scene


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scenes.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(title="Scene fixture", short_id="scene-edit", status="ready")
        session.add(project)
        session.flush()
        scene = Scene(project_id=project.id, order=0, status="approved", prompt="Clock",
                      narration="Before", video_path="old.mp4", last_frame_path="old.png", audio_path="old.wav")
        session.add(scene)
        session.flush()
        media = ProductionMedia(project_id=project.id, scene_id=scene.id, role="visual", path="old.mp4",
                                sha256="fixture", mime="video/mp4", width=64, height=64, approved=True)
        session.add(media)
        session.commit()
        yield session, project, scene, media
    engine.dispose()


@pytest.mark.parametrize("state", ["project", "queued", "generating", "other_scene"])
def test_scene_edit_rejected_while_project_video_work_active(database, state):
    session, project, scene, _ = database
    if state == "project":
        project.status = "generating"
        session.add(project)
    elif state == "other_scene":
        session.add(Scene(project_id=project.id, order=1, status="queued"))
    else:
        scene.status = state
        session.add(scene)
    session.commit()
    with pytest.raises(HTTPException) as error:
        patch_scene(scene.id, ScenePatchRequest(prompt="Changed"), session)
    assert error.value.status_code == 409
    assert scene.prompt == "Clock"


@pytest.mark.parametrize("status", ["queued", "running", "waiting_resource", "retrying", "cancel_requested"])
def test_scene_edit_rejected_while_audio_active(database, status):
    session, project, scene, _ = database
    session.add(AudioTask(project_id=project.id, title="Fixture", snapshot_json="{}", status=status))
    session.commit()
    with pytest.raises(HTTPException) as error:
        patch_scene(scene.id, ScenePatchRequest(narration="Changed"), session)
    assert error.value.status_code == 409
    assert scene.audio_path == "old.wav"


@pytest.mark.parametrize("change", [{"prompt": "Changed"}, {"narration": "Changed"},
                                   {"duration": 10}, {"location_hint": "outdoor"}])
def test_content_edit_invalidates_generated_clip_and_review(database, change):
    session, _, scene, media = database
    patch_scene(scene.id, ScenePatchRequest(**change), session)
    assert scene.video_path is None
    assert scene.last_frame_path is None
    assert scene.status == "draft"
    assert not media.approved
    assert scene.audio_path == (None if "narration" in change else "old.wav")


def test_unchanged_content_preserves_generated_media(database):
    session, _, scene, media = database
    patch_scene(scene.id, ScenePatchRequest(prompt="Clock", narration="Before", duration=8), session)
    assert scene.video_path == "old.mp4"
    assert scene.last_frame_path == "old.png"
    assert scene.audio_path == "old.wav"
    assert media.approved


async def test_discovery_reports_configured_callback_port(monkeypatch):
    from server.api.routes.ext_discovery import ext_discovery
    from server.config import Settings

    monkeypatch.setattr("server.config.load_settings", lambda: Settings(port=8123, ws_port=9234))
    result = await ext_discovery(None)
    assert result["callback_url"] == "http://127.0.0.1:8123/api/ext/callback"
    assert result["ws_url"] == "ws://127.0.0.1:9234"
