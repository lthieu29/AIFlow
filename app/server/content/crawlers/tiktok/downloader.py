"""TikTok downloader.

Downloads TikTok videos using yt-dlp with optional cookie authentication.
Cookies may be required for age-restricted content or to avoid rate limiting.

Supported URL formats:
- https://www.tiktok.com/@username/video/7123456789012345678
- https://vm.tiktok.com/XXXXXXXX/  (short links — yt-dlp follows redirects)
- https://vt.tiktok.com/XXXXXXXX/  (short links)
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


class TikTokDownloader(BaseDownloader):
    """Download TikTok videos via yt-dlp.

    Example::

        downloader = TikTokDownloader()
        result = downloader.download(
            "https://www.tiktok.com/@user/video/7123456789012345678",
            output_dir=Path("storage/media/proj_001"),
            cookies=Path("storage/cookies/tiktok.txt"),
        )
    """

    platform = "tiktok"

    def download(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
    ) -> DownloadResult:
        """Download a TikTok video.

        Args:
            url:        TikTok video URL (full or short link).
            output_dir: Directory where the video will be saved.
            cookies:    Optional path to a Netscape cookies file.

        Returns:
            :class:`~server.content.crawlers.base.DownloadResult`.

        Raises:
            :class:`~server.content.crawlers.base.DownloadError`: On failure.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

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
