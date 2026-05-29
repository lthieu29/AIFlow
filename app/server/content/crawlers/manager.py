"""Download manager — auto-detects platform and dispatches to the right downloader.

Usage::

    from server.content.crawlers.manager import DownloadManager
    from pathlib import Path

    manager = DownloadManager()
    result = manager.download(
        "https://www.bilibili.com/video/BV1xx411c7mD",
        output_dir=Path("storage/media/proj_001"),
        cookies=Path("storage/cookies/bilibili.txt"),
    )
    print(result.title, result.output_path)

The manager uses :func:`~server.content.crawlers.generic.detect_platform` to
identify the platform from the URL, then instantiates the appropriate
platform-specific downloader.  If no specific downloader is registered for
the detected platform, it falls back to
:class:`~server.content.crawlers.generic.GenericDownloader`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from server.content.crawlers.base import BaseDownloader, DownloadResult
from server.content.crawlers.generic import GenericDownloader, detect_platform


class DownloadManager:
    """Orchestrates downloads across multiple platforms.

    Platform-specific downloaders are registered at construction time.
    :meth:`download` auto-detects the platform from the URL and delegates
    to the appropriate downloader, falling back to
    :class:`~server.content.crawlers.generic.GenericDownloader` for unknown
    platforms.

    Attributes:
        _downloaders: Mapping of platform name → downloader instance.
        _generic:     Fallback downloader for unrecognised platforms.
    """

    def __init__(self) -> None:
        # Import here to avoid circular imports at module level
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader
        from server.content.crawlers.douyin.downloader import DouyinDownloader
        from server.content.crawlers.tiktok.downloader import TikTokDownloader

        self._downloaders: dict[str, BaseDownloader] = {
            "bilibili": BilibiliDownloader(),
            "douyin": DouyinDownloader(),
            "tiktok": TikTokDownloader(),
        }
        self._generic = GenericDownloader()

    def download(
        self,
        url: str,
        output_dir: Path,
        cookies: Optional[Path] = None,
    ) -> DownloadResult:
        """Download a video from *url*.

        Auto-detects the platform and uses the appropriate downloader.
        Falls back to :class:`~server.content.crawlers.generic.GenericDownloader`
        for unrecognised platforms.

        Args:
            url:        Video URL to download.
            output_dir: Directory where the downloaded file will be saved.
            cookies:    Optional path to a Netscape-format cookies file.
                        Passed to the platform downloader as-is.

        Returns:
            :class:`~server.content.crawlers.base.DownloadResult` with
            metadata about the downloaded file.

        Raises:
            :class:`~server.content.crawlers.base.DownloadError`: On failure.
        """
        platform = detect_platform(url)
        downloader = self._downloaders.get(platform, self._generic)
        return downloader.download(url, output_dir, cookies=cookies)

    def get_downloader(self, platform: str) -> BaseDownloader:
        """Return the downloader registered for *platform*.

        Args:
            platform: Platform identifier (e.g. ``"bilibili"``).

        Returns:
            The registered :class:`BaseDownloader`, or the generic fallback
            if no specific downloader is registered.
        """
        return self._downloaders.get(platform, self._generic)

    def supported_platforms(self) -> list[str]:
        """Return the list of platforms with dedicated downloaders.

        Returns:
            Sorted list of platform names (e.g. ``["bilibili", "douyin", "tiktok"]``).
        """
        return sorted(self._downloaders.keys())
