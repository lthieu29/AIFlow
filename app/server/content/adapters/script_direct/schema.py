"""Pydantic input schema for the ``script_direct`` adapter.

Defines the authoritative contract for ``script_direct`` JSON input
(Requirements 1.15–1.19):

- Top-level object with a required ``scenes`` array (≥ 1 element).
- Each scene requires ``narration`` and ``visual_prompt`` (non-blank strings).
- Optional ``duration_sec`` (float) and ``asset_ids`` (list).
- Extra fields are silently ignored (``extra="ignore"``), not rejected.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ScriptDirectScene(BaseModel):
    """Schema for a single scene in a ``script_direct`` input payload.

    Attributes:
        narration:      TTS narration text for the scene (required, non-blank).
        visual_prompt:  Veo3 generation prompt for the scene (required, non-blank).
        duration_sec:   Optional desired clip duration in seconds.
        asset_ids:      Optional list of asset identifiers to attach to the scene.

    Extra fields beyond these four are silently ignored (R1.19).
    """

    model_config = {"extra": "ignore"}  # R1.19 — ignore unknown fields

    narration: str
    visual_prompt: str
    duration_sec: float | None = None   # R1.17 — number if present
    asset_ids: list | None = None       # R1.18 — array if present

    @field_validator("narration", "visual_prompt")
    @classmethod
    def not_blank(cls, v: str) -> str:
        """Reject empty or whitespace-only strings (R1.16)."""
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty, non-blank string")
        return v


class ScriptDirectInput(BaseModel):
    """Schema for the top-level ``script_direct`` input object.

    Attributes:
        scenes: Non-empty list of scene objects (R1.15).

    Extra fields at the top level are silently ignored (R1.19).
    """

    model_config = {"extra": "ignore"}  # R1.19 — ignore unknown top-level fields

    scenes: list[ScriptDirectScene] = Field(..., min_length=1)  # R1.15 — ≥ 1 scene
