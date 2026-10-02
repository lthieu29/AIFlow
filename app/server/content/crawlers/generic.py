"""Generic yt-dlp fallback downloader.

Works for any URL that yt-dlp supports (YouTube, Vimeo, Twitter/X, Reddit,
Instagram, etc.).  Used by :class:`DownloadManager` when no platform-specific
downloader matches the URL.

Also provides :func:`detect_platform` for URL-based platform detection.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from server.content.crawlers.base import (
    BaseDownloader,
    DownloadError,
    DownloadResult,
)


# ─── Platform detection ───────────────────────────────────────────────────────

# Ordered list of (pattern, platform_name) tuples.
# First match wins.
_PLATFORM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"bilibili\.com|b23\.tv", re.IGNORECASE), "bilibili"),
    (re.compile(r"douyin\.com|v\.douyin\.com", re.IGNORECASE), "douyin"),
    (re.compile(r"tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com", re.IGNORECASE), "tiktok"),
    (re.compile(r"youtube\.com|youtu\.be", re.IGNORECASE), "youtube"),
    (re.compile(r"vimeo\.com", re.IGNORECASE), "vimeo"),
    (re.compile(r"twitter\.com|x\.com", re.IGNORECASE), "twitter"),
    (re.compile(r"instagram\.com", re.IGNORECASE), "instagram"),
    (re.compile(r"reddit\.com|redd\.it", re.IGNORECASE), "reddit"),
    (re.compile(r"facebook\.com|fb\.watch", re.IGNORECASE), "facebook"),
    (re.compile(r"weibo\.com", re.IGNORECASE), "weibo"),
    (re.compile(r"xiaohongshu\.com|xhslink\.com", re.IGNORECASE), "xiaohongshu"),
]


def detect_platform(url: str) -> str:
    """Detect the platform from a URL.

    Args:
        url: Video URL to inspect.

    Returns:
        Platform identifier string (e.g. ``"bilibili"``, ``"youtube"``).
        Returns ``"generic"`` if no known platform is detected.
    """
    for pattern, platform in _PLATFORM_PATTERNS:
        if pattern.search(url):
            return platform
    return "generic"


# ─── Downloader ───────────────────────────────────────────────────────────────


class GenericDownloader(BaseDownloader):
    """Generic yt-dlp downloader — works for any yt-dlp supported URL.

    This is the fallback used by :class:`~server.content.crawlers.manager.DownloadManager`
    when no platform-specific downloader matches the URL.

    Example::

        downloader = GenericDownloader()
        result = downloader.download(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir=Path("storage/media/proj_001"),
        )
    """

    platform = "generic"

    def download(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
    ) -> DownloadResult:
        """Download a video from any yt-dlp supported URL.

        Args:
            url:        Video URL.
            output_dir: Directory where the video will be saved.
            cookies:    Optional path to a Netscape cookies file.

        Returns:
            :class:`~server.content.crawlers.base.DownloadResult`.

        Raises:
            :class:`~server.content.crawlers.base.DownloadError`: On failure.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Detect actual platform for metadata
        detected = detect_platform(url)

        cmd = self._build_ytdlp_cmd(
            url,
            output_dir,
            cookies=cookies,
            extra_args=["--no-playlist"],
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max
            )
        except subprocess.TimeoutExpired as exc:
            raise DownloadError(
                url,
                "Download timed out after 600 seconds",
                code="DOWNLOAD_TIMEOUT",
            ) from exc
        except OSError as exc:
            raise DownloadError(
                url,
                f"Failed to launch yt-dlp: {exc}",
                code="YTDLP_LAUNCH_FAILED",
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise DownloadError(
                url,
                f"yt-dlp exited with code {result.returncode}: {stderr[:500]}",
                code="YTDLP_ERROR",
            )

        video_file = self._find_downloaded_file(output_dir)
        if video_file is None:
            raise DownloadError(
                url,
                "yt-dlp succeeded but no video file found in output directory",
                code="OUTPUT_NOT_FOUND",
            )

        title, duration = self._parse_info_json(output_dir, url)

        return DownloadResult(
            url=url,
            output_path=video_file,
            title=title,
            duration=duration,
            platform=detected,
            metadata={
                "detected_platform": detected,
                "stdout": result.stdout[-2000:] if result.stdout else "",
            },
        )
