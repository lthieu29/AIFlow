"""Dedicated FASHN engine; this module never imports or constructs SDXL."""

import importlib.metadata
import json
import time
from pathlib import Path

from ..image_worker.app import decode_reference
from ..image_worker.bootstrap import verify_runtime
from .models import POSE_REPO, VTON_REPO, verify_models

SOURCE_REVISION = "7c0f10af3f91ad4048fe9729c470a13ef905d25a"


def memory_diagnostic(torch, *, stage):
    print("VTON worker diagnostic " + json.dumps({"stage": stage,
          "gpu_allocated_bytes": torch.cuda.memory_allocated(),
          "gpu_reserved_bytes": torch.cuda.memory_reserved()}), flush=True)


class VtonEngine:
    ready = False
    capabilities = ["image", "virtual_try_on"]

    def __init__(self, *, model_root: Path, model_lock: Path):
        from .bootstrap import verify_review
        verify_review(Path(__file__).resolve().parent)
        import torch
        from .pipeline import MasklessFlatLayPipeline

        self.torch = torch
        self.runtime = verify_runtime()
        self.lock = verify_models(model_root, model_lock)
        self.model_revision = self.lock[VTON_REPO]["revision"]
        memory_diagnostic(torch, stage="vton_before_load")
        self.pipeline = MasklessFlatLayPipeline(
            model_path=model_root / VTON_REPO.replace("/", "--") / "model.safetensors",
            pose_directory=model_root / POSE_REPO.replace("/", "--"),
        )
        memory_diagnostic(torch, stage="vton_ready")
        self.ready = True

    def generate(self, request):
        if request.generation_mode != "vton" or request.garment_photo_type != "flat-lay":
            raise ValueError("This worker supports parser-free flat-lay virtual try-on only")
        person, garment = [decode_reference(reference) for reference in request.references]
        self.torch.cuda.synchronize()
        self.torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        output = self.pipeline(person_image=person, garment_image=garment, category=request.garment_category,
                               steps=request.steps, guidance_scale=request.guidance_scale, seed=request.seed)
        self.torch.cuda.synchronize()
        memory_diagnostic(self.torch, stage="vton_finished")
        hashes = [reference.sha256 for reference in request.references]
        metadata = {
            "engine": "fashn-vton-1.5-maskless-flat-lay", "generation_mode": "vton",
            "reference_count": 2, "adapter_active": False, "subject_type": "human",
            "input_roles": ["person", "garment"], "input_sha256": hashes, "reference_sha256": hashes,
            "garment_category": request.garment_category, "garment_photo_type": request.garment_photo_type,
            "base_model": VTON_REPO, "model_revision": self.model_revision,
            "pose_model": POSE_REPO, "pose_revision": self.lock[POSE_REPO]["revision"],
            "source_revision": SOURCE_REVISION, "human_parser": "excluded", "segmentation_free": True,
            "seed": request.seed, "steps": request.steps, "guidance_scale": request.guidance_scale,
            "width": output.width, "height": output.height, "native_width": 576, "native_height": 864,
            "output_resampling": "none-full-native-canvas", "input_preprocessing": "upstream-aspect-fit-zero-pad",
            "text_conditioning": False, "prompt": request.prompt, "negative_prompt": request.negative_prompt,
            "ignored_parameters": ["prompt", "negative_prompt", "reference_strength"],
            "reference_strength": 0.0, "pose_execution_provider": "CPUExecutionProvider",
            "precision": str(self.pipeline.inference_dtype).removeprefix("torch."),
            "duration_seconds": round(time.monotonic() - started, 3),
            "device": self.torch.cuda.get_device_name(0),
            "peak_vram_allocated_bytes": self.torch.cuda.max_memory_allocated(),
            "peak_vram_reserved_bytes": self.torch.cuda.max_memory_reserved(),
            "scheduler": "EulerRectifiedFlow", "time_shift_mu": 1.5, "skip_cfg_last_n_steps": 1,
            "runtime_review": self.runtime,
            "versions": {name: importlib.metadata.version(name) for name in
                         ("torch", "torchvision", "safetensors", "Pillow", "einops", "onnxruntime", "opencv-python-headless")},
        }
        return output, metadata
