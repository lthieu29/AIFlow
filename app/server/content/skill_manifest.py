"""Skill manifest schema and loader.

Skills are pure data — YAML/JSON/Markdown files in a folder.  No Python code.
This module defines the Pydantic model for ``manifest.yaml`` and a helper
function to load it from a skill directory.

Skill directory layout::

    skills/{skill_id}/
    ├── manifest.yaml          ← loaded by load_skill_manifest()
    ├── style.json             ← Layer 1 continuity (art style, lighting, …)
    ├── prefix.md              ← Text prepended to every shot prompt
    ├── character.md           ← Character template (Toonflow format)
    ├── scene.md               ← Scene template
    └── motion.md              ← Motion vocabulary

A skill may ``extends: _base`` to inherit shared rules from
``skills/_base/``.  The loader does NOT perform inheritance merging — that
is the responsibility of the higher-level ``SkillLoader`` class (Phase 4.0).

Example manifest.yaml::

    name: ecommerce-fashion
    version: 1.0.0
    adapter_type: ecommerce_product
    style_ref: style.json
    voice: vi-VN-HoaiMyNeural
    camera_lock: true
    safety_level: standard
    options:
      default_aspect_ratio: "9:16"
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    """Pydantic model for a skill's ``manifest.yaml``.

    Attributes:
        name:          Unique skill identifier (e.g. ``"ecommerce-fashion"``).
        version:       Semantic version string (e.g. ``"1.0.0"``).
        adapter_type:  The adapter this skill is designed for
                       (e.g. ``"ecommerce_product"``).
        style_ref:     Relative path to the ``style.json`` file inside the
                       skill directory.  ``None`` means no style file.
        voice:         TTS voice preference
                       (e.g. ``"vi-VN-HoaiMyNeural"``).  ``None`` means use
                       the system default.
        camera_lock:   When ``True`` (default), all scenes use a static camera
                       unless the adapter explicitly overrides it.
        safety_level:  Content safety level applied to prompts.
                       ``"strict"`` adds extra negative prompts;
                       ``"relaxed"`` removes some restrictions.
        options:       Free-form dict for adapter-specific defaults
                       (e.g. ``{"default_aspect_ratio": "9:16"}``).
    """

    name: str
    version: str
    adapter_type: str
    style_ref: Optional[str] = None
    voice: Optional[str] = None
    camera_lock: bool = True
    safety_level: Literal["strict", "standard", "relaxed"] = "standard"
    options: dict = Field(default_factory=dict)

    model_config = {"extra": "allow"}  # tolerate unknown keys in manifest.yaml


# ─── Loader ───────────────────────────────────────────────────────────────────


def load_skill_manifest(skill_dir: Path) -> SkillManifest:
    """Load and validate ``manifest.yaml`` from *skill_dir*.

    Args:
        skill_dir: Path to the skill directory (e.g.
                   ``Path("skills/ecommerce-fashion")``).

    Returns:
        A validated :class:`SkillManifest` instance.

    Raises:
        FileNotFoundError: If ``manifest.yaml`` does not exist in *skill_dir*.
        ValueError: If the YAML is malformed or fails Pydantic validation.
    """
    manifest_path = skill_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Skill manifest not found: {manifest_path}. "
            f"Expected a 'manifest.yaml' file in {skill_dir}."
        )

    raw = manifest_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse {manifest_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"manifest.yaml in {skill_dir} must be a YAML mapping, got {type(data).__name__}"
        )

    return SkillManifest.model_validate(data)
