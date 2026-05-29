"""StoryboardManualAdapter — converts a manually authored JSON storyboard into a SceneList.

Input (``AdapterInput.raw_content``): JSON string matching the :class:`Storyboard` schema.

Example input::

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
            }
        ]
    }

Output: :class:`~server.content.base.SceneList` with one :class:`~server.content.base.SceneSpec`
per storyboard scene.

The adapter performs strict validation — every field is checked before any
scene is built.  If ``input.skill_name`` is set, the skill prefix is applied
to every scene prompt via
:func:`~server.content.skill_loader.apply_skill_to_scene`.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from server.content.base import (
    AdapterError,
    AdapterInput,
    ContentAdapter,
    SceneList,
    SceneSpec,
)
from server.content.adapters.storyboard_manual.schema import (
    Storyboard,
    validate_storyboard,
)

logger = logging.getLogger(__name__)


# ─── StoryboardManualAdapter ─────────────────────────────────────────────────


class StoryboardManualAdapter:
    """ContentAdapter for manually authored storyboard JSON inputs.

    Converts a JSON storyboard (list of scenes with prompts, durations, and
    optional narration) directly into a :class:`~server.content.base.SceneList`
    without any LLM calls.

    Attributes:
        adapter_type: Registry key — ``"storyboard_manual"``.
    """

    adapter_type: str = "storyboard_manual"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse a JSON storyboard and return a :class:`~server.content.base.SceneList`.

        Args:
            input: Adapter input with JSON ``raw_content`` matching the
                   :class:`~server.content.adapters.storyboard_manual.schema.Storyboard`
                   schema.

        Returns:
            A :class:`~server.content.base.SceneList` with one scene per
            storyboard entry.

        Raises:
            :class:`~server.content.base.AdapterError`: On parse or
                validation failure.
        """
        # 1. Validate input
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid storyboard_manual input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        # 2. Parse JSON → Storyboard model
        storyboard = self._parse_storyboard(input.raw_content)

        # 3. Build SceneSpec list
        scenes = self._build_scenes(storyboard)

        # 4. Apply skill if requested
        if input.skill_name:
            scenes = self._apply_skill(scenes, input.skill_name)

        # 5. Determine voice: storyboard field → options override → storyboard default
        voice = input.options.get("voice") or storyboard.voice

        # 6. Assemble SceneList
        project_id = input.options.get("project_id", "storyboard_manual")
        scene_list = SceneList(
            project_id=project_id,
            scenes=scenes,
            voice=voice,
            metadata={
                "adapter": self.adapter_type,
                "title": storyboard.title,
                "scene_count": len(scenes),
                "skill_name": input.skill_name,
            },
        )

        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )

        logger.debug(
            "StoryboardManualAdapter: generated %d scenes for %r",
            len(scenes),
            storyboard.title or "(untitled)",
        )
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Validate the adapter input without calling any external APIs.

        Checks:
        - ``raw_content`` is non-empty.
        - ``raw_content`` is valid JSON.
        - JSON matches the :class:`~server.content.adapters.storyboard_manual.schema.Storyboard`
          schema (at least 1 scene, contiguous orders, valid durations, etc.).
        - ``start_image`` paths exist on disk (if provided).

        Args:
            input: The adapter input to validate.

        Returns:
            A list of human-readable error strings.  Empty list = valid.
        """
        errors: list[str] = []

        if not input.raw_content or not input.raw_content.strip():
            errors.append("raw_content must not be empty")
            return errors

        try:
            data = json.loads(input.raw_content)
        except json.JSONDecodeError as exc:
            errors.append(f"raw_content is not valid JSON: {exc}")
            return errors

        if not isinstance(data, dict):
            errors.append("raw_content must be a JSON object")
            return errors

        ok, schema_errors = validate_storyboard(data)
        if not ok:
            errors.extend(schema_errors)

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_storyboard(self, raw_content: str) -> Storyboard:
        """Parse raw JSON content into a validated :class:`Storyboard` model."""
        data = json.loads(raw_content)
        return Storyboard.model_validate(data)

    def _build_scenes(self, storyboard: Storyboard) -> list[SceneSpec]:
        """Convert :class:`Storyboard` scenes into :class:`SceneSpec` objects."""
        scenes: list[SceneSpec] = []
        for sb_scene in storyboard.scenes:
            start_image: Optional[Path] = None
            if sb_scene.start_image is not None:
                start_image = Path(sb_scene.start_image)

            scene = SceneSpec(
                order=sb_scene.order,
                prompt=sb_scene.prompt,
                duration=sb_scene.duration,
                start_image=start_image,
                location_hint=sb_scene.location_hint,
                narration=sb_scene.narration,
            )
            scenes.append(scene)
        return scenes

    def _apply_skill(
        self,
        scenes: list[SceneSpec],
        skill_name: str,
    ) -> list[SceneSpec]:
        """Apply a skill's prefix to all scenes.

        Loads the skill from the ``skills/`` directory relative to the
        project root.  If the skill cannot be loaded (e.g. directory not
        found), logs a warning and returns the scenes unchanged.

        Args:
            scenes:     List of scenes to apply the skill to.
            skill_name: Name of the skill directory (e.g. ``"ecommerce-fashion"``).

        Returns:
            List of scenes with skill prefix applied (new SceneSpec objects).
        """
        try:
            from server.content.skill_loader import SkillLoader, apply_skill_to_scene

            # Resolve skills directory relative to this file's package root
            # server/content/adapters/storyboard_manual/adapter.py
            # → go up 4 levels to reach app/, then skills/
            adapter_dir = Path(__file__).resolve().parent
            app_dir = adapter_dir.parents[3]  # app/
            skills_dir = app_dir / "skills"

            loader = SkillLoader(skills_dir)
            skill = loader.load(skill_name)
            return [apply_skill_to_scene(scene, skill) for scene in scenes]

        except FileNotFoundError:
            logger.warning(
                "StoryboardManualAdapter: skill %r not found — skipping skill application",
                skill_name,
            )
            return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "StoryboardManualAdapter: failed to apply skill %r: %s — skipping",
                skill_name,
                exc,
            )
            return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: StoryboardManualAdapter = StoryboardManualAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = StoryboardManualAdapter
