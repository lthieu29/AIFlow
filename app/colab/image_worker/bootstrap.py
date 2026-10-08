"""Fail-closed bootstrap; installs only hashed wheels covered by review approval."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.update(DIFFUSERS_DISABLE_REMOTE_CODE="1", HF_HUB_DISABLE_TELEMETRY="1",
                  DO_NOT_TRACK="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")


def verify_runtime():
    import torch

    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("This reviewed worker requires Python 3.12")
    if torch.__version__ != "2.11.0+cu128" or importlib.metadata.version("torchvision") != "0.26.0+cu128":
        raise RuntimeError("Runtime Torch/TorchVision differs from the reviewed Colab exception")
    if not torch.cuda.is_available():
        raise RuntimeError("Select a CUDA GPU runtime")
    return {"python": sys.version.split()[0], "torch": torch.__version__,
            "torchvision": importlib.metadata.version("torchvision"),
            "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
            "torch_advisory_exception": "GHSA-rrmf-rvhw-rf47; no torch.jit/compile, pickle or remote code"}


def install_reviewed_packages(directory: Path, python: Path):
    requirements = directory / "requirements-lock.txt"
    approval = json.loads((directory / "audit-approval.json").read_text(encoding="utf-8"))
    checksum = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if approval.get("approved") is not True or approval.get("requirements_sha256") != checksum:
        raise RuntimeError("Package audit is absent or requirements do not match approved bytes")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--index-url",
                    "https://pypi.org/simple", "--only-binary=:all:", "--ignore-installed", "--no-deps",
                    "--require-hashes", "-r", str(requirements)], check=True)


if __name__ == "__main__":
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Package installation requires the isolated worker venv; global installation is disabled")
    if Path(sys.executable).absolute().parent.parent.resolve() != Path(sys.prefix).resolve():
        raise RuntimeError("Python executable is outside the selected worker venv")
    directory = Path(__file__).resolve().parent
    install_reviewed_packages(directory, Path(sys.executable))
