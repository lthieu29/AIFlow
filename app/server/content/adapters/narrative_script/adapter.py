"""NarrativeScriptAdapter — converts a markdown narrative script into a SceneList.

Input (``AdapterInput.raw_content``): Markdown string with optional H2 headings.

Parsing rules (see :mod:`parser`):
- ``## Scene Title`` → scene boundary
- Body text → visual prompt
- ``**Narration:** text`` or ``> blockquote`` → TTS narration
- ``**Location:** value`` → location_hint
- No H2 headings → paragraph-based fallback

Output: :class:`~server.content.base.SceneList` with one :class:`~server.content.base.SceneSpec`
per parsed scene.  Duration is estimated from narration text via
:func:`~server.content.duration_estimator.estimate_scene_duration`.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import logging
from pathlib import Path

from server.content.base import (
    AdapterError,
    AdapterInput,
    ContentAdapter,
    SceneList,
    SceneSpec,
)
from server.content.adapters.narrative_script.parser import (
    NarrativeScene,
    parse_markdown_script,
)
from server.content.duration_estimator import estimate_scene_duration

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION = 8.0  # seconds — used when narration is empty


# ─── NarrativeScriptAdapter ──────────────────────────────────────────────────


class NarrativeScriptAdapter:
    """ContentAdapter for markdown narrative / vlog scripts.

    Parses a markdown document into scenes using H2 headings as boundaries.
    Falls back to paragraph splitting when no headings are present.

    Attributes:
        adapter_type: Registry key — ``"narrative_script"``.
    """

    adapter_type: str = "narrative_script"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse a markdown narrative script and return a :class:`SceneList`.

        Args:
            input: Adapter input whose ``raw_content`` is a markdown string.

        Returns:
            A :class:`~server.content.base.SceneList` with one scene per
            parsed section.

        Raises:
            :class:`~server.content.base.AdapterError`: On validation failure
                or if the markdown produces no scenes.
        """
        # 1. Validate input
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid narrative_script input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        # 2. Parse markdown → NarrativeScene list
        narrative_scenes = parse_markdown_script(input.raw_content)

        if not narrative_scenes:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "Markdown produced no scenes — content may be empty or unparseable.",
            )

        # 3. Convert NarrativeScene → SceneSpec
        scenes = [self._to_scene_spec(ns) for ns in narrative_scenes]

        # 4. Apply skill if requested
        if input.skill_name:
            scenes = self._apply_skill(scenes, input.skill_name)

        # 5. Assemble SceneList
        project_id = input.options.get("project_id", "narrative_script")
        scene_list = SceneList(
            project_id=project_id,
            scenes=scenes,
            voice=input.options.get("voice", "vi-VN-HoaiMyNeural"),
            metadata={
                "adapter": self.adapter_type,
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
            "NarrativeScriptAdapter: generated %d scenes from markdown",
            len(scenes),
        )
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Validate the adapter input without calling any external APIs.

        Checks:
        - ``raw_content`` is non-empty and not whitespace-only.

        Args:
            input: The adapter input to validate.

        Returns:
            A list of human-readable error strings.  Empty list = valid.
        """
        errors: list[str] = []

        if not input.raw_content or not input.raw_content.strip():
            errors.append("raw_content must not be empty")

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _to_scene_spec(self, ns: NarrativeScene) -> SceneSpec:
        """Convert a :class:`NarrativeScene` to a :class:`SceneSpec`.

        Duration is estimated from narration text.  If narration is empty,
        the body text is used for estimation; if both are empty, the default
        duration is used.

        Args:
            ns: Parsed narrative scene.

        Returns:
            A :class:`SceneSpec` ready for the pipeline.
        """
        # Build visual prompt from heading + body
        if ns.body:
            prompt = f"{ns.heading}\n\n{ns.body}" if ns.heading else ns.body
        else:
            prompt = ns.heading

        # Narration: prefer explicit narration, fall back to body text
        narration = ns.narration if ns.narration else ns.body

        # Estimate duration from narration (or body as fallback)
        duration_text = narration or ns.body
        if duration_text:
            duration = estimate_scene_duration(duration_text)
        else:
            duration = _DEFAULT_DURATION

        return SceneSpec(
            order=ns.order,
            prompt=prompt,
            duration=duration,
            location_hint=ns.location_hint,
            narration=narration if narration else None,
        )

    def _apply_skill(
        self,
        scenes: list[SceneSpec],
        skill_name: str,
    ) -> list[SceneSpec]:
        """Apply a skill's prefix to all scene prompts.

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
            # server/content/adapters/narrative_script/adapter.py
            # → go up 4 levels to reach app/, then skills/
            adapter_dir = Path(__file__).resolve().parent
            app_dir = adapter_dir.parents[3]  # app/
            skills_dir = app_dir / "skills"

            loader = SkillLoader(skills_dir)
            skill = loader.load(skill_name)
            return [apply_skill_to_scene(scene, skill) for scene in scenes]

        except FileNotFoundError:
            logger.warning(
                "NarrativeScriptAdapter: skill %r not found — skipping skill application",
                skill_name,
            )
            return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "NarrativeScriptAdapter: failed to apply skill %r: %s — skipping",
                skill_name,
                exc,
            )
            return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: NarrativeScriptAdapter = NarrativeScriptAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = NarrativeScriptAdapter
