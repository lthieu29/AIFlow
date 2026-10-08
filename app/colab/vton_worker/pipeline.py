"""Parser-free equivalent of upstream segmentation_free + flat-lay inference.

Derived from FASHN Apache-2.0 pipeline at revision
7c0f10af3f91ad4048fe9729c470a13ef905d25a. Both disabled-mask helpers return
their input unchanged; segmentation labels/predictions are therefore unnecessary.
The full native canvas is retained instead of upstream unpadding.
"""

import numpy as np
import torch

from .vendor.fashn_vton.dwpose import DWposeDetector, draw_pose
from .vendor.fashn_vton.preprocessing import AspectPreserveResize, ResizePad
from .vendor.fashn_vton.tryon_mmdit import TryOnModel
from .vendor.fashn_vton.utils import (
    get_dummy_dw_keypoints,
    get_rf_schedule,
    load_checkpoint,
    normalize_uint8_to_neg1_1,
    numpy_to_torch,
    tensor_to_pil,
)

CATEGORY_TO_LABEL = {"tops": 1, "bottoms": 2, "one-pieces": 3}


class MasklessFlatLayPipeline:
    def __init__(self, *, model_path, pose_directory):
        self.device = torch.device("cuda")
        # Match official precision policy, including fp32 on T4; no untested fp16 cast.
        self.inference_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float32
        self.tryon_model = TryOnModel()
        state_dict = load_checkpoint(str(model_path), device="cpu")
        self.tryon_model.load_state_dict(state_dict, strict=True)
        del state_dict
        self.tryon_model.to(self.device, dtype=self.inference_dtype).eval()
        self.pose_model = DWposeDetector(checkpoints_dir=str(pose_directory), device="cpu")
        h, w = self.tryon_model.input_shape
        self.pre_resize = AspectPreserveResize(target_size=(max(h, w), max(h, w)), mode="fit", backend="pil")
        self.resize_pad = ResizePad((w, h), backend="opencv")

    @torch.inference_mode()
    def __call__(self, *, person_image, garment_image, category, steps, guidance_scale, seed):
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        np.random.seed(seed)
        person = np.array(self.pre_resize(person_image, allow_upsampling=False))
        garment = np.array(self.pre_resize(garment_image, allow_upsampling=False))
        person_pose = draw_pose(self.pose_model(person[..., ::-1]), *person.shape[:2], grayscale=True)
        garment_pose = draw_pose(get_dummy_dw_keypoints(), *garment.shape[:2], grayscale=True)

        def prepare(image, *, pose=False):
            if pose:
                import cv2
                image = self.resize_pad(image, interpolation=cv2.INTER_NEAREST_EXACT)
            else:
                image = self.resize_pad(image)
            tensor = numpy_to_torch(image)
            if tensor.ndim == 2:
                tensor = tensor.unsqueeze(0)  # Grayscale pose must retain its single channel.
            return normalize_uint8_to_neg1_1(tensor.unsqueeze(0)).to(
                device=self.device, dtype=self.inference_dtype)

        model_kwargs = {
            "ca_images": prepare(person), "garment_images": prepare(garment),
            "person_poses": prepare(person_pose, pose=True), "garment_poses": prepare(garment_pose, pose=True),
            "garment_categories": torch.tensor([CATEGORY_TO_LABEL[category]], device=self.device),
        }
        c, h, w = self.tryon_model.channels_in, *self.tryon_model.input_shape
        images = torch.randn((1, c, h, w), dtype=self.inference_dtype, device=self.device)
        timesteps = get_rf_schedule(num_steps=steps, mu=1.5)
        for step, (current, following) in enumerate(zip(timesteps[:-1], timesteps[1:])):
            t = torch.full((1,), current, dtype=self.inference_dtype, device=self.device)
            prediction = self.tryon_model.forward_for_cfg(images, t, **model_kwargs)
            conditional, unconditional = prediction["v_c"], prediction["v_u"]
            guided = conditional if step == steps - 1 else unconditional + guidance_scale * (conditional - unconditional)
            images = images + (following - current) * guided
        return tensor_to_pil(images[0].to(dtype=torch.float).clamp_(-1.0, 1.0), unnormalize=True)
