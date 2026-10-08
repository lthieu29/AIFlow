"""VTON contract is independent of legacy SDXL defaults and immutable digests."""

from typing import Literal

from pydantic import Field, model_validator

from ..image_worker.app import ImageRequest, Reference


class VtonReference(Reference):
    role: Literal["person", "garment"]


class VtonRequest(ImageRequest):
    generation_mode: Literal["vton"]
    subject_type: Literal["human"]
    prompt: str = Field(default="", max_length=2000)
    width: Literal[576] = 576
    height: Literal[864] = 864
    guidance_scale: float = Field(default=1.5, ge=1.0, le=12.0, allow_inf_nan=False)
    references: list[VtonReference] = Field(min_length=2, max_length=2)
    garment_category: Literal["tops", "bottoms", "one-pieces"]
    garment_photo_type: Literal["flat-lay"]

    @model_validator(mode="after")
    def validate_shape(self):
        if [reference.role for reference in self.references] != ["person", "garment"]:
            raise ValueError("VTON requires ordered person then garment references")
        return self
