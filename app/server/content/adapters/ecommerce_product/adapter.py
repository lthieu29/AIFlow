"""EcommerceProductAdapter — converts a product image + metadata into a SceneList.

Input (``AdapterInput.raw_content``): JSON string with fields:
    - ``product_name`` (str, required)
    - ``price`` (str, required)
    - ``description`` (str, required)
    - ``cta`` (str, optional) — call-to-action text

Assets (``AdapterInput.assets``):
    - ``product_image`` (Path, optional) — product image for scene chaining

Output: ``SceneList`` with 5 scenes (40 s total):
    hero_shot → detail_shot → lifestyle_shot → feature_shot → cta_shot

Each scene has:
    - A Veo3 generation prompt (English)
    - A Vietnamese TTS narration string
    - Duration: 8 s

If ``input.skill_name`` is set, the skill prefix is applied to every scene
prompt via :func:`~server.content.skill_loader.apply_skill_to_scene`.

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
from server.content.adapters.ecommerce_product.prompts import (
    SCENE_TYPES,
    build_narration,
    build_scene_prompt,
)

logger = logging.getLogger(__name__)

# ─── Scene configuration ──────────────────────────────────────────────────────

_SCENE_DURATION = 8.0  # seconds per scene
_SCENE_COUNT = 5       # hero + detail + lifestyle + feature + cta

# Map scene index → (scene_type, location_hint)
_SCENE_CONFIG: list[tuple[str, str]] = [
    ("hero_shot",      "abstract"),        # clean studio reveal
    ("detail_shot",    "abstract"),        # macro detail, neutral bg
    ("lifestyle_shot", "indoor_home"),     # everyday use context
    ("feature_shot",   "abstract"),        # feature demo, clean bg
    ("cta_shot",       "abstract"),        # final CTA, premium bg
]


# ─── EcommerceProductAdapter ─────────────────────────────────────────────────


class EcommerceProductAdapter:
    """ContentAdapter for e-commerce product videos (TikTok/Reels 9:16 style).

    Generates a 5-scene, 40-second SceneList from a product image and metadata.
    Designed for use with the ``ecommerce-fashion`` skill.

    Attributes:
        adapter_type: Registry key — ``"ecommerce_product"``.
    """

    adapter_type: str = "ecommerce_product"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse product metadata and generate a 5-scene SceneList.

        Args:
            input: Adapter input with JSON ``raw_content`` and optional
                   ``product_image`` asset.

        Returns:
            A :class:`~server.content.base.SceneList` with 5 scenes.

        Raises:
            :class:`~server.content.base.AdapterError`: On parse or
                validation failure.
        """
        # 1. Validate input first
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid ecommerce_product input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        # 2. Parse product metadata
        product = self._parse_product(input.raw_content)

        # 3. Resolve optional product image
        product_image: Optional[Path] = input.assets.get("product_image")

        # 4. Build scenes
        scenes = self._build_scenes(product, product_image)

        # 5. Apply skill if requested
        if input.skill_name:
            scenes = self._apply_skill(scenes, input.skill_name)

        # 6. Assemble SceneList
        scene_list = SceneList(
            project_id=input.options.get("project_id", "ecommerce_product"),
            scenes=scenes,
            voice=input.options.get("voice", "vi-VN-HoaiMyNeural"),
            metadata={
                "adapter": self.adapter_type,
                "product_name": product["product_name"],
                "price": product["price"],
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
            "EcommerceProductAdapter: generated %d scenes for %r",
            len(scenes),
            product["product_name"],
        )
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Validate the adapter input without calling any external APIs.

        Checks:
        - ``raw_content`` is non-empty.
        - ``raw_content`` is valid JSON.
        - Required fields ``product_name``, ``price``, ``description`` are present
          and non-empty strings.
        - ``product_image`` asset path exists on disk (if provided).

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

        for field in ("product_name", "price", "description"):
            value = data.get(field)
            if not value:
                errors.append(f"Missing required field: {field!r}")
            elif not isinstance(value, str):
                errors.append(f"Field {field!r} must be a string")
            elif not value.strip():
                errors.append(f"Field {field!r} must not be blank")

        # Validate product_image path if provided
        product_image = input.assets.get("product_image")
        if product_image is not None:
            if not isinstance(product_image, Path):
                errors.append("assets['product_image'] must be a Path object")
            elif not product_image.exists():
                errors.append(
                    f"assets['product_image'] path does not exist: {product_image}"
                )

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_product(self, raw_content: str) -> dict:
        """Parse and return the product dict from raw JSON content."""
        data = json.loads(raw_content)
        return {
            "product_name": data["product_name"].strip(),
            "price": data["price"].strip(),
            "description": data["description"].strip(),
            "cta": data.get("cta", "Nhấn vào link dưới đây để mua ngay!").strip(),
        }

    def _build_scenes(
        self,
        product: dict,
        product_image: Optional[Path],
    ) -> list[SceneSpec]:
        """Build the 5 SceneSpec objects for the product video."""
        scenes: list[SceneSpec] = []

        for idx, (scene_type, location_hint) in enumerate(_SCENE_CONFIG):
            # Build Veo3 prompt
            prompt = build_scene_prompt(
                scene_num=idx,
                product_name=product["product_name"],
                product_desc=product["description"],
                scene_type=scene_type,
            )

            # Build Vietnamese narration
            narration = build_narration(
                product_name=product["product_name"],
                price=product["price"],
                cta=product["cta"],
                scene_type=scene_type,
            )

            # Use product image as start_image for hero and cta shots
            # (Layer 3 continuity: anchor product appearance)
            start_image: Optional[Path] = None
            if product_image and scene_type in ("hero_shot", "cta_shot"):
                start_image = product_image

            scene = SceneSpec(
                order=idx,
                prompt=prompt,
                duration=_SCENE_DURATION,
                start_image=start_image,
                location_hint=location_hint,
                narration=narration,
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
            # server/content/adapters/ecommerce_product/adapter.py
            # → go up 4 levels to reach app/, then skills/
            adapter_dir = Path(__file__).resolve().parent
            app_dir = adapter_dir.parents[3]  # app/
            skills_dir = app_dir / "skills"

            loader = SkillLoader(skills_dir)
            skill = loader.load(skill_name)
            return [apply_skill_to_scene(scene, skill) for scene in scenes]

        except FileNotFoundError:
            logger.warning(
                "EcommerceProductAdapter: skill %r not found — skipping skill application",
                skill_name,
            )
            return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "EcommerceProductAdapter: failed to apply skill %r: %s — skipping",
                skill_name,
                exc,
            )
            return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: EcommerceProductAdapter = EcommerceProductAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = EcommerceProductAdapter
