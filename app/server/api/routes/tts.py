"""TTS API routes — voice listing, on-demand synthesis, and custom voice gallery.

Endpoints:
    GET    /api/tts/voices                    — list preset + custom voices
    POST   /api/tts/synthesize                — synthesize text on demand
    POST   /api/tts/voices/custom             — upload custom voice package zip
    GET    /api/tts/voices/custom/{id}        — get custom voice info
    DELETE /api/tts/voices/custom/{id}        — delete custom voice

Phase 3.2 — Task 3.2.3
Phase 5.1 — Task 5.1 (custom voice gallery endpoints)
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel

from server.audio.tts.voice_catalog import VoiceInfo
from server.audio.tts.voice_metadata import get_all_voices
from server.config import Settings, load_settings

router = APIRouter(prefix="/api/tts", tags=["tts"])

# Sub-directory inside settings.data_dir for custom voice files
_VOICE_GALLERY_SUBDIR = "voice_gallery"
_CATALOG_FILENAME = "catalog.json"


# ─── Dependency ───────────────────────────────────────────────────────────────


def get_settings() -> Settings:
    """FastAPI dependency that returns the loaded Settings."""
    return load_settings()


# ─── Request / Response models ────────────────────────────────────────────────


class SynthesizeRequest(BaseModel):
    """Request body for POST /api/tts/synthesize."""

    text: str
    voice: str = "vi-VN-HoaiMyNeural"
    speed: float = 1.0


class SynthesizeResponse(BaseModel):
    """Response body for POST /api/tts/synthesize."""

    success: bool
    audio_path: str
    duration_sec: float
    backend: str


class CustomVoiceUploadResponse(BaseModel):
    """Response body for POST /api/tts/voices/custom."""

    id: str
    name: str
    status: str


class DeleteVoiceResponse(BaseModel):
    """Response body for DELETE /api/tts/voices/custom/{id}."""

    deleted: bool


# ─── Catalog helpers ──────────────────────────────────────────────────────────


def _catalog_path(data_dir: Path) -> Path:
    return data_dir / _VOICE_GALLERY_SUBDIR / _CATALOG_FILENAME


def _load_catalog(data_dir: Path) -> list[dict]:
    """Load the raw catalog list from catalog.json.

    Returns an empty list if the file does not exist or is malformed.
    """
    path = _catalog_path(data_dir)
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        voices = data.get("voices", [])
        return voices if isinstance(voices, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[tts:routes] failed to read catalog %s: %s", path, exc)
        return []


def _save_catalog(data_dir: Path, voices: list[dict]) -> None:
    """Persist the catalog list to catalog.json."""
    path = _catalog_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"voices": voices}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _find_in_catalog(voices: list[dict], voice_id: str) -> Optional[dict]:
    """Return the catalog entry for ``voice_id``, or None."""
    for entry in voices:
        eid = entry.get("id") or entry.get("voice_id")
        if eid == voice_id:
            return entry
    return None


def _catalog_entry_to_voice_info(entry: dict) -> VoiceInfo:
    """Convert a raw catalog dict to a VoiceInfo model."""
    e = dict(entry)
    # Normalise id / voice_id
    if "voice_id" in e and "id" not in e:
        e["id"] = e.pop("voice_id")
    # Normalise label / name
    if "label" in e and "name" not in e:
        e["name"] = e.pop("label")
    e.setdefault("backend", "vieneu")
    e.setdefault("language", "vi-VN")
    e.setdefault("gender", "neutral")
    e.setdefault("description", "")
    e.setdefault("is_custom", True)
    return VoiceInfo(**e)


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get("/voices", response_model=list[VoiceInfo])
def list_voices(settings: Settings = Depends(get_settings)) -> list[VoiceInfo]:
    """List all preset and custom voices.

    Returns preset voices (from ``voice_catalog.py``) followed by any custom
    voices found in ``storage/voice_gallery/catalog.json``.

    Returns:
        List of ``VoiceInfo`` objects.
    """
    logger.debug("[tts:routes] GET /api/tts/voices — data_dir=%s", settings.data_dir)
    voices = get_all_voices(settings.data_dir)
    logger.info("[tts:routes] returning %d voice(s)", len(voices))
    return voices


@router.post("/synthesize", response_model=SynthesizeResponse)
def synthesize(
    body: SynthesizeRequest,
    settings: Settings = Depends(get_settings),
) -> SynthesizeResponse:
    """Synthesize text to audio on demand.

    Creates a ``TTSService`` instance, runs synthesis through the configured
    provider chain, and returns the output audio path and duration.

    Args:
        body: ``SynthesizeRequest`` with ``text``, ``voice``, and ``speed``.
        settings: Loaded application settings (injected via dependency).

    Returns:
        ``SynthesizeResponse`` with ``success``, ``audio_path``,
        ``duration_sec``, and ``backend``.

    Raises:
        HTTPException 500: When synthesis fails for all providers.
    """
    from server.audio.tts.service import TTSService

    logger.info(
        "[tts:routes] POST /api/tts/synthesize — voice=%s speed=%.2f text_len=%d",
        body.voice,
        body.speed,
        len(body.text),
    )

    try:
        service = TTSService(settings)
        result = service.synthesize(
            text=body.text,
            voice=body.voice,
            speed=body.speed,
        )
        logger.info(
            "[tts:routes] synthesis OK — backend=%s duration=%.2fs path=%s",
            result.backend,
            result.duration_sec,
            result.output_path,
        )
        return SynthesizeResponse(
            success=True,
            audio_path=str(result.output_path),
            duration_sec=result.duration_sec,
            backend=result.backend,
        )
    except Exception as exc:
        logger.error("[tts:routes] synthesis failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Custom voice gallery endpoints ──────────────────────────────────────────


@router.post("/voices/custom", response_model=CustomVoiceUploadResponse, status_code=201)
async def upload_custom_voice(
    file: UploadFile = File(..., description="Voice package zip file"),
    settings: Settings = Depends(get_settings),
) -> CustomVoiceUploadResponse:
    """Upload a custom voice package zip.

    Accepts a multipart file upload of a ``.zip`` produced by the Colab
    notebook (``colab/train_custom_voice.ipynb``).  The zip must contain
    ``metadata.json`` and ``voices.json`` at minimum (spec 11).

    Steps:
    1. Save upload to a temp file.
    2. Validate zip structure via ``validate_voice_package()``.
    3. Extract to ``storage/voice_gallery/{voice_id}/``.
    4. Register the voice in ``catalog.json``.
    5. Return ``{"id": voice_id, "name": ..., "status": "ready"}``.

    Args:
        file: Uploaded zip file (multipart/form-data field ``file``).
        settings: Loaded application settings.

    Returns:
        ``CustomVoiceUploadResponse`` with ``id``, ``name``, and ``status``.

    Raises:
        HTTPException 400: If the zip is invalid or missing required files.
        HTTPException 409: If a voice with the same ID already exists.
    """
    from server.audio.tts.voice_package import extract_voice_package, validate_voice_package

    logger.info("[tts:routes] POST /api/tts/voices/custom — filename=%s", file.filename)

    # 1. Save upload to a temp file
    suffix = Path(file.filename or "upload.zip").suffix or ".zip"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        # 2. Validate zip structure
        ok, errors = validate_voice_package(tmp_path)
        if not ok:
            logger.warning("[tts:routes] invalid voice package: %s", errors)
            raise HTTPException(
                status_code=400,
                detail=f"Invalid voice package: {'; '.join(errors)}",
            )

        # 3. Extract to storage/voice_gallery/{voice_id}/
        try:
            manifest = extract_voice_package(
                tmp_path,
                # Temporary extraction dir — we'll move it after conflict check
                settings.data_dir / _VOICE_GALLERY_SUBDIR / "__tmp_extract__",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        voice_id = manifest.voice_id
        final_dir = settings.data_dir / _VOICE_GALLERY_SUBDIR / voice_id
        tmp_extract = settings.data_dir / _VOICE_GALLERY_SUBDIR / "__tmp_extract__"

        # 4. Conflict check
        catalog = _load_catalog(settings.data_dir)
        if _find_in_catalog(catalog, voice_id) is not None:
            # Clean up temp extraction
            shutil.rmtree(tmp_extract, ignore_errors=True)
            raise HTTPException(
                status_code=409,
                detail=f"Voice '{voice_id}' already exists. Delete it first or use a different voice_id.",
            )

        # Move temp extraction to final location
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.move(str(tmp_extract), str(final_dir))

        # 5. Register in catalog
        display_name = manifest.name or voice_id
        new_entry: dict = {
            "id": voice_id,
            "name": display_name,
            "backend": "vieneu",
            "language": _map_language(manifest.language),
            "gender": manifest.gender,
            "description": manifest.description,
            "is_custom": True,
            "approach": manifest.approach,
        }
        # Add demo_audio_path if demo file exists
        demo_path = final_dir / manifest.demo_file
        if demo_path.exists():
            new_entry["demo_audio_path"] = str(demo_path)

        catalog.append(new_entry)
        _save_catalog(settings.data_dir, catalog)

        logger.info("[tts:routes] custom voice registered: %s (%s)", voice_id, display_name)
        return CustomVoiceUploadResponse(id=voice_id, name=display_name, status="ready")

    finally:
        # Always clean up the temp upload file
        tmp_path.unlink(missing_ok=True)


@router.get("/voices/custom/{voice_id}", response_model=VoiceInfo)
def get_custom_voice(
    voice_id: str,
    settings: Settings = Depends(get_settings),
) -> VoiceInfo:
    """Get custom voice info by ID.

    Args:
        voice_id: The unique voice identifier.
        settings: Loaded application settings.

    Returns:
        ``VoiceInfo`` for the requested custom voice.

    Raises:
        HTTPException 404: If the voice is not found in the catalog.
    """
    logger.debug("[tts:routes] GET /api/tts/voices/custom/%s", voice_id)
    catalog = _load_catalog(settings.data_dir)
    entry = _find_in_catalog(catalog, voice_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Custom voice '{voice_id}' not found")
    return _catalog_entry_to_voice_info(entry)


@router.delete("/voices/custom/{voice_id}", response_model=DeleteVoiceResponse)
def delete_custom_voice(
    voice_id: str,
    settings: Settings = Depends(get_settings),
) -> DeleteVoiceResponse:
    """Delete a custom voice and its associated files.

    Removes the voice from ``catalog.json`` and deletes the directory
    ``storage/voice_gallery/{voice_id}/``.

    Args:
        voice_id: The unique voice identifier to delete.
        settings: Loaded application settings.

    Returns:
        ``{"deleted": true}``

    Raises:
        HTTPException 404: If the voice is not found in the catalog.
    """
    logger.info("[tts:routes] DELETE /api/tts/voices/custom/%s", voice_id)
    catalog = _load_catalog(settings.data_dir)
    entry = _find_in_catalog(catalog, voice_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Custom voice '{voice_id}' not found")

    # Remove from catalog
    updated = [
        e for e in catalog
        if (e.get("id") or e.get("voice_id")) != voice_id
    ]
    _save_catalog(settings.data_dir, updated)

    # Delete files from storage/voice_gallery/{voice_id}/
    voice_dir = settings.data_dir / _VOICE_GALLERY_SUBDIR / voice_id
    if voice_dir.exists():
        shutil.rmtree(voice_dir)
        logger.info("[tts:routes] deleted voice directory: %s", voice_dir)
    else:
        logger.warning("[tts:routes] voice directory not found (already deleted?): %s", voice_dir)

    return DeleteVoiceResponse(deleted=True)


# ─── Language mapping helper ──────────────────────────────────────────────────


def _map_language(lang: str) -> str:
    """Map spec 11 language codes to BCP-47 tags used by VoiceInfo.

    Args:
        lang: Language code from metadata.json ("vi", "en", "vi-en").

    Returns:
        BCP-47 language tag (e.g. "vi-VN", "en-US", "vi-VN").
    """
    mapping = {
        "vi": "vi-VN",
        "en": "en-US",
        "vi-en": "vi-VN",  # bilingual — default to vi-VN
    }
    return mapping.get(lang, lang)
