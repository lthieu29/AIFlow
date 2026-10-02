"""Download vendor binaries for AIFlow.

Downloads FFmpeg 7.0+ and aria2c to the vendor/ directory.
Verifies binaries work by running --version after extraction.
Idempotent: skips download if the binary already exists.

Usage:
    python scripts/download_vendor.py
    python scripts/download_vendor.py --force   # re-download even if present

Sources (ADR-005):
    FFmpeg: BtbN/FFmpeg-Builds on GitHub (GPL Windows x64 build)
    aria2c: aria2/aria2 on GitHub (Windows x64 release)

Phase 3.3 — Task Vendor binaries (Task 54)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

# ─── Configuration ────────────────────────────────────────────────────────────

# Vendor directory: scripts/ is one level below app/, vendor/ is a sibling.
_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_DIR = _SCRIPT_DIR.parent
_VENDOR_DIR = _APP_DIR / "vendor"

# ── FFmpeg ────────────────────────────────────────────────────────────────────
# BtbN/FFmpeg-Builds: GPL Windows x64 release build
# Pin to a specific release tag for reproducibility.
# Update this URL when upgrading FFmpeg.
FFMPEG_VERSION = "7.1"
FFMPEG_RELEASE_TAG = "n7.1-latest"
FFMPEG_DOWNLOAD_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    f"{FFMPEG_RELEASE_TAG}/"
    "ffmpeg-n7.1-latest-win64-gpl-7.1.zip"
)
# SHA256 checksum — fill in after first download and verify manually.
# Set to None to skip checksum verification (not recommended for production).
FFMPEG_SHA256: Optional[str] = None  # TODO: pin after first download

# ── aria2c ────────────────────────────────────────────────────────────────────
# aria2/aria2 GitHub releases — Windows x64 zip
ARIA2C_VERSION = "1.37.0"
ARIA2C_DOWNLOAD_URL = (
    "https://github.com/aria2/aria2/releases/download/"
    f"release-{ARIA2C_VERSION}/"
    f"aria2-{ARIA2C_VERSION}-win-64bit-build1.zip"
)
# SHA256 checksum — fill in after first download and verify manually.
ARIA2C_SHA256: Optional[str] = None  # TODO: pin after first download


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _print_progress(downloaded: int, total: int, name: str) -> None:
    """Print a simple download progress bar to stdout."""
    if total <= 0:
        print(f"\r  {name}: {downloaded // 1024} KB downloaded...", end="", flush=True)
        return
    pct = downloaded / total * 100
    bar_len = 40
    filled = int(bar_len * downloaded / total)
    bar = "#" * filled + "-" * (bar_len - filled)
    mb_done = downloaded / 1_048_576
    mb_total = total / 1_048_576
    print(
        f"\r  [{bar}] {pct:5.1f}%  {mb_done:.1f}/{mb_total:.1f} MB",
        end="",
        flush=True,
    )


def _download_bytes(url: str, name: str) -> bytes:
    """Download a URL to memory with progress reporting.

    Args:
        url:  URL to download.
        name: Display name for progress output.

    Returns:
        Raw bytes of the downloaded content.

    Raises:
        URLError: On network failure.
        RuntimeError: On HTTP error status.
    """
    print(f"  Downloading {name}...")
    print(f"  URL: {url}")

    req = Request(url, headers={"User-Agent": "AIFlow/1.0 (vendor downloader)"})
    try:
        with urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            buf = io.BytesIO()
            downloaded = 0
            chunk_size = 65536  # 64 KB chunks

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                buf.write(chunk)
                downloaded += len(chunk)
                _print_progress(downloaded, total, name)

    except URLError as exc:
        print()  # newline after progress
        raise URLError(f"Failed to download {name}: {exc}") from exc

    print()  # newline after progress bar
    data = buf.getvalue()
    print(f"  Downloaded {len(data) / 1_048_576:.1f} MB")
    return data


def _verify_sha256(data: bytes, expected: str, name: str) -> None:
    """Verify SHA256 checksum of downloaded data.

    Args:
        data:     Raw bytes to verify.
        expected: Expected hex digest string.
        name:     Display name for error messages.

    Raises:
        ValueError: If the checksum does not match.
    """
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected.lower():
        raise ValueError(
            f"SHA256 mismatch for {name}!\n"
            f"  Expected: {expected}\n"
            f"  Actual:   {actual}\n"
            "The download may be corrupted or tampered with."
        )
    print(f"  [OK] SHA256 verified: {actual[:16]}...")


def _find_on_path(name: str) -> Optional[Path]:
    """Return the path to a binary already available on the system PATH.

    Args:
        name: Binary name without extension (e.g. "ffmpeg").

    Returns:
        Absolute Path if found on PATH, else ``None``.
    """
    which = shutil.which(name)
    return Path(which) if which else None


def _verify_binary(binary_path: Path, version_flag: str = "--version") -> bool:
    """Run the binary with a version flag to confirm it works.

    Args:
        binary_path:  Path to the binary to test.
        version_flag: Flag used to print the version. FFmpeg/FFprobe use the
                      single-dash ``-version``; aria2c uses ``--version``.

    Returns:
        True if the binary ran successfully, False otherwise.
    """
    try:
        result = subprocess.run(
            [str(binary_path), version_flag],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            first_line = result.stdout.decode(errors="replace").splitlines()[0]
            print(f"  [OK] {binary_path.name}: {first_line}")
            return True
        else:
            print(f"  [X] {binary_path.name} {version_flag} returned code {result.returncode}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print(f"  [X] {binary_path.name} failed to run: {exc}")
        return False


# ─── FFmpeg download ──────────────────────────────────────────────────────────

def _find_ffmpeg_exe_in_zip(zf: zipfile.ZipFile) -> Optional[str]:
    """Find ffmpeg.exe inside the zip (may be in a subdirectory).

    BtbN builds have structure: ffmpeg-n7.x-win64-gpl-7.x/bin/ffmpeg.exe

    Args:
        zf: Open ZipFile object.

    Returns:
        Zip member path string, or None if not found.
    """
    for name in zf.namelist():
        if name.endswith("/bin/ffmpeg.exe") or name == "ffmpeg.exe":
            return name
    return None


def _find_ffprobe_exe_in_zip(zf: zipfile.ZipFile) -> Optional[str]:
    """Find ffprobe.exe inside the zip."""
    for name in zf.namelist():
        if name.endswith("/bin/ffprobe.exe") or name == "ffprobe.exe":
            return name
    return None


def download_ffmpeg(force: bool = False) -> bool:
    """Download FFmpeg to vendor/ffmpeg.exe and vendor/ffprobe.exe.

    Args:
        force: If True, re-download even if binaries already exist.

    Returns:
        True if download succeeded (or was skipped), False on failure.
    """
    ffmpeg_dest = _VENDOR_DIR / "ffmpeg.exe"
    ffprobe_dest = _VENDOR_DIR / "ffprobe.exe"

    if not force and ffmpeg_dest.is_file() and ffprobe_dest.is_file():
        print(f"  [OK] FFmpeg already present: {ffmpeg_dest}")
        print(f"  [OK] FFprobe already present: {ffprobe_dest}")
        _verify_binary(ffmpeg_dest, "-version")
        _verify_binary(ffprobe_dest, "-version")
        return True

    # Skip download when both are already available on the system PATH.
    # The runtime resolver (server/render/ffmpeg_utils.py) falls back to PATH
    # when vendor/ is empty, so there is no need to download a second copy.
    if not force:
        ffmpeg_path = _find_on_path("ffmpeg")
        ffprobe_path = _find_on_path("ffprobe")
        if ffmpeg_path and ffprobe_path:
            print(f"  [OK] FFmpeg found on PATH: {ffmpeg_path}")
            print(f"  [OK] FFprobe found on PATH: {ffprobe_path}")
            print("  Skipping download - the runtime will use the PATH binaries.")
            print("  (Use --force to download a pinned copy into vendor/ anyway.)")
            _verify_binary(ffmpeg_path, "-version")
            _verify_binary(ffprobe_path, "-version")
            return True

    try:
        data = _download_bytes(FFMPEG_DOWNLOAD_URL, f"FFmpeg {FFMPEG_VERSION}")
    except Exception as exc:
        print(f"  [X] Download failed: {exc}")
        return False

    if FFMPEG_SHA256:
        try:
            _verify_sha256(data, FFMPEG_SHA256, "FFmpeg")
        except ValueError as exc:
            print(f"  [X] {exc}")
            return False

    print("  Extracting ffmpeg.exe and ffprobe.exe...")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            ffmpeg_member = _find_ffmpeg_exe_in_zip(zf)
            ffprobe_member = _find_ffprobe_exe_in_zip(zf)

            if ffmpeg_member is None:
                print("  [X] ffmpeg.exe not found in zip archive")
                print("  Available entries (first 20):")
                for entry in zf.namelist()[:20]:
                    print(f"    {entry}")
                return False

            if ffprobe_member is None:
                print("  [X] ffprobe.exe not found in zip archive")
                return False

            _VENDOR_DIR.mkdir(parents=True, exist_ok=True)

            with zf.open(ffmpeg_member) as src, open(ffmpeg_dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"  Extracted -> {ffmpeg_dest}")

            with zf.open(ffprobe_member) as src, open(ffprobe_dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"  Extracted -> {ffprobe_dest}")

    except zipfile.BadZipFile as exc:
        print(f"  [X] Bad zip file: {exc}")
        return False

    # Verify both binaries work
    ok_ffmpeg = _verify_binary(ffmpeg_dest, "-version")
    ok_ffprobe = _verify_binary(ffprobe_dest, "-version")

    if ok_ffmpeg and ok_ffprobe:
        # Print checksums for pinning in README
        ffmpeg_sha = hashlib.sha256(ffmpeg_dest.read_bytes()).hexdigest()
        ffprobe_sha = hashlib.sha256(ffprobe_dest.read_bytes()).hexdigest()
        print(f"  ffmpeg.exe  SHA256: {ffmpeg_sha}")
        print(f"  ffprobe.exe SHA256: {ffprobe_sha}")

    return ok_ffmpeg and ok_ffprobe


# ─── aria2c download ──────────────────────────────────────────────────────────

def _find_aria2c_exe_in_zip(zf: zipfile.ZipFile) -> Optional[str]:
    """Find aria2c.exe inside the zip.

    aria2 releases have structure: aria2-1.37.0-win-64bit-build1/aria2c.exe

    Args:
        zf: Open ZipFile object.

    Returns:
        Zip member path string, or None if not found.
    """
    for name in zf.namelist():
        if name.endswith("/aria2c.exe") or name == "aria2c.exe":
            return name
    return None


def download_aria2c(force: bool = False) -> bool:
    """Download aria2c to vendor/aria2c.exe.

    Args:
        force: If True, re-download even if binary already exists.

    Returns:
        True if download succeeded (or was skipped), False on failure.
    """
    aria2c_dest = _VENDOR_DIR / "aria2c.exe"

    if not force and aria2c_dest.is_file():
        print(f"  [OK] aria2c already present: {aria2c_dest}")
        _verify_binary(aria2c_dest)
        return True

    # Skip download when aria2c is already available on the system PATH.
    if not force:
        aria2c_path = _find_on_path("aria2c")
        if aria2c_path:
            print(f"  [OK] aria2c found on PATH: {aria2c_path}")
            print("  Skipping download - the runtime will use the PATH binary.")
            print("  (Use --force to download a pinned copy into vendor/ anyway.)")
            _verify_binary(aria2c_path)
            return True

    try:
        data = _download_bytes(ARIA2C_DOWNLOAD_URL, f"aria2c {ARIA2C_VERSION}")
    except Exception as exc:
        print(f"  [X] Download failed: {exc}")
        return False

    if ARIA2C_SHA256:
        try:
            _verify_sha256(data, ARIA2C_SHA256, "aria2c")
        except ValueError as exc:
            print(f"  [X] {exc}")
            return False

    print("  Extracting aria2c.exe...")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            aria2c_member = _find_aria2c_exe_in_zip(zf)

            if aria2c_member is None:
                print("  [X] aria2c.exe not found in zip archive")
                print("  Available entries (first 20):")
                for entry in zf.namelist()[:20]:
                    print(f"    {entry}")
                return False

            _VENDOR_DIR.mkdir(parents=True, exist_ok=True)

            with zf.open(aria2c_member) as src, open(aria2c_dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            print(f"  Extracted -> {aria2c_dest}")

    except zipfile.BadZipFile as exc:
        print(f"  [X] Bad zip file: {exc}")
        return False

    ok = _verify_binary(aria2c_dest)

    if ok:
        aria2c_sha = hashlib.sha256(aria2c_dest.read_bytes()).hexdigest()
        print(f"  aria2c.exe  SHA256: {aria2c_sha}")

    return ok


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    """Main entry point.

    Returns:
        Exit code: 0 = all binaries ready, 1 = one or more failures.
    """
    parser = argparse.ArgumentParser(
        description="Download FFmpeg and aria2c vendor binaries for AIFlow.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/download_vendor.py           # download missing binaries
  python scripts/download_vendor.py --force   # re-download all binaries
  python scripts/download_vendor.py --ffmpeg  # download FFmpeg only
  python scripts/download_vendor.py --aria2c  # download aria2c only
        """,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download binaries even if they already exist.",
    )
    parser.add_argument(
        "--ffmpeg",
        action="store_true",
        help="Download FFmpeg only (skip aria2c).",
    )
    parser.add_argument(
        "--aria2c",
        action="store_true",
        help="Download aria2c only (skip FFmpeg).",
    )
    args = parser.parse_args()

    # Windows consoles often default to cp1252, which cannot encode the
    # box-drawing / checkmark characters used below. Force UTF-8 output so the
    # script does not crash with UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    # If neither flag is set, download both
    do_ffmpeg = args.ffmpeg or (not args.ffmpeg and not args.aria2c)
    do_aria2c = args.aria2c or (not args.ffmpeg and not args.aria2c)

    _VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Vendor directory: {_VENDOR_DIR}")
    print()

    results: list[bool] = []

    if do_ffmpeg:
        print(f"-- FFmpeg {FFMPEG_VERSION} {'-' * 40}")
        ok = download_ffmpeg(force=args.force)
        results.append(ok)
        print()

    if do_aria2c:
        print(f"-- aria2c {ARIA2C_VERSION} {'-' * 40}")
        ok = download_aria2c(force=args.force)
        results.append(ok)
        print()

    # Summary
    all_ok = all(results)
    if all_ok:
        print("[OK] All vendor binaries ready.")
        print()
        print("Next steps:")
        print("  1. Pin SHA256 checksums in vendor/README.md")
        print("  2. Commit vendor/*.exe to the repository (ADR-005)")
    else:
        print("[X] Some downloads failed. Check the output above.")
        print()
        print("Troubleshooting:")
        print("  - Check your internet connection")
        print("  - Try --force to retry a failed download")
        print("  - Download manually from the URLs in vendor/README.md")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
