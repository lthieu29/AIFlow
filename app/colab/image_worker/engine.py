"""Official Diffusers pipeline, safetensors only, offline after verified downloads."""

from __future__ import annotations

import importlib.metadata
import json
import os
import time
from pathlib import Path

from PIL import Image, ImageOps

from .app import decode_reference
from .models import ADAPTER_REPO, BASE_REPO, verify_models

os.environ.update(DIFFUSERS_DISABLE_REMOTE_CODE="1", HF_HUB_DISABLE_TELEMETRY="1",
                  DO_NOT_TRACK="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")


class PromptTooLongError(ValueError):
    """The complete prompt must fit both SDXL CLIP context windows."""


def validate_prompt_tokens(pipeline, request):
    for tokenizer in (pipeline.tokenizer, pipeline.tokenizer_2):
        limit = min(int(tokenizer.model_max_length), 77)
        for text in (request.prompt, request.negative_prompt):
            if len(tokenizer.encode(text, add_special_tokens=True, truncation=False)) > limit:
                raise PromptTooLongError("Prompt or negative prompt exceeds the SDXL token limit")


def memory_diagnostic(torch, *, stage: str, pipeline=None):
    """Flush only hardware/model facts; never request text, references or credentials."""
    value = {"stage": stage, "gpu_allocated_bytes": torch.cuda.memory_allocated(),
             "gpu_reserved_bytes": torch.cuda.memory_reserved()}
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                name, size, _unit = line.split()
                value[name.rstrip(":") + "_bytes"] = int(size) * 1024
    if pipeline is not None:
        value["components"] = {}
        for name in ("unet", "vae", "text_encoder", "text_encoder_2", "image_encoder"):
            module = getattr(pipeline, name, None)
            if module is not None and hasattr(module, "parameters"):
                parameters = list(module.parameters())
                value["components"][name] = {
                    "dtypes": sorted({str(parameter.dtype) for parameter in parameters}),
                    "devices": sorted({str(parameter.device) for parameter in parameters}),
                    "parameter_bytes": sum(parameter.numel() * parameter.element_size() for parameter in parameters),
                }
    print("Image worker diagnostic " + json.dumps(value, separators=(",", ":")), flush=True)
    return value


def prepare_reference(image: Image.Image, size: int = 224) -> Image.Image:
    """Letterbox the whole subject so CLIP's center crop cannot cut off ears/head."""
    return ImageOps.pad(image.convert("RGB"), (size, size), method=Image.Resampling.LANCZOS,
                        color=(255, 255, 255), centering=(0.5, 0.5))


class SDXLEngine:
    ready = False

    def __init__(self, *, model_root: Path, model_lock: Path):
        import torch
        from diffusers import DPMSolverMultistepScheduler, StableDiffusionXLPipeline
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

        from .bootstrap import verify_runtime

        if not torch.cuda.is_available():
            raise RuntimeError("A CUDA GPU runtime is required; CPU generation is disabled")
        self.torch = torch
        self.runtime = verify_runtime()
        memory_diagnostic(torch, stage="before_model_load")
        self.lock = verify_models(model_root, model_lock)
        self.model_revision = self.lock[BASE_REPO]["revision"]
        base = model_root / BASE_REPO.replace("/", "--")
        adapter = model_root / ADAPTER_REPO.replace("/", "--")
        encoder = CLIPVisionModelWithProjection.from_pretrained(
            str(adapter / "models/image_encoder"), dtype=torch.float16,
            local_files_only=True, use_safetensors=True, trust_remote_code=False,
        )
        self._image_encoder = encoder
        self._feature_extractor = CLIPImageProcessor()
        self._adapter_path = adapter
        self.pipeline = StableDiffusionXLPipeline.from_pretrained(
            str(base), image_encoder=encoder, feature_extractor=self._feature_extractor,
            dtype=torch.float16, variant="fp16", use_safetensors=True, local_files_only=True,
        )
        self.pipeline.scheduler = DPMSolverMultistepScheduler.from_config(
            self.pipeline.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True,
            solver_order=2, thresholding=False,
        )
        self.pipeline.load_ip_adapter(
            str(adapter), subfolder="sdxl_models", weight_name="ip-adapter-plus_sdxl_vit-h.safetensors",
            image_encoder_folder=None, local_files_only=True,
        )
        self._adapter_active = True
        memory_diagnostic(torch, stage="models_loaded", pipeline=self.pipeline)
        # Keep weights on the T4 to avoid returning the 5 GB UNet to a 13 GB host at decode.
        # SDXL's default 1024 tile threshold does not tile a 1024 output; use 512 instead.
        self.pipeline.vae.register_to_config(force_upcast=True)
        self.pipeline.vae.tile_sample_min_size = 512
        self.pipeline.vae.tile_latent_min_size = 512 // self.pipeline.vae_scale_factor
        self.pipeline.vae.enable_slicing()
        self.pipeline.vae.enable_tiling()
        self.pipeline.to("cuda")
        self.pipeline.set_progress_bar_config(disable=True)
        memory_diagnostic(torch, stage="worker_ready", pipeline=self.pipeline)
        self.ready = True

    def _select_generation_mode(self, mode: str):
        if mode == "text" and self._adapter_active:
            # 0.40 also clears encoder/processor registrations; retain audited objects for reference jobs.
            self.pipeline.unload_ip_adapter()
            self._adapter_active = False
        elif mode == "reference" and not self._adapter_active:
            self.pipeline.register_modules(image_encoder=self._image_encoder, feature_extractor=self._feature_extractor)
            self.pipeline.load_ip_adapter(
                str(self._adapter_path), subfolder="sdxl_models",
                weight_name="ip-adapter-plus_sdxl_vit-h.safetensors",
                image_encoder_folder=None, local_files_only=True,
            )
            self._adapter_active = True

    def generate(self, request):
        validate_prompt_tokens(self.pipeline, request)
        self._select_generation_mode(request.generation_mode)
        self.torch.cuda.synchronize()
        self.torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        conditioning = {}
        if request.generation_mode == "reference":
            images = [prepare_reference(decode_reference(reference)) for reference in request.references]
            self.pipeline.set_ip_adapter_scale(request.reference_strength)
            conditioning["ip_adapter_image"] = [images]
        generator = self.torch.Generator(device="cpu").manual_seed(request.seed)
        memory_diagnostic(self.torch, stage="generation_start", pipeline=self.pipeline)

        def denoise_progress(_pipeline, step_index, _timestep, callback_kwargs):
            if step_index == request.steps - 1:
                memory_diagnostic(self.torch, stage="denoise_finished", pipeline=self.pipeline)
            return callback_kwargs

        with self.torch.inference_mode():
            output = self.pipeline(
                prompt=request.prompt, negative_prompt=request.negative_prompt,
                width=request.width, height=request.height, num_inference_steps=request.steps,
                guidance_scale=request.guidance_scale, generator=generator,
                num_images_per_prompt=1, **conditioning,
                callback_on_step_end=denoise_progress,
            ).images[0]
        self.torch.cuda.synchronize()
        duration = time.monotonic() - started
        scheduler_config = self.pipeline.scheduler.config
        memory_diagnostic(self.torch, stage="generation_finished", pipeline=self.pipeline)
        metadata = {
            "engine": "diffusers-sdxl-text2image" if request.generation_mode == "text" else "diffusers-sdxl-ip-adapter-plus",
            "generation_mode": request.generation_mode, "reference_count": len(request.references),
            "adapter_active": self._adapter_active, "base_model": BASE_REPO,
            "model_revision": self.model_revision,
            "seed": request.seed, "steps": request.steps, "guidance_scale": request.guidance_scale,
            "reference_strength": request.reference_strength if self._adapter_active else 0.0,
            "reference_sha256": [r.sha256 for r in request.references],
            "subject_type": request.subject_type,
            "reference_preprocessing": "RGB-white-letterbox-224" if self._adapter_active else "none",
            "width": request.width, "height": request.height, "prompt": request.prompt,
            "negative_prompt": request.negative_prompt, "duration_seconds": round(duration, 3),
            "scheduler": type(self.pipeline.scheduler).__name__,
            "scheduler_config": {key: scheduler_config[key] for key in
                                 ("algorithm_type", "use_karras_sigmas", "solver_order", "prediction_type",
                                  "timestep_spacing", "beta_schedule", "num_train_timesteps", "thresholding")
                                 if key in scheduler_config},
            "peak_vram_allocated_bytes": self.torch.cuda.max_memory_allocated(),
            "peak_vram_reserved_bytes": self.torch.cuda.max_memory_reserved(),
            "device": self.torch.cuda.get_device_name(0), "precision": "float16", "cpu_offload": False,
            "memory_profile": "t4-gpu-resident-vae512", "vae_precision": "float32_decode",
            "vae_tile_size": 512,
            "versions": {name: importlib.metadata.version(name) for name in
                         ("torch", "diffusers", "transformers", "accelerate", "safetensors", "Pillow")},
            "runtime_review": self.runtime,
        }
        if self._adapter_active:
            metadata.update(adapter_model=ADAPTER_REPO, adapter_revision=self.lock[ADAPTER_REPO]["revision"],
                            adapter_file="sdxl_models/ip-adapter-plus_sdxl_vit-h.safetensors")
        return output, metadata
