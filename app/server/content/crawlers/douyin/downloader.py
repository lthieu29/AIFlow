"""Douyin downloader.

Downloads Douyin (抖音) videos using yt-dlp with optional cookie
authentication.  Cookies are typically required for Douyin since most
content is region-locked or requires login.

Supported URL formats:
- https://www.douyin.com/video/7123456789012345678
- https://v.douyin.com/iXXXXXX/  (short links — yt-dlp follows redirects)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from server.content.crawlers.base import (
    BaseDownloader,
    DownloadError,
    DownloadResult,
)


class DouyinDownloader(BaseDownloader):
    """Download Douyin videos via yt-dlp.

    Cookies are strongly recommended for Douyin downloads.  Without them
    yt-dlp may only be able to fetch watermarked or low-quality streams.

    Example::

        downloader = DouyinDownloader()
        result = downloader.download(
            "https://www.douyin.com/video/7123456789012345678",
            output_dir=Path("storage/media/proj_001"),
            cookies=Path("storage/cookies/douyin.txt"),
        )
    """

    platform = "douyin"

    def download(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
    ) -> DownloadResult:
        """Download a Douyin video.

        Args:
            url:        Douyin video URL (full or short link).
            output_dir: Directory where the video will be saved.
            cookies:    Optional path to a Netscape cookies file.

        Returns:
            :class:`~server.content.crawlers.base.DownloadResult`.

        Raises:
            :class:`~server.content.crawlers.base.DownloadError`: On failure.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Douyin-specific: prefer no-watermark format when available
        extra_args = [
            "--no-playlist",
        ]

        cmd = self._build_ytdlp_cmd(
            url,
            output_dir,
            cookies=cookies,
            extra_args=extra_args,
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes max
            )
        except subprocess.TimeoutExpired as exc:
            raise DownloadError(
                url,
                "Download timed out after 300 seconds",
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
            platform=self.platform,
            metadata={
                "stdout": result.stdout[-2000:] if result.stdout else "",
            },
        )
