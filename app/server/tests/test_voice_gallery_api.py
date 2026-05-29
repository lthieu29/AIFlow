"""Unit tests for Voice Gallery API — Task 5.1.

Tests cover:
    VoicePackageManifest:
        - Valid manifest construction
        - Invalid gender raises ValidationError
        - Invalid language raises ValidationError
        - Empty voice_id raises ValidationError
        - display_name alias works

    validate_voice_package():
        - Valid zip passes
        - Missing metadata.json fails
        - Missing voices.json fails
        - Non-zip file fails
        - Non-existent file fails
        - Invalid metadata.json JSON fails
        - Invalid manifest schema fails

    extract_voice_package():
        - Extracts files to output_dir
        - Returns correct manifest
        - Raises ValueError on invalid zip
        - Handles top-level directory wrapper in zip

    POST /api/tts/voices/custom:
        - Valid zip returns 201 with id/name/status
        - Invalid zip returns 400
        - Duplicate voice_id returns 409
        - Non-zip file returns 400

    GET /api/tts/voices/custom/{id}:
        - Returns VoiceInfo for existing voice
        - Returns 404 for unknown voice

    DELETE /api/tts/voices/custom/{id}:
        - Returns {"deleted": true} and removes catalog entry
        - Removes voice directory from filesystem
        - Returns 404 for unknown voice

Phase 5.1 — Task 5.1
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.audio.tts.voice_package import (
    VoicePackageManifest,
    extract_voice_package,
    validate_voice_package,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_valid_metadata(
    voice_id: str = "test-voice",
    display_name: str = "Test Voice",
    language: str = "vi",
    gender: str = "female",
    approach: str = "persistent_embedding",
) -> dict:
    return {
        "schema_version": "1.0",
        "voice_id": voice_id,
        "display_name": display_name,
        "language": language,
        "gender": gender,
        "approach": approach,
        "description": "A test voice",
    }


def _make_zip_bytes(
    metadata: dict | None = None,
    include_voices_json: bool = True,
    include_demo: bool = False,
    top_level_dir: str | None = None,
) -> bytes:
    """Build an in-memory zip with the given contents."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        prefix = (top_level_dir + "/") if top_level_dir else ""

        if metadata is not None:
            zf.writestr(prefix + "metadata.json", json.dumps(metadata))

        if include_voices_json:
            voices_data = {"voices": [{"id": "test-voice", "codes": [1, 2, 3]}]}
            zf.writestr(prefix + "voices.json", json.dumps(voices_data))

        if include_demo:
            zf.writestr(prefix + "demo.mp3", b"\xff\xfb\x90\x00" * 10)

    return buf.getvalue()


def _write_zip(path: Path, zip_bytes: bytes) -> None:
    path.write_bytes(zip_bytes)


def _make_settings(tmp_path: Path) -> MagicMock:
    settings = MagicMock()
    settings.data_dir = tmp_path
    return settings


# ─── VoicePackageManifest tests ───────────────────────────────────────────────


class TestVoicePackageManifest:
    def test_valid_manifest_construction(self):
        m = VoicePackageManifest(
            voice_id="phuong-anh-female",
            display_name="Phương Anh",
            language="vi",
            gender="female",
            approach="lora_finetune",
        )
        assert m.voice_id == "phuong-anh-female"
        assert m.name == "Phương Anh"
        assert m.gender == "female"
        assert m.language == "vi"
        assert m.approach == "lora_finetune"

    def test_default_values(self):
        m = VoicePackageManifest(voice_id="my-voice")
        assert m.sample_rate == 22050
        assert m.description == ""
        assert m.approach == "persistent_embedding"
        assert m.gender == "neutral"
        assert m.demo_file == "demo.mp3"

    def test_display_name_alias(self):
        """display_name alias should populate the name field."""
        m = VoicePackageManifest(voice_id="v1", display_name="My Voice")
        assert m.name == "My Voice"

    def test_name_field_direct(self):
        m = VoicePackageManifest(voice_id="v1", name="Direct Name")
        assert m.name == "Direct Name"

    def test_invalid_gender_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            VoicePackageManifest(voice_id="v1", gender="unknown")

    def test_invalid_language_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            VoicePackageManifest(voice_id="v1", language="fr")

    def test_empty_voice_id_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            VoicePackageManifest(voice_id="")

    def test_whitespace_voice_id_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            VoicePackageManifest(voice_id="   ")

    def test_all_valid_genders(self):
        for gender in ("male", "female", "neutral"):
            m = VoicePackageManifest(voice_id="v1", gender=gender)
            assert m.gender == gender

    def test_all_valid_languages(self):
        for lang in ("vi", "en", "vi-en"):
            m = VoicePackageManifest(voice_id="v1", language=lang)
            assert m.language == lang

    def test_both_approaches(self):
        for approach in ("lora_finetune", "persistent_embedding"):
            m = VoicePackageManifest(voice_id="v1", approach=approach)
            assert m.approach == approach


# ─── validate_voice_package tests ─────────────────────────────────────────────


class TestValidateVoicePackage:
    def test_valid_zip_passes(self, tmp_path):
        metadata = _make_valid_metadata()
        zip_bytes = _make_zip_bytes(metadata=metadata)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        ok, errors = validate_voice_package(zip_path)
        assert ok is True
        assert errors == []

    def test_missing_metadata_json_fails(self, tmp_path):
        zip_bytes = _make_zip_bytes(metadata=None)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        ok, errors = validate_voice_package(zip_path)
        assert ok is False
        assert any("metadata.json" in e for e in errors)

    def test_missing_voices_json_fails(self, tmp_path):
        metadata = _make_valid_metadata()
        zip_bytes = _make_zip_bytes(metadata=metadata, include_voices_json=False)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        ok, errors = validate_voice_package(zip_path)
        assert ok is False
        assert any("voices.json" in e for e in errors)

    def test_non_existent_file_fails(self, tmp_path):
        ok, errors = validate_voice_package(tmp_path / "nonexistent.zip")
        assert ok is False
        assert any("not found" in e.lower() or "nonexistent" in e for e in errors)

    def test_non_zip_file_fails(self, tmp_path):
        bad_file = tmp_path / "notazip.zip"
        bad_file.write_bytes(b"this is not a zip file at all")

        ok, errors = validate_voice_package(bad_file)
        assert ok is False
        assert len(errors) > 0

    def test_invalid_metadata_json_fails(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("metadata.json", "{ invalid json }")
            zf.writestr("voices.json", "{}")
        zip_path = tmp_path / "voice.zip"
        zip_path.write_bytes(buf.getvalue())

        ok, errors = validate_voice_package(zip_path)
        assert ok is False
        assert any("json" in e.lower() for e in errors)

    def test_invalid_manifest_schema_fails(self, tmp_path):
        """metadata.json with missing required fields should fail."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Missing voice_id
            zf.writestr("metadata.json", json.dumps({"display_name": "No ID"}))
            zf.writestr("voices.json", "{}")
        zip_path = tmp_path / "voice.zip"
        zip_path.write_bytes(buf.getvalue())

        ok, errors = validate_voice_package(zip_path)
        assert ok is False
        assert any("schema" in e.lower() or "voice_id" in e.lower() for e in errors)

    def test_zip_with_top_level_dir_passes(self, tmp_path):
        """Zip with a single top-level directory wrapper should still validate."""
        metadata = _make_valid_metadata()
        zip_bytes = _make_zip_bytes(metadata=metadata, top_level_dir="custom_voice_test")
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        ok, errors = validate_voice_package(zip_path)
        assert ok is True
        assert errors == []

    def test_invalid_gender_in_metadata_fails(self, tmp_path):
        metadata = _make_valid_metadata(gender="robot")
        zip_bytes = _make_zip_bytes(metadata=metadata)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        ok, errors = validate_voice_package(zip_path)
        assert ok is False

    def test_invalid_language_in_metadata_fails(self, tmp_path):
        metadata = _make_valid_metadata(language="zh")
        zip_bytes = _make_zip_bytes(metadata=metadata)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        ok, errors = validate_voice_package(zip_path)
        assert ok is False


# ─── extract_voice_package tests ──────────────────────────────────────────────


class TestExtractVoicePackage:
    def test_extracts_files_to_output_dir(self, tmp_path):
        metadata = _make_valid_metadata(voice_id="my-voice")
        zip_bytes = _make_zip_bytes(metadata=metadata, include_demo=True)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        out_dir = tmp_path / "extracted"
        manifest = extract_voice_package(zip_path, out_dir)

        assert (out_dir / "metadata.json").exists()
        assert (out_dir / "voices.json").exists()
        assert manifest.voice_id == "my-voice"

    def test_returns_correct_manifest(self, tmp_path):
        metadata = _make_valid_metadata(
            voice_id="phuong-anh",
            display_name="Phương Anh",
            language="vi",
            gender="female",
        )
        zip_bytes = _make_zip_bytes(metadata=metadata)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        out_dir = tmp_path / "out"
        manifest = extract_voice_package(zip_path, out_dir)

        assert manifest.voice_id == "phuong-anh"
        assert manifest.name == "Phương Anh"
        assert manifest.language == "vi"
        assert manifest.gender == "female"

    def test_raises_value_error_on_invalid_zip(self, tmp_path):
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip")

        with pytest.raises(ValueError, match="Invalid voice package"):
            extract_voice_package(bad_zip, tmp_path / "out")

    def test_handles_top_level_dir_wrapper(self, tmp_path):
        """Zip with a top-level directory should extract files flat."""
        metadata = _make_valid_metadata(voice_id="wrapped-voice")
        zip_bytes = _make_zip_bytes(metadata=metadata, top_level_dir="custom_voice_wrapped")
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        out_dir = tmp_path / "out"
        manifest = extract_voice_package(zip_path, out_dir)

        # Files should be directly in out_dir, not in a subdirectory
        assert (out_dir / "metadata.json").exists()
        assert (out_dir / "voices.json").exists()
        assert manifest.voice_id == "wrapped-voice"

    def test_creates_output_dir_if_not_exists(self, tmp_path):
        metadata = _make_valid_metadata(voice_id="new-voice")
        zip_bytes = _make_zip_bytes(metadata=metadata)
        zip_path = tmp_path / "voice.zip"
        _write_zip(zip_path, zip_bytes)

        out_dir = tmp_path / "deep" / "nested" / "dir"
        assert not out_dir.exists()

        extract_voice_package(zip_path, out_dir)
        assert out_dir.exists()
        assert (out_dir / "metadata.json").exists()


# ─── API endpoint tests ───────────────────────────────────────────────────────


@pytest.fixture()
def app_with_tmp_storage(tmp_path):
    """Create a FastAPI test app with settings pointing to tmp_path."""
    from fastapi import FastAPI
    from server.api.routes.tts import get_settings, router

    test_app = FastAPI()
    test_app.include_router(router)

    # Override settings dependency to use tmp_path as data_dir
    mock_settings = _make_settings(tmp_path)

    test_app.dependency_overrides[get_settings] = lambda: mock_settings
    return test_app, tmp_path


@pytest.fixture()
def client(app_with_tmp_storage):
    """Synchronous TestClient for the test app."""
    from fastapi.testclient import TestClient

    app, tmp_path = app_with_tmp_storage
    return TestClient(app), tmp_path


class TestUploadCustomVoice:
    def test_valid_zip_returns_201(self, client):
        tc, tmp_path = client
        metadata = _make_valid_metadata(voice_id="test-upload", display_name="Test Upload")
        zip_bytes = _make_zip_bytes(metadata=metadata)

        response = tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["id"] == "test-upload"
        assert body["name"] == "Test Upload"
        assert body["status"] == "ready"

    def test_valid_zip_registers_in_catalog(self, client):
        tc, tmp_path = client
        metadata = _make_valid_metadata(voice_id="catalog-test")
        zip_bytes = _make_zip_bytes(metadata=metadata)

        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

        catalog_path = tmp_path / "voice_gallery" / "catalog.json"
        assert catalog_path.exists()
        data = json.loads(catalog_path.read_text())
        ids = [e.get("id") or e.get("voice_id") for e in data["voices"]]
        assert "catalog-test" in ids

    def test_valid_zip_extracts_files(self, client):
        tc, tmp_path = client
        metadata = _make_valid_metadata(voice_id="extract-test")
        zip_bytes = _make_zip_bytes(metadata=metadata)

        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

        voice_dir = tmp_path / "voice_gallery" / "extract-test"
        assert voice_dir.exists()
        assert (voice_dir / "metadata.json").exists()
        assert (voice_dir / "voices.json").exists()

    def test_invalid_zip_returns_400(self, client):
        tc, _ = client
        response = tc.post(
            "/api/tts/voices/custom",
            files={"file": ("bad.zip", b"not a zip", "application/zip")},
        )
        assert response.status_code == 400

    def test_missing_metadata_json_returns_400(self, client):
        tc, _ = client
        zip_bytes = _make_zip_bytes(metadata=None)  # no metadata.json

        response = tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )
        assert response.status_code == 400
        assert "metadata.json" in response.json()["detail"]

    def test_duplicate_voice_id_returns_409(self, client):
        tc, tmp_path = client
        metadata = _make_valid_metadata(voice_id="duplicate-voice")
        zip_bytes = _make_zip_bytes(metadata=metadata)

        # First upload
        r1 = tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )
        assert r1.status_code == 201

        # Second upload with same voice_id
        r2 = tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )
        assert r2.status_code == 409
        assert "duplicate-voice" in r2.json()["detail"]

    def test_demo_mp3_path_stored_in_catalog(self, client):
        tc, tmp_path = client
        metadata = _make_valid_metadata(voice_id="demo-voice")
        zip_bytes = _make_zip_bytes(metadata=metadata, include_demo=True)

        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

        catalog_path = tmp_path / "voice_gallery" / "catalog.json"
        data = json.loads(catalog_path.read_text())
        entry = next(e for e in data["voices"] if e.get("id") == "demo-voice")
        assert entry.get("demo_audio_path") is not None


class TestGetCustomVoice:
    def _upload_voice(self, tc, voice_id: str = "get-test") -> None:
        metadata = _make_valid_metadata(voice_id=voice_id, display_name="Get Test")
        zip_bytes = _make_zip_bytes(metadata=metadata)
        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

    def test_returns_voice_info_for_existing_voice(self, client):
        tc, _ = client
        self._upload_voice(tc, "get-test")

        response = tc.get("/api/tts/voices/custom/get-test")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == "get-test"
        assert body["is_custom"] is True

    def test_returns_404_for_unknown_voice(self, client):
        tc, _ = client
        response = tc.get("/api/tts/voices/custom/nonexistent-voice")
        assert response.status_code == 404

    def test_voice_info_has_correct_gender(self, client):
        tc, _ = client
        metadata = _make_valid_metadata(voice_id="gender-test", gender="male")
        zip_bytes = _make_zip_bytes(metadata=metadata)
        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

        response = tc.get("/api/tts/voices/custom/gender-test")
        assert response.status_code == 200
        assert response.json()["gender"] == "male"

    def test_voice_info_has_correct_language(self, client):
        tc, _ = client
        metadata = _make_valid_metadata(voice_id="lang-test", language="en")
        zip_bytes = _make_zip_bytes(metadata=metadata)
        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

        response = tc.get("/api/tts/voices/custom/lang-test")
        assert response.status_code == 200
        assert response.json()["language"] == "en-US"


class TestDeleteCustomVoice:
    def _upload_voice(self, tc, voice_id: str = "del-test") -> None:
        metadata = _make_valid_metadata(voice_id=voice_id)
        zip_bytes = _make_zip_bytes(metadata=metadata)
        tc.post(
            "/api/tts/voices/custom",
            files={"file": ("voice.zip", zip_bytes, "application/zip")},
        )

    def test_delete_returns_deleted_true(self, client):
        tc, _ = client
        self._upload_voice(tc, "del-test")

        response = tc.delete("/api/tts/voices/custom/del-test")
        assert response.status_code == 200
        assert response.json() == {"deleted": True}

    def test_delete_removes_from_catalog(self, client):
        tc, tmp_path = client
        self._upload_voice(tc, "del-catalog")

        tc.delete("/api/tts/voices/custom/del-catalog")

        catalog_path = tmp_path / "voice_gallery" / "catalog.json"
        data = json.loads(catalog_path.read_text())
        ids = [e.get("id") or e.get("voice_id") for e in data["voices"]]
        assert "del-catalog" not in ids

    def test_delete_removes_voice_directory(self, client):
        tc, tmp_path = client
        self._upload_voice(tc, "del-dir")

        voice_dir = tmp_path / "voice_gallery" / "del-dir"
        assert voice_dir.exists()

        tc.delete("/api/tts/voices/custom/del-dir")
        assert not voice_dir.exists()

    def test_delete_nonexistent_returns_404(self, client):
        tc, _ = client
        response = tc.delete("/api/tts/voices/custom/does-not-exist")
        assert response.status_code == 404

    def test_deleted_voice_not_found_on_get(self, client):
        tc, _ = client
        self._upload_voice(tc, "del-get-test")

        tc.delete("/api/tts/voices/custom/del-get-test")

        response = tc.get("/api/tts/voices/custom/del-get-test")
        assert response.status_code == 404

    def test_delete_does_not_affect_other_voices(self, client):
        tc, _ = client
        self._upload_voice(tc, "keep-voice")
        self._upload_voice(tc, "remove-voice")

        tc.delete("/api/tts/voices/custom/remove-voice")

        response = tc.get("/api/tts/voices/custom/keep-voice")
        assert response.status_code == 200
