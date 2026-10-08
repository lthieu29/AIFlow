"""Contract/security tests. No model downloads and no synthetic production engine."""

import ast
import base64
import hashlib
import io
import json
import sys
import threading
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from colab.image_worker.app import MAX_BODY_BYTES, ImageRequest, create_app, decode_reference, digest
from colab.image_worker.bootstrap import install_reviewed_packages
from colab.image_worker.bundle import BUNDLE_FILES, bundle_bytes, notebook_bytes
from colab.image_worker.engine import PromptTooLongError, SDXLEngine, prepare_reference, validate_prompt_tokens
from colab.image_worker.models import ADAPTER_REPO, BASE_REPO, REVISIONS, read_lock, verify_file

TOKEN = "test-session-token-" + "x" * 32


class InjectedEngine:
    ready = True
    model_revision = "test-only-revision"

    def __init__(self, *, gate=None, fail=False):
        self.calls = 0
        self.gate = gate
        self.fail = fail

    def generate(self, request):
        self.calls += 1
        if self.gate:
            assert self.gate.wait(10)
        if self.fail:
            raise RuntimeError("secret must never reach API")
        return Image.new("RGB", (request.width, request.height), "navy"), {"seed": request.seed}


def payload():
    buffer = io.BytesIO()
    Image.new("RGB", (48, 64), "orange").save(buffer, format="PNG")
    raw = buffer.getvalue()
    return {"request_id": str(uuid.uuid4()), "generation_mode": "reference",
            "subject_type": "pet", "prompt": "Realistic pet portrait",
            "negative_prompt": "cartoon", "width": 256, "height": 256, "seed": 10, "steps": 10,
            "guidance_scale": 5.0, "reference_strength": 0.65,
            "references": [{"mime": "image/png", "data": base64.b64encode(raw).decode(),
                            "sha256": hashlib.sha256(raw).hexdigest()}]}


def client_for(tmp_path, engine=None, **kwargs):
    engine = engine or InjectedEngine()
    app = create_app(token=TOKEN, root=tmp_path, engine=engine, **kwargs)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}), app, engine


def test_auth_every_route_and_no_docs(tmp_path):
    client, app, _ = client_for(tmp_path)
    for path in ("/v1/health", "/v1/images/jobs/" + str(uuid.uuid4())):
        assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/v1/images/jobs", json=payload(), headers={"Authorization": ""}).status_code == 401
    assert client.get("/docs").status_code == 404
    health = client.get("/v1/health").json()
    assert health["api_version"] == "1" and health["status"] == "ready"
    assert "reference_image" in health["capabilities"] and health["persistent_jobs"] is True
    app.state.executor.shutdown()


def test_unauthorized_body_rejected_before_image_decoding(tmp_path, monkeypatch):
    client, app, _ = client_for(tmp_path)
    def must_not_decode(_reference):
        raise AssertionError("Unauthenticated requests must not decode images")
    monkeypatch.setattr("colab.image_worker.app.decode_reference", must_not_decode)
    response = client.post("/v1/images/jobs", json=payload(), headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    app.state.executor.shutdown()


@pytest.mark.parametrize("token", ["", "x" * 31, "x" * 32 + "\n", "é" * 32])
def test_short_or_invalid_tokens_rejected(tmp_path, token):
    with pytest.raises(ValueError):
        create_app(token=token, root=tmp_path, engine=InjectedEngine())


def test_generation_hash_idempotency_and_restart(tmp_path):
    client, app, engine = client_for(tmp_path)
    request = payload()
    submitted = client.post("/v1/images/jobs", json=request)
    assert submitted.status_code == 202
    app.state.executor.shutdown(wait=True)
    job_id = submitted.json()["job_id"]
    job = client.get(f"/v1/images/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert job["request_id"] == request["request_id"]
    assert job["input_sha256"] == digest(request)
    raw = base64.b64decode(job["result"]["data"], validate=True)
    assert hashlib.sha256(raw).hexdigest() == job["result"]["sha256"]
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        assert image.size == (256, 256) and image.format == "PNG"
    assert client.post("/v1/images/jobs", json=request).status_code == 202
    request["prompt"] = "different"
    assert client.post("/v1/images/jobs", json=request).status_code == 409
    assert engine.calls == 1
    second, second_app, second_engine = client_for(tmp_path)
    assert second.get("/v1/health").json()["worker_id"] == job["worker_id"]
    assert second.get(f"/v1/images/jobs/{job_id}").json()["result"] == job["result"]
    assert second_engine.calls == 0
    # Manifests contain hash/state/provenance, never session credentials or raw reference bytes.
    manifest = (tmp_path / "jobs" / f"{job_id}.json").read_text()
    assert TOKEN not in manifest and request["references"][0]["data"] not in manifest
    second_app.state.executor.shutdown()


def test_interrupted_job_is_failed_without_reexecution(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    job_id = str(uuid.uuid4())
    (jobs / f"{job_id}.json").write_text(json.dumps({"job_id": job_id, "status": "running", "input_sha256": "x" * 64}))
    client, app, engine = client_for(tmp_path)
    job = client.get(f"/v1/images/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "interrupted"
    assert engine.calls == 0
    app.state.executor.shutdown()


def test_bounded_queue_allows_duplicate_and_single_gpu(tmp_path):
    gate = threading.Event()
    client, app, engine = client_for(tmp_path, InjectedEngine(gate=gate), max_pending=1)
    request = payload()
    assert client.post("/v1/images/jobs", json=request).status_code == 202
    assert client.post("/v1/images/jobs", json=request).status_code == 202
    assert client.post("/v1/images/jobs", json=payload()).status_code == 429
    gate.set()
    app.state.executor.shutdown(wait=True)
    assert engine.calls == 1


@pytest.mark.parametrize("field,value", [("subject_type", "product"), ("width", 257), ("height", 1600),
                                        ("steps", 51), ("seed", -1), ("reference_strength", 1.1),
                                        ("guidance_scale", 0.5), ("prompt", "   "), ("extra", True)])
def test_invalid_request_constraints(tmp_path, field, value):
    client, app, engine = client_for(tmp_path)
    request = payload()
    request[field] = value
    response = client.post("/v1/images/jobs", json=request)
    assert response.status_code == 422
    assert request["references"][0]["data"] not in response.text
    assert engine.calls == 0
    app.state.executor.shutdown()


@pytest.mark.parametrize("mutation", ["bad_hash", "bad_mime", "bad_base64", "not_image", "tiny_image"])
def test_invalid_reference(tmp_path, mutation):
    client, app, _ = client_for(tmp_path)
    request = payload()
    ref = request["references"][0]
    if mutation == "bad_hash":
        ref["sha256"] = "0" * 64
    elif mutation == "bad_mime":
        ref["mime"] = "image/jpeg"
    elif mutation == "bad_base64":
        ref["data"] = "!!!!"
    else:
        raw = b"not an image"
        if mutation == "tiny_image":
            buffer = io.BytesIO()
            Image.new("RGB", (16, 16)).save(buffer, format="PNG")
            raw = buffer.getvalue()
        ref["data"] = base64.b64encode(raw).decode()
        ref["sha256"] = hashlib.sha256(raw).hexdigest()
    assert client.post("/v1/images/jobs", json=request).status_code == 422
    app.state.executor.shutdown()


def test_failure_sanitized_and_result_tamper_rejected(tmp_path):
    client, app, _ = client_for(tmp_path, InjectedEngine(fail=True))
    request = payload()
    job_id = client.post("/v1/images/jobs", json=request).json()["job_id"]
    app.state.executor.shutdown(wait=True)
    response = client.get(f"/v1/images/jobs/{job_id}")
    assert response.json()["status"] == "failed"
    assert "secret must never" not in response.text
    client2, app2, _ = client_for(tmp_path / "success")
    job_id = client2.post("/v1/images/jobs", json=payload()).json()["job_id"]
    app2.state.executor.shutdown(wait=True)
    (tmp_path / "success" / "jobs" / f"{job_id}.png").write_bytes(b"tampered")
    assert client2.get(f"/v1/images/jobs/{job_id}").status_code == 500


def test_body_size_and_path_traversal(tmp_path):
    client, app, _ = client_for(tmp_path)
    response = client.post("/v1/images/jobs", content=b"{}", headers={"Content-Length": str(MAX_BODY_BYTES + 1)})
    assert response.status_code == 413
    assert client.get("/v1/images/jobs/not-a-uuid").status_code == 404
    app.state.executor.shutdown()


def test_reference_letterbox_preserves_top_and_bottom():
    image = Image.new("RGB", (40, 80), "red")
    prepared = prepare_reference(image)
    assert prepared.size == (224, 224)
    assert prepared.getpixel((112, 0)) == (255, 0, 0)
    assert prepared.getpixel((112, 223)) == (255, 0, 0)
    assert prepared.getpixel((0, 112)) == (255, 255, 255)
    reference = ImageRequest.model_validate(payload()).references[0]
    assert decode_reference(reference).size == (48, 64)


def test_model_lock_safe_and_exact_file_hash(tmp_path):
    lock_path = Path(__file__).parents[1] / "image_worker" / "model-lock.json"
    lock = read_lock(lock_path)
    assert len(lock) == 2 and sum(len(value["files"]) for value in lock.values()) == 21
    changed = json.loads(lock_path.read_text())
    changed["h94/IP-Adapter"]["files"][0]["path"] = "../escape.py"
    bad_lock = tmp_path / "bad.json"
    bad_lock.write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        read_lock(bad_lock)
    file = tmp_path / "config.json"
    file.write_bytes(b"{}")
    entry = {"path": file.name, "size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}
    verify_file(file, entry)
    file.write_bytes(b"[]")
    with pytest.raises(ValueError):
        verify_file(file, entry)


def test_bootstrap_fails_closed_when_requirements_change(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements-lock.txt"
    requirements.write_bytes(b"safe==1 --hash=sha256:hash\n")
    approval = {"approved": True, "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest()}
    (tmp_path / "audit-approval.json").write_text(json.dumps(approval))
    calls = []
    monkeypatch.setattr("colab.image_worker.bootstrap.subprocess.run", lambda args, **kwargs: calls.append(args))
    install_reviewed_packages(tmp_path, Path("python"))
    assert "--require-hashes" in calls[0] and "--no-deps" in calls[0] and "--only-binary=:all:" in calls[0]
    requirements.write_bytes(b"other==2\n")
    with pytest.raises(RuntimeError):
        install_reviewed_packages(tmp_path, Path("python"))
    assert len(calls) == 1


def test_deterministic_bundle_and_matching_notebook(tmp_path):
    root = Path(__file__).parents[1]
    package = root / "image_worker"
    first = bundle_bytes(package)
    second = bundle_bytes(package)
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == [f"image_worker/{name}" for name in sorted(BUNDLE_FILES)]
        assert all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in archive.infolist())
    checksum = hashlib.sha256(first).hexdigest()
    notebook = json.loads(notebook_bytes(root / "serve_image_api.ipynb", checksum))
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert f".hexdigest() != '{checksum}'" in source
    assert all(not cell["outputs"] for cell in notebook["cells"] if cell["cell_type"] == "code")
    # A changed source file updates both ZIP and notebook's approved-byte check.
    copied = tmp_path / "image_worker"
    copied.mkdir()
    for name in BUNDLE_FILES:
        (copied / name).write_bytes((package / name).read_bytes())
    with (copied / "app.py").open("a", encoding="utf-8") as stream:
        stream.write("\n# revised worker\n")
    changed = bundle_bytes(copied)
    assert first != changed
    changed_sha = hashlib.sha256(changed).hexdigest()
    updated = notebook_bytes(root / "serve_image_api.ipynb", changed_sha)
    assert changed_sha.encode() in updated and checksum.encode() not in updated


def test_engine_initializes_with_diffusers_040_component_api(tmp_path, monkeypatch):
    """0.40 exposes VAE toggles on the component and accepts dtype, not legacy helpers."""
    class FakeVAE:
        slicing = False
        tiling = False

        def register_to_config(self, *, force_upcast):
            self.force_upcast = force_upcast

        def enable_slicing(self):
            self.slicing = True

        def enable_tiling(self):
            self.tiling = True

    class CurrentPipelineAPI:
        def __init__(self):
            self.vae = FakeVAE()
            self.vae_scale_factor = 8
            self.device = "cpu"
            self.scheduler = SimpleNamespace(config={"prediction_type": "epsilon", "beta_schedule": "scaled_linear"})

        @classmethod
        def from_pretrained(cls, path, *, image_encoder, feature_extractor, dtype, variant,
                            use_safetensors, local_files_only):
            assert dtype == "fp16" and variant == "fp16"
            assert use_safetensors is True and local_files_only is True
            return cls()

        def load_ip_adapter(self, path, *, subfolder, weight_name, image_encoder_folder, local_files_only):
            assert weight_name.endswith(".safetensors") and image_encoder_folder is None and local_files_only is True

        def to(self, device):
            self.device = device
            return self

        def set_progress_bar_config(self, *, disable):
            assert disable is True

    class CurrentEncoderAPI:
        @classmethod
        def from_pretrained(cls, path, *, dtype, local_files_only, use_safetensors, trust_remote_code):
            assert dtype == "fp16" and local_files_only is True and use_safetensors is True
            assert trust_remote_code is False
            return cls()

    class OptimizedSchedulerAPI:
        @classmethod
        def from_config(cls, config, *, algorithm_type, use_karras_sigmas, solver_order, thresholding):
            assert config["prediction_type"] == "epsilon" and config["beta_schedule"] == "scaled_linear"
            return SimpleNamespace(config={**config, "algorithm_type": algorithm_type,
                                           "use_karras_sigmas": use_karras_sigmas,
                                           "solver_order": solver_order, "thresholding": thresholding})

    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: True, memory_allocated=lambda: 0, memory_reserved=lambda: 0)
    torch.float16 = "fp16"
    diffusers = ModuleType("diffusers")
    diffusers.StableDiffusionXLPipeline = CurrentPipelineAPI
    diffusers.DPMSolverMultistepScheduler = OptimizedSchedulerAPI
    transformers = ModuleType("transformers")
    transformers.CLIPVisionModelWithProjection = CurrentEncoderAPI
    transformers.CLIPImageProcessor = lambda: object()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "diffusers", diffusers)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setattr("colab.image_worker.bootstrap.verify_runtime", lambda: {})
    lock_path = Path(__file__).parents[1] / "image_worker/model-lock.json"
    monkeypatch.setattr("colab.image_worker.engine.verify_models", lambda *_: read_lock(lock_path))
    engine = SDXLEngine(model_root=tmp_path, model_lock=lock_path)
    assert engine.ready and engine.pipeline.device == "cuda"
    assert engine.pipeline.vae.slicing and engine.pipeline.vae.tiling
    assert engine.pipeline.vae.force_upcast is True
    assert engine.pipeline.vae.tile_sample_min_size == 512 and engine.pipeline.vae.tile_latent_min_size == 64
    assert engine.pipeline.scheduler.config["algorithm_type"] == "dpmsolver++"
    assert engine.pipeline.scheduler.config["use_karras_sigmas"] is True
    assert engine.pipeline.scheduler.config["solver_order"] == 2
    assert engine.pipeline.scheduler.config["thresholding"] is False
    assert not hasattr(engine.pipeline, "enable_vae_slicing")


def test_prompt_preflight_checks_both_tokenizers_and_negative_before_gpu():
    class Tokenizer:
        model_max_length = 77

        def __init__(self, extra=0):
            self.extra = extra

        def encode(self, text, *, add_special_tokens, truncation):
            assert add_special_tokens is True and truncation is False
            return [0] * (len(text.split()) + 2 + self.extra)

    pipeline = SimpleNamespace(tokenizer=Tokenizer(), tokenizer_2=Tokenizer(extra=1))
    request = ImageRequest.model_validate(payload())
    request.prompt = "word " * 74  # 76 and 77 tokens including special tokens: valid.
    validate_prompt_tokens(pipeline, request)
    request.prompt = "word " * 75  # Second tokenizer exceeds the limit, first does not.
    with pytest.raises(PromptTooLongError):
        validate_prompt_tokens(pipeline, request)
    request.prompt = "short"
    request.negative_prompt = "word " * 76
    engine = SDXLEngine.__new__(SDXLEngine)
    engine.pipeline = pipeline
    # No Torch attribute exists: preflight must reject before touching CUDA or decoding refs.
    with pytest.raises(PromptTooLongError):
        engine.generate(request)


def test_prompt_length_failure_has_specific_safe_diagnostic(tmp_path):
    class LongPromptEngine(InjectedEngine):
        def generate(self, _request):
            raise PromptTooLongError("must not echo caller text")

    client, app, _ = client_for(tmp_path, LongPromptEngine())
    job_id = client.post("/v1/images/jobs", json=payload()).json()["job_id"]
    app.state.executor.shutdown(wait=True)
    job = client.get(f"/v1/images/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["error"]["code"] == "prompt_too_long"
    assert "must not echo" not in json.dumps(job)


def test_notebook_run_all_skips_smoke_and_repeated_cells_keep_processes(capsys):
    notebook_path = Path(__file__).parents[1] / "serve_image_api.ipynb"
    cells = {cell["id"]: "".join(cell["source"]) for cell in json.loads(notebook_path.read_text())["cells"]
             if cell["cell_type"] == "code"}
    for source in cells.values():
        ast.parse(source)

    class RunningProcess:
        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("Run All must preserve the running worker")

    class NoUpload:
        def upload(self):
            raise AssertionError("Default Run All must not request smoke inputs")

    process = RunningProcess()
    namespace = {"worker": process, "tunnel": process, "files": NoUpload()}
    # Missing subprocess/getpass/download dependencies make any unexpected startup fail too.
    exec(compile(cells["image-worker-5"], "worker-start-cell", "exec"), namespace)
    exec(compile(cells["image-worker-tunnel"], "tunnel-start-cell", "exec"), namespace)
    exec(compile(cells["image-worker-8"], "optional-smoke-cell", "exec"), namespace)
    assert namespace["worker"] is process and namespace["tunnel"] is process
    assert namespace["RUN_SMOKE"] is False
    output = capsys.readouterr().out
    assert "Worker already running" in output and "Tunnel already running" in output
    assert "smoke skipped" in output


@pytest.mark.parametrize("mode,subject,references,valid", [
    ("text", "human", [], True), ("text", "pet", [], False),
    ("reference", "human", [], False), ("unknown", "human", [], False),
])
def test_generation_mode_validation(tmp_path, mode, subject, references, valid):
    client, app, _ = client_for(tmp_path)
    request = payload()
    request.update(generation_mode=mode, subject_type=subject, references=references)
    assert client.post("/v1/images/jobs", json=request).status_code == (202 if valid else 422)
    app.state.executor.shutdown(wait=True)


def test_text_mode_rejects_reference_images(tmp_path):
    client, app, _ = client_for(tmp_path)
    request = payload()
    request.update(generation_mode="text", subject_type="human")
    assert client.post("/v1/images/jobs", json=request).status_code == 422
    app.state.executor.shutdown()


def test_engine_alternates_text_and_reference_without_stale_adapter(tmp_path, monkeypatch):
    encoder, processor = object(), object()

    class Pipeline:
        adapter_active = True
        image_encoder = encoder
        feature_extractor = processor
        tokenizer = SimpleNamespace(model_max_length=77, encode=lambda *_args, **_kwargs: [1, 2])
        tokenizer_2 = tokenizer
        scheduler = SimpleNamespace(config={"algorithm_type": "dpmsolver++"})

        def __init__(self):
            self.events = []

        def unload_ip_adapter(self):
            self.events.append("unload")
            self.adapter_active = False
            self.image_encoder = self.feature_extractor = None

        def register_modules(self, *, image_encoder, feature_extractor):
            assert image_encoder is encoder and feature_extractor is processor
            self.events.append("register")
            self.image_encoder, self.feature_extractor = image_encoder, feature_extractor

        def load_ip_adapter(self, *_args, **kwargs):
            assert self.image_encoder is encoder and self.feature_extractor is processor
            assert kwargs["local_files_only"] is True and kwargs["weight_name"].endswith(".safetensors")
            self.events.append("load")
            self.adapter_active = True

        def set_ip_adapter_scale(self, _value):
            assert self.adapter_active

        def __call__(self, **kwargs):
            has_image = "ip_adapter_image" in kwargs
            assert has_image == self.adapter_active
            self.events.append("reference" if has_image else "text")
            return SimpleNamespace(images=[Image.new("RGB", (kwargs["width"], kwargs["height"]))])

    pipeline = Pipeline()
    engine = SDXLEngine.__new__(SDXLEngine)
    engine.pipeline = pipeline
    engine._image_encoder, engine._feature_extractor = encoder, processor
    engine._adapter_path, engine._adapter_active = tmp_path, True
    engine.model_revision = REVISIONS[BASE_REPO]
    engine.lock = {ADAPTER_REPO: {"revision": REVISIONS[ADAPTER_REPO]}}
    engine.runtime = {}
    engine.torch = SimpleNamespace(
        cuda=SimpleNamespace(synchronize=lambda: None, reset_peak_memory_stats=lambda: None,
                             memory_allocated=lambda: 0, memory_reserved=lambda: 0,
                             max_memory_allocated=lambda: 0, max_memory_reserved=lambda: 0,
                             get_device_name=lambda *_: "testGPU"),
        Generator=lambda **_: SimpleNamespace(manual_seed=lambda seed: seed), inference_mode=nullcontext,
    )
    monkeypatch.setattr("colab.image_worker.engine.importlib.metadata.version", lambda _name: "test-only")
    reference = ImageRequest.model_validate(payload())
    text = ImageRequest.model_validate({**payload(), "generation_mode": "text", "subject_type": "human", "references": []})
    for request in (text, text, reference, reference, text, reference):
        _image, metadata = engine.generate(request)
        active = request.generation_mode == "reference"
        assert metadata["adapter_active"] is active
        assert metadata["generation_mode"] == request.generation_mode
        assert metadata["reference_count"] == len(request.references)
        assert ("adapter_model" in metadata) is active
        if not active:
            assert metadata["reference_strength"] == 0.0 and metadata["engine"] == "diffusers-sdxl-text2image"
    assert pipeline.events == ["unload", "text", "text", "register", "load", "reference", "reference",
                               "unload", "text", "register", "load", "reference"]
