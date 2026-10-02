"""SkillLoader — loads, validates, and applies skills to scenes.

Skills are pure data (YAML/JSON/Markdown) stored in ``skills/{skill_id}/``.
This module provides:

- :class:`LoadedSkill` — dataclass holding a fully-resolved skill.
- :class:`SkillLoader` — loads skills with ``_base`` inheritance, caches
  results, and validates skill directories.
- :func:`apply_skill_to_scene` — applies a loaded skill's prefix to a
  :class:`~server.content.base.SceneSpec`.

Design decision D8: Skills are data only — no Python code in skill folders.

Example::

    from pathlib import Path
    from server.content.skill_loader import SkillLoader

    loader = SkillLoader(Path("skills"))
    skill = loader.load("ecommerce-fashion")
    print(skill.manifest.name)          # "ecommerce-fashion"
    print(skill.prefix[:50])            # merged _base + skill prefix
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from server.content.base import SceneSpec
from server.content.skill_manifest import SkillManifest, load_skill_manifest
from server.content.style_validator import load_style_json, validate_style_json


# ─── LoadedSkill ──────────────────────────────────────────────────────────────


@dataclass
class LoadedSkill:
    """A fully-resolved skill ready for use by the pipeline.

    Attributes:
        manifest:  Validated :class:`~server.content.skill_manifest.SkillManifest`.
        style:     Parsed ``style.json`` content (merged with ``_base`` if
                   the skill does not define its own style).
        prefix:    Prompt prefix text.  When the skill declares
                   ``extends: _base``, this is the concatenation of
                   ``_base/prefix.md`` and the skill's own ``prefix.md``.
        skill_dir: Absolute path to the skill directory.
    """

    manifest: SkillManifest
    style: dict
    prefix: str
    skill_dir: Path


# ─── SkillLoader ──────────────────────────────────────────────────────────────


class SkillLoader:
    """Load and cache skills from a ``skills/`` directory.

    Args:
        skills_dir: Path to the root ``skills/`` directory that contains
                    individual skill sub-directories (e.g. ``_base``,
                    ``ecommerce-fashion``).
    """

    BASE_SKILL = "_base"

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = Path(skills_dir)
        self._cache: dict[str, LoadedSkill] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, skill_name: str) -> LoadedSkill:
        """Load a skill by name, resolving ``_base`` inheritance.

        The result is cached — subsequent calls with the same *skill_name*
        return the cached instance without re-reading files.

        Args:
            skill_name: Directory name of the skill (e.g.
                        ``"ecommerce-fashion"``).

        Returns:
            A :class:`LoadedSkill` with merged prefix and style.

        Raises:
            FileNotFoundError: If the skill directory or ``manifest.yaml``
                               does not exist.
            ValueError: If ``manifest.yaml`` or ``style.json`` is invalid.
        """
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_dir = self.skills_dir / skill_name
        if not skill_dir.is_dir():
            raise FileNotFoundError(
                f"Skill directory not found: {skill_dir}"
            )

        manifest = load_skill_manifest(skill_dir)
        style = self._load_style(skill_dir, manifest)
        prefix = self._load_prefix(skill_dir, manifest)

        loaded = LoadedSkill(
            manifest=manifest,
            style=style,
            prefix=prefix,
            skill_dir=skill_dir,
        )
        self._cache[skill_name] = loaded
        return loaded

    def list_skills(self) -> list[str]:
        """Return sorted list of available skill names, excluding ``_base``.

        Returns:
            Sorted list of skill directory names that contain a
            ``manifest.yaml`` file.
        """
        if not self.skills_dir.is_dir():
            return []

        skills = []
        for entry in self.skills_dir.iterdir():
            if (
                entry.is_dir()
                and entry.name != self.BASE_SKILL
                and not entry.name.startswith(".")
                and (entry / "manifest.yaml").exists()
            ):
                skills.append(entry.name)

        return sorted(skills)

    def validate_skill(self, skill_name: str) -> list[str]:
        """Validate a skill directory and return a list of errors.

        Checks:
        - Skill directory exists.
        - ``manifest.yaml`` exists and is valid.
        - ``style.json`` exists (if referenced in manifest) and is valid.
        - ``prefix.md`` exists (if referenced in manifest).

        Args:
            skill_name: Directory name of the skill to validate.

        Returns:
            A list of human-readable error strings.  An empty list means
            the skill is valid.
        """
        errors: list[str] = []
        skill_dir = self.skills_dir / skill_name

        if not skill_dir.is_dir():
            errors.append(f"Skill directory not found: {skill_dir}")
            return errors

        # Validate manifest
        manifest_path = skill_dir / "manifest.yaml"
        if not manifest_path.exists():
            errors.append(f"Missing manifest.yaml in {skill_dir}")
            return errors

        try:
            manifest = load_skill_manifest(skill_dir)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(f"manifest.yaml error: {exc}")
            return errors

        # Validate style.json if referenced
        if manifest.style_ref:
            style_path = skill_dir / manifest.style_ref
            if not style_path.exists():
                errors.append(f"style_ref '{manifest.style_ref}' not found in {skill_dir}")
            else:
                try:
                    import json as _json
                    raw = style_path.read_text(encoding="utf-8")
                    style_data = _json.loads(raw)
                    style_errors = validate_style_json(style_data)
                    errors.extend(
                        f"style.json: {e}" for e in style_errors
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"style.json error: {exc}")

        # Validate prefix.md if referenced
        prefix_file = manifest.options.get("prefix_file", "prefix.md")
        # Also check the manifest field directly if it has one
        prefix_ref = getattr(manifest, "prefix_file", None) or prefix_file
        prefix_path = skill_dir / prefix_ref
        if not prefix_path.exists():
            # prefix.md is optional — only warn if explicitly referenced
            # For _base inheriting skills, the base prefix is used as fallback
            pass  # Not an error — prefix is optional

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_style(self, skill_dir: Path, manifest: SkillManifest) -> dict:
        """Load style.json for a skill, falling back to _base style."""
        if manifest.style_ref:
            style_path = skill_dir / manifest.style_ref
            if style_path.exists():
                return load_style_json(style_path)

        # Fall back to _base style if available
        base_style_path = self.skills_dir / self.BASE_SKILL / "style.json"
        if base_style_path.exists():
            try:
                return load_style_json(base_style_path)
            except (FileNotFoundError, ValueError):
                pass

        return {}

    def _load_prefix(self, skill_dir: Path, manifest: SkillManifest) -> str:
        """Load and merge prefix.md, prepending _base prefix when extends: _base."""
        # Determine if this skill extends _base
        extends = getattr(manifest, "extends", None)
        # SkillManifest uses model_config extra="allow", so extra fields are
        # accessible via model_extra or direct attribute access
        if extends is None and hasattr(manifest, "model_extra"):
            extends = manifest.model_extra.get("extends")

        parts: list[str] = []

        # Load _base prefix when extends: _base (and we're not loading _base itself)
        if extends == self.BASE_SKILL and manifest.name != self.BASE_SKILL:
            base_prefix_path = self.skills_dir / self.BASE_SKILL / "prefix.md"
            if base_prefix_path.exists():
                base_text = base_prefix_path.read_text(encoding="utf-8").strip()
                if base_text:
                    parts.append(base_text)

        # Load this skill's own prefix.md
        prefix_path = skill_dir / "prefix.md"
        if prefix_path.exists():
            skill_text = prefix_path.read_text(encoding="utf-8").strip()
            if skill_text:
                parts.append(skill_text)

        return "\n\n".join(parts)


# ─── apply_skill_to_scene ─────────────────────────────────────────────────────


def apply_skill_to_scene(scene: SceneSpec, skill: LoadedSkill) -> SceneSpec:
    """Apply a skill's prefix to a scene's prompt.

    Creates a new :class:`~server.content.base.SceneSpec` with the skill
    prefix prepended to the scene's prompt.  The original scene is not
    modified.

    Args:
        scene: The scene to apply the skill to.
        skill: The loaded skill to apply.

    Returns:
        A new :class:`~server.content.base.SceneSpec` with the merged prompt.
        All other fields are copied from the original scene.
    """
    if not skill.prefix:
        return scene

    merged_prompt = f"{skill.prefix}\n\n{scene.prompt}"

    return SceneSpec(
        order=scene.order,
        prompt=merged_prompt,
        duration=scene.duration,
        start_image=scene.start_image,
        location_hint=scene.location_hint,
        narration=scene.narration,
    )
