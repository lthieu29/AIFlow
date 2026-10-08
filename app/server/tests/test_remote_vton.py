"""Offline VTON route, ordered input integrity and reviewed reuse contracts."""
import base64
import hashlib
import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import SecretStr
from sqlmodel import Session

from server.db.models.production import ProductionMedia
from server.db.models.project import Project
from server.db.models.studio import StudioOperation
from server.image import remote
from server.tests.test_remote_image import TOKEN, WORKER, URL, connect, portrait, refresh, submit, worker
from server.tests.test_studio_settings import client


def inputs(client, worker):
    project, person = portrait(client)
    stream = io.BytesIO()
    Image.new("RGB", (80, 96), "red").save(stream, "PNG")
    result = client.post(f"/api/production/projects/{project}/media", data={"role": "garment"},
        files={"file": ("shop.png", stream.getvalue(), "image/png")})
    assert result.status_code == 201, result.text
    connect(client)
    worker[0].health["capabilities"] = ["image", "virtual_try_on"]
    return project, {"generation_mode": "vton", "person_media_id": person, "garment_media_id": result.json()["id"],
                     "garment_category": "tops", "garment_photo_type": "flat-lay"}


def result(worker):
    stream = io.BytesIO()
    Image.new("RGB", (576, 864), "blue").save(stream, "PNG")
    raw = stream.getvalue()
    sent = worker[3]["payload"]
    return {"mime": "image/png", "data": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest(),
            "width": 576, "height": 864, "metadata": {"generation_mode": "vton", "reference_count": 2,
                "adapter_active": False, "input_roles": ["person", "garment"],
                "human_parser": "excluded", "segmentation_free": True, "text_conditioning": False,
                "output_resampling": "none-full-native-canvas", "width": 576, "height": 864,
                "native_width": 576, "native_height": 864, "model_revision": "a" * 40,
                "input_sha256": [ref["sha256"] for ref in sent["references"]],
                "garment_category": sent["garment_category"], "garment_photo_type": sent["garment_photo_type"]}}


def finish(client, worker, project, payload):
    worker[3].update(status="succeeded", result=result(worker))
    response = refresh(client, project, payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_vton_ordered_wire_native_dimensions_and_durable_receipt(client, worker):
    project, values = inputs(client, worker)
    payload, first = submit(client, project, **values)
    assert first.status_code == 200 and first.json()["status"] == "queued"
    sent = worker[3]["payload"]
    assert sent["prompt"] == "" and (sent["width"], sent["height"]) == (576, 864)
    assert sent["guidance_scale"] == 1.5
    assert [ref["role"] for ref in sent["references"]] == ["person", "garment"]
    checkpoint = json.loads(first.json()["input_json"])["_remote"]
    assert checkpoint["input_sha256"] == remote.digest(sent)
    with Session(client.engine) as db:
        for identity, ref in zip((values["person_media_id"], values["garment_media_id"]), sent["references"]):
            source = db.get(ProductionMedia, identity)
            assert hashlib.sha256(remote.reference_png(Path(source.path).read_bytes())).hexdigest() == ref["sha256"]
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).json()["status"] == "queued"
    assert client.post(f"/api/studio/projects/{project}/generate-image",
                       json={**payload, "garment_category": "bottoms"}).status_code == 409
    completed = finish(client, worker, project, payload)
    media = json.loads(completed["result_json"])
    assert completed["status"] == "succeeded" and not media["approved"]
    assert media["generation_mode"] == "vton" and media["person_media_id"] == values["person_media_id"]
    assert media["garment_media_id"] == values["garment_media_id"] and media["garment_category"] == "tops"
    assert media["width"] == 576 and media["height"] == 864
    assert refresh(client, project, payload).json() == completed
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


@pytest.mark.parametrize("changes", [{"provider": "gemini"}, {"subject_type": "pet"},
    {"person_media_id": None}, {"garment_category": None}, {"garment_category": "shoes"},
    {"garment_photo_type": "model"}, {"reference_media_ids": [1]}])
def test_vton_invalid_combinations_fail_before_worker(client, worker, changes):
    project, values = inputs(client, worker)
    assert submit(client, project, **{**values, **changes})[1].status_code == 422
    assert not any(call[0] == "POST" for call in worker[1])


@pytest.mark.parametrize("change", ["same_id", "cross_project", "roles_swapped", "archived", "outside_storage", "changed_bytes", "same_bytes"])
def test_vton_input_integrity_failures_never_submit(client, worker, change):
    project, values = inputs(client, worker)
    if change == "same_id":
        values["garment_media_id"] = values["person_media_id"]
    elif change == "cross_project":
        _, values["person_media_id"] = portrait(client)
    elif change == "roles_swapped":
        values["person_media_id"], values["garment_media_id"] = values["garment_media_id"], values["person_media_id"]
    else:
        with Session(client.engine) as db:
            garment = db.get(ProductionMedia, values["garment_media_id"])
            if change == "archived":
                garment.role = "archived"
            elif change == "outside_storage":
                garment.path = str(client.root.parent / "outside.png")
            elif change == "changed_bytes":
                Path(garment.path).write_bytes(b"changed")
            else:
                person = db.get(ProductionMedia, values["person_media_id"])
                Path(garment.path).write_bytes(Path(person.path).read_bytes())
                garment.sha256 = person.sha256
            db.add(garment); db.commit()
    assert submit(client, project, **values)[1].status_code == 422
    assert not any(call[0] == "POST" for call in worker[1])


def test_garment_never_auto_used_as_identity_or_sent_to_other_worker(client, worker):
    project, values = inputs(client, worker)
    assert submit(client, project)[1].status_code == 409
    worker[0].health["capabilities"] = ["image", "reference_image", "text_to_image"]
    assert submit(client, project, **values)[1].status_code == 409
    assert submit(client, project, reference_media_ids=[values["garment_media_id"]])[1].status_code == 422
    _, response = submit(client, project)
    assert response.status_code == 200 and len(worker[3]["payload"]["references"]) == 1
    assert "role" not in worker[3]["payload"]["references"][0]


@pytest.mark.parametrize("change", ["mode", "roles", "hashes", "category", "photo_type", "adapter", "count",
    "parser", "segmentation", "text", "resampling", "native", "revision"])
def test_vton_result_provenance_must_match_sent_inputs(client, worker, change):
    project, values = inputs(client, worker)
    payload, _ = submit(client, project, **values)
    bad = result(worker)
    changes = {"mode": ("generation_mode", "reference"), "roles": ("input_roles", ["garment", "person"]),
        "hashes": ("input_sha256", ["0" * 64, "1" * 64]), "category": ("garment_category", "bottoms"),
        "photo_type": ("garment_photo_type", "model"), "adapter": ("adapter_active", True), "count": ("reference_count", 1),
        "parser": ("human_parser", "fashn-human-parser"), "segmentation": ("segmentation_free", False),
        "text": ("text_conditioning", True), "resampling": ("output_resampling", "upscaled"),
        "native": ("native_width", 768), "revision": ("model_revision", "b" * 40)}
    key, value = changes[change]
    bad["metadata"][key] = value
    worker[3].update(status="succeeded", result=bad)
    response = refresh(client, project, payload).json()
    assert response["status"] == "needs_attention" and response["result_json"] == "{}"


@pytest.mark.parametrize("change", ["person_bytes", "garment_bytes", "garment_archive", "person_approval"])
def test_vton_queued_changed_inputs_are_archived(client, worker, change):
    project, values = inputs(client, worker)
    if change == "person_approval":
        with Session(client.engine) as db:
            person = db.get(ProductionMedia, values["person_media_id"])
            person.role, person.approved = "portrait", True
            db.add(person); db.commit()
    payload, _ = submit(client, project, **values)
    with Session(client.engine) as db:
        person = db.get(ProductionMedia, values["person_media_id"])
        garment = db.get(ProductionMedia, values["garment_media_id"])
        if change == "person_bytes":
            Path(person.path).write_bytes(b"changed")
        elif change == "garment_bytes":
            Path(garment.path).write_bytes(b"changed")
        elif change == "garment_archive":
            garment.role = "archived"
        else:
            person.approved = False
        db.add(person); db.add(garment); db.commit()
    completed = finish(client, worker, project, payload)
    assert completed["status"] == "needs_attention" and json.loads(completed["result_json"])["role"] == "archived"


def test_vton_review_fidelity_export_and_promotion_require_trusted_receipt(client, worker, monkeypatch):
    from server.api.routes import production
    monkeypatch.setattr(production, "get_engine", lambda settings: client.engine)
    project, values = inputs(client, worker)
    payload, _ = submit(client, project, **values)
    completed = finish(client, worker, project, payload)
    identity = json.loads(completed["result_json"])["id"]
    route = f"/api/production/media/{identity}/review"
    checklist = ["likeness", "anatomy", "crop", "artifacts"]
    assert client.post(route, json={"checklist": checklist}).status_code == 422
    assert client.post(f"/api/studio/projects/{project}/references", json={"media_id": identity}).status_code == 422
    assert client.post(route, json={"checklist": checklist + ["garment_fidelity"]}).status_code == 200
    render = client.post(f"/api/production/projects/{project}/render", json={})
    assert render.status_code == 202, render.text
    detail = client.get(f"/api/production/outputs/{render.json()['output_id']}").json()
    assert detail["manifest"]["generation_mode"] == "vton"
    assert detail["manifest"]["vton"]["garment_media_id"] == values["garment_media_id"]
    assert detail["manifest"]["delivery_pixels"] == {"width": 576, "height": 864}
    assert detail["manifest"]["upscaled"] is False
    promoted_project, _ = portrait(client)
    promoted = client.post(f"/api/studio/projects/{promoted_project}/references", json={"media_id": identity})
    assert promoted.status_code == 200 and promoted.json()["role"] == "reference"
    with Session(client.engine) as db:
        receipt = db.get(StudioOperation, payload["request_id"])
        receipt.status = "queued"
        db.add(receipt); db.commit()
    assert client.post(f"/api/production/projects/{project}/render", json={}).status_code == 409
    assert client.post(f"/api/studio/projects/{project}/references", json={"media_id": identity}).status_code == 422


@pytest.mark.parametrize("change", ["hashes", "mode", "category", "fidelity", "source_bytes", "worker", "parser"])
def test_vton_tampered_or_stale_approved_portrait_cannot_export_or_promote(client, worker, change):
    project, values = inputs(client, worker)
    payload, _ = submit(client, project, **values)
    identity = json.loads(finish(client, worker, project, payload)["result_json"])["id"]
    checklist = ["likeness", "anatomy", "crop", "artifacts", "garment_fidelity"]
    assert client.post(f"/api/production/media/{identity}/review", json={"checklist": checklist}).status_code == 200
    with Session(client.engine) as db:
        media = db.get(ProductionMedia, identity)
        review = json.loads(media.review_json)
        if change == "hashes":
            review["origin"]["render_metadata"]["input_sha256"].reverse()
        elif change == "mode":
            review["origin"]["generation_mode"] = "reference"
        elif change == "category":
            review["origin"]["garment_category"] = "bottoms"
        elif change == "fidelity":
            review["checklist"].remove("garment_fidelity")
        elif change == "source_bytes":
            source = db.get(ProductionMedia, values["garment_media_id"])
            Path(source.path).write_bytes(b"changed")
        elif change == "parser":
            review["origin"]["render_metadata"]["human_parser"] = "fashn-human-parser"
        else:
            review["origin"]["worker_id"] = "another-worker"
        media.review_json = json.dumps(review)
        db.add(media); db.commit()
    assert client.post(f"/api/production/projects/{project}/render", json={}).status_code == 409
    assert client.post(f"/api/studio/projects/{project}/references", json={"media_id": identity}).status_code == 422


def test_vton_timeout_reconciles_without_reposting_inputs(client, worker):
    project, values = inputs(client, worker)
    worker[3]["submit_timeout"] = True
    payload, response = submit(client, project, **values)
    assert response.json()["status"] == "needs_attention"
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).json()["status"] == "needs_attention"
    assert finish(client, worker, project, payload)["status"] == "succeeded"
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


def test_historical_reference_receipt_without_vton_defaults_is_idempotent(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, response = submit(client, project)
    assert response.status_code == 200
    with Session(client.engine) as db:
        receipt = db.get(StudioOperation, payload["request_id"])
        saved = json.loads(receipt.input_json)
        for key in ("person_media_id", "garment_media_id", "garment_category", "garment_photo_type"):
            saved.pop(key)
        receipt.input_json = json.dumps(saved)
        db.add(receipt); db.commit()
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).status_code == 200
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


def test_reviewed_vton_is_promoted_and_selected_explicitly_for_video(client, worker, monkeypatch):
    from server.api.routes import production
    from server.production import flow_video
    from server.tests.test_production_flow_video import create_project
    project, values = inputs(client, worker)
    payload, _ = submit(client, project, **values)
    identity = json.loads(finish(client, worker, project, payload)["result_json"])["id"]
    assert client.post(f"/api/production/media/{identity}/review", json={
        "checklist": ["likeness", "anatomy", "crop", "artifacts", "garment_fidelity"]}).status_code == 200
    video, scene = create_project(client)
    promoted = client.post(f"/api/studio/projects/{video}/references", json={"media_id": identity})
    assert promoted.status_code == 200 and not promoted.json()["approved"]
    ref = promoted.json()["id"]
    assert client.post(f"/api/production/media/{ref}/review", json={
        "checklist": ["identity", "clothing", "rights"]}).status_code == 200
    sdk = AsyncMock()
    sdk.resolve_project_id.return_value = "12345678-1234-4234-8234-123456789abc"
    sdk.gen_text_video.return_value = "rpc:fixture:video"
    sdk.check_async.side_effect = ConnectionError("fixture interruption after accepted video")
    monkeypatch.setattr(flow_video, "get_flow_sdk", lambda: sdk)
    monkeypatch.setattr(production, "get_engine", lambda settings: client.engine)
    response = client.post(f"/api/production/projects/{video}/generate-video", json={
        "request_id": str(uuid.uuid4()), "scene_id": scene, "reference_mode": "first_frame", "reference_media_id": ref})
    assert response.status_code == 202
    sdk.gen_text_video.assert_awaited_once()
    reference_path = sdk.gen_text_video.call_args.kwargs["reference_image"]
    with Image.open(reference_path) as image:
        assert image.size == (576, 864)
    assert sdk.gen_text_video.call_args.kwargs["reference_mode"] == "first_frame"


def test_direct_vton_video_visual_requires_fidelity_and_successful_receipt_at_export(client, worker):
    from server.production.render import snapshot
    from server.tests.test_production_flow_video import create_project
    from server.tests.test_studio_settings import image_bytes
    video, scene = create_project(client)
    person = client.post(f"/api/production/projects/{video}/media", data={"role": "reference"},
        files={"file": ("person.png", image_bytes(), "image/png")})
    assert person.status_code == 201
    stream = io.BytesIO()
    Image.new("RGB", (80, 96), "red").save(stream, "PNG")
    garment = client.post(f"/api/production/projects/{video}/media", data={"role": "garment"},
        files={"file": ("shop.png", stream.getvalue(), "image/png")})
    assert garment.status_code == 201
    connect(client)
    worker[0].health["capabilities"] = ["image", "virtual_try_on"]
    payload, response = submit(client, video, generation_mode="vton", scene_id=scene,
        person_media_id=person.json()["id"], garment_media_id=garment.json()["id"],
        garment_category="tops", garment_photo_type="flat-lay")
    assert response.status_code == 200
    media = json.loads(finish(client, worker, video, payload)["result_json"])
    assert media["role"] == "visual" and media["scene_id"] == scene
    route = f"/api/production/media/{media['id']}/review"
    base = ["content", "continuity", "framing"]
    assert client.post(route, json={"checklist": base}).status_code == 422
    assert client.post(route, json={"checklist": base + ["garment_fidelity"]}).status_code == 200
    with Session(client.engine) as db:
        project = db.get(Project, video)
        assert snapshot(db, project, client.root)["scenes"][0]["visual"]["id"] == media["id"]
        operation = db.get(StudioOperation, payload["request_id"])
        operation.status = "queued"
        db.add(operation); db.commit()
        with pytest.raises(ValueError, match="biên nhận"):
            snapshot(db, project, client.root)


def test_vton_only_health_can_connect_without_reference_adapter(monkeypatch):
    monkeypatch.setattr(remote, "request", lambda *args, **kwargs: {"api_version": "1", "status": "ready",
        "capabilities": ["image", "virtual_try_on"], "worker_id": WORKER, "persistent_jobs": True, "model_revision": "a" * 40})
    health = remote.ImageConnection.check_health(URL, SecretStr(TOKEN))
    assert health["capabilities"] == ["image", "virtual_try_on"]


def test_vton_descriptor_matches_worker_schema(client, worker):
    from colab.vton_worker.schema import VtonRequest
    project, values = inputs(client, worker)
    _, response = submit(client, project, **values)
    normalized = VtonRequest.model_validate(worker[3]["payload"]).model_dump(mode="json")
    checkpoint = json.loads(response.json()["input_json"])["_remote"]
    assert remote.digest(normalized) == checkpoint["input_sha256"]


def test_vton_downloads_fail_closed_when_reviewed_bundle_is_unavailable(client, monkeypatch):
    from colab.vton_worker import bundle
    def unavailable(root):
        raise ValueError("unapproved package bytes")
    monkeypatch.setattr(bundle, "bundle_bytes", unavailable)
    for route in ("worker.zip", "notebook"):
        response = client.get(f"/api/studio/colab-vton/{route}")
        assert response.status_code == 503
        assert "unapproved package bytes" not in response.text


def test_vton_download_routes_use_identical_reviewed_bundle_and_notebook_pin(client):
    from colab.vton_worker.bundle import BUNDLE_FILES
    zipped = client.get("/api/studio/colab-vton/worker.zip")
    notebook = client.get("/api/studio/colab-vton/notebook")
    assert zipped.status_code == notebook.status_code == 200
    source = "\n".join("".join(cell["source"]) for cell in notebook.json()["cells"])
    assert re.findall(r"hexdigest\(\) != '([a-f0-9]{64})'", source) == [hashlib.sha256(zipped.content).hexdigest()]
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert set(archive.namelist()) == set(BUNDLE_FILES)
        assert "colab/image_worker/engine.py" not in archive.namelist()
        assert not any("human_parser" in name for name in archive.namelist())
    assert all(not cell.get("outputs") for cell in notebook.json()["cells"])
