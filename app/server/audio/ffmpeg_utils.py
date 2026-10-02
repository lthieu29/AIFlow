"""Audio-specific FFmpeg/FFprobe utilities.

REVIEW-02 #9 — This module is for *audio* operations only (probe duration,
encode mp3).  Video-composition helpers live in ``server/render/ffmpeg_utils.py``
and must NOT be imported from here.

Phase 3.1 — Task 3.1.1
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

# ─── Binary discovery ─────────────────────────────────────────────────────────

# Vendor directory relative to this file's package root (app/).
# Resolved at import time so callers don't need to know the layout.
_VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor"


def find_ffmpeg() -> Optional[Path]:
    """Locate the ffmpeg binary.

    Search order:
    1. ``vendor/ffmpeg.exe`` (Windows bundled binary)
    2. System PATH (``shutil.which``)

    Returns:
        Absolute path to ffmpeg, or ``None`` if not found.
    """
    vendor_path = _VENDOR_DIR / "ffmpeg.exe"
    if vendor_path.is_file():
        return vendor_path

    which = shutil.which("ffmpeg")
    if which:
        return Path(which)

    return None


def find_ffprobe() -> Optional[Path]:
    """Locate the ffprobe binary.

    Search order:
    1. ``vendor/ffprobe.exe`` (Windows bundled binary)
    2. System PATH (``shutil.which``)

    Returns:
        Absolute path to ffprobe, or ``None`` if not found.
    """
    vendor_path = _VENDOR_DIR / "ffprobe.exe"
    if vendor_path.is_file():
        return vendor_path

    which = shutil.which("ffprobe")
    if which:
        return Path(which)

    return None


# ─── Audio probing ────────────────────────────────────────────────────────────

def probe_duration(audio_path: Path) -> float:
    """Return the duration of an audio file in seconds using ffprobe.

    Args:
        audio_path: Path to the audio file to probe.

    Returns:
        Duration in seconds as a float.

    Raises:
        FileNotFoundError: If ffprobe cannot be located.
        subprocess.CalledProcessError: If ffprobe exits with a non-zero code.
        ValueError: If the ffprobe output cannot be parsed as a float.
    """
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise FileNotFoundError(
            "ffprobe not found. Place ffprobe.exe in vendor/ or add it to PATH."
        )

    cmd = [
        str(ffprobe),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.DEVNULL)
    return float(output.strip())


# ─── Audio encoding ───────────────────────────────────────────────────────────

def run_ffmpeg(args: list[str], *, timeout: int = 60) -> None:
    """Run ffmpeg with the given argument list.

    Resolves the ffmpeg binary via ``find_ffmpeg()`` (vendor/ first, then PATH).
    Raises ``subprocess.CalledProcessError`` on non-zero exit.

    Args:
        args: Arguments to pass after the ``ffmpeg`` binary name.
        timeout: Maximum seconds to wait for the process (default 60).

    Raises:
        FileNotFoundError: If ffmpeg cannot be located.
        subprocess.CalledProcessError: If ffmpeg exits with a non-zero code.
        subprocess.TimeoutExpired: If the process exceeds *timeout* seconds.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise FileNotFoundError(
            "ffmpeg not found. Place ffmpeg.exe in vendor/ or add it to PATH."
        )

    cmd = [str(ffmpeg)] + args
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)
