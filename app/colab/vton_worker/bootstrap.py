"""Install only VTON requirements reviewed against their exact byte hash."""

import sys
import hashlib
import json
from pathlib import Path

from ..image_worker.bootstrap import install_reviewed_packages
from .bundle import SOURCE_FILES


def verify_review(directory: Path):
    approval = json.loads((directory / "audit-approval.json").read_text(encoding="utf-8"))
    if approval.get("approved") is not True:
        raise RuntimeError("VTON review is not approved")
    for name, key in (("requirements-lock.txt", "requirements_sha256"),
                      ("model-lock.json", "model_lock_sha256"), ("source-lock.json", "source_lock_sha256")):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != approval.get(key):
            raise RuntimeError("VTON review bytes do not match approval")
    source = json.loads((directory / "source-lock.json").read_text(encoding="utf-8"))
    if set(source["files"]) != set(SOURCE_FILES):
        raise RuntimeError("VTON source inventory must cover every reviewed executable and notice")
    root = directory.parent.parent
    for name, checksum in source["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError("VTON source differs from reviewed source inventory")


if __name__ == "__main__":
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("VTON package installation requires an isolated venv")
    if Path(sys.executable).absolute().parent.parent.resolve() != Path(sys.prefix).resolve():
        raise RuntimeError("Python executable is outside the selected worker venv")
    directory = Path(__file__).resolve().parent
    verify_review(directory)
    install_reviewed_packages(directory, Path(sys.executable))
