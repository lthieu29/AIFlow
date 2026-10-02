"""Voice package validation and extraction — spec 11.

Handles the unified `.zip` format produced by the Colab notebook
(``colab/train_custom_voice.ipynb``) for both Path A (LoRA fine-tune) and
Path B (persistent embedding).

Expected zip structure:
    custom_voice_{voice_id}.zip
    ├── metadata.json          ← required — VoicePackageManifest
    ├── voices.json            ← required — VieNeu native preset format
    ├── demo.mp3               ← optional — sample audio
    ├── README.md              ← optional
    ├── lora/                  ← Path A only
    │   ├── adapter_model.safetensors
    │   ├── adapter_config.json
    │   └── tokenizer*.json
    └── training_log.txt       ← Path A only

Public API:
    VoicePackageManifest       — Pydantic model for metadata.json
    validate_voice_package()   — check zip structure, return (ok, errors)
    extract_voice_package()    — extract + validate, return manifest

Phase 5.1 — Task 5.1
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Manifest model ───────────────────────────────────────────────────────────


class VoicePackageManifest(BaseModel):
    """Pydantic model for ``metadata.json`` inside a voice package zip.

    Required fields match the spec 11 ``metadata.json`` schema.
    Optional fields have sensible defaults so older packages remain compatible.

    Attributes:
        schema_version: Package schema version string (e.g. "1.0").
        voice_id: Unique kebab-case identifier (e.g. "phuong-anh-female").
        name: Human-readable display name (alias: ``display_name``).
        language: Language code — "vi", "en", or "vi-en".
        gender: Speaker gender.
        approach: Training approach — "lora_finetune" or "persistent_embedding".
        sample_rate: Audio sample rate in Hz (default 22050).
        description: Short description of the voice.
        created_at: ISO-8601 timestamp string (optional).
        demo_file: Filename of the demo audio inside the zip (default "demo.mp3").
    """

    schema_version: str = "1.0"
    voice_id: str
    name: str = Field(alias="display_name", default="")
    language: str = "vi"
    gender: Literal["male", "female", "neutral"] = "neutral"
    approach: Literal["lora_finetune", "persistent_embedding"] = "persistent_embedding"
    sample_rate: int = 22050
    description: str = ""
    created_at: Optional[str] = None
    demo_file: str = "demo.mp3"

    model_config = {"populate_by_name": True}

    @field_validator("name", mode="before")
    @classmethod
    def _coerce_name(cls, v: object) -> str:
        """Accept empty string; caller can fall back to voice_id."""
        if v is None:
            return ""
        return str(v)

    @field_validator("voice_id")
    @classmethod
    def _validate_voice_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("voice_id must not be empty")
        return v.strip()

    @field_validator("language")
    @classmethod
    def _validate_language(cls, v: str) -> str:
        allowed = {"vi", "en", "vi-en"}
        if v not in allowed:
            raise ValueError(f"language must be one of {allowed}, got {v!r}")
        return v


# ─── Required zip members ─────────────────────────────────────────────────────

_REQUIRED_FILES = {"metadata.json", "voices.json"}


# ─── validate_voice_package ───────────────────────────────────────────────────


def validate_voice_package(zip_path: Path) -> tuple[bool, list[str]]:
    """Validate the structure of a voice package zip file.

    Checks:
    1. File exists and is a valid zip archive.
    2. Required files (``metadata.json``, ``voices.json``) are present.
    3. ``metadata.json`` parses as a valid ``VoicePackageManifest``.

    Args:
        zip_path: Path to the ``.zip`` file to validate.

    Returns:
        A ``(ok, errors)`` tuple where ``ok`` is ``True`` when the package is
        valid and ``errors`` is a list of human-readable error strings (empty
        when ``ok`` is ``True``).
    """
    errors: list[str] = []

    # 1. File existence
    if not zip_path.exists():
        return False, [f"File not found: {zip_path}"]

    # 2. Valid zip
    if not zipfile.is_zipfile(zip_path):
        return False, [f"Not a valid zip archive: {zip_path.name}"]

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names_in_zip = set(zf.namelist())

            # Normalise: strip leading directory component if all files share one
            # e.g. "custom_voice_foo/metadata.json" → "metadata.json"
            top_dirs = {n.split("/")[0] for n in names_in_zip if "/" in n}
            if top_dirs and all(n.startswith(next(iter(top_dirs)) + "/") for n in names_in_zip if "/" in n):
                # Check if required files are under a single top-level folder
                top = next(iter(top_dirs))
                flat_names = {
                    n[len(top) + 1:] if n.startswith(top + "/") else n
                    for n in names_in_zip
                }
            else:
                flat_names = names_in_zip

            # 3. Required files present
            for required in _REQUIRED_FILES:
                if required not in flat_names:
                    errors.append(f"Missing required file in zip: {required}")

            if errors:
                return False, errors

            # 4. Parse metadata.json
            metadata_name = _find_in_zip(zf, "metadata.json")
            if metadata_name is None:
                errors.append("Cannot locate metadata.json in zip")
                return False, errors

            try:
                raw = zf.read(metadata_name).decode("utf-8")
                data = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"metadata.json is not valid JSON: {exc}")
                return False, errors

            # Map spec field names to model fields
            _normalise_metadata(data)

            try:
                VoicePackageManifest(**data)
            except Exception as exc:
                errors.append(f"metadata.json schema invalid: {exc}")
                return False, errors

    except zipfile.BadZipFile as exc:
        return False, [f"Corrupt zip archive: {exc}"]

    return True, []


# ─── extract_voice_package ────────────────────────────────────────────────────


def extract_voice_package(zip_path: Path, output_dir: Path) -> VoicePackageManifest:
    """Extract a voice package zip to ``output_dir`` and return its manifest.

    Validates the zip first; raises ``ValueError`` if validation fails.
    Extracts all contents, stripping any single top-level directory wrapper
    so files land directly in ``output_dir``.

    Args:
        zip_path: Path to the ``.zip`` file.
        output_dir: Destination directory (created if it does not exist).

    Returns:
        Parsed ``VoicePackageManifest`` from the extracted ``metadata.json``.

    Raises:
        ValueError: If the zip fails validation.
        OSError: If extraction fails due to filesystem errors.
    """
    ok, errors = validate_voice_package(zip_path)
    if not ok:
        raise ValueError(f"Invalid voice package: {'; '.join(errors)}")

    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()

        # Detect single top-level directory wrapper
        top_prefix = _detect_top_prefix(names)

        for member in names:
            # Determine target path
            if top_prefix and member.startswith(top_prefix):
                rel = member[len(top_prefix):]
            else:
                rel = member

            if not rel:
                # Skip the directory entry itself
                continue

            target = output_dir / rel

            if member.endswith("/"):
                # Directory entry
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))

        # Read and parse manifest from extracted file
        manifest_path = output_dir / "metadata.json"
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        _normalise_metadata(data)
        return VoicePackageManifest(**data)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _find_in_zip(zf: zipfile.ZipFile, filename: str) -> Optional[str]:
    """Return the full zip member name for ``filename``, searching recursively."""
    for name in zf.namelist():
        if name == filename or name.endswith("/" + filename):
            return name
    return None


def _detect_top_prefix(names: list[str]) -> str:
    """Return the common top-level directory prefix if all members share one.

    E.g. if all names start with ``"custom_voice_foo/"`` return that prefix.
    Returns empty string if there is no single shared prefix.
    """
    if not names:
        return ""

    # Collect top-level components
    tops = {n.split("/")[0] for n in names}
    if len(tops) != 1:
        return ""

    top = next(iter(tops))
    prefix = top + "/"

    # Verify every name starts with the prefix (or IS the prefix directory entry)
    if all(n == top or n.startswith(prefix) for n in names):
        return prefix

    return ""


def _normalise_metadata(data: dict) -> None:
    """Normalise metadata.json field names in-place for VoicePackageManifest.

    Handles the spec 11 schema which uses ``display_name`` (alias for ``name``)
    and ``voice_id`` (which may also appear as ``id``).
    """
    # display_name → name (via alias, but also handle direct key)
    if "display_name" in data and "name" not in data:
        data["name"] = data["display_name"]

    # id → voice_id
    if "id" in data and "voice_id" not in data:
        data["voice_id"] = data.pop("id")
