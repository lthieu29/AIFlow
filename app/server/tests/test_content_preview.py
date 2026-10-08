"""Preview accepts the same form input as project creation, without providers."""

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routes.content import router
from server.content.adapters.storyboard_manual.adapter import StoryboardManualAdapter
from server.content.base import SceneList, SceneSpec
from server.content.registry import REGISTRY


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(REGISTRY, "_instances", {"storyboard_manual": StoryboardManualAdapter()})
    app = FastAPI()
    app.include_router(router)
    with TestClient(app, headers={"X-AIFlow-Client": "1"}) as browser:
        yield browser


def test_storyboard_form_placeholder_previews_successfully(client):
    page = Path(__file__).resolve().parents[2] / "ui/src/pages/NewProject.tsx"
    placeholder = re.search(r"inputPlaceholder: '([^']+)'", page.read_text(encoding="utf-8"))
    assert placeholder is not None
    storyboard = json.loads(placeholder.group(1))
    response = client.post("/api/content/parse", json={"adapter": "storyboard_manual", "input_data": storyboard})
    assert response.status_code == 200, response.text
    assert response.json()["scene_count"] == 1
    scene = response.json()["scenes"][0]
    assert scene["order"] == 0
    assert scene["duration"] == 8
    assert scene["prompt"] == storyboard["scenes"][0]["prompt"]


def test_invalid_storyboard_reports_missing_field_paths_without_echoing_input(client):
    response = client.post("/api/content/parse", json={"adapter": "storyboard_manual", "input_data": {
        "scenes": [{"narration": "private narration", "visual_prompt": "private prompt"}]}})
    assert response.status_code == 400
    errors = response.json()["detail"]["error"]["details"]["errors"]
    assert any("scenes → 0 → order" in error for error in errors)
    assert any("scenes → 0 → prompt" in error for error in errors)
    assert "private narration" not in response.text
    assert "private prompt" not in response.text


def test_explicit_raw_content_remains_supported_and_takes_precedence(client):
    storyboard = {"scenes": [{"order": 0, "prompt": "A boat on a stream", "duration": 8}]}
    response = client.post("/api/content/parse", json={"adapter": "storyboard_manual", "input_data": {
        "raw_content": json.dumps(storyboard), "scenes": [], "script": "ignored"}})
    assert response.status_code == 200, response.text
    assert response.json()["scene_count"] == 1


def test_duration_checks_use_normalized_schema_values(client):
    response = client.post("/api/content/parse", json={"adapter": "storyboard_manual", "input_data": {
        "scenes": [{"order": "0", "prompt": "A boat", "duration": "8", "narration": "The boat begins."}]}})
    assert response.status_code == 200, response.text
    assert response.json()["scenes"][0]["duration"] == 8


@pytest.mark.parametrize("scene,field", [
    ({"order": 0, "prompt": "A boat", "duration": 12}, "duration"),
    ({"order": 0, "prompt": "A boat", "duration": 4, "narration": " ".join(["word"] * 15)}, "narration"),
])
def test_preview_reports_authored_duration_problems_without_mutating_scenes(client, scene, field):
    response = client.post("/api/content/parse", json={"adapter": "storyboard_manual", "input_data": {"scenes": [scene]}})
    assert response.status_code == 400
    errors = response.json()["detail"]["error"]["details"]["errors"]
    assert any(f"scenes → 0 → {field}" in message for message in errors)


@pytest.mark.parametrize("key", ["script", "url", "text", "content"])
def test_preview_maps_common_form_fields_to_raw_content(client, monkeypatch, key):
    class LocalAdapter:
        def validate_input(self, payload):
            assert payload.raw_content == "form value"
            return []

        async def adapt(self, payload):
            return SceneList(project_id="preview", scenes=[SceneSpec(order=0, prompt=payload.raw_content, duration=8)])

    monkeypatch.setitem(REGISTRY._instances, "local", LocalAdapter())
    response = client.post("/api/content/parse", json={"adapter": "local", "input_data": {key: "form value"}})
    assert response.status_code == 200, response.text
    assert response.json()["scenes"][0]["prompt"] == "form value"


def test_preview_rejects_requests_without_local_client_header(client):
    client.headers.pop("X-AIFlow-Client")
    response = client.post("/api/content/parse", json={"adapter": "storyboard_manual", "input_data": {}})
    assert response.status_code == 403


def test_ecommerce_form_maps_product_image_to_scene_references(client, monkeypatch, tmp_path):
    from PIL import Image
    from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter

    image = tmp_path / "product.png"
    Image.new("RGB", (64, 64)).save(image)
    monkeypatch.setitem(REGISTRY._instances, "ecommerce_product", EcommerceProductAdapter())
    response = client.post("/api/content/parse", json={"adapter": "ecommerce_product", "input_data": {
        "product_name": "Áo", "price": "100.000đ", "description": "Vải mềm", "product_image_path": str(image)}})
    assert response.status_code == 200, response.text
    references = [scene["start_image"] for scene in response.json()["scenes"] if scene["start_image"]]
    assert references and set(references) == {str(image)}


def test_ecommerce_preview_rejects_non_image_product_file(client, monkeypatch, tmp_path):
    from server.content.adapters.ecommerce_product.adapter import EcommerceProductAdapter

    source = tmp_path / "product.png"
    source.write_bytes(b"not an image")
    monkeypatch.setitem(REGISTRY._instances, "ecommerce_product", EcommerceProductAdapter())
    response = client.post("/api/content/parse", json={"adapter": "ecommerce_product", "input_data": {
        "product_name": "Áo", "price": "100.000đ", "description": "Vải mềm", "product_image_path": str(source)}})
    assert response.status_code == 400
    assert "readable image" in response.text


def test_preview_reports_multi_episode_selection_as_actionable_input_error(client, monkeypatch):
    from server.content.adapters.epub_novel.tiers import EpisodeList

    class NovelAdapter:
        def validate_input(self, payload):
            return []

        async def adapt(self, payload):
            return EpisodeList(project_title="Novel", episodes=[SceneList(project_id="episode", scenes=[])])

    monkeypatch.setitem(REGISTRY._instances, "epub_novel", NovelAdapter())
    response = client.post("/api/content/parse", json={"adapter": "epub_novel", "input_data": {"raw_content": "book.epub"}})
    assert response.status_code == 400
    error = response.json()["detail"]["error"]
    assert error["code"] == "ADAPTER_EPISODE_SELECTION_REQUIRED"
    assert "chapter_start" in error["message"] and "chapter_end" in error["message"]
