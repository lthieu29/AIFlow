"""Offline security and durable image job lifecycle contracts."""
import base64
import hashlib
import io
import json
import socket
import uuid

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from sqlmodel import Session, select

from server.audio import remote as audio_remote
from server.image import remote
from server.db.models.asset import Asset
from server.db.models.production import ProductionMedia
from server.db.models.project import Project
from server.db.models.studio import StudioOperation
from server.tests.test_studio_settings import client, image_bytes

TOKEN = "fixture-image-token-" + "x" * 32
WORKER = str(uuid.uuid4())
URL = "https://image-fixture.trycloudflare.com"


def png(width=768, height=1344):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(stream, "PNG")
    return stream.getvalue()


def artifact():
    raw = png()
    return {"mime": "image/png", "data": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest(), "width": 768, "height": 1344,
            "metadata": {"unknown": "must not be persisted"}}


@pytest.fixture
def worker(monkeypatch):
    connection = remote.ImageConnection()
    monkeypatch.setattr(remote, "connection", connection)
    monkeypatch.setattr(remote, "validate_url", lambda url: URL)
    calls, jobs = [], {}
    control = {"status": "queued", "submit_timeout": False, "result": None}
    real_client = httpx.Client
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"api_version": "1", "capabilities": ["image", "reference_image", "text_to_image"],
                "persistent_jobs": True, "status": "ready", "worker_id": WORKER,
                "model_revision": "a" * 40, "extra": TOKEN})
        if request.method == "POST":
            payload = json.loads(request.content)
            control["payload"] = payload
            jobs[payload["request_id"]] = {"request_id": payload["request_id"], "worker_id": WORKER, "input_sha256": remote.digest(payload),
                                           "status": "queued", "generation_mode": payload.get("generation_mode", "reference")}
            if control["submit_timeout"]:
                raise httpx.ReadTimeout(TOKEN, request=request)
            return httpx.Response(202, json=jobs[payload["request_id"]])
        identity = request.url.path.rsplit("/", 1)[-1]
        if identity not in jobs:
            return httpx.Response(404, text=TOKEN)
        job = {**jobs[identity], "status": control["status"]}
        if job["status"] == "succeeded":
            job["result"] = control["result"] or artifact()
            if job["generation_mode"] == "text" and not control["result"]:
                job["result"]["metadata"].update(generation_mode="text", reference_count=0, adapter_active=False, reference_strength=0.0)
        return httpx.Response(200, json=job)
    monkeypatch.setattr(remote.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    return connection, calls, jobs, control


def connect(client):
    result = client.put("/api/studio/connections/colab-image", json={"url": URL, "token": TOKEN})
    assert result.status_code == 200, result.text
    return result.json()


def portrait(client):
    project = client.post("/api/production/portraits", json={"title": "Fixture", "species": "human",
        "identity": "Round face", "style": "portrait"}).json()["id"]
    media = client.post(f"/api/production/projects/{project}/media", data={"role": "reference"},
        files={"file": ("ref.png", image_bytes(), "image/png")})
    assert media.status_code == 201
    return project, media.json()["id"]


def submit(client, project, **values):
    payload = {"request_id": str(uuid.uuid4()), "provider": "colab", **values}
    response = client.post(f"/api/studio/projects/{project}/generate-image", json=payload)
    return payload, response


def refresh(client, project, payload):
    return client.post(f"/api/studio/projects/{project}/operations/{payload['request_id']}/refresh")


def test_connection_credentials_process_only_and_audio_independent(client, worker):
    public = connect(client)
    assert public["configured"] and public["state"] == "ready"
    assert TOKEN not in json.dumps(public)
    assert isinstance(worker[0].token, SecretStr)
    assert client.post("/api/studio/connections/colab-image/check").status_code == 200
    assert TOKEN not in client.get("/api/studio/connections/colab-image").text
    assert not list(client.root.glob("*connection*"))
    audio = audio_remote.connection.public(client.root)
    assert audio["url"] != URL
    disconnected = client.put("/api/studio/connections/colab-image", json={"url": "", "token": ""})
    assert disconnected.status_code == 200 and not disconnected.json()["configured"]
    assert client.post("/api/studio/connections/colab-image/check").status_code == 409


@pytest.mark.parametrize("url", ["http://x.trycloudflare.com", "https://localhost", "https://x.trycloudflare.com/path",
    "https://x.trycloudflare.com?token=secret", "https://user:pass@x.trycloudflare.com", "https://x.trycloudflare.com:444",
    "https://x.trycloudflare.com.evil.test", "https://[", "https://x.trycloudflare.com:bad"])
def test_invalid_urls_never_send_credentials(url):
    with pytest.raises(remote.ImageUnavailable):
        remote.request(url, SecretStr(TOKEN), "GET", "/v1/health")


def test_private_resolution_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(remote.ImageUnavailable):
        remote.request(URL, SecretStr(TOKEN), "GET", "/v1/health")


def test_redirects_and_proxy_disabled(monkeypatch):
    monkeypatch.setattr(remote, "validate_url", lambda url: URL)
    real_client = httpx.Client
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.test"}, text=TOKEN)
    def make_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(remote.httpx, "Client", make_client)
    with pytest.raises(remote.ImageUnavailable) as error:
        remote.request(URL, SecretStr(TOKEN), "GET", "/v1/health")
    assert TOKEN not in str(error.value) and len(calls) == 1


def test_submit_once_explicit_refresh_then_unapproved_result(client, worker):
    project, reference_id = portrait(client)
    connect(client)
    payload, first = submit(client, project, subject_type="pet", reference_media_ids=[reference_id], seed=123)
    assert first.status_code == 200 and first.json()["status"] == "queued"
    assert "data" not in json.loads(first.json()["input_json"])
    route = f"/api/studio/projects/{project}/generate-image"
    assert client.post(route, json=payload).json()["status"] == "queued"
    assert client.post(route, json={**payload, "prompt": "Different"}).status_code == 409
    before = len(worker[1])
    assert client.get(f"/api/studio/projects/{project}/operations").json()[0]["status"] == "queued"
    assert len(worker[1]) == before
    worker[3]["status"] = "running"
    assert refresh(client, project, payload).json()["status"] == "running"
    assert client.get(f"/api/studio/projects/{project}/operations").json()[0]["status"] == "running"
    worker[3]["status"] = "succeeded"
    received = refresh(client, project, payload).json()
    media = json.loads(received["result_json"])
    assert received["status"] == "succeeded" and media["role"] == "portrait" and not media["approved"]
    before = len(worker[1])
    assert refresh(client, project, payload).json() == received
    assert len(worker[1]) == before
    with Session(client.engine) as db:
        rows = db.exec(select(ProductionMedia).where(ProductionMedia.role == "portrait")).all()
        assert len(rows) == 1
        assert "colab_reference_image" in rows[0].review_json
        assert "unknown" not in rows[0].review_json and TOKEN not in rows[0].review_json
        assert TOKEN not in db.get(StudioOperation, payload["request_id"]).input_json
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


def test_unknown_acceptance_never_resubmits_and_recovers(client, worker):
    project, _ = portrait(client)
    connect(client)
    worker[3]["submit_timeout"] = True
    payload, first = submit(client, project)
    assert first.json()["status"] == "needs_attention" and TOKEN not in first.text
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).json()["status"] == "needs_attention"
    worker[3]["status"] = "succeeded"
    assert refresh(client, project, payload).json()["status"] == "succeeded"
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


def test_missing_job_and_changed_worker_no_resubmission(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    worker[2].clear()
    assert refresh(client, project, payload).json()["status"] == "needs_attention"
    before = len(worker[1])
    worker[0].health["worker_id"] = str(uuid.uuid4())
    assert refresh(client, project, payload).json()["status"] == "needs_attention"
    assert len(worker[1]) == before
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


@pytest.mark.parametrize("change", ["brief", "aspect", "reference_bytes", "archive"])
def test_stale_inputs_archived(client, worker, change):
    project, ref_id = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    with Session(client.engine) as db:
        row = db.get(Project, project)
        reference = db.get(ProductionMedia, ref_id)
        if change == "brief":
            row.production_brief = '{"identity":"changed"}'
        elif change == "aspect":
            row.aspect = "1:1"
        elif change == "archive":
            reference.role = "archived"
        elif change == "reference_bytes":
            from pathlib import Path
            Path(reference.path).write_bytes(b"changed")
        db.add(row); db.add(reference); db.commit()
    worker[3]["status"] = "succeeded"
    result = refresh(client, project, payload).json()
    assert result["status"] == "needs_attention" and json.loads(result["result_json"])["role"] == "archived"
    assert not json.loads(result["result_json"])["approved"]


@pytest.mark.parametrize("field,value", [("mime", "image/jpeg"), ("sha256", "0" * 64), ("data", "garbage"),
    ("width", 64), ("height", True)])
def test_malformed_results_not_imported(client, worker, field, value):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    worker[3].update(status="succeeded", result={**artifact(), field: value})
    result = refresh(client, project, payload).json()
    assert result["status"] == "needs_attention" and json.loads(result["result_json"]) == {}
    with Session(client.engine) as db:
        assert len(db.exec(select(ProductionMedia)).all()) == 1
    worker[3]["result"] = artifact()
    assert refresh(client, project, payload).json()["status"] == "succeeded"


def test_corrupt_png_with_matching_checksum_rejected():
    raw = png()[:100]
    result = {**artifact(), "data": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}
    with pytest.raises(remote.ImageUnavailable):
        remote.verify_result(result, 768, 1344)


@pytest.mark.parametrize("values", [{"subject_type": "product"}, {"seed": -1}, {"seed": 2**32},
    {"reference_strength": 1.1}, {"steps": 9}, {"guidance_scale": 13}])
def test_invalid_generation_inputs_rejected(client, values):
    project, _ = portrait(client)
    raw = json.dumps({"request_id": str(uuid.uuid4()), "provider": "colab", **values})
    response = client.post(f"/api/studio/projects/{project}/generate-image", content=raw,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_cross_project_and_arbitrary_file_reference_rejected(client, worker, tmp_path):
    project, ref = portrait(client)
    other, other_ref = portrait(client)
    connect(client)
    assert submit(client, project, reference_media_ids=[other_ref])[1].status_code == 422
    assert submit(client, project, reference_media_ids=[ref, ref])[1].status_code == 422
    with Session(client.engine) as db:
        row = db.get(ProductionMedia, ref)
        row.path = str(client.root.parent / "not-owned.png")
        db.add(row); db.commit()
    assert submit(client, project)[1].status_code == 422
    assert not any(call[0] == "POST" for call in worker[1])


def test_approved_image_reference_promotion_and_dedup(client, worker):
    project, _ = portrait(client)
    target, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    worker[3]["status"] = "succeeded"
    media_id = json.loads(refresh(client, project, payload).json()["result_json"])["id"]
    route = f"/api/studio/projects/{target}/references"
    assert client.post(route, json={"media_id": media_id}).status_code == 422
    approved = client.post(f"/api/production/media/{media_id}/review",
        json={"checklist": ["likeness", "anatomy", "crop", "artifacts"]})
    assert approved.status_code == 200
    promoted = client.post(route, json={"media_id": media_id})
    assert promoted.status_code == 200 and promoted.json()["role"] == "reference"
    assert promoted.json()["project_id"] == target and not promoted.json()["approved"]
    assert client.post(route, json={"media_id": media_id}).json()["id"] == promoted.json()["id"]
    with Session(client.engine) as db:
        source = db.get(ProductionMedia, media_id)
        copied = db.get(ProductionMedia, promoted.json()["id"])
        assert copied.path != source.path and copied.sha256 == source.sha256
        assert source.approved


def test_ecommerce_product_adapter_rejected(client, worker):
    project, _ = portrait(client)
    connect(client)
    with Session(client.engine) as db:
        row = db.get(Project, project)
        row.adapter = "ecommerce_product"
        db.add(row); db.commit()
    assert submit(client, project)[1].status_code == 422


def test_ecommerce_human_reference_explicitly_selected_allowed(client, worker):
    project, ref = portrait(client)
    connect(client)
    with Session(client.engine) as db:
        row = db.get(Project, project)
        row.adapter = "ecommerce_product"
        db.add(row); db.commit()
    assert submit(client, project, reference_media_ids=[ref])[1].json()["status"] == "queued"


@pytest.mark.parametrize("payload", [{"token": TOKEN}, {"url": URL, "token": TOKEN * 30},
    {"url": "x" * 500, "token": TOKEN}, {"url": URL, "token": TOKEN, "extra": "secret"}])
def test_invalid_credentials_not_echoed(client, worker, payload):
    result = client.put("/api/studio/connections/colab-image", json=payload)
    assert result.status_code == 422 and TOKEN not in result.text


def test_reference_transparency_white_and_limits():
    stream = io.BytesIO()
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(stream, "PNG")
    normalized = remote.reference_png(stream.getvalue())
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)
    stream = io.BytesIO()
    Image.new("RGB", (8193, 64)).save(stream, "PNG")
    with pytest.raises(remote.ImageUnavailable):
        remote.reference_png(stream.getvalue())


def test_nonfinite_model_inputs_rejected():
    from pydantic import ValidationError
    from server.api.routes.studio import GenerateImage
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            GenerateImage(request_id=uuid.uuid4(), reference_strength=value)


def test_video_scene_generation_and_stale_scene(client, worker):
    from server.tests.test_production_flow_video import create_project
    from server.db.models.scene import Scene
    project, scene = create_project(client)
    with Session(client.engine) as db:
        row = db.get(Project, project)
        row.aspect = "9:16"
        db.add(row); db.commit()
    assert client.post(f"/api/production/projects/{project}/media", data={"role": "reference"},
        files={"file": ("ref.png", image_bytes(), "image/png")}).status_code == 201
    connect(client)
    payload, response = submit(client, project, scene_id=scene)
    assert response.status_code == 200, response.text
    with Session(client.engine) as db:
        row = db.get(Scene, scene)
        row.prompt = "Changed after submission"
        db.add(row); db.commit()
    worker[3]["status"] = "succeeded"
    result = refresh(client, project, payload).json()
    assert result["status"] == "needs_attention"
    assert json.loads(result["result_json"])["role"] == "archived"


def test_worker_identity_and_digest_mismatch_rejected(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    worker[2][payload["request_id"]]["worker_id"] = str(uuid.uuid4())
    assert refresh(client, project, payload).json()["status"] == "needs_attention"
    worker[2][payload["request_id"]]["worker_id"] = WORKER
    worker[2][payload["request_id"]]["input_sha256"] = "0" * 64
    assert refresh(client, project, payload).json()["status"] == "needs_attention"


def test_render_metadata_preserved_and_credentials_excluded(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    metadata = {"scheduler": "EulerDiscreteScheduler", "precision": "float16", "duration_seconds": 5.1,
                "engine": "diffusers-sdxl-ip-adapter-plus", "device": TOKEN,
                "versions": {"diffusers": "0.35.1", "secret": TOKEN}, "unrelated": TOKEN}
    worker[3].update(status="succeeded", result={**artifact(), "metadata": metadata})
    result = refresh(client, project, payload).json()
    with Session(client.engine) as db:
        row = db.get(ProductionMedia, json.loads(result["result_json"])["id"])
        review = json.loads(row.review_json)["origin"]["render_metadata"]
        assert review["scheduler"] == "EulerDiscreteScheduler" and review["duration_seconds"] == 5.1
        assert review["versions"] == {"diffusers": "0.35.1"}
        assert TOKEN not in row.review_json


def test_submission_matches_worker_canonical_schema(client, worker):
    from colab.image_worker.app import ImageRequest
    project, _ = portrait(client)
    connect(client)
    payload, response = submit(client, project)
    assert response.status_code == 200
    checkpoint = json.loads(response.json()["input_json"])["_remote"]
    # Reconstruct exactly what the backend sends from the managed reference.
    with Session(client.engine) as db:
        ref = db.exec(select(ProductionMedia).where(ProductionMedia.role == "reference")).one()
        from pathlib import Path
        raw = remote.reference_png(Path(ref.path).read_bytes())
        brief = json.loads(db.get(Project, project).production_brief)
    request = {"request_id": payload["request_id"], "subject_type": "human", "negative_prompt": "", "seed": 0,
        "generation_mode": "reference",
        "steps": 30, "guidance_scale": 4.5, "reference_strength": 0.45, "width": 768, "height": 1344,
        "references": [{"mime": "image/png", "data": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}],
        "prompt": "\n".join(["Natural human portrait; preserve identity.", brief["identity"], brief["style"]])}
    normalized = ImageRequest.model_validate(request).model_dump(mode="json")
    assert remote.digest(normalized) == checkpoint["input_sha256"]


def test_download_bundle_and_notebook_have_matching_integrity_pin(client):
    import re
    import zipfile
    from colab.image_worker.bundle import BUNDLE_FILES
    bundle = client.get("/api/studio/colab-image/worker.zip")
    notebook = client.get("/api/studio/colab-image/notebook")
    assert bundle.status_code == notebook.status_code == 200
    assert client.get("/api/studio/colab-image/worker.zip").content == bundle.content
    data = notebook.json()
    source = "\n".join("".join(cell["source"]) for cell in data["cells"])
    hashes = re.findall(r"hexdigest\(\) != '([a-f0-9]{64})'", source)
    assert hashes == [hashlib.sha256(bundle.content).hexdigest()]
    for cell in data["cells"]:
        assert not cell.get("outputs")
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert set(archive.namelist()) == {f"image_worker/{name}" for name in BUNDLE_FILES}
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_unused_assets_not_read_or_used_for_colab(client, worker, monkeypatch):
    from server.image import jobs
    project, _ = portrait(client)
    connect(client)
    unrelated = client.root / "unused-video.mp4"
    with Session(client.engine) as db:
        db.add(Asset(project_id=project, name="Unused video", type="reference", file_path=str(unrelated)))
        db.commit()
    original = jobs.contained
    def only_actual_reference(root, value):
        assert value != str(unrelated)
        return original(root, value)
    monkeypatch.setattr(jobs, "contained", only_actual_reference)
    payload, first = submit(client, project)
    assert first.json()["status"] == "queued"
    worker[3]["status"] = "succeeded"
    assert refresh(client, project, payload).json()["status"] == "succeeded"


def test_contradictory_model_provenance_not_accepted(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    worker[3].update(status="succeeded", result={**artifact(), "metadata": {"model_revision": "b" * 40}})
    result = refresh(client, project, payload).json()
    assert result["status"] == "needs_attention" and result["result_json"] == "{}"


def test_connection_rejects_image_only_worker(client, worker, monkeypatch):
    monkeypatch.setattr(remote, "request", lambda *a, **kw: {"api_version": "1", "capabilities": ["image"],
        "persistent_jobs": True, "status": "ready", "worker_id": WORKER, "model_revision": "a" * 40})
    result = client.put("/api/studio/connections/colab-image", json={"url": URL, "token": TOKEN})
    assert result.status_code == 422
    assert not client.get("/api/studio/connections/colab-image").json()["configured"]


def test_receipt_survives_backend_connection_reset_without_resubmission(client, worker, monkeypatch):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    monkeypatch.setattr(remote, "connection", remote.ImageConnection())
    assert not client.get("/api/studio/connections/colab-image").json()["configured"]
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).json()["status"] == "queued"
    connect(client)
    worker[3]["status"] = "succeeded"
    assert refresh(client, project, payload).json()["status"] == "succeeded"
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


def test_portrait_brief_supports_people_and_pets_without_pet_only_default(client):
    project, _ = portrait(client)
    result = client.get(f"/api/production/projects/{project}")
    assert result.status_code == 200
    assert result.json()["brief"]["species"] == "human"
    assert "person or pet" in result.json()["prompt"]
    assert "personalized pet portrait" not in result.json()["prompt"]


def test_hardware_and_sampler_metadata_bounded():
    from server.image.jobs import provenance_metadata
    value = {"peak_vram_allocated_bytes": 9 * 1024**3, "peak_vram_reserved_bytes": 15 * 1024**3,
        "scheduler_config": {"algorithm_type": "dpmsolver++", "use_karras_sigmas": True,
            "solver_order": 2, "prediction_type": "epsilon", "timestep_spacing": "leading",
            "beta_schedule": "scaled_linear", "num_train_timesteps": 1000, "thresholding": False,
            "private": TOKEN}}
    actual = provenance_metadata(value, SecretStr(TOKEN))
    assert actual["peak_vram_allocated_bytes"] == 9 * 1024**3
    assert actual["peak_vram_reserved_bytes"] == 15 * 1024**3
    assert actual["scheduler_config"] == {key: item for key, item in value["scheduler_config"].items() if key != "private"}
    for invalid in (-1, 65 * 1024**3, True, 1.5):
        assert "peak_vram_allocated_bytes" not in provenance_metadata({"peak_vram_allocated_bytes": invalid}, SecretStr(TOKEN))
    bad = {"scheduler_config": {"algorithm_type": TOKEN, "solver_order": -1, "prediction_type": "x" * 81,
                               "num_train_timesteps": 1_000_001, "thresholding": {"secret": TOKEN}}}
    assert provenance_metadata(bad, SecretStr(TOKEN))["scheduler_config"] == {}


def test_dns_failure_is_recoverable_connection_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise socket.gaierror("DNS failed with a diagnostic that must not be echoed")
    monkeypatch.setattr(socket, "getaddrinfo", unavailable)
    with pytest.raises(remote.ImageUnavailable) as caught:
        remote.request(URL, SecretStr(TOKEN), "GET", "/v1/health")
    assert caught.value.state == "unreachable"
    assert "Không phân giải" in str(caught.value)
    assert "Quick Tunnel công khai" not in str(caught.value)
    assert "diagnostic" not in str(caught.value)


def test_gpu_resident_vae_profile_provenance():
    from server.image.jobs import provenance_metadata
    value = {"cpu_offload": False, "memory_profile": "t4-gpu-resident-vae512",
             "vae_precision": "float32_decode", "vae_tile_size": 512}
    assert provenance_metadata(value, SecretStr(TOKEN)) == value
    for invalid in (True, -1, 2049, 512.0):
        assert "vae_tile_size" not in provenance_metadata({"vae_tile_size": invalid}, SecretStr(TOKEN))


def test_prompt_prioritizes_composition_preserves_instructions_and_deduplicates():
    from server.image.jobs import compile_prompt
    user = "Upper body, both hands visible, light blue background."
    scene = "Standing by a window in afternoon light."
    identity = "Brown hair, oval face, green eyes."
    requirements = "Keep the mole above the left eyebrow."
    prompt = compile_prompt({"species": "human", "identity": identity, "style": user, "requirements": requirements},
                            scene, user, "human")
    assert prompt.startswith(user + "\n" + scene)
    assert prompt.count(user) == 1
    assert identity in prompt and requirements in prompt
    assert "Natural human portrait; preserve identity." in prompt
    assert len(prompt) < len(user + scene + identity + requirements) + 60


def test_prompt_limit_rejects_without_silently_losing_instructions(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, result = submit(client, project, prompt="Keep every requested detail. " * 100)
    assert result.status_code == 422
    assert not any(call[0] == "POST" for call in worker[1])
    with Session(client.engine) as db:
        assert db.get(StudioOperation, payload["request_id"]) is None


def test_token_limit_failure_actionable_without_echoing_worker_text(client, worker):
    project, _ = portrait(client)
    connect(client)
    payload, _ = submit(client, project)
    worker[3]["status"] = "failed"
    worker[2][payload["request_id"]]["error"] = {"code": "prompt_too_long", "message": TOKEN}
    result = refresh(client, project, payload).json()
    assert result["status"] == "failed"
    assert "77 token" in result["error"] and "mô tả nhân vật" in result["error"]
    assert TOKEN not in result["error"]


def text_portrait(client):
    response = client.post("/api/production/portraits", json={"title": "Fictional actor", "species": "human",
        "identity": "Brown hair, oval face", "style": "natural photograph"})
    assert response.status_code == 201
    return response.json()["id"]


def test_text_human_without_photo_durable_unapproved_and_canonical(client, worker):
    from colab.image_worker.app import ImageRequest
    project = text_portrait(client)
    connect(client)
    payload, first = submit(client, project, generation_mode="text", prompt="Upper body, blue background.")
    assert first.status_code == 200 and first.json()["status"] == "queued"
    sent = worker[3]["payload"]
    assert sent["generation_mode"] == "text" and sent["references"] == []
    assert "fictional human" in sent["prompt"] and "preserve identity" not in sent["prompt"]
    normalized = ImageRequest.model_validate(sent).model_dump(mode="json")
    checkpoint = json.loads(first.json()["input_json"])["_remote"]
    assert remote.digest(normalized) == checkpoint["input_sha256"]
    assert checkpoint["snapshot"]["references"] == checkpoint["snapshot"]["reference_ids"] == []
    assert not checkpoint["snapshot"]["automatic_references"]
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).json()["status"] == "queued"
    worker[3]["status"] = "succeeded"
    result = refresh(client, project, payload).json()
    assert result["status"] == "succeeded"
    with Session(client.engine) as db:
        media = db.get(ProductionMedia, json.loads(result["result_json"])["id"])
        origin = json.loads(media.review_json)["origin"]
        assert not media.approved and origin["generation_mode"] == "text"
        assert origin["reference_count"] == 0 and origin["kind"] == "colab_text_image"
    assert len([call for call in worker[1] if call[0] == "POST"]) == 1


def test_text_mode_never_reads_or_autoattaches_existing_photos(client, worker, monkeypatch):
    from server.image import jobs
    project, ref_id = portrait(client)
    connect(client)
    def no_photos(*args, **kwargs):
        raise AssertionError("Text mode must not read any reference image")
    monkeypatch.setattr(jobs, "contained", no_photos)
    payload, first = submit(client, project, generation_mode="text")
    assert first.status_code == 200
    assert worker[3]["payload"]["references"] == []
    with Session(client.engine) as db:
        ref = db.get(ProductionMedia, ref_id)
        ref.role = "archived"
        ref.sha256 = "0" * 64
        db.add(ref); db.commit()
    worker[3]["status"] = "succeeded"
    assert refresh(client, project, payload).json()["status"] == "succeeded"


@pytest.mark.parametrize("values", [{"subject_type": "pet"}, {"provider": "gemini"}, {"reference_media_ids": [1]},
                                    {"generation_mode": "unknown"}])
def test_invalid_text_mode_combination_rejected_before_worker(client, worker, values):
    project = text_portrait(client)
    connect(client)
    _, response = submit(client, project, generation_mode="text", **values) if "generation_mode" not in values else submit(client, project, **values)
    assert response.status_code == 422
    assert not any(call[0] == "POST" for call in worker[1])


def test_text_mode_stale_brief_archived_and_request_mode_collision_rejected(client, worker):
    project = text_portrait(client)
    connect(client)
    payload, _ = submit(client, project, generation_mode="text")
    assert client.post(f"/api/studio/projects/{project}/generate-image",
        json={**payload, "generation_mode": "reference"}).status_code == 409
    with Session(client.engine) as db:
        row = db.get(Project, project)
        row.production_brief = '{"identity":"Different fictional actor"}'
        db.add(row); db.commit()
    worker[3]["status"] = "succeeded"
    result = refresh(client, project, payload).json()
    assert result["status"] == "needs_attention"
    assert json.loads(result["result_json"])["role"] == "archived"


def test_reference_mode_still_requires_photo_and_old_receipt_without_mode_survives(client, worker):
    project = text_portrait(client)
    connect(client)
    assert submit(client, project)[1].status_code == 422
    project, _ = portrait(client)
    payload, first = submit(client, project)
    with Session(client.engine) as db:
        row = db.get(StudioOperation, payload["request_id"])
        saved = json.loads(row.input_json)
        saved.pop("generation_mode")
        saved["_remote"]["snapshot"].pop("generation_mode")
        row.input_json = json.dumps(saved)
        db.add(row); db.commit()
    assert client.post(f"/api/studio/projects/{project}/generate-image", json=payload).status_code == 200
    worker[3]["status"] = "succeeded"
    assert refresh(client, project, payload).json()["status"] == "succeeded"


def test_high_resolution_reference_downscaled_without_changing_original():
    stream = io.BytesIO()
    Image.new("RGB", (4000, 6000), "green").save(stream, "JPEG")
    raw = stream.getvalue()
    original = hashlib.sha256(raw).hexdigest()
    normalized = remote.reference_png(raw)
    assert hashlib.sha256(raw).hexdigest() == original
    assert hashlib.sha256(normalized).hexdigest() != original
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.size == (1365, 2048) and image.mode == "RGB"
    small = image_bytes()
    assert remote.reference_png(small) == small


@pytest.mark.parametrize("size", [(8193, 64), (8192, 8192)])
def test_reference_dimension_limit_checked_before_pixel_decode(monkeypatch, size):
    dimensions = size
    class HeaderOnlyImage:
        width, height = dimensions
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        @property
        def size(self):
            return self.width, self.height
        def load(self):
            raise AssertionError("Oversized image must be rejected before decoding")
    monkeypatch.setattr(remote.Image, "open", lambda raw: HeaderOnlyImage())
    with pytest.raises(remote.ImageUnavailable):
        remote.reference_png(b"header")


def test_reference_exif_orientation_applied_and_metadata_removed():
    stream = io.BytesIO()
    image = Image.new("RGB", (40, 80), "red")
    exif = image.getexif()
    exif[274] = 6
    image.save(stream, "JPEG", exif=exif)
    normalized = remote.reference_png(stream.getvalue())
    with Image.open(io.BytesIO(normalized)) as image:
        assert image.size == (80, 40)
        assert "exif" not in image.info


def test_text_worker_capability_required_and_legacy_reference_payload_compatible(client, worker):
    project, _ = portrait(client)
    connect(client)
    worker[0].health["capabilities"] = ["image", "reference_image"]
    assert submit(client, project, generation_mode="text")[1].status_code == 409
    assert not any(call[0] == "POST" for call in worker[1])
    _, result = submit(client, project)
    assert result.status_code == 200 and result.json()["status"] == "queued"
    assert "generation_mode" not in worker[3]["payload"]
    checkpoint = json.loads(result.json()["input_json"])["_remote"]
    assert checkpoint["input_sha256"] == remote.digest(worker[3]["payload"])


@pytest.mark.parametrize("metadata", [{}, {"generation_mode": "reference", "reference_count": 0, "adapter_active": False},
    {"generation_mode": "text", "reference_count": 1, "adapter_active": False},
    {"generation_mode": "text", "reference_count": 0, "adapter_active": True}])
def test_text_receipt_requires_proof_of_no_reference_adapter(client, worker, metadata):
    project = text_portrait(client)
    connect(client)
    payload, _ = submit(client, project, generation_mode="text")
    worker[3].update(status="succeeded", result={**artifact(), "metadata": metadata})
    result = refresh(client, project, payload).json()
    assert result["status"] == "needs_attention" and result["result_json"] == "{}"
    with Session(client.engine) as db:
        assert db.exec(select(ProductionMedia)).all() == []


def test_text_approved_portrait_exports_without_photo_and_no_origin_spoofing(client, worker, monkeypatch):
    import zipfile
    from server.api.routes import production
    monkeypatch.setattr(production, "get_engine", lambda settings: client.engine)
    project = text_portrait(client)
    connect(client)
    payload, _ = submit(client, project, generation_mode="text")
    worker[3]["status"] = "succeeded"
    result = refresh(client, project, payload).json()
    media_id = json.loads(result["result_json"])["id"]
    route = f"/api/production/projects/{project}/render"
    assert client.post(route, json={}).status_code == 409
    review = client.post(f"/api/production/media/{media_id}/review", json={
        "checklist": ["likeness", "anatomy", "crop", "artifacts"],
        "origin": {"generation_mode": "reference", "reference_count": 3}})
    assert review.status_code == 200
    with Session(client.engine) as db:
        media = db.get(ProductionMedia, media_id)
        origin = json.loads(media.review_json)["origin"]
        assert origin["generation_mode"] == "text" and origin["reference_count"] == 0
        assert origin["reference_strength"] == 0.0
    rendered = client.post(route, json={})
    assert rendered.status_code == 202, rendered.text
    output_id = rendered.json()["output_id"]
    detail = client.get(f"/api/production/outputs/{output_id}").json()
    assert detail["status"] == "awaiting_review" and detail["manifest"]["references"] == []
    assert detail["manifest"]["generation_mode"] == "text"
    assert client.post(f"/api/production/outputs/{output_id}/review",
                       json={"checklist": ["quality", "rights", "delivery"]}).status_code == 200
    downloaded = client.get(f"/api/production/outputs/{output_id}/download")
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert {"portrait.png", "portrait.jpg", "preview.jpg", "manifest.json"}.issubset(archive.namelist())
        listing = archive.read("listing-draft.txt").decode()
        assert "person or pet" in listing and "Personalized pet portrait" not in listing
        assert str(client.root) not in archive.read("manifest.json").decode()


@pytest.mark.parametrize("change", ["incomplete", "no_adapter_fact", "count", "operation", "checksum", "mode"])
def test_forged_or_incomplete_text_provenance_cannot_bypass_export(client, worker, change):
    project = text_portrait(client)
    connect(client)
    payload, _ = submit(client, project, generation_mode="text")
    worker[3]["status"] = "succeeded"
    media_id = json.loads(refresh(client, project, payload).json()["result_json"])["id"]
    assert client.post(f"/api/production/media/{media_id}/review",
        json={"checklist": ["likeness", "anatomy", "crop", "artifacts"]}).status_code == 200
    with Session(client.engine) as db:
        media = db.get(ProductionMedia, media_id)
        review = json.loads(media.review_json)
        origin = review["origin"]
        operation = db.get(StudioOperation, payload["request_id"])
        if change == "incomplete":
            review["origin"] = {"kind": "colab_text_image"}
        elif change == "no_adapter_fact":
            origin["render_metadata"].pop("adapter_active")
        elif change == "count":
            origin["reference_count"] = 1
        elif change == "operation":
            origin["request_id"] = str(uuid.uuid4())
        elif change == "checksum":
            saved = json.loads(operation.result_json)
            saved["sha256"] = "0" * 64
            operation.result_json = json.dumps(saved)
        else:
            saved = json.loads(operation.input_json)
            saved["generation_mode"] = "reference"
            operation.input_json = json.dumps(saved)
        media.review_json = json.dumps(review)
        db.add(media); db.add(operation); db.commit()
    assert client.post(f"/api/production/projects/{project}/render", json={}).status_code == 409


def test_imported_no_reference_portrait_still_cannot_export(client):
    project = text_portrait(client)
    uploaded = client.post(f"/api/production/projects/{project}/media", data={"role": "portrait"},
        files={"file": ("portrait.png", image_bytes(), "image/png")})
    assert uploaded.status_code == 201
    assert client.post(f"/api/production/media/{uploaded.json()['id']}/review",
        json={"checklist": ["likeness", "anatomy", "crop", "artifacts"]}).status_code == 200
    assert client.post(f"/api/production/projects/{project}/render", json={}).status_code == 409


def test_portrait_prompt_preview_does_not_claim_missing_reference_photos(client):
    project = text_portrait(client)
    preview = client.get(f"/api/production/projects/{project}").json()["prompt"]
    assert "following this brief" in preview
    assert "reference images" not in preview and "Preserve identity" not in preview
    project, _ = portrait(client)
    preview = client.get(f"/api/production/projects/{project}").json()["prompt"]
    assert "Preserve identity using the provided reference images" in preview
    assert "attached" not in preview
