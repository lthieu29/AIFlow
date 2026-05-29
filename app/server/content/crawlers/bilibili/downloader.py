"""Bilibili downloader.

Downloads Bilibili videos using yt-dlp with optional cookie authentication.
Supports:
- Full URLs: https://www.bilibili.com/video/BV1xx411c7mD
- BV IDs:    BV1xx411c7mD
- AV IDs:    av170001 / 170001

aria2c is used for parallel segment download when available (vendor/aria2c.exe
or PATH), significantly speeding up DASH stream downloads.
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


# ─── URL normalisation ────────────────────────────────────────────────────────

_BV_RE = re.compile(r"^BV[0-9A-Za-z]{10}$")
_AV_RE = re.compile(r"^(?:av)?(\d+)$", re.IGNORECASE)
_BILIBILI_URL_RE = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10}|av\d+)",
    re.IGNORECASE,
)


def _normalise_bilibili_url(url: str) -> str:
    """Convert a BV/AV ID or partial URL to a canonical Bilibili URL.

    Args:
        url: Raw input — may be a full URL, a BV ID, or an AV ID.

    Returns:
        Canonical ``https://www.bilibili.com/video/<id>`` URL.
    """
    url = url.strip()

    # Already a full URL
    if url.startswith("http"):
        return url

    # BV ID
    if _BV_RE.match(url):
        return f"https://www.bilibili.com/video/{url}"

    # AV ID (with or without "av" prefix)
    m = _AV_RE.match(url)
    if m:
        return f"https://www.bilibili.com/video/av{m.group(1)}"

    # Unknown format — pass through and let yt-dlp handle it
    return url


# ─── Downloader ───────────────────────────────────────────────────────────────


class BilibiliDownloader(BaseDownloader):
    """Download Bilibili videos via yt-dlp.

    Uses yt-dlp with optional Netscape-format cookies for authenticated
    downloads (required for high-quality streams and member-only content).
    When aria2c is available it is used as the external downloader for
    parallel segment fetching.

    Example::

        downloader = BilibiliDownloader()
        result = downloader.download(
            "BV1xx411c7mD",
            output_dir=Path("storage/media/proj_001"),
            cookies=Path("storage/cookies/bilibili.txt"),
        )
        print(result.title, result.duration)
    """

    platform = "bilibili"

    def download(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
    ) -> DownloadResult:
        """Download a Bilibili video.

        Args:
            url:        Bilibili URL, BV ID, or AV ID.
            output_dir: Directory where the video will be saved.
            cookies:    Optional path to a Netscape cookies file for
                        authenticated access.

        Returns:
            :class:`~server.content.crawlers.base.DownloadResult` with
            metadata about the downloaded file.

        Raises:
            :class:`~server.content.crawlers.base.DownloadError`: On failure.
        """
        canonical_url = _normalise_bilibili_url(url)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Bilibili-specific extra args: prefer Chinese subtitles if available
        extra_args = [
            "--sub-lang", "zh-Hans,zh-Hant,zh",
            "--write-subs",
            "--embed-subs",
        ]

        cmd = self._build_ytdlp_cmd(
            canonical_url,
            output_dir,
            cookies=cookies,
            extra_args=extra_args,
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
                canonical_url,
                "Download timed out after 600 seconds",
                code="DOWNLOAD_TIMEOUT",
            ) from exc
        except OSError as exc:
            raise DownloadError(
                canonical_url,
                f"Failed to launch yt-dlp: {exc}",
                code="YTDLP_LAUNCH_FAILED",
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise DownloadError(
                canonical_url,
                f"yt-dlp exited with code {result.returncode}: {stderr[:500]}",
                code="YTDLP_ERROR",
            )

        # Locate downloaded file
        video_file = self._find_downloaded_file(output_dir)
        if video_file is None:
            raise DownloadError(
                canonical_url,
                "yt-dlp succeeded but no video file found in output directory",
                code="OUTPUT_NOT_FOUND",
            )

        title, duration = self._parse_info_json(output_dir, canonical_url)

        return DownloadResult(
            url=canonical_url,
            output_path=video_file,
            title=title,
            duration=duration,
            platform=self.platform,
            metadata={
                "original_url": url,
                "stdout": result.stdout[-2000:] if result.stdout else "",
            },
        )
