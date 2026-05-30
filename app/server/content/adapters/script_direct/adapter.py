"""ScriptDirectAdapter — pass-through adapter for pre-composed JSON scene lists.

Input (``AdapterInput.raw_content``): JSON string with the authoritative contract:

    {
        "scenes": [
            {
                "narration": "...",        # required, non-blank string
                "visual_prompt": "...",    # required, non-blank string
                "duration_sec": 8.0,       # optional float (default 8.0)
                "asset_ids": ["..."]       # optional list
            },
            ...
        ]
    }

Extra fields at any level are silently ignored (R1.19).

Processing order in ``adapt()`` (Requirements 1.6, 1.10):
    1. ``validate_input()`` — cheap structural check, no external API calls.
    2. Parse JSON → raise ``ADAPTER_INVALID_INPUT`` on parse error (R1.7).
    3. Check ``scenes`` present and non-empty → ``ADAPTER_INVALID_INPUT`` (R1.8).
    4. Check each scene for required fields (narration, visual_prompt) with index
       in ``details`` → ``ADAPTER_INVALID_INPUT`` (R1.9).
    5. Validate ALL durations BEFORE assigning order (R1.10):
       - Default 8.0 when ``duration_sec`` is absent (R1.5).
       - Raise ``ADAPTER_INVALID_INPUT`` immediately if any duration ∉ [3, 30].
    6. Assign contiguous ``order`` starting from 0 (R1.6).
    7. Build ``SceneSpec`` objects.
    8. Apply skill prefix via ``apply_skill_to_scene`` if ``skill_name`` set (R1.14).
    9. ``SceneList.validate()`` → ``ADAPTER_INVALID_OUTPUT`` on failure (R1.13).
    10. ``enforce_pipeline_limits()`` → ``ADAPTER_INVALID_OUTPUT`` if limits exceeded.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from server.content.base import (
    AdapterError,
    AdapterInput,
    SceneList,
    SceneSpec,
)
from server.content.adapters.script_direct.schema import (
    ScriptDirectInput,
    ScriptDirectScene,
)
from server.content.pipeline_limits import enforce_pipeline_limits

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION: float = 8.0   # R1.5 / R6.4 — Veo3_Clip_Duration
_MIN_DURATION: float = 3.0       # SceneList.validate() lower bound
_MAX_DURATION: float = 30.0      # SceneList.validate() upper bound


# ─── ScriptDirectAdapter ─────────────────────────────────────────────────────


class ScriptDirectAdapter:
    """ContentAdapter for pre-composed JSON scene lists (pass-through).

    Accepts a JSON payload with a ``scenes`` array and maps each element
    directly to a :class:`~server.content.base.SceneSpec` without calling
    any LLM or external API.

    Attributes:
        adapter_type: Registry key — ``"script_direct"``.
    """

    adapter_type: str = "script_direct"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse a JSON scene list and return a validated :class:`SceneList`.

        Processing order strictly follows Requirements 1.6 and 1.10:
        all durations are validated BEFORE any ``order`` is assigned.

        Args:
            input: Adapter input whose ``raw_content`` is a JSON string
                   conforming to the ``script_direct`` contract.

        Returns:
            A :class:`~server.content.base.SceneList` with one scene per
            input scene element.

        Raises:
            :class:`~server.content.base.AdapterError`:
                - ``ADAPTER_INVALID_INPUT`` on parse/validation failure.
                - ``ADAPTER_INVALID_OUTPUT`` if the generated SceneList fails
                  structural validation or pipeline limits.
        """
        # Step 1 — cheap pre-flight (no external calls)
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid script_direct input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        # Step 2 — parse JSON
        try:
            raw = json.loads(input.raw_content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"raw_content is not valid JSON: {exc}",
            ) from exc

        # Step 3 — check scenes key and non-empty
        if not isinstance(raw, dict) or "scenes" not in raw:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "raw_content must be a JSON object with a 'scenes' array",
            )
        raw_scenes = raw.get("scenes")
        if not raw_scenes or not isinstance(raw_scenes, list):
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "'scenes' must be a non-empty array",
            )

        # Step 4 — validate each scene for required fields (with index in details)
        parsed_scenes: list[ScriptDirectScene] = []
        for idx, raw_scene in enumerate(raw_scenes):
            try:
                parsed_scenes.append(ScriptDirectScene.model_validate(raw_scene))
            except ValidationError as exc:
                # Extract human-readable messages from Pydantic errors
                messages = [
                    f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
                    for e in exc.errors()
                ]
                raise AdapterError(
                    "ADAPTER_INVALID_INPUT",
                    f"scenes[{idx}] validation failed: {'; '.join(messages)}",
                    details={"scene_index": idx, "errors": messages},
                ) from exc

        # Step 5 — validate ALL durations BEFORE assigning order (R1.10)
        durations: list[float] = []
        for idx, scene in enumerate(parsed_scenes):
            duration = scene.duration_sec if scene.duration_sec is not None else _DEFAULT_DURATION
            if not (_MIN_DURATION <= duration <= _MAX_DURATION):
                raise AdapterError(
                    "ADAPTER_INVALID_INPUT",
                    (
                        f"scenes[{idx}].duration_sec={duration} is outside "
                        f"[{_MIN_DURATION}, {_MAX_DURATION}]"
                    ),
                    details={"scene_index": idx, "duration": duration},
                )
            durations.append(duration)

        # Step 6 + 7 — assign contiguous order and build SceneSpec objects
        specs: list[SceneSpec] = []
        for order, (scene, duration) in enumerate(zip(parsed_scenes, durations)):
            spec = SceneSpec(
                order=order,
                prompt=scene.visual_prompt,
                duration=duration,
                narration=scene.narration,
                # asset_ids are stored in metadata; SceneSpec has no asset_ids field
            )
            specs.append(spec)

        # Step 8 — apply skill prefix if requested (R1.14)
        if input.skill_name:
            specs = self._apply_skill(specs, input.skill_name)

        # Assemble SceneList
        scene_list = SceneList(
            project_id=input.options.get("project_id", "script_direct"),
            scenes=specs,
            voice=input.options.get("voice", "vi-VN-HoaiMyNeural"),
            metadata={
                "adapter": self.adapter_type,
                "scene_count": len(specs),
                "skill_name": input.skill_name,
            },
        )

        # Step 9 — structural validation
        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )

        # Step 10 — pipeline limits (Max_Scenes=50, Max_Duration=600s)
        enforce_pipeline_limits(scene_list)

        logger.debug(
            "ScriptDirectAdapter: generated %d scenes",
            len(specs),
        )
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Perform cheap pre-flight validation without calling any external APIs.

        Checks:
        - ``raw_content`` is non-empty.
        - ``raw_content`` is valid JSON.
        - Top-level object has a non-empty ``scenes`` array.
        - Each scene has non-blank ``narration`` and ``visual_prompt``.
        - ``duration_sec`` is a number when present.
        - ``asset_ids`` is an array when present.

        Does NOT call any network/LLM API (R1.12).

        Args:
            input: The adapter input to validate.

        Returns:
            A list of human-readable error strings.  Empty list = valid (R1.11).
        """
        errors: list[str] = []

        if not input.raw_content or not input.raw_content.strip():
            errors.append("raw_content must not be empty")
            return errors

        try:
            raw = json.loads(input.raw_content)
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(f"raw_content is not valid JSON: {exc}")
            return errors

        if not isinstance(raw, dict):
            errors.append("raw_content must be a JSON object")
            return errors

        raw_scenes = raw.get("scenes")
        if not raw_scenes:
            errors.append("'scenes' array is required and must not be empty")
            return errors

        if not isinstance(raw_scenes, list):
            errors.append("'scenes' must be an array")
            return errors

        if len(raw_scenes) == 0:
            errors.append("'scenes' array must not be empty")
            return errors

        # Validate each scene using Pydantic schema
        for idx, raw_scene in enumerate(raw_scenes):
            try:
                ScriptDirectScene.model_validate(raw_scene)
            except ValidationError as exc:
                for e in exc.errors():
                    loc = ".".join(str(loc) for loc in e["loc"])
                    errors.append(f"scenes[{idx}].{loc}: {e['msg']}")

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _apply_skill(
        self,
        scenes: list[SceneSpec],
        skill_name: str,
    ) -> list[SceneSpec]:
        """Apply a skill's prefix to all scene prompts via ``apply_skill_to_scene``.

        Loads the skill from the ``skills/`` directory relative to the
        project root.  If the skill cannot be loaded, logs a warning and
        returns the scenes unchanged.

        Args:
            scenes:     List of scenes to apply the skill to.
            skill_name: Name of the skill directory (e.g. ``"ecommerce-fashion"``).

        Returns:
            List of scenes with skill prefix applied (new SceneSpec objects).
        """
        try:
            from server.content.skill_loader import SkillLoader, apply_skill_to_scene

            # Resolve skills directory relative to this file's package root
            # server/content/adapters/script_direct/adapter.py
            # → go up 4 levels to reach app/, then skills/
            adapter_dir = Path(__file__).resolve().parent
            app_dir = adapter_dir.parents[3]  # app/
            skills_dir = app_dir / "skills"

            loader = SkillLoader(skills_dir)
            skill = loader.load(skill_name)
            return [apply_skill_to_scene(scene, skill) for scene in scenes]

        except FileNotFoundError:
            logger.warning(
                "ScriptDirectAdapter: skill %r not found — skipping skill application",
                skill_name,
            )
            return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ScriptDirectAdapter: failed to apply skill %r: %s — skipping",
                skill_name,
                exc,
            )
            return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: ScriptDirectAdapter = ScriptDirectAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = ScriptDirectAdapter
