"""Base downloader infrastructure.

Defines:
- DownloadResult: dataclass for successful download metadata
- DownloadError: exception for download failures
- BaseDownloader: abstract base class all platform downloaders inherit from
- find_aria2c(): locate aria2c binary (vendor/ first, then PATH)
- find_ytdlp(): locate yt-dlp binary or Python package (vendor/ first, then PATH)

Binary search order (matches ffmpeg_utils.py pattern):
    1. vendor/aria2c.exe / vendor/yt-dlp.exe  (Windows bundled)
    2. System PATH via shutil.which
    3. Python package (yt-dlp only — importable as module)
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Vendor directory ─────────────────────────────────────────────────────────

# Resolved at import time: server/content/crawlers/ → parents[3] = app/
_VENDOR_DIR = Path(__file__).resolve().parents[3] / "vendor"


# ─── Binary discovery ─────────────────────────────────────────────────────────


def find_aria2c() -> Optional[Path]:
    """Locate the aria2c binary.

    Search order:
    1. ``vendor/aria2c.exe`` (Windows bundled binary)
    2. System PATH (``shutil.which``)

    Returns:
        Absolute path to aria2c, or ``None`` if not found.
    """
    vendor_path = _VENDOR_DIR / "aria2c.exe"
    if vendor_path.is_file():
        return vendor_path

    which = shutil.which("aria2c")
    if which:
        return Path(which)

    return None


def find_ytdlp() -> Optional[Path]:
    """Locate the yt-dlp binary or Python package.

    Search order:
    1. ``vendor/yt-dlp.exe`` (Windows bundled binary)
    2. System PATH (``shutil.which`` for ``yt-dlp`` or ``yt_dlp``)
    3. Python package (``import yt_dlp`` — importable as module)

    Returns:
        Absolute path to yt-dlp executable, or ``None`` if only the Python
        package is available (callers should use ``yt_dlp`` module directly
        in that case).  Returns a sentinel ``Path("yt_dlp:module")`` when
        only the Python package is found so callers can distinguish.
    """
    # 1. Vendor binary
    vendor_path = _VENDOR_DIR / "yt-dlp.exe"
    if vendor_path.is_file():
        return vendor_path

    # 2. PATH binary
    for name in ("yt-dlp", "yt_dlp"):
        which = shutil.which(name)
        if which:
            return Path(which)

    # 3. Python package fallback
    try:
        import yt_dlp  # noqa: F401
        return Path("yt_dlp:module")
    except ImportError:
        pass

    return None


# ─── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class DownloadResult:
    """Metadata for a successfully downloaded video.

    Attributes:
        url:         Original URL that was downloaded.
        output_path: Absolute path to the downloaded file on disk.
        title:       Video title (may be empty string if unavailable).
        duration:    Video duration in seconds (0.0 if unavailable).
        platform:    Platform identifier, e.g. "bilibili", "douyin", "tiktok",
                     "generic".
        metadata:    Extra platform-specific metadata (free-form dict).
    """

    url: str
    output_path: Path
    title: str
    duration: float
    platform: str
    metadata: dict = field(default_factory=dict)


# ─── Exception ────────────────────────────────────────────────────────────────


class DownloadError(Exception):
    """Raised when a download fails.

    Attributes:
        url:     The URL that failed.
        reason:  Human-readable failure reason.
        code:    Optional machine-readable error code.
    """

    def __init__(self, url: str, reason: str, code: str = "DOWNLOAD_FAILED") -> None:
        self.url = url
        self.reason = reason
        self.code = code
        super().__init__(f"[{code}] {reason} (url={url})")


# ─── Abstract base ────────────────────────────────────────────────────────────


class BaseDownloader(ABC):
    """Abstract base class for all platform downloaders.

    Subclasses implement :meth:`download` for their specific platform.
    The base class provides shared helpers for building yt-dlp command lines
    and running aria2c for parallel segment downloads.
    """

    #: Platform identifier — set by each subclass.
    platform: str = "unknown"

    @abstractmethod
    def download(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
    ) -> DownloadResult:
        """Download a video from *url* into *output_dir*.

        Args:
            url:        Video URL to download.
            output_dir: Directory where the downloaded file will be saved.
                        Created if it does not exist.
            cookies:    Optional path to a Netscape-format cookies file for
                        authenticated downloads.

        Returns:
            :class:`DownloadResult` with metadata about the downloaded file.

        Raises:
            :class:`DownloadError`: On any unrecoverable download failure.
        """
        ...

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _build_ytdlp_cmd(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
        extra_args: Optional[list[str]] = None,
    ) -> list[str]:
        """Build a yt-dlp command list for subprocess execution.

        Args:
            url:        Video URL.
            output_dir: Output directory (must exist before calling).
            cookies:    Optional cookies file path.
            extra_args: Additional yt-dlp arguments to append.

        Returns:
            Command list suitable for ``subprocess.run``.

        Raises:
            DownloadError: If yt-dlp cannot be located.
        """
        ytdlp = find_ytdlp()
        if ytdlp is None:
            raise DownloadError(
                url,
                "yt-dlp not found. Place yt-dlp.exe in vendor/ or install via pip.",
                code="YTDLP_NOT_FOUND",
            )

        # When only the Python module is available, invoke via python -m yt_dlp
        if str(ytdlp) == "yt_dlp:module":
            import sys
            cmd: list[str] = [sys.executable, "-m", "yt_dlp"]
        else:
            cmd = [str(ytdlp)]

        # Output template: title.ext inside output_dir
        output_template = str(output_dir / "%(title)s.%(ext)s")
        cmd += ["--output", output_template]

        # Prefer mp4 container
        cmd += ["--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]

        # Write metadata JSON for title/duration extraction
        cmd += ["--write-info-json", "--no-playlist"]

        # Cookies
        if cookies and cookies.is_file():
            cmd += ["--cookies", str(cookies)]

        # aria2c external downloader for parallel segments
        aria2c = find_aria2c()
        if aria2c is not None:
            cmd += [
                "--external-downloader", str(aria2c),
                "--external-downloader-args",
                "aria2c:--max-connection-per-server=16 --split=16 --min-split-size=1M",
            ]

        if extra_args:
            cmd += extra_args

        cmd.append(url)
        return cmd

    def _parse_info_json(self, output_dir: Path, url: str) -> tuple[str, float]:
        """Extract title and duration from the yt-dlp .info.json file.

        yt-dlp writes ``<title>.info.json`` alongside the downloaded file.
        This method finds the first ``.info.json`` in *output_dir* and reads
        ``title`` and ``duration`` fields.

        Args:
            output_dir: Directory where yt-dlp wrote its output.
            url:        Original URL (used in error messages only).

        Returns:
            ``(title, duration)`` tuple.  Falls back to ``("", 0.0)`` if the
            file is missing or malformed.
        """
        import json

        info_files = list(output_dir.glob("*.info.json"))
        if not info_files:
            return "", 0.0

        try:
            data = json.loads(info_files[0].read_text(encoding="utf-8"))
            title = data.get("title", "") or ""
            duration = float(data.get("duration") or 0.0)
            return title, duration
        except (json.JSONDecodeError, ValueError, OSError):
            return "", 0.0

    def _find_downloaded_file(self, output_dir: Path) -> Optional[Path]:
        """Find the primary downloaded video file in *output_dir*.

        Looks for common video extensions, excluding ``.info.json`` and
        other metadata files.

        Args:
            output_dir: Directory to search.

        Returns:
            Path to the first video file found, or ``None``.
        """
        video_extensions = {".mp4", ".mkv", ".webm", ".flv", ".avi", ".mov", ".m4v"}
        for path in sorted(output_dir.iterdir()):
            if path.suffix.lower() in video_extensions:
                return path
        return None
