"""Download only audited, immutable model files; verify bytes before model load."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

BASE_REPO = "SG161222/RealVisXL_V5.0"
ADAPTER_REPO = "h94/IP-Adapter"
REVISIONS = {BASE_REPO: "ac93e0dda1f6d448cae19bbfab8c5e720a5e48bc",
             ADAPTER_REPO: "018e402774aeeddd60609b4ecdb7e298259dc729"}


def read_lock(lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if set(lock) != set(REVISIONS):
        raise ValueError("Model lock has unreviewed repositories")
    for repo, revision in REVISIONS.items():
        if lock[repo]["revision"] != revision:
            raise ValueError("Model lock has unreviewed revisions")
        for entry in lock[repo]["files"]:
            relative = PurePosixPath(entry["path"])
            if relative.is_absolute() or ".." in relative.parts or "\\" in entry["path"]:
                raise ValueError("Unsafe model path")
            if relative.suffix not in (".json", ".txt", ".safetensors"):
                raise ValueError("Model lock contains executable or unsafe serialization")
            if len(entry["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in entry["sha256"]):
                raise ValueError("Invalid model file hash")
    return lock


def verify_file(path: Path, entry: dict):
    if not path.is_file() or path.stat().st_size != entry["size"]:
        raise ValueError(f"Missing or incorrect model file: {entry['path']}")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != entry["sha256"]:
        raise ValueError(f"Model hash mismatch: {entry['path']}")


def verify_models(root: Path, lock_path: Path) -> dict:
    lock = read_lock(lock_path)
    for repo, model in lock.items():
        for entry in model["files"]:
            verify_file(root / repo.replace("/", "--") / entry["path"], entry)
    return lock


def download_models(root: Path, lock_path: Path):
    from huggingface_hub import hf_hub_download

    lock = read_lock(lock_path)
    for repo, model in lock.items():
        destination = root / repo.replace("/", "--")
        for entry in model["files"]:
            path = hf_hub_download(repo_id=repo, filename=entry["path"], revision=model["revision"],
                                   local_dir=str(destination), token=False)
            verify_file(Path(path), entry)
    return lock
