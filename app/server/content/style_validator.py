"""Style.json validator for AIFlow skills.

Validates the structure of a skill's ``style.json`` file and provides a
helper to load + validate in one call.

Required keys:
    - ``art_style``     (str)
    - ``lighting``      (str)
    - ``color_palette`` (str or list[str])

Optional keys (validated if present):
    - ``camera_rules``      (str)
    - ``negative_prompts``  (list[str])
    - ``aspect_ratio``      (str, e.g. "9:16")
    - ``lens``              (str)
    - ``post``              (str)

Any additional keys are tolerated (skills may add custom fields).

Example::

    from server.content.style_validator import load_style_json, validate_style_json

    style = load_style_json(Path("skills/ecommerce-fashion/style.json"))
    errors = validate_style_json(style)
    assert errors == []
"""

from __future__ import annotations

import json
from pathlib import Path


# ─── Validator ────────────────────────────────────────────────────────────────


def validate_style_json(style: dict) -> list[str]:
    """Validate the structure of a parsed ``style.json`` dict.

    Args:
        style: Parsed JSON content of a skill's ``style.json``.

    Returns:
        A list of human-readable error strings.  An empty list means the
        style is valid.
    """
    errors: list[str] = []

    if not isinstance(style, dict):
        errors.append(f"style.json must be a JSON object, got {type(style).__name__}")
        return errors

    # ── Required keys ─────────────────────────────────────────────────────────

    if "art_style" not in style:
        errors.append("missing required key: 'art_style'")
    elif not isinstance(style["art_style"], str):
        errors.append(f"'art_style' must be a string, got {type(style['art_style']).__name__}")
    elif not style["art_style"].strip():
        errors.append("'art_style' must not be empty")

    if "lighting" not in style:
        errors.append("missing required key: 'lighting'")
    elif not isinstance(style["lighting"], str):
        errors.append(f"'lighting' must be a string, got {type(style['lighting']).__name__}")
    elif not style["lighting"].strip():
        errors.append("'lighting' must not be empty")

    if "color_palette" not in style:
        errors.append("missing required key: 'color_palette'")
    else:
        cp = style["color_palette"]
        if isinstance(cp, str):
            if not cp.strip():
                errors.append("'color_palette' string must not be empty")
        elif isinstance(cp, list):
            if not cp:
                errors.append("'color_palette' list must not be empty")
            else:
                for i, item in enumerate(cp):
                    if not isinstance(item, str):
                        errors.append(
                            f"'color_palette[{i}]' must be a string, got {type(item).__name__}"
                        )
        else:
            errors.append(
                f"'color_palette' must be a string or list, got {type(cp).__name__}"
            )

    # ── Optional keys (validated only when present) ───────────────────────────

    if "camera_rules" in style and not isinstance(style["camera_rules"], str):
        errors.append(
            f"'camera_rules' must be a string, got {type(style['camera_rules']).__name__}"
        )

    if "negative_prompts" in style:
        np_ = style["negative_prompts"]
        if not isinstance(np_, list):
            errors.append(
                f"'negative_prompts' must be a list, got {type(np_).__name__}"
            )
        else:
            for i, item in enumerate(np_):
                if not isinstance(item, str):
                    errors.append(
                        f"'negative_prompts[{i}]' must be a string, got {type(item).__name__}"
                    )

    if "aspect_ratio" in style and not isinstance(style["aspect_ratio"], str):
        errors.append(
            f"'aspect_ratio' must be a string, got {type(style['aspect_ratio']).__name__}"
        )

    return errors


# ─── Loader ───────────────────────────────────────────────────────────────────


def load_style_json(path: Path) -> dict:
    """Load and validate a ``style.json`` file.

    Args:
        path: Absolute or relative path to the ``style.json`` file.

    Returns:
        The parsed and validated style dict.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file is not valid JSON, not a JSON object, or
                    fails structural validation.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"style.json not found: {path}"
        )

    raw = path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse {path}: {exc}") from exc

    errors = validate_style_json(data)
    if errors:
        raise ValueError(
            f"style.json at {path} has validation errors:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return data
