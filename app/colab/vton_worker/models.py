"""Only reviewed immutable safetensors/ONNX bytes, verified before runtime load."""

import json
import re
from pathlib import Path, PurePosixPath

from ..image_worker.models import verify_file

VTON_REPO = "fashn-ai/fashn-vton-1.5"
POSE_REPO = "fashn-ai/DWPose"
EXPECTED_FILES = {VTON_REPO: {"model.safetensors"}, POSE_REPO: {"yolox_l.onnx", "dw-ll_ucoco_384.onnx"}}
REVISIONS = {VTON_REPO: "7720683168567eb5a2a4c67f15116c6e29c83ded",
             POSE_REPO: "548b5df25b84d9f4aac0611dfa1c2a7a12f15571"}
REVIEWED_BYTES = {
    "model.safetensors": (1943668048, "d6cd38286885bc29fa487ea9383f80ffeb95862e7747c630d42c5d3c05bdd35a"),
    "yolox_l.onnx": (216746733, "7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411"),
    "dw-ll_ucoco_384.onnx": (134399116, "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843"),
}


def read_lock(path: Path):
    lock = json.loads(path.read_text(encoding="utf-8"))
    if set(lock) != set(EXPECTED_FILES):
        raise ValueError("VTON lock contains unreviewed repositories")
    for repository, expected in EXPECTED_FILES.items():
        model = lock[repository]
        if model["revision"] != REVISIONS[repository]:
            raise ValueError("VTON lock requires immutable model revisions")
        files = model["files"]
        if len(files) != len(expected) or {entry["path"] for entry in files} != expected:
            raise ValueError("VTON lock contains unreviewed model files")
        for entry in files:
            relative = PurePosixPath(entry["path"])
            if relative.is_absolute() or ".." in relative.parts or "\\" in entry["path"]:
                raise ValueError("Unsafe VTON model path")
            if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or type(entry["size"]) is not int or entry["size"] < 1:
                raise ValueError("Invalid VTON model size/hash")
            if (entry["size"], entry["sha256"]) != REVIEWED_BYTES[entry["path"]]:
                raise ValueError("VTON model bytes differ from reviewed inventory")
    return lock


def verify_models(root: Path, lock_path: Path):
    lock = read_lock(lock_path)
    for repository, model in lock.items():
        for entry in model["files"]:
            verify_file(root / repository.replace("/", "--") / entry["path"], entry)
    return lock


def download_models(root: Path, lock_path: Path):
    from huggingface_hub import hf_hub_download

    lock = read_lock(lock_path)
    for repository, model in lock.items():
        destination = root / repository.replace("/", "--")
        for entry in model["files"]:
            path = hf_hub_download(repo_id=repository, filename=entry["path"], revision=model["revision"],
                                   local_dir=str(destination), token=False)
            verify_file(Path(path), entry)
    return lock
