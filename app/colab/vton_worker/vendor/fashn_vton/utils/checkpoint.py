"""AIFlow modification: local safetensors only; no pickle or remote download."""
from pathlib import Path
from safetensors.torch import load_file


def load_checkpoint(checkpoint_path: str, device: str = "cpu") -> dict:
    path = Path(checkpoint_path)
    if path.suffix != ".safetensors" or not path.is_file():
        raise ValueError("Only verified local safetensors checkpoints are supported")
    return load_file(str(path), device=device)
