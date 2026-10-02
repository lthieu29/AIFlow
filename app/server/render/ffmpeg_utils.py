"""Render-layer FFmpeg/FFprobe/aria2c path resolution.

ADR-005 — Ship Vendor Binaries: resolve binary paths from vendor/ first,
fall back to PATH if vendor binaries are absent.

This module is the canonical source for binary paths used by the render
pipeline (composer, overlay_compositor, visual_layer, stream_merger).
Audio-only helpers (probe_duration, run_ffmpeg) live in
``server.audio.ffmpeg_utils`` and import from here for binary discovery.

Exports:
    get_ffmpeg_path()   → Path to ffmpeg binary
    get_ffprobe_path()  → Path to ffprobe binary
    get_aria2c_path()   → Path to aria2c binary

Phase 3.3 — Task Vendor binaries (Task 54)
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

# ─── Vendor directory ─────────────────────────────────────────────────────────

# Resolved relative to this file: server/render/ffmpeg_utils.py → app/vendor/
_VENDOR_DIR: Path = Path(__file__).resolve().parents[2] / "vendor"


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _find_binary(name: str) -> Optional[Path]:
    """Locate a binary by name.

    Search order:
    1. ``vendor/{name}.exe`` (Windows bundled binary — ADR-005)
    2. System PATH via ``shutil.which``

    Args:
        name: Binary name without extension (e.g. "ffmpeg").

    Returns:
        Absolute Path to the binary, or ``None`` if not found anywhere.
    """
    vendor_path = _VENDOR_DIR / f"{name}.exe"
    if vendor_path.is_file():
        return vendor_path

    which = shutil.which(name)
    if which:
        return Path(which)

    return None


# ─── Public API ───────────────────────────────────────────────────────────────

def get_ffmpeg_path() -> Path:
    """Return the absolute path to the ffmpeg binary.

    Checks ``vendor/ffmpeg.exe`` first; falls back to PATH.

    Returns:
        Absolute Path to ffmpeg.

    Raises:
        FileNotFoundError: If ffmpeg is not found in vendor/ or PATH.
            Hint: run ``python scripts/download_vendor.py`` to download.
    """
    path = _find_binary("ffmpeg")
    if path is None:
        raise FileNotFoundError(
            "ffmpeg not found in vendor/ or PATH.\n"
            "Run: python scripts/download_vendor.py\n"
            f"Expected: {_VENDOR_DIR / 'ffmpeg.exe'}"
        )
    return path


def get_ffprobe_path() -> Path:
    """Return the absolute path to the ffprobe binary.

    Checks ``vendor/ffprobe.exe`` first; falls back to PATH.

    Returns:
        Absolute Path to ffprobe.

    Raises:
        FileNotFoundError: If ffprobe is not found in vendor/ or PATH.
            Hint: run ``python scripts/download_vendor.py`` to download.
    """
    path = _find_binary("ffprobe")
    if path is None:
        raise FileNotFoundError(
            "ffprobe not found in vendor/ or PATH.\n"
            "Run: python scripts/download_vendor.py\n"
            f"Expected: {_VENDOR_DIR / 'ffprobe.exe'}"
        )
    return path


def get_aria2c_path() -> Path:
    """Return the absolute path to the aria2c binary.

    Checks ``vendor/aria2c.exe`` first; falls back to PATH.

    Returns:
        Absolute Path to aria2c.

    Raises:
        FileNotFoundError: If aria2c is not found in vendor/ or PATH.
            Hint: run ``python scripts/download_vendor.py`` to download.
    """
    path = _find_binary("aria2c")
    if path is None:
        raise FileNotFoundError(
            "aria2c not found in vendor/ or PATH.\n"
            "Run: python scripts/download_vendor.py\n"
            f"Expected: {_VENDOR_DIR / 'aria2c.exe'}"
        )
    return path


def find_ffmpeg() -> Optional[Path]:
    """Locate ffmpeg without raising — returns None if not found.

    Convenience wrapper used by composer.py and other render modules that
    handle the missing-binary case themselves.

    Returns:
        Absolute Path to ffmpeg, or ``None`` if not found.
    """
    return _find_binary("ffmpeg")


def find_ffprobe() -> Optional[Path]:
    """Locate ffprobe without raising — returns None if not found.

    Returns:
        Absolute Path to ffprobe, or ``None`` if not found.
    """
    return _find_binary("ffprobe")


def find_aria2c() -> Optional[Path]:
    """Locate aria2c without raising — returns None if not found.

    Returns:
        Absolute Path to aria2c, or ``None`` if not found.
    """
    return _find_binary("aria2c")


def vendor_dir() -> Path:
    """Return the resolved vendor directory path.

    Useful for scripts that need to know where to place downloaded binaries.

    Returns:
        Absolute Path to the vendor/ directory.
    """
    return _VENDOR_DIR
