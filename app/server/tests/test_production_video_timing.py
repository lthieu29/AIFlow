"""Production must not silently turn sparse video timestamps into frozen padding."""

import pytest
from sqlmodel import Session

from server.db.models.project import Project
from server.db.models.scene import Scene
from server.production.media import ffmpeg
from server.tests.test_production import client as client


@pytest.mark.parametrize("gap", [False, True])
def test_render_rejects_timestamp_gap_but_accepts_normal_b_frames(client, gap):
    path = client.root / "source.mp4"
    args = ["-f", "lavfi", "-i", "testsrc2=size=64x64:rate=24:duration=2"]
    if gap:
        args += ["-vf", "setpts=PTS+gte(N\\,24)/TB", "-fps_mode", "passthrough"]
    ffmpeg(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    with Session(client.engine) as db:
        project = Project(title="Timing fixture", short_id="timing", kind="video")
        db.add(project)
        db.flush()
        scene = Scene(project_id=project.id, order=0, prompt="A moving pattern", duration=2)
        db.add(scene)
        db.commit()
        project_id, scene_id = project.id, scene.id
    response = client.post(f"/api/production/projects/{project_id}/media", data={
        "role": "visual", "scene_id": str(scene_id),
    }, files={"file": ("source.mp4", path.read_bytes(), "video/mp4")})
    assert response.status_code == 201, response.text
    media = response.json()["id"]
    client.post(f"/api/production/media/{media}/review", json={
        "checklist": ["content", "continuity", "framing"],
    })
    response = client.post(f"/api/production/projects/{project_id}/render", json={})
    if gap:
        assert response.status_code == 409, response.text
        assert "timestamp" in response.json()["detail"]
        with Session(client.engine) as db:
            assert db.get(Project, project_id).status != "generating"
    else:
        assert response.status_code == 202, response.text
        output = client.get(f"/api/production/outputs/{response.json()['output_id']}").json()
        assert output["status"] == "awaiting_review", output
