"""Douyin downloader.

Native-API-first strategy (ADR-0004): tries the Douyin web API with A-Bogus
signing first, then falls back to yt-dlp when signing is unavailable, the API
rejects the request, or any error occurs.

Cookies are typically required for Douyin since most content is region-locked
or requires login.

Supported URL formats:
- https://www.douyin.com/video/7123456789012345678
- https://v.douyin.com/iXXXXXX/  (short links — resolved via redirect)
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from server.content.crawlers.base import (
    BaseDownloader,
    DownloadError,
    DownloadResult,
)
from server.content.crawlers.cookies.manager import read_cookie_string
from server.content.crawlers.native import (
    DEFAULT_UA,
    NativeAPIError,
    douyin_fetch_video_url,
    download_url_to_file,
    extract_douyin_aweme_id,
    resolve_redirect,
)


class DouyinDownloader(BaseDownloader):
    """Download Douyin videos via the native web API (A-Bogus), with yt-dlp fallback.

    Cookies are strongly recommended for Douyin downloads.  Without them the
    native API may return no detail and the downloader falls back to yt-dlp.

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
        """Download a Douyin video (native API first, yt-dlp fallback).

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

        # ── Native API path (A-Bogus) ─────────────────────────────────────────
        try:
            return self._download_native(url, output_dir, cookies)
        except NativeAPIError as exc:
            # Expected, recoverable: fall back to yt-dlp.
            from loguru import logger as _logger

            _logger.info(
                "[douyin] native API path unavailable ({}); falling back to yt-dlp",
                exc,
            )

        return self._download_ytdlp(url, output_dir, cookies)

    # ── Native API path ───────────────────────────────────────────────────────

    def _download_native(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path],
    ) -> DownloadResult:
        """Resolve + download via the Douyin web API. Raises NativeAPIError on failure."""
        cookie_str = read_cookie_string(cookies)

        async def _run() -> tuple[str, str, float, str]:
            resolved = url
            if "v.douyin.com" in url or "/video/" not in url:
                resolved = await resolve_redirect(url, cookie_str)
            aweme_id = extract_douyin_aweme_id(resolved)
            if not aweme_id:
                raise NativeAPIError(
                    f"Could not extract aweme_id from URL: {resolved}",
                    code="DOUYIN_NO_AWEME_ID",
                )
            video_url, title, duration = await douyin_fetch_video_url(
                aweme_id, cookie=cookie_str, user_agent=DEFAULT_UA
            )
            out_path = output_dir / f"douyin_{aweme_id}.mp4"
            await download_url_to_file(
                video_url,
                out_path,
                referer=f"https://www.douyin.com/video/{aweme_id}",
                cookie=cookie_str,
                user_agent=DEFAULT_UA,
            )
            return str(out_path), title, duration, aweme_id

        out_str, title, duration, aweme_id = asyncio.run(_run())
        out_path = Path(out_str)

        from loguru import logger as _logger

        _logger.info("[douyin] native API download succeeded → {}", out_path)
        return DownloadResult(
            url=url,
            output_path=out_path,
            title=title,
            duration=duration,
            platform=self.platform,
            metadata={"source": "native_api", "aweme_id": aweme_id},
        )

    # ── yt-dlp fallback ─────────────────────────────────────────────────────────

    def _download_ytdlp(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path],
    ) -> DownloadResult:
        """Original yt-dlp download path (fallback)."""
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
                "source": "yt_dlp",
                "stdout": result.stdout[-2000:] if result.stdout else "",
            },
        )
