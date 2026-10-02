"""Layer 1 — Style Lock.

Ensures every Veo3 prompt is prepended with a consistent visual style prefix,
so all clips in a project share the same art style, lighting, and color palette.

Usage::

    lock = StyleLock.load(style_json_str)
    final_prompt = lock.inject(scene_visual_prompt)
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, model_validator


class StyleData(BaseModel):
    """Parsed representation of a style.json blob.

    Fields map to the style.json schema defined in docs/06-continuity-spec.md.
    If ``prefix_text`` is provided it is used verbatim; otherwise the prefix is
    built from the individual fields.
    """

    # Core style fields
    camera: str = ""          # e.g. "locked-off static frame"
    lighting: str = ""        # e.g. "soft even key light"
    color_palette: str = ""   # e.g. "muted earth tones with cream highlights"
    visual_style: str = ""    # e.g. "editorial fashion photography"

    # Optional fields from the full style.json schema
    lens: str = ""            # e.g. "85mm portrait, shallow depth of field"
    post_processing: str = "" # e.g. "slight film grain, warm tone curve"
    negative_prompt: str = "" # e.g. "no anime, no cartoon"

    # If set, overrides the auto-generated prefix entirely
    prefix_text: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _map_style_json_fields(cls, values: dict) -> dict:
        """Map style.json field names to StyleData field names.

        The style.json schema uses ``art_style``, ``camera_style``, etc.
        We normalise them here so callers can pass the raw JSON dict directly.
        """
        if isinstance(values, dict):
            # art_style → visual_style
            if "art_style" in values and not values.get("visual_style"):
                values["visual_style"] = values["art_style"]
            # camera_style → camera
            if "camera_style" in values and not values.get("camera"):
                values["camera"] = values["camera_style"]
        return values

    def build_prefix(self) -> str:
        """Build the style prefix text from individual fields.

        Returns a multi-sentence description suitable for prepending to a
        Veo3 prompt.  Empty fields are skipped.
        """
        parts: list[str] = []

        if self.visual_style:
            parts.append(self.visual_style.capitalize() + ".")
        if self.lighting:
            parts.append(self.lighting.capitalize() + ".")
        if self.lens:
            parts.append(self.lens.capitalize() + ".")
        if self.camera:
            parts.append(self.camera.capitalize() + ".")
        if self.post_processing:
            parts.append(self.post_processing.capitalize() + ".")
        if self.color_palette:
            parts.append(self.color_palette.capitalize() + ".")

        prefix = " ".join(parts)

        if self.negative_prompt:
            prefix += f"\n\nAvoid: {self.negative_prompt}."

        return prefix.strip()


class StyleLock:
    """Layer 1 continuity — locks visual style across all Veo3 prompts.

    Typical usage::

        lock = StyleLock.load(style_json_str)
        final_prompt = lock.inject(scene_prompt)
    """

    def __init__(self, style_data: StyleData) -> None:
        self._data = style_data
        # Cache the resolved prefix so we don't rebuild it on every inject()
        self._prefix: str = (
            style_data.prefix_text
            if style_data.prefix_text
            else style_data.build_prefix()
        )

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, style_json: str) -> "StyleLock":
        """Parse a style.json string (from DB or skill file) and return a StyleLock.

        Args:
            style_json: JSON string conforming to the style.json schema
                        (see docs/06-continuity-spec.md).

        Returns:
            A ready-to-use StyleLock instance.

        Raises:
            ValueError: If ``style_json`` is not valid JSON.
        """
        raw: dict = json.loads(style_json)
        style_data = StyleData.model_validate(raw)
        return cls(style_data)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def prefix(self) -> str:
        """The resolved style prefix text (read-only)."""
        return self._prefix

    @property
    def data(self) -> StyleData:
        """The underlying StyleData model (read-only)."""
        return self._data

    def inject(self, prompt: str) -> str:
        """Prepend the style prefix to a Veo3 prompt.

        Args:
            prompt: The raw scene visual prompt.

        Returns:
            ``"{style_prefix}\\n\\n{prompt}"`` — the style prefix is always
            prepended, even if ``prompt`` is empty.
        """
        if not self._prefix:
            return prompt
        return f"{self._prefix}\n\n{prompt}"
