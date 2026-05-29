"""Voice metadata helpers — load custom voices and merge with presets.

Provides:
    _load_custom_catalog(storage_dir)  — load custom voices from voice_gallery/
    _get_or_load_vieneu()              — try to get VieNeu preset voice list
    get_all_voices(storage_dir)        — preset + custom voices combined

REVIEW-02 #11: custom voice folder is ``storage/voice_gallery/`` (NOT ``voices/``).

Phase 3.2 — Task 3.2.2
"""

import json
import logging
from pathlib import Path
from typing import Optional

from server.audio.tts.voice_catalog import (
    VoiceInfo,
    get_preset_voices,
)

log = logging.getLogger(__name__)

# ─── Custom catalog loader ────────────────────────────────────────────────────

# Folder name per REVIEW-02 #11 — must be voice_gallery, NOT voices
_VOICE_GALLERY_SUBDIR = "voice_gallery"
_CATALOG_FILENAME = "catalog.json"


def _load_custom_catalog(storage_dir: Path) -> list[VoiceInfo]:
    """Load custom voices from ``storage/voice_gallery/catalog.json``.

    Reads the catalog index file and deserialises each entry into a
    ``VoiceInfo`` model.  Entries that fail validation are skipped with a
    warning so a single corrupt entry does not break the whole catalog.

    If the catalog file does not exist (no custom voices imported yet) an
    empty list is returned silently.

    Args:
        storage_dir: Root storage directory (e.g. ``Path("storage")``).
                     The catalog is expected at
                     ``storage_dir/voice_gallery/catalog.json``.

    Returns:
        List of ``VoiceInfo`` for all valid custom voices in the catalog.
    """
    # REVIEW-02 #11: folder name is voice_gallery
    catalog_path = storage_dir / _VOICE_GALLERY_SUBDIR / _CATALOG_FILENAME

    if not catalog_path.exists():
        log.debug("[voice_metadata] no custom catalog at %s — returning empty list", catalog_path)
        return []

    try:
        raw = catalog_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[voice_metadata] failed to read catalog %s: %s", catalog_path, exc)
        return []

    voices_raw = data.get("voices", [])
    if not isinstance(voices_raw, list):
        log.warning("[voice_metadata] catalog 'voices' field is not a list — skipping")
        return []

    result: list[VoiceInfo] = []
    for entry in voices_raw:
        if not isinstance(entry, dict):
            log.warning("[voice_metadata] skipping non-dict catalog entry: %r", entry)
            continue

        # Normalise: catalog may use voice_id (spec addendum) or id (VoiceInfo field)
        if "voice_id" in entry and "id" not in entry:
            entry = dict(entry)
            entry["id"] = entry.pop("voice_id")

        # Normalise: catalog may use label instead of name
        if "label" in entry and "name" not in entry:
            entry = dict(entry)
            entry["name"] = entry.pop("label")

        # Ensure required fields have defaults so Pydantic validation passes
        entry.setdefault("backend", "vieneu")
        entry.setdefault("language", "vi-VN")
        entry.setdefault("gender", "neutral")
        entry.setdefault("description", "")
        entry.setdefault("is_custom", True)

        try:
            voice = VoiceInfo(**entry)
            result.append(voice)
        except Exception as exc:
            log.warning("[voice_metadata] skipping invalid catalog entry %r: %s", entry, exc)

    log.debug("[voice_metadata] loaded %d custom voice(s) from %s", len(result), catalog_path)
    return result


# ─── VieNeu preset voice list ─────────────────────────────────────────────────


def _get_or_load_vieneu() -> Optional[list[str]]:
    """Try to get the VieNeu preset voice list from the engine.

    Attempts to import the ``vieneu`` package and call
    ``Vieneu.list_preset_voices()`` without loading the full model (uses the
    class-level method if available, otherwise returns ``None``).

    Returns:
        List of voice ID strings if VieNeu is installed and the preset list
        is accessible without loading the model, otherwise ``None``.
    """
    try:
        from vieneu import Vieneu  # type: ignore[import]
    except ImportError:
        log.debug("[voice_metadata] vieneu not installed — _get_or_load_vieneu returns None")
        return None

    # Try class-level method first (no model load required)
    try:
        if hasattr(Vieneu, "list_preset_voices"):
            voices_raw = Vieneu.list_preset_voices()
            # Returns list of (description, voice_id) tuples or list of str
            ids: list[str] = []
            for item in voices_raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    ids.append(str(item[1]))
                elif isinstance(item, str):
                    ids.append(item)
            log.debug("[voice_metadata] vieneu class-level preset voices: %s", ids)
            return ids if ids else None
    except Exception as exc:
        log.debug("[voice_metadata] vieneu class-level list_preset_voices failed: %s", exc)

    # Fallback: return None — caller will use PRESET_VOICE_METADATA instead
    return None


# ─── Combined voice list ──────────────────────────────────────────────────────


def get_all_voices(storage_dir: Path) -> list[VoiceInfo]:
    """Return all voices: preset voices followed by custom voices.

    Preset voices come from ``PRESET_VOICE_METADATA`` in ``voice_catalog.py``.
    Custom voices are loaded from ``storage_dir/voice_gallery/catalog.json``.

    The lists are concatenated with presets first so the default voices
    always appear at the top of any UI listing.

    Args:
        storage_dir: Root storage directory (e.g. ``Path("storage")``).

    Returns:
        Combined list of preset + custom ``VoiceInfo`` entries.
    """
    preset = get_preset_voices()
    custom = _load_custom_catalog(storage_dir)

    log.debug(
        "[voice_metadata] get_all_voices: %d preset + %d custom = %d total",
        len(preset),
        len(custom),
        len(preset) + len(custom),
    )

    return preset + custom
