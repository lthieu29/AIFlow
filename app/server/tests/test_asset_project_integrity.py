"""Reference ownership and project deletion regressions on isolated storage."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from server.api.routes import assets, projects
from server.config import Settings
from server.db.models.asset import Asset
from server.db.models.job import Job, JobLog
from server.db.models.project import Project
from server.db.models.quality_gate import QualityGate
from server.db.models.scene import Scene
from server.db.models.scene_asset import SceneAsset
from server.db.models.style import Style
from server.db.models.script_revision import ScriptRevision


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'assets.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    settings = Settings(_env_file=None, data_dir=tmp_path / "storage")
    app = FastAPI()
    app.include_router(assets.router)
    app.include_router(projects.router)
    def sessions():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[assets.get_session] = sessions
    app.dependency_overrides[projects.get_session] = sessions
    app.dependency_overrides[assets.get_settings] = lambda: settings
    app.dependency_overrides[projects.get_settings] = lambda: settings
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        browser.engine = engine
        browser.root = settings.data_dir
        browser.settings = settings
        yield browser
    engine.dispose()


def project(client):
    with Session(client.engine) as db:
        row = Project(short_id="project-a", title="Original")
        db.add(row)
        db.commit()
        return row.id


def test_ecommerce_creation_retains_managed_product_reference(client, monkeypatch, tmp_path):
    from PIL import Image
    from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter
    from server.content.registry import REGISTRY
    from server.pipeline.orchestrator import _resolve_ref_image_paths

    source = tmp_path / "original.png"
    Image.new("RGB", (64, 64)).save(source)
    monkeypatch.setattr(REGISTRY, "_instances", {"ecommerce_product": EcommerceProductAdapter()})
    response = client.post("/api/projects", json={"name": "Product", "adapter": "ecommerce_product", "skill": "",
        "adapter_input": {"product_name": "Áo", "price": "100.000đ", "description": "Vải mềm", "product_image_path": str(source)}})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready" and response.json()["scene_count"] > 0
    with Session(client.engine) as db:
        reference = db.exec(select(Asset)).one()
        assert reference.type == "product"
        copied = Path(reference.file_path)
        assert copied.is_relative_to(client.root) and copied != source
        assert copied.read_bytes() == source.read_bytes()
        assert _resolve_ref_image_paths([reference]) == [copied]
        assert db.exec(select(SceneAsset)).all()
    assert source.is_file()


def test_multi_episode_creation_stays_draft_with_selection_guidance(client, monkeypatch):
    from server.content.adapters.epub_novel.tiers import EpisodeList
    from server.content.registry import REGISTRY

    class NovelAdapter:
        async def adapt(self, payload):
            return EpisodeList(project_title="Novel", episodes=[])

    monkeypatch.setattr(REGISTRY, "_instances", {"epub_novel": NovelAdapter()})
    response = client.post("/api/projects", json={"name": "Novel", "adapter": "epub_novel", "skill": "",
        "adapter_input": {"raw_content": "book.epub"}})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft" and response.json()["scene_count"] == 0
    assert "chapter_start" in response.json()["parse_error"]
    with Session(client.engine) as db:
        assert db.exec(select(Scene)).all() == []


@pytest.mark.parametrize("foreign_keys", [False, True])
def test_delete_project_removes_dependents_without_rebinding_or_deleting_files(client, foreign_keys):
    pid = project(client)
    reference = client.root / "reference.png"
    reference.write_bytes(b"user reference")
    with Session(client.engine) as db:
        db.execute(text(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}"))
        scene = Scene(project_id=pid, order=0)
        asset = Asset(project_id=pid, name="Character", type="character", file_path=str(reference))
        job = Job(project_id=pid, type="gen_video", status="failed")
        db.add_all([scene, asset, job])
        db.flush()
        db.add_all([SceneAsset(scene_id=scene.id, asset_id=asset.id),
                    QualityGate(project_id=pid, scene_id=scene.id, gate_id="G3"),
                    QualityGate(project_id=pid, gate_id="G2"),
                    Style(project_id=pid, style_json="{}"), JobLog(job_id=job.id, message="Original job")])
        db.commit()
        assert projects.delete_project(str(pid), db, client.settings).deleted
        for model in (Scene, Asset, Job, JobLog, SceneAsset, QualityGate, Style):
            assert db.exec(select(model)).all() == []
        replacement = Project(short_id="project-b", title="Replacement")
        db.add(replacement)
        db.commit()
        assert replacement.id == pid
    assert reference.read_bytes() == b"user reference"


def upload(client, pid, filename="portrait.png"):
    return client.post("/api/assets/upload", data={"project_id": pid, "name": "Character", "type": "character"},
                       files={"file": (filename, b"reference", "image/png")})


def test_upload_requires_existing_project(client):
    assert upload(client, 999).status_code == 404
    assert list(client.root.rglob("*.png")) == []


def test_delete_project_preserves_script_history(client):
    pid = project(client)
    with Session(client.engine) as db:
        db.add(ScriptRevision(request_id="history", title="Script", stage="manual", project_id=pid,
                              project_short_id="project-a"))
        db.commit()
    assert client.delete(f"/api/projects/{pid}").status_code == 409
    with Session(client.engine) as db:
        assert db.get(Project, pid) is not None


@pytest.mark.parametrize("artifact", ["output", "video_path", "audio_path", "last_frame_path"])
def test_delete_project_preserves_generated_artifacts_and_prevents_id_reuse(client, artifact):
    pid = project(client)
    if artifact == "output":
        folder = client.root / "output" / str(pid)
        folder.mkdir(parents=True)
        (folder / "final.mp4").write_bytes(b"original video")
    else:
        with Session(client.engine) as db:
            db.add(Scene(project_id=pid, order=0, **{artifact: "generated-artifact"}))
            db.commit()
    assert client.delete(f"/api/projects/{pid}").status_code == 409
    with Session(client.engine) as db:
        assert db.get(Project, pid) is not None
        replacement = Project(short_id="project-b", title="Replacement")
        db.add(replacement)
        db.commit()
        assert replacement.id != pid
    if artifact == "output":
        assert (folder / "final.mp4").read_bytes() == b"original video"


def test_asset_mutation_requires_local_ui_header(client):
    pid = project(client)
    assert client.post("/api/assets/upload", headers={"X-AIFlow-Client": ""},
        data={"project_id": pid, "name": "Character", "type": "character"},
        files={"file": ("ref.png", b"reference", "image/png")}).status_code == 403


def test_delete_missing_managed_file_still_cleans_database(client):
    pid = project(client)
    uploaded = upload(client, pid).json()
    Path(uploaded["file_path"]).unlink()
    assert client.get(f"/api/assets/file/{uploaded['id']}").status_code == 404
    assert client.delete(f"/api/assets/item/{uploaded['id']}").status_code == 200


def test_upload_filename_cannot_escape_project_folder(client):
    pid = project(client)
    response = upload(client, pid, "../../../escaped.png")
    assert response.status_code == 200, response.text
    path = Path(response.json()["file_path"]).resolve()
    assert path.parent == (client.root / "media" / str(pid) / "assets").resolve()
    assert path.read_bytes() == b"reference"


def test_asset_delete_removes_scene_links(client):
    pid = project(client)
    uploaded = upload(client, pid).json()
    with Session(client.engine) as db:
        scene = Scene(project_id=pid, order=0)
        db.add(scene)
        db.flush()
        db.add(SceneAsset(scene_id=scene.id, asset_id=uploaded["id"]))
        db.commit()
    response = client.delete(f"/api/assets/item/{uploaded['id']}")
    assert response.status_code == 200, response.text
    with Session(client.engine) as db:
        assert db.exec(select(SceneAsset)).all() == []
    assert not Path(uploaded["file_path"]).exists()


def test_asset_routes_refuse_paths_outside_storage(client, tmp_path):
    pid = project(client)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private")
    with Session(client.engine) as db:
        asset = Asset(project_id=pid, name="Legacy external", type="character", file_path=str(outside))
        db.add(asset)
        db.commit()
        aid = asset.id
    assert client.get(f"/api/assets/file/{aid}").status_code == 409
    assert client.delete(f"/api/assets/item/{aid}").status_code == 409
    assert outside.read_bytes() == b"private"
