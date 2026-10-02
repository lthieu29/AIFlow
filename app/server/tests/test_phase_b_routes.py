"""Integration tests for Phase B routes: secure demo audio + dry-run generate.

- GET /api/tts/voices rewrites demo paths to safe API URLs.
- GET /api/tts/voices/{id}/demo blocks path traversal (403) and serves files.
- POST /api/projects/{id}/generate?dry_run produces a placeholder video that
  /output then serves — without calling Veo3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIFLOW_GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))

    # Reset the cached engine so each test gets its own tmp DB.
    import server.db.session as sess_mod
    sess_mod._engine = None

    # Stub the WebSocket server so the test does not try to bind port 9223
    # (which may already be in use by a running dev server). The HTTP routes
    # under test do not need the WS server.
    import server.flow.ws_server as ws_mod

    async def _noop_ws_server(*args, **kwargs):
        return None

    monkeypatch.setattr(ws_mod, "start_ws_server", _noop_ws_server)

    from server.config import load_settings
    from server.db.session import bootstrap_schema

    bootstrap_schema(load_settings())

    from server.main import create_app

    with TestClient(create_app()) as c:
        yield c

    sess_mod._engine = None


# ─── Secure demo audio ────────────────────────────────────────────────────────


class TestVoiceDemoSecurity:
    def test_demo_route_blocks_traversal(self, client):
        # A traversal voice_id must be blocked (403) — never read outside gallery.
        resp = client.get("/api/tts/voices/..%2F..%2Fcookies/demo")
        assert resp.status_code in (403, 404)

    def test_demo_route_404_for_unknown_voice(self, client):
        resp = client.get("/api/tts/voices/Binh/demo")
        # Preset 'Binh' has no demo file on disk in this fresh tmp storage.
        assert resp.status_code == 404

    def test_voices_list_uses_safe_demo_urls(self, client, tmp_path):
        # Seed a custom voice with a demo file + catalog entry.
        gallery = tmp_path / "storage" / "voice_gallery" / "myvoice"
        gallery.mkdir(parents=True)
        (gallery / "demo.mp3").write_bytes(b"ID3fakeaudio")
        catalog = tmp_path / "storage" / "voice_gallery" / "catalog.json"
        catalog.write_text(json.dumps({"voices": [{
            "id": "myvoice", "name": "My Voice", "backend": "vieneu",
            "language": "vi-VN", "gender": "male", "description": "",
            "is_custom": True, "demo_audio_path": str(gallery / "demo.mp3"),
        }]}), encoding="utf-8")

        resp = client.get("/api/tts/voices")
        assert resp.status_code == 200
        entry = next(v for v in resp.json() if v["id"] == "myvoice")
        # The path must be rewritten to the safe API URL, never the FS path.
        assert entry["demo_audio_path"] == "/tts/voices/myvoice/demo"
        assert "storage" not in entry["demo_audio_path"]

        # And that safe URL actually serves the file.
        demo = client.get("/api/tts/voices/myvoice/demo")
        assert demo.status_code == 200
        assert demo.content == b"ID3fakeaudio"


# ─── Dry-run generate ─────────────────────────────────────────────────────────


def _make_project_with_scene(client) -> str:
    scenes = {"scenes": [
        {"narration": "Xin chao", "visual_prompt": "A blue sky", "duration_sec": 4},
    ]}
    body = {
        "title": "Dry Run Test",
        "adapter_name": "script_direct",
        "skill_id": "ecommerce-fashion",
        "aspect_ratio": "9:16",
        "adapter_input": {"raw_content": json.dumps(scenes)},
    }
    resp = client.post("/api/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["short_id"]


class TestDryRunGenerate:
    def test_generate_dry_run_accepts(self, client):
        short_id = _make_project_with_scene(client)
        resp = client.post(f"/api/projects/{short_id}/generate", json={"dry_run": True})
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "generating"
        assert isinstance(body["job_id"], int)

    def test_generate_requires_scenes(self, client):
        # Project with no adapter_input → no scenes → 422 on generate.
        resp = client.post("/api/projects", json={
            "title": "Empty", "adapter_name": "script_direct",
            "skill_id": "ecommerce-fashion", "aspect_ratio": "9:16",
        })
        short_id = resp.json()["short_id"]
        gen = client.post(f"/api/projects/{short_id}/generate", json={"dry_run": True})
        assert gen.status_code == 422

    def test_output_404_before_generation(self, client):
        short_id = _make_project_with_scene(client)
        resp = client.get(f"/api/projects/{short_id}/output")
        assert resp.status_code == 404
