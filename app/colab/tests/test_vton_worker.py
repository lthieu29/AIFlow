"""Dedicated VTON API/security tests; no dependency install, model download or CUDA claim."""

import ast
import base64
import hashlib
import io
import json
import importlib.util
import sys
import uuid
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from colab.image_worker.app import ImageRequest, create_app, digest
from colab.vton_worker.bootstrap import verify_review
from colab.vton_worker.bundle import BUNDLE_FILES, SOURCE_FILES, bundle_bytes, notebook_bytes
from colab.vton_worker.models import POSE_REPO, VTON_REPO, read_lock
from colab.vton_worker.schema import VtonRequest

COLAB_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "test-vton-token-" + "x" * 32


def reference(role, color):
    buffer = io.BytesIO()
    Image.new("RGB", (48, 64), color).save(buffer, format="PNG")
    raw = buffer.getvalue()
    return {"role": role, "mime": "image/png", "data": base64.b64encode(raw).decode(),
            "sha256": hashlib.sha256(raw).hexdigest()}


def payload():
    return {"request_id": str(uuid.uuid4()), "generation_mode": "vton", "subject_type": "human",
            "prompt": "", "negative_prompt": "", "width": 576, "height": 864,
            "seed": 10, "steps": 30, "guidance_scale": 1.5, "reference_strength": 0.45,
            "garment_category": "tops", "garment_photo_type": "flat-lay",
            "references": [reference("person", "navy"), reference("garment", "orange")]}


class InjectedVtonEngine:
    ready = True
    model_revision = "test-only-revision"
    capabilities = ["image", "virtual_try_on"]

    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return Image.new("RGB", (576, 864), "navy"), {
            "generation_mode": "vton", "input_roles": [r.role for r in request.references],
            "input_sha256": [r.sha256 for r in request.references], "reference_count": 2,
            "adapter_active": False, "garment_category": request.garment_category,
            "garment_photo_type": request.garment_photo_type,
        }


def test_vton_schema_has_independent_native_size_and_guidance_defaults():
    value = payload()
    for key in ("width", "height", "guidance_scale", "prompt"):
        del value[key]
    request = VtonRequest.model_validate(value)
    assert (request.width, request.height, request.guidance_scale, request.prompt) == (576, 864, 1.5, "")
    value = payload()
    assert VtonRequest.model_validate(value).model_dump(mode="json") == value


@pytest.mark.parametrize("change", [
    {"generation_mode": "reference"}, {"subject_type": "pet"}, {"width": 1024}, {"height": 1024},
    {"garment_photo_type": "model"}, {"garment_category": "dress"}, {"garment_category": None},
    {"steps": 9}, {"guidance_scale": float("inf")}, {"extra": "forbidden"},
])
def test_vton_rejects_unsupported_or_noncommercial_paths(change):
    value = payload()
    value.update(change)
    with pytest.raises(ValidationError):
        VtonRequest.model_validate(value)


@pytest.mark.parametrize("mutation", ["reverse", "same-role", "missing-role", "missing-image", "third-image", "bad-hash"])
def test_vton_rejects_ambiguous_or_corrupt_input(mutation):
    value = payload()
    if mutation == "reverse":
        value["references"].reverse()
    elif mutation == "same-role":
        value["references"][1]["role"] = "person"
    elif mutation == "missing-role":
        del value["references"][0]["role"]
    elif mutation == "missing-image":
        value["references"].pop()
    elif mutation == "third-image":
        value["references"].append(reference("garment", "white"))
    else:
        value["references"][0]["sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        VtonRequest.model_validate(value)


def test_vton_does_not_change_legacy_schema_or_digest():
    value = payload()
    value.update(generation_mode="reference", subject_type="pet", prompt="pet portrait", width=1024, height=1024)
    del value["garment_category"], value["garment_photo_type"]
    for image in value["references"]:
        del image["role"]
    request = ImageRequest.model_validate(value)
    assert request.model_dump(mode="json") == value
    assert digest(request.model_dump(mode="json")) == digest(value)
    with pytest.raises(ValidationError):
        ImageRequest.model_validate(payload())


def test_authenticated_vton_health_jobs_idempotency_and_result_receipt(tmp_path):
    engine = InjectedVtonEngine()
    app = create_app(token=TOKEN, root=tmp_path, engine=engine, request_model=VtonRequest)
    client = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    assert client.get("/v1/health", headers={"Authorization": "wrong"}).status_code == 401
    assert client.get("/v1/health").json()["capabilities"] == ["image", "virtual_try_on"]
    value = payload()
    response = client.post("/v1/images/jobs", json=value)
    assert response.status_code == 202
    assert response.json()["input_sha256"] == digest(value)
    app.state.executor.shutdown(wait=True)
    result = client.get("/v1/images/jobs/" + value["request_id"]).json()
    assert result["status"] == "succeeded"
    assert (result["result"]["width"], result["result"]["height"]) == (576, 864)
    metadata = result["result"]["metadata"]
    assert metadata["input_roles"] == ["person", "garment"]
    assert metadata["input_sha256"] == [r["sha256"] for r in value["references"]]
    assert client.post("/v1/images/jobs", json=value).status_code == 202
    value["garment_category"] = "bottoms"
    assert client.post("/v1/images/jobs", json=value).status_code == 409
    assert engine.calls == 1
    value["garment_photo_type"] = "model"
    rejected = client.post("/v1/images/jobs", json=value)
    assert rejected.status_code == 422 and value["references"][0]["data"] not in rejected.text


def test_reviewed_model_inventory_is_three_local_safe_files():
    lock = read_lock(COLAB_ROOT / "vton_worker/model-lock.json")
    assert len(lock[VTON_REPO]["files"]) == 1 and len(lock[POSE_REPO]["files"]) == 2
    assert sum(entry["size"] for model in lock.values() for entry in model["files"]) == 2_294_813_897


@pytest.mark.parametrize("mutation", ["unreviewed-repo", "unpinned", "pickle", "duplicate", "bad-hash"])
def test_model_lock_fails_closed(tmp_path, mutation):
    lock = read_lock(COLAB_ROOT / "vton_worker/model-lock.json")
    if mutation == "unreviewed-repo":
        lock["unreviewed/model"] = lock.pop(VTON_REPO)
    elif mutation == "unpinned":
        lock[VTON_REPO]["revision"] = "main"
    elif mutation == "pickle":
        lock[VTON_REPO]["files"][0]["path"] = "model.pth"
    elif mutation == "duplicate":
        lock[POSE_REPO]["files"][1] = lock[POSE_REPO]["files"][0]
    else:
        lock[VTON_REPO]["files"][0]["sha256"] = "garbage"
    path = tmp_path / "model-lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(ValueError):
        read_lock(path)


def test_vendored_source_has_no_parser_pickle_dynamic_execution_or_download():
    for path in (COLAB_ROOT / "vton_worker/vendor").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id in ("eval", "exec") for node in ast.walk(tree))
        for forbidden in ("fashn_human_parser", "torch.load(", "hf_hub_download", "subprocess",
                          "torch.compile", "torch.jit", "matplotlib"):
            # License/change comments can mention an excluded dependency, imports/calls cannot.
            assert forbidden not in source.replace("no matplotlib", ""), (path, forbidden)
    entrypoint = (COLAB_ROOT / "vton_worker/__main__.py").read_text(encoding="utf-8")
    assert "SDXLEngine" not in entrypoint
    assert "SDXLEngine" not in (COLAB_ROOT / "vton_worker/engine.py").read_text(encoding="utf-8")


def test_vton_notebook_code_compiles_and_keeps_token_hidden():
    notebook = json.loads((COLAB_ROOT / "serve_vton_api.ipynb").read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            source = "".join(cell["source"])
            ast.parse(source)
            assert cell["outputs"] == [] and cell["execution_count"] is None
            assert "print(session_token" not in source
    content = json.dumps(notebook)
    assert "colab.vton_worker" in content and "RUN_SMOKE = False" in content
    assert "WORKER_KIND" in content and "virtual_try_on" in content


def test_maskless_pipeline_model_inputs_and_final_step_cfg(monkeypatch):
    """Exercise real orchestration against a shape-checking model, without importing CUDA dependencies."""
    class Array:
        def __init__(self, shape):
            self.shape = shape

        def __getitem__(self, _slice):
            return self

    class Tensor:
        def __init__(self, shape, value=0):
            self.shape, self.value = shape, value
            self.ndim = len(shape)

        def unsqueeze(self, dim):
            return Tensor(self.shape[:dim] + (1,) + self.shape[dim:], self.value)

        def to(self, **_kwargs):
            return self

        def __getitem__(self, _index):
            return Tensor(self.shape[1:], self.value)

        def __add__(self, other):
            return Tensor(self.shape, self.value + other.value)

        def __sub__(self, other):
            return Tensor(self.shape, self.value - other.value)

        def __mul__(self, scalar):
            return Tensor(self.shape, self.value * scalar)

        __rmul__ = __mul__

        def clamp_(self, minimum, maximum):
            return Tensor(self.shape, min(maximum, max(minimum, self.value)))

    def module(name, **values):
        result = ModuleType(name)
        result.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    module("torch", inference_mode=lambda: lambda fn: fn, manual_seed=lambda _seed: None,
           cuda=SimpleNamespace(manual_seed_all=lambda _seed: None), float="float32",
           tensor=lambda values, **_kwargs: Tensor((len(values),)),
           randn=lambda shape, **_kwargs: Tensor(shape), full=lambda shape, value, **_kwargs: Tensor(shape, value))
    module("numpy", array=lambda image: Array((image.height, image.width, 3)),
           random=SimpleNamespace(seed=lambda _seed: None))
    module("cv2", INTER_NEAREST_EXACT=6)
    prefix = "colab.vton_worker.vendor.fashn_vton"
    module(prefix + ".dwpose", DWposeDetector=object,
           draw_pose=lambda _pose, height, width, **_kwargs: Array((height, width)))
    module(prefix + ".preprocessing", AspectPreserveResize=object, ResizePad=object)
    module(prefix + ".tryon_mmdit", TryOnModel=object)
    module(prefix + ".utils", get_dummy_dw_keypoints=lambda: {}, get_rf_schedule=lambda **_kwargs: [0, 0.5, 1],
           load_checkpoint=lambda *_args, **_kwargs: {}, normalize_uint8_to_neg1_1=lambda tensor: tensor,
           numpy_to_torch=lambda image: Tensor((image.shape[2], *image.shape[:2]) if len(image.shape) == 3 else image.shape),
           tensor_to_pil=lambda image, **_kwargs: image)
    name = "colab.vton_worker.pipeline_contract_test"
    spec = importlib.util.spec_from_file_location(name, COLAB_ROOT / "vton_worker/pipeline.py")
    pipeline_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipeline_module)
    calls = []

    def forward(images, timestep, **kwargs):
        assert images.shape == (1, 3, 864, 576)
        assert kwargs["ca_images"].shape == kwargs["garment_images"].shape == (1, 3, 864, 576)
        assert kwargs["person_poses"].shape == kwargs["garment_poses"].shape == (1, 1, 864, 576)
        assert kwargs["garment_categories"].shape == (1,)
        calls.append(timestep.value)
        return {"v_c": Tensor(images.shape, 0.2), "v_u": Tensor(images.shape, 0.0)}

    pipeline = pipeline_module.MasklessFlatLayPipeline.__new__(pipeline_module.MasklessFlatLayPipeline)
    pipeline.device, pipeline.inference_dtype = "cuda", "float32"
    pipeline.pre_resize = lambda image, **_kwargs: image
    pipeline.resize_pad = lambda image, **_kwargs: Array((864, 576, 3) if len(image.shape) == 3 else (864, 576))
    pipeline.pose_model = lambda _image: {}
    pipeline.tryon_model = SimpleNamespace(channels_in=3, input_shape=(864, 576), forward_for_cfg=forward)
    output = pipeline(person_image=Image.new("RGB", (400, 600)), garment_image=Image.new("RGB", (500, 500)),
                      category="tops", steps=2, guidance_scale=1.5, seed=42)
    assert output.shape == (3, 864, 576) and abs(output.value - 0.25) < 1e-9
    assert calls == [0, 0.5]


def test_reviewed_vton_bundle_and_runtime_source_integrity():
    verify_review(COLAB_ROOT / "vton_worker")
    raw = bundle_bytes(COLAB_ROOT)
    assert raw == bundle_bytes(COLAB_ROOT)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == set(BUNDLE_FILES)
        assert all("agnostic" not in name and "parser" not in name for name in archive.namelist())
        assert "colab/image_worker/engine.py" not in archive.namelist()
    prepared = notebook_bytes(COLAB_ROOT / "serve_vton_api.ipynb", hashlib.sha256(raw).hexdigest())
    assert hashlib.sha256(raw).hexdigest().encode() in prepared


def test_review_cannot_drop_executable_source_coverage(tmp_path):
    directory = tmp_path / "colab/vton_worker"
    directory.mkdir(parents=True)
    source = {"files": {name: "0" * 64 for name in SOURCE_FILES if not name.endswith("bundle.py")}}
    source_raw = json.dumps(source).encode()
    (directory / "source-lock.json").write_bytes(source_raw)
    (directory / "model-lock.json").write_bytes(b"{}")
    (directory / "requirements-lock.txt").write_bytes(b"reviewed")
    approval = {"approved": True, "requirements_sha256": hashlib.sha256(b"reviewed").hexdigest(),
                "model_lock_sha256": hashlib.sha256(b"{}").hexdigest(),
                "source_lock_sha256": hashlib.sha256(source_raw).hexdigest()}
    (directory / "audit-approval.json").write_text(json.dumps(approval))
    with pytest.raises(RuntimeError, match="every reviewed executable"):
        verify_review(directory)
