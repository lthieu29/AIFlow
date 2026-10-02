"""Downloader framework for video platforms.

Provides platform-specific downloaders (Bilibili, Douyin, TikTok) and a
generic yt-dlp fallback, all orchestrated by DownloadManager.

Usage:
    from server.content.crawlers.manager import DownloadManager

    manager = DownloadManager()
    result = manager.download("https://www.bilibili.com/video/BV1xx411c7mD", output_dir)
"""

from server.content.crawlers.base import (
    DownloadResult,
    DownloadError,
    BaseDownloader,
    find_aria2c,
    find_ytdlp,
)
from server.content.crawlers.manager import DownloadManager

__all__ = [
    "DownloadResult",
    "DownloadError",
    "BaseDownloader",
    "find_aria2c",
    "find_ytdlp",
    "DownloadManager",
]
