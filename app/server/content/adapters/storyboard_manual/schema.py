"""JSON schema and Pydantic models for the storyboard_manual adapter.

A storyboard is a manually authored list of scenes, each with a Veo3 prompt,
optional narration, duration, and optional start image for scene chaining.

Example JSON input::

    {
        "title": "My Product Video",
        "voice": "vi-VN-HoaiMyNeural",
        "scenes": [
            {
                "order": 0,
                "prompt": "Close-up of a coffee cup on a wooden table, steam rising.",
                "duration": 8.0,
                "narration": "Bắt đầu ngày mới với ly cà phê thơm ngon.",
                "location_hint": "indoor_cafe"
            },
            {
                "order": 1,
                "prompt": "Person smiling while drinking coffee, warm morning light.",
                "duration": 8.0,
                "narration": "Hương vị đậm đà, khó quên."
            }
        ]
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── Pydantic models ──────────────────────────────────────────────────────────


class StoryboardScene(BaseModel):
    """A single scene in a manually authored storyboard.

    Attributes:
        order:          0-based position in the scene list (required).
        prompt:         Veo3 generation prompt (required, non-empty).
        duration:       Desired clip duration in seconds (default 8.0).
        narration:      Optional TTS narration text for this scene.
        location_hint:  Optional location category for continuity chain reset
                        detection.  Should use canonical ``LocationCategory``
                        values from the content adapter spec.
        start_image:    Optional path to a start-frame image for scene chaining
                        (Layer 3 continuity).  If provided, the path must exist
                        on disk.
    """

    order: int
    prompt: str
    duration: float = 8.0
    narration: Optional[str] = None
    location_hint: Optional[str] = None
    start_image: Optional[str] = None  # stored as string path; validated below

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("prompt must not be blank")
        return v

    @field_validator("duration")
    @classmethod
    def duration_in_range(cls, v: float) -> float:
        if not (3.0 <= v <= 30.0):
            raise ValueError(f"duration must be in [3, 30], got {v}")
        return v

    @field_validator("start_image")
    @classmethod
    def start_image_path_must_exist(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            p = Path(v)
            if not p.exists():
                raise ValueError(f"start_image path does not exist: {v!r}")
        return v


class Storyboard(BaseModel):
    """A complete manually authored storyboard.

    Attributes:
        title:  Optional title for the project (default empty string).
        voice:  Optional TTS voice preference (e.g. ``"vi-VN-HoaiMyNeural"``).
        scenes: Ordered list of scenes (at least 1 required).
    """

    title: str = ""
    voice: Optional[str] = None
    scenes: list[StoryboardScene] = Field(..., min_length=1)

    @model_validator(mode="after")
    def scenes_order_must_be_contiguous(self) -> "Storyboard":
        """Validate that scene orders are contiguous starting from 0."""
        for expected, scene in enumerate(self.scenes):
            if scene.order != expected:
                raise ValueError(
                    f"scenes[{expected}].order is {scene.order}, expected {expected}. "
                    "Scene orders must be contiguous starting from 0."
                )
        return self


# ─── Validation helper ────────────────────────────────────────────────────────


def validate_storyboard(data: dict) -> tuple[bool, list[str]]:
    """Validate a storyboard dict against the :class:`Storyboard` schema.

    Args:
        data: A dict (typically parsed from JSON) to validate.

    Returns:
        A ``(ok, errors)`` tuple.  ``ok`` is ``True`` when ``errors`` is empty.
        ``errors`` is a list of human-readable error strings.
    """
    try:
        Storyboard.model_validate(data)
        return True, []
    except Exception as exc:  # noqa: BLE001
        # Pydantic v2 raises ValidationError; collect all messages
        errors: list[str] = []
        if hasattr(exc, "errors"):
            for err in exc.errors():
                loc = " → ".join(str(p) for p in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"{loc}: {msg}" if loc else msg)
        else:
            errors.append(str(exc))
        return False, errors


# ─── JSON Schema (for documentation / OpenAPI) ───────────────────────────────

STORYBOARD_JSON_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Storyboard",
    "description": (
        "Manually authored storyboard for the storyboard_manual content adapter. "
        "Each scene maps directly to one Veo3 clip."
    ),
    "type": "object",
    "required": ["scenes"],
    "properties": {
        "title": {
            "type": "string",
            "description": "Optional project title.",
            "default": "",
        },
        "voice": {
            "type": ["string", "null"],
            "description": (
                "TTS voice preference, e.g. 'vi-VN-HoaiMyNeural'. "
                "Passed through to the SceneList."
            ),
        },
        "scenes": {
            "type": "array",
            "description": "Ordered list of scenes (at least 1 required).",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["order", "prompt"],
                "properties": {
                    "order": {
                        "type": "integer",
                        "description": "0-based scene index. Must be contiguous from 0.",
                        "minimum": 0,
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Veo3 generation prompt for this scene.",
                        "minLength": 1,
                    },
                    "duration": {
                        "type": "number",
                        "description": "Clip duration in seconds.",
                        "minimum": 3.0,
                        "maximum": 30.0,
                        "default": 8.0,
                    },
                    "narration": {
                        "type": ["string", "null"],
                        "description": "TTS narration text for this scene.",
                    },
                    "location_hint": {
                        "type": ["string", "null"],
                        "description": (
                            "Location category for continuity chain reset detection. "
                            "Use canonical LocationCategory values from the adapter spec."
                        ),
                    },
                    "start_image": {
                        "type": ["string", "null"],
                        "description": (
                            "Absolute or relative path to a start-frame image for "
                            "scene chaining (Layer 3 continuity). Path must exist on disk."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}
