"""Deterministic reviewed VTON bundle; no SDXL engine or parser source included."""

import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import Path

SHARED_FILES = ("__init__.py", "app.py", "bootstrap.py", "models.py")
WORKER_FILES = (
    "__init__.py", "__main__.py", "bootstrap.py", "bundle.py", "engine.py", "models.py", "pipeline.py", "schema.py",
    "README.md", "model-lock.json", "requirements-lock.txt", "audit-approval.json", "source-lock.json",
    "vendor/__init__.py", "vendor/fashn_vton/__init__.py", "vendor/fashn_vton/LICENSE", "vendor/fashn_vton/NOTICE",
    "vendor/fashn_vton/tryon_mmdit.py", "vendor/fashn_vton/preprocessing/__init__.py",
    "vendor/fashn_vton/preprocessing/transforms.py",
    "vendor/fashn_vton/dwpose/__init__.py", "vendor/fashn_vton/dwpose/dwpose.py",
    "vendor/fashn_vton/dwpose/onnxdet.py", "vendor/fashn_vton/dwpose/onnxpose.py",
    "vendor/fashn_vton/dwpose/utils.py", "vendor/fashn_vton/dwpose/wholebody.py",
    "vendor/fashn_vton/utils/__init__.py", "vendor/fashn_vton/utils/checkpoint.py",
    "vendor/fashn_vton/utils/common.py", "vendor/fashn_vton/utils/keypoints.py",
    "vendor/fashn_vton/utils/logger.py", "vendor/fashn_vton/utils/sampling.py", "vendor/fashn_vton/utils/tensor.py",
)
BUNDLE_FILES = tuple("colab/image_worker/" + name for name in SHARED_FILES) + tuple(
    "colab/vton_worker/" + name for name in WORKER_FILES)
SOURCE_FILES = tuple(name for name in BUNDLE_FILES if name.endswith((".py", "README.md", "/LICENSE", "/NOTICE")))
_NOTEBOOK_HASH = re.compile(r"(hashlib\.sha256\(Path\('aiflow-vton-worker\.zip'\)\.read_bytes\(\)\)\.hexdigest\(\) != ')[0-9a-f]{64}(')")


def bundle_bytes(colab_root: Path) -> bytes:
    root = Path(colab_root).parent
    contents = {}
    for name in sorted(BUNDLE_FILES):
        path = root / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError(f"Missing or oversized VTON bundle member: {name}")
        contents[name] = path.read_bytes()
    if sum(map(len, contents.values())) > 3_000_000:
        raise ValueError("VTON worker bundle exceeds reviewed size limit")
    prefix = "colab/vton_worker/"
    approval = json.loads(contents[prefix + "audit-approval.json"])
    if (approval.get("approved") is not True or
            approval.get("requirements_sha256") != hashlib.sha256(contents[prefix + "requirements-lock.txt"]).hexdigest()):
        raise ValueError("VTON requirements do not match approved audit bytes")
    if approval.get("model_lock_sha256") != hashlib.sha256(contents[prefix + "model-lock.json"]).hexdigest():
        raise ValueError("VTON models do not match reviewed lock bytes")
    source = json.loads(contents[prefix + "source-lock.json"])
    if set(source["files"]) != set(SOURCE_FILES):
        raise ValueError("VTON source inventory must cover every reviewed executable and notice")
    for name, checksum in source["files"].items():
        if name not in contents or hashlib.sha256(contents[name]).hexdigest() != checksum:
            raise ValueError("VTON source differs from reviewed source inventory")
    if approval.get("source_lock_sha256") != hashlib.sha256(contents[prefix + "source-lock.json"]).hexdigest():
        raise ValueError("VTON source inventory does not match approval")
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in contents.items():
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, raw, compresslevel=9)
    return result.getvalue()


def notebook_bytes(notebook_path: Path, bundle_sha256: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", bundle_sha256):
        raise ValueError("Invalid bundle SHA256")
    notebook = json.loads(Path(notebook_path).read_text(encoding="utf-8"))
    replacements = 0
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        source, count = _NOTEBOOK_HASH.subn(lambda match: match[1] + bundle_sha256 + match[2], "".join(cell["source"]))
        replacements += count
        cell["source"] = source.splitlines(keepends=True)
        cell["outputs"] = []
        cell["execution_count"] = None
    if replacements != 1:
        raise ValueError("Notebook must contain exactly one VTON bundle SHA256 check")
    return (json.dumps(notebook, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_artifacts(colab_root: Path) -> str:
    root = Path(colab_root)
    raw = bundle_bytes(root)
    checksum = hashlib.sha256(raw).hexdigest()
    notebook = notebook_bytes(root / "serve_vton_api.ipynb", checksum)
    for path, content in ((root / "aiflow-vton-worker.zip", raw), (root / "serve_vton_api.ipynb", notebook)):
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(content)
        temporary.replace(path)
    return checksum


if __name__ == "__main__":
    print(write_artifacts(Path(__file__).resolve().parent.parent))
