"""Tests for vendor binary path resolution.

Tests server.render.ffmpeg_utils path resolution logic:
- vendor/ directory lookup (primary)
- PATH fallback (secondary)
- FileNotFoundError when neither is available
- find_* helpers return None instead of raising

Does NOT test actual downloads or binary execution.

Phase 3.3 — Task Vendor binaries (Task 54)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

import server.render.ffmpeg_utils as rfu


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_fake_exe(directory: Path, name: str) -> Path:
    """Create a zero-byte file to simulate a binary existing on disk."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_bytes(b"")
    return p


# ─── _find_binary ─────────────────────────────────────────────────────────────

class TestFindBinary:
    """Unit tests for the internal _find_binary helper."""

    def test_vendor_binary_found_first(self, tmp_path: Path) -> None:
        """vendor/{name}.exe is returned when it exists, even if PATH also has it."""
        fake_vendor = tmp_path / "vendor"
        _make_fake_exe(fake_vendor, "ffmpeg.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                result = rfu._find_binary("ffmpeg")

        assert result == fake_vendor / "ffmpeg.exe"

    def test_path_fallback_when_vendor_missing(self, tmp_path: Path) -> None:
        """Falls back to PATH when vendor binary does not exist."""
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=r"C:\Windows\System32\ffmpeg.exe"):
                result = rfu._find_binary("ffmpeg")

        assert result == Path(r"C:\Windows\System32\ffmpeg.exe")

    def test_returns_none_when_not_found_anywhere(self, tmp_path: Path) -> None:
        """Returns None when binary is absent from vendor/ and PATH."""
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                result = rfu._find_binary("ffmpeg")

        assert result is None

    def test_vendor_dir_does_not_exist(self, tmp_path: Path) -> None:
        """Returns None gracefully when vendor/ directory itself is missing."""
        nonexistent_vendor = tmp_path / "no_such_vendor"

        with patch.object(rfu, "_VENDOR_DIR", nonexistent_vendor):
            with patch("shutil.which", return_value=None):
                result = rfu._find_binary("ffmpeg")

        assert result is None

    def test_returns_absolute_path(self, tmp_path: Path) -> None:
        """Returned path is absolute."""
        fake_vendor = tmp_path / "vendor"
        _make_fake_exe(fake_vendor, "ffprobe.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu._find_binary("ffprobe")

        assert result is not None
        assert result.is_absolute()


# ─── get_ffmpeg_path ──────────────────────────────────────────────────────────

class TestGetFfmpegPath:
    """Tests for get_ffmpeg_path()."""

    def test_returns_vendor_path_when_present(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        expected = _make_fake_exe(fake_vendor, "ffmpeg.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu.get_ffmpeg_path()

        assert result == expected

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                with pytest.raises(FileNotFoundError) as exc_info:
                    rfu.get_ffmpeg_path()

        assert "ffmpeg" in str(exc_info.value).lower()
        assert "download_vendor.py" in str(exc_info.value)

    def test_error_message_includes_expected_path(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                with pytest.raises(FileNotFoundError) as exc_info:
                    rfu.get_ffmpeg_path()

        assert "ffmpeg.exe" in str(exc_info.value)

    def test_path_fallback_used(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()
        system_ffmpeg = r"C:\tools\ffmpeg.exe"

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=system_ffmpeg):
                result = rfu.get_ffmpeg_path()

        assert result == Path(system_ffmpeg)


# ─── get_ffprobe_path ─────────────────────────────────────────────────────────

class TestGetFfprobePath:
    """Tests for get_ffprobe_path()."""

    def test_returns_vendor_path_when_present(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        expected = _make_fake_exe(fake_vendor, "ffprobe.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu.get_ffprobe_path()

        assert result == expected

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                with pytest.raises(FileNotFoundError) as exc_info:
                    rfu.get_ffprobe_path()

        assert "ffprobe" in str(exc_info.value).lower()

    def test_path_fallback_used(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()
        system_ffprobe = r"C:\tools\ffprobe.exe"

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=system_ffprobe):
                result = rfu.get_ffprobe_path()

        assert result == Path(system_ffprobe)


# ─── get_aria2c_path ──────────────────────────────────────────────────────────

class TestGetAria2cPath:
    """Tests for get_aria2c_path()."""

    def test_returns_vendor_path_when_present(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        expected = _make_fake_exe(fake_vendor, "aria2c.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu.get_aria2c_path()

        assert result == expected

    def test_raises_when_not_found(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                with pytest.raises(FileNotFoundError) as exc_info:
                    rfu.get_aria2c_path()

        assert "aria2c" in str(exc_info.value).lower()
        assert "download_vendor.py" in str(exc_info.value)

    def test_path_fallback_used(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()
        system_aria2c = r"C:\tools\aria2c.exe"

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=system_aria2c):
                result = rfu.get_aria2c_path()

        assert result == Path(system_aria2c)


# ─── find_* helpers (non-raising) ────────────────────────────────────────────

class TestFindHelpers:
    """Tests for find_ffmpeg(), find_ffprobe(), find_aria2c() — non-raising variants."""

    def test_find_ffmpeg_returns_none_when_missing(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                assert rfu.find_ffmpeg() is None

    def test_find_ffprobe_returns_none_when_missing(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                assert rfu.find_ffprobe() is None

    def test_find_aria2c_returns_none_when_missing(self, tmp_path: Path) -> None:
        empty_vendor = tmp_path / "vendor"
        empty_vendor.mkdir()

        with patch.object(rfu, "_VENDOR_DIR", empty_vendor):
            with patch("shutil.which", return_value=None):
                assert rfu.find_aria2c() is None

    def test_find_ffmpeg_returns_path_when_present(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        expected = _make_fake_exe(fake_vendor, "ffmpeg.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu.find_ffmpeg()

        assert result == expected

    def test_find_ffprobe_returns_path_when_present(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        expected = _make_fake_exe(fake_vendor, "ffprobe.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu.find_ffprobe()

        assert result == expected

    def test_find_aria2c_returns_path_when_present(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        expected = _make_fake_exe(fake_vendor, "aria2c.exe")

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            result = rfu.find_aria2c()

        assert result == expected


# ─── vendor_dir() ────────────────────────────────────────────────────────────

class TestVendorDir:
    """Tests for vendor_dir() helper."""

    def test_returns_path_object(self) -> None:
        result = rfu.vendor_dir()
        assert isinstance(result, Path)

    def test_returns_absolute_path(self) -> None:
        result = rfu.vendor_dir()
        assert result.is_absolute()

    def test_ends_with_vendor(self) -> None:
        result = rfu.vendor_dir()
        assert result.name == "vendor"

    def test_matches_module_constant(self) -> None:
        assert rfu.vendor_dir() == rfu._VENDOR_DIR


# ─── Priority: vendor over PATH ──────────────────────────────────────────────

class TestVendorPriority:
    """Verify vendor/ always takes priority over PATH."""

    def test_vendor_wins_over_path_for_ffmpeg(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        vendor_ffmpeg = _make_fake_exe(fake_vendor, "ffmpeg.exe")
        path_ffmpeg = r"C:\Windows\System32\ffmpeg.exe"

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            with patch("shutil.which", return_value=path_ffmpeg):
                result = rfu.get_ffmpeg_path()

        assert result == vendor_ffmpeg
        assert str(result) != path_ffmpeg

    def test_vendor_wins_over_path_for_aria2c(self, tmp_path: Path) -> None:
        fake_vendor = tmp_path / "vendor"
        vendor_aria2c = _make_fake_exe(fake_vendor, "aria2c.exe")
        path_aria2c = r"C:\tools\aria2c.exe"

        with patch.object(rfu, "_VENDOR_DIR", fake_vendor):
            with patch("shutil.which", return_value=path_aria2c):
                result = rfu.get_aria2c_path()

        assert result == vendor_aria2c
        assert str(result) != path_aria2c
