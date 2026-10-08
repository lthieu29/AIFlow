"""Deterministic reviewed download pair shared by the backend and local packaging."""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import Path

BUNDLE_FILES = ("__init__.py", "__main__.py", "app.py", "audit-approval.json", "bootstrap.py",
                "engine.py", "model-lock.json", "models.py", "README.md", "requirements-lock.txt")
_NOTEBOOK_HASH = re.compile(
    r"(hashlib\.sha256\(Path\('aiflow-image-worker\.zip'\)\.read_bytes\(\)\)\.hexdigest\(\) != ')[0-9a-f]{64}(')"
)


def bundle_bytes(package_root: Path) -> bytes:
    root = Path(package_root)
    contents = {}
    for filename in sorted(BUNDLE_FILES):
        path = root / filename
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError(f"Missing or oversized worker bundle member: {filename}")
        contents[filename] = path.read_bytes()
    if sum(map(len, contents.values())) > 3_000_000:
        raise ValueError("Worker bundle exceeds reviewed size limit")
    approval = json.loads(contents["audit-approval.json"])
    if (approval.get("approved") is not True or
            approval.get("requirements_sha256") != hashlib.sha256(contents["requirements-lock.txt"]).hexdigest()):
        raise ValueError("Worker requirements do not match approved audit bytes")
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for filename, raw in contents.items():
            entry = zipfile.ZipInfo(f"image_worker/{filename}", date_time=(1980, 1, 1, 0, 0, 0))
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
        source = "".join(cell["source"])
        source, count = _NOTEBOOK_HASH.subn(lambda match: match[1] + bundle_sha256 + match[2], source)
        replacements += count
        cell["source"] = source.splitlines(keepends=True)
        cell["outputs"] = []
        cell["execution_count"] = None
    if replacements != 1:
        raise ValueError("Notebook must contain exactly one reviewed worker-bundle SHA256 check")
    return (json.dumps(notebook, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_artifacts(colab_root: Path) -> str:
    root = Path(colab_root)
    bundle = bundle_bytes(root / "image_worker")
    checksum = hashlib.sha256(bundle).hexdigest()
    notebook = notebook_bytes(root / "serve_image_api.ipynb", checksum)
    for path, raw in ((root / "aiflow-image-worker.zip", bundle), (root / "serve_image_api.ipynb", notebook)):
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(raw)
        temporary.replace(path)
    return checksum


if __name__ == "__main__":
    print(write_artifacts(Path(__file__).resolve().parent.parent))
