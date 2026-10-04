"""Regression coverage for the legacy workspace's persisted UI operations."""

import json
import subprocess
from pathlib import Path

import pytest
from sqlmodel import Session

from server.tests import test_phase_b_routes
from server.config import load_settings
from server.db.models.project import Project
from server.db.models.scene import Scene
from server.db.session import get_engine

client = test_phase_b_routes.client


def make_project(client):
    result = client.post("/api/projects", json={"title": "Workspace audit", "adapter_name": "script_direct",
        "skill_id": "ecommerce-fashion", "adapter_input": {"raw_content": json.dumps({"scenes": [
            {"visual_prompt": "A tree", "narration": "Hello", "duration_sec": 4},
            {"visual_prompt": "A river", "narration": "World", "duration_sec": 4},
        ]})}})
    assert result.status_code == 201, result.text
    return client.get(f"/api/projects/{result.json()['short_id']}").json()


def edits(project):
    return [{key: scene[key] for key in ("id", "duration", "prompt", "narration", "location_hint")}
            for scene in project["scenes"]]


def test_scene_add_remove_reorder_survives_reload(client):
    project = make_project(client)
    original = edits(project)
    draft = [original[1], {"prompt": "New scene", "duration": 5}, original[0]]
    response = client.put(f"/api/projects/{project['short_id']}/scenes", json={"scenes": draft})
    assert response.status_code == 200, response.text
    rows = response.json()["scenes"]
    assert [row["prompt"] for row in rows] == [original[1]["prompt"], "New scene", original[0]["prompt"]]
    assert rows[0]["id"] == original[1]["id"]
    assert [row["order"] for row in rows] == [0, 1, 2]
    draft = edits(response.json())[:2]
    assert client.put(f"/api/projects/{project['id']}/scenes", json={"scenes": draft}).status_code == 200
    reloaded = client.get(f"/api/projects/{project['short_id']}").json()
    assert [row["id"] for row in reloaded["scenes"]] == [row["id"] for row in rows[:2]]


@pytest.mark.parametrize("invalid", ["duplicate", "foreign", "duration", "empty"])
def test_invalid_scene_list_does_not_partially_save(client, invalid):
    project = make_project(client)
    draft = edits(project)
    draft[0]["prompt"] = "Should not persist"
    if invalid == "duplicate":
        draft[1]["id"] = draft[0]["id"]
    elif invalid == "foreign":
        draft[1]["id"] = make_project(client)["scenes"][0]["id"]
    elif invalid == "duration":
        draft[1]["duration"] = -1
    else:
        draft = []
    assert client.put(f"/api/projects/{project['id']}/scenes", json={"scenes": draft}).status_code == 422
    assert client.get(f"/api/projects/{project['id']}").json()["scenes"] == project["scenes"]


def test_active_generation_cannot_be_edited(client):
    project = make_project(client)
    with Session(get_engine(load_settings())) as session:
        row = session.get(Project, project["id"])
        row.status = "generating"
        session.add(row)
        session.commit()
    assert client.put(f"/api/projects/{project['id']}/scenes", json={"scenes": edits(project)}).status_code == 409


@pytest.mark.parametrize("status", ["queued", "running", "waiting_resource", "retrying", "cancel_requested"])
def test_audio_must_finish_or_acknowledge_cancellation_before_scene_edit(client, status):
    from server.db.models.audio_task import AudioTask
    project = make_project(client)
    with Session(get_engine(load_settings())) as session:
        task = AudioTask(project_id=project["id"], title="QA", snapshot_json="{}", status=status)
        session.add(task)
        session.commit()
        task_id = task.id
    draft = edits(project)
    draft[0]["narration"] = "New narration"
    endpoint = f"/api/projects/{project['id']}/scenes"
    assert client.put(endpoint, json={"scenes": draft}).status_code == 409
    assert client.get(f"/api/projects/{project['id']}").json()["scenes"] == project["scenes"]
    with Session(get_engine(load_settings())) as session:
        task = session.get(AudioTask, task_id)
        task.status = "cancelled"
        session.add(task)
        session.commit()
    assert client.put(endpoint, json={"scenes": draft}).status_code == 200


def test_unchanged_save_preserves_done_but_edit_invalidates_outputs(client):
    project = make_project(client)
    with Session(get_engine(load_settings())) as session:
        row = session.get(Project, project["id"])
        row.status = "done"
        scene = session.get(Scene, project["scenes"][0]["id"])
        scene.audio_path = "old.wav"
        scene.video_path = "old.mp4"
        session.add(row)
        session.add(scene)
        session.commit()
    endpoint = f"/api/projects/{project['id']}/scenes"
    assert client.put(endpoint, json={"scenes": edits(project)}).json()["status"] == "done"
    draft = edits(project)
    draft[0]["narration"] = "Changed narration"
    assert client.put(endpoint, json={"scenes": draft}).json()["status"] == "ready"
    with Session(get_engine(load_settings())) as session:
        scene = session.get(Scene, draft[0]["id"])
        assert scene.audio_path is None
        assert scene.video_path is None


def test_subtitles_accept_short_id_and_provide_browser_vtt(client):
    project = make_project(client)
    endpoint = f"/api/projects/{project['short_id']}/export/srt"
    srt = client.get(endpoint)
    assert srt.status_code == 200, srt.text
    assert "Hello" in srt.text
    vtt = client.get(endpoint + "?format=vtt")
    assert vtt.status_code == 200
    assert vtt.headers["content-type"].startswith("text/vtt")
    assert vtt.text.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:04.000" in vtt.text
    output = Path(load_settings().data_dir) / "output" / str(project["id"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nMeasured subtitle\n", encoding="utf-8")
    assert "Measured subtitle" in client.get(endpoint).text


def test_capcut_accepts_ui_short_id(client, monkeypatch, tmp_path):
    project = make_project(client)
    from server.export.capcut_exporter import CapCutExporter
    captured = {}
    def fake_export(self, **kwargs):
        captured["id"] = kwargs["project"].id
        return str(tmp_path / "draft")
    monkeypatch.setattr(CapCutExporter, "export", fake_export)
    response = client.post(f"/api/projects/{project['short_id']}/export/capcut", json={})
    assert response.status_code == 200, response.text
    assert captured["id"] == project["id"]
    assert response.json()["draft_path"].endswith("draft")


@pytest.mark.parametrize("project_id", ["999999", "p_missing"])
def test_missing_export_project_returns_404_with_real_database(client, project_id):
    assert client.get(f"/api/projects/{project_id}/export/srt").status_code == 404
    assert client.post(f"/api/projects/{project_id}/export/capcut", json={}).status_code == 404


def test_cannot_delete_scene_with_flow_operation_history(client):
    from server.db.models.studio import StudioOperation
    project = make_project(client)
    with Session(get_engine(load_settings())) as session:
        session.add(StudioOperation(request_id="qa-operation", project_id=project["id"], kind="flow_video",
                                    input_json=json.dumps({"scene_id": project["scenes"][1]["id"]})))
        session.commit()
    response = client.put(f"/api/projects/{project['id']}/scenes", json={"scenes": edits(project)[:1]})
    assert response.status_code == 409
    assert len(client.get(f"/api/projects/{project['id']}").json()["scenes"]) == 2


@pytest.mark.parametrize(("aspect", "expected"), [("16:9", (1280, 720)), ("1:1", (720, 720))])
def test_dry_run_uses_project_aspect(client, aspect, expected):
    from server.audio.ffmpeg_utils import find_ffmpeg, find_ffprobe
    if not find_ffmpeg() or not find_ffprobe():
        pytest.skip("FFmpeg unavailable")
    project = make_project(client)
    with Session(get_engine(load_settings())) as session:
        row = session.get(Project, project["id"])
        row.aspect = aspect
        session.add(row)
        session.commit()
    response = client.post(f"/api/projects/{project['id']}/generate", json={"dry_run": True})
    assert response.status_code == 202
    source = Path(load_settings().data_dir) / "output" / str(project["id"]) / "final.mp4"
    metadata = json.loads(subprocess.run([find_ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(source)],
                                        capture_output=True, text=True, check=True).stdout)
    video = metadata["streams"][0]
    assert (video["width"], video["height"]) == expected


def test_download_really_converts_format_and_resolution(client):
    from server.audio.ffmpeg_utils import find_ffmpeg, find_ffprobe
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not find_ffprobe():
        pytest.skip("FFmpeg unavailable")
    project = make_project(client)
    output = Path(load_settings().data_dir) / "output" / str(project["id"])
    output.mkdir(parents=True)
    original = output / "final.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x90:d=0.25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(original)], check=True)
    original_bytes = original.read_bytes()
    response = client.get(f"/api/projects/{project['short_id']}/output?download=1&quality=480p&format=webm")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "video/webm"
    assert ".webm" in response.headers["content-disposition"]
    assert response.content[:4] == bytes.fromhex("1a45dfa3")
    variant = next(output.glob("export-*.webm"))
    metadata = json.loads(subprocess.run([find_ffprobe(), "-v", "error", "-show_streams", "-of", "json", str(variant)],
                                       capture_output=True, text=True, check=True).stdout)
    assert metadata["streams"][0]["height"] == 480
    assert metadata["streams"][0]["codec_name"] == "vp9"
    assert original.read_bytes() == original_bytes
    assert client.get(f"/api/projects/{project['id']}/output?format=exe").status_code == 422
