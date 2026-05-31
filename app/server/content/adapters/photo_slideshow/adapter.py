"""PhotoSlideshowAdapter — turns an album of images into a slideshow SceneList.

Input (images provided either way):
- ``AdapterInput.assets`` — named image paths (e.g. ``{"img_0": Path(...)}``), OR
- ``AdapterInput.raw_content`` — a JSON array of image path strings.

Optional per-image narration:
- ``AdapterInput.options["captions"]`` — a list of caption strings aligned by
  order with the images.

Processing:
1. ``validate_input()`` — STRICT local-only checks (R4.6 + design): every image
   must exist and be readable (header verified via Pillow when available).  If
   ANY image is unreadable, validation fails (fail-fast, no silent drop).
2. Each image → one scene with ``start_image`` set to that image path.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from server.content.base import (
    AdapterError,
    AdapterInput,
    SceneList,
    SceneSpec,
)
from server.content.duration_estimator import estimate_scene_duration
from server.content.pipeline_limits import enforce_pipeline_limits

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION = 8.0
_DEFAULT_VOICE = "vi-VN-HoaiMyNeural"
_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
)

_SCENE_PROMPT_TEMPLATE = (
    "Photo slideshow scene. Gentle Ken Burns pan/zoom over the photograph. "
    "Warm nostalgic memory aesthetic.{caption_suffix}"
)


class PhotoSlideshowAdapter:
    """ContentAdapter that builds a slideshow from a list of images.

    Attributes:
        adapter_type: Registry key — ``"photo_slideshow"``.
    """

    adapter_type: str = "photo_slideshow"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Build a slideshow :class:`SceneList` (strict image validation)."""
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid photo_slideshow input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        images = _resolve_images(input)
        captions = input.options.get("captions") or []

        scenes: list[SceneSpec] = []
        for order, img in enumerate(images):
            caption = ""
            if order < len(captions) and captions[order]:
                caption = str(captions[order]).strip()
            scenes.append(self._image_to_scene(order, img, caption))

        if input.skill_name:
            scenes = _apply_skill(scenes, input.skill_name, self.adapter_type)

        scene_list = SceneList(
            project_id=input.options.get("project_id", "photo_slideshow"),
            scenes=scenes,
            voice=input.options.get("voice", _DEFAULT_VOICE),
            metadata={
                "adapter": self.adapter_type,
                "scene_count": len(scenes),
                "skill_name": input.skill_name,
                "image_count": len(images),
            },
        )

        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )
        enforce_pipeline_limits(scene_list)

        logger.debug("PhotoSlideshowAdapter: generated %d scenes", len(scenes))
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """STRICT local validation — no network/LLM calls (R4.6).

        Every resolved image path must exist and be a readable image.  When
        Pillow is available, the image header is verified.  Any unreadable or
        missing image produces an error (fail-fast, no silent drop).
        """
        errors: list[str] = []

        try:
            images = _resolve_images(input)
        except AdapterError as exc:
            return [exc.message]

        if not images:
            errors.append(
                "No images provided — supply image paths via assets or a JSON "
                "array in raw_content"
            )
            return errors

        for idx, img in enumerate(images):
            if not img.exists():
                errors.append(f"images[{idx}] not found: {img}")
                continue
            if img.suffix.lower() not in _IMAGE_EXTENSIONS:
                errors.append(
                    f"images[{idx}] has unsupported extension {img.suffix!r}: {img}"
                )
                continue
            errors.extend(_verify_image_header(idx, img))

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _image_to_scene(self, order: int, img: Path, caption: str) -> SceneSpec:
        suffix = f" Caption: {caption}" if caption else ""
        prompt = _SCENE_PROMPT_TEMPLATE.format(caption_suffix=suffix)
        duration = estimate_scene_duration(caption) if caption else _DEFAULT_DURATION
        return SceneSpec(
            order=order,
            prompt=prompt,
            duration=duration,
            start_image=img,
            narration=caption if caption else None,
        )


def _resolve_images(input: AdapterInput) -> list[Path]:  # noqa: A002
    """Resolve the ordered list of image paths from assets or raw_content.

    Precedence: explicit ``assets`` (sorted by key) first; otherwise a JSON
    array of path strings in ``raw_content``.
    """
    if input.assets:
        return [Path(input.assets[k]) for k in sorted(input.assets.keys())]

    raw = (input.raw_content or "").strip()
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"raw_content must be a JSON array of image paths: {exc}",
        ) from exc

    if not isinstance(data, list):
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "raw_content JSON must be an array of image path strings",
        )

    return [Path(str(p)) for p in data]


def _verify_image_header(idx: int, img: Path) -> list[str]:
    """Verify an image header using Pillow when available.

    Returns a list of error strings (empty = OK).  When Pillow is not
    installed, the structural check is skipped (extension check already done).
    """
    try:
        from PIL import Image  # lazy import — optional dependency
    except ImportError:
        logger.debug("Pillow not installed; skipping header check for %s", img)
        return []

    try:
        with Image.open(img) as im:
            im.verify()
        return []
    except Exception as exc:  # noqa: BLE001
        return [f"images[{idx}] is corrupt or unreadable: {img} ({exc})"]


def _apply_skill(
    scenes: list[SceneSpec],
    skill_name: str,
    adapter_type: str,
) -> list[SceneSpec]:
    """Apply a skill's prefix to all scene prompts (best-effort)."""
    try:
        from server.content.skill_loader import SkillLoader, apply_skill_to_scene

        adapter_dir = Path(__file__).resolve().parent
        app_dir = adapter_dir.parents[3]
        skills_dir = app_dir / "skills"

        loader = SkillLoader(skills_dir)
        skill = loader.load(skill_name)
        return [apply_skill_to_scene(scene, skill) for scene in scenes]
    except FileNotFoundError:
        logger.warning(
            "%s: skill %r not found — skipping skill application",
            adapter_type, skill_name,
        )
        return scenes
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s: failed to apply skill %r: %s — skipping",
            adapter_type, skill_name, exc,
        )
        return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

ADAPTER: PhotoSlideshowAdapter = PhotoSlideshowAdapter()
ADAPTER_CLASS = PhotoSlideshowAdapter
