"""Bilibili downloader.

Native-API-first strategy (ADR-0004): tries the Bilibili web API with WBI
signing first (view → WBI-signed playurl → DASH merge), then falls back to
yt-dlp when signing/keys are unavailable, the API rejects the request, or any
error occurs.

Supports:
- Full URLs: https://www.bilibili.com/video/BV1xx411c7mD
- BV IDs:    BV1xx411c7mD
- AV IDs:    av170001 / 170001

aria2c is used for parallel segment download (yt-dlp path) when available.
"""

from __future__ import annotations

import asyncio
import re
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
    bilibili_fetch_streams,
    download_url_to_file,
    extract_bilibili_id,
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
        """Download a Bilibili video (native WBI API first, yt-dlp fallback).

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

        # ── Native API path (WBI) ─────────────────────────────────────────────
        try:
            return self._download_native(url, canonical_url, output_dir, cookies)
        except NativeAPIError as exc:
            from loguru import logger as _logger

            _logger.info(
                "[bilibili] native API path unavailable ({}); falling back to yt-dlp",
                exc,
            )

        return self._download_ytdlp(url, canonical_url, output_dir, cookies)

    # ── Native API path ───────────────────────────────────────────────────────

    def _download_native(
        self,
        original_url: str,
        canonical_url: str,
        output_dir: Path,
        cookies: Optional[Path],
    ) -> DownloadResult:
        """Resolve + download via the WBI-signed playurl API. Raises NativeAPIError."""
        from server.content.crawlers.stream_merger import StreamMerger

        cookie_str = read_cookie_string(cookies)
        bvid, aid = extract_bilibili_id(canonical_url)
        if not bvid and aid is None:
            raise NativeAPIError(
                f"Could not extract BV/AV id from URL: {canonical_url}",
                code="BILI_NO_ID",
            )

        async def _run() -> dict:
            streams = await bilibili_fetch_streams(
                bvid, aid, cookie=cookie_str, user_agent=DEFAULT_UA
            )
            stem = bvid or f"av{aid}"
            referer = streams["referer"]

            if streams["audio_url"]:
                # DASH: download video + audio separately, then mux.
                video_tmp = output_dir / f"{stem}_video.m4s"
                audio_tmp = output_dir / f"{stem}_audio.m4s"
                await download_url_to_file(
                    streams["video_url"], video_tmp, referer=referer,
                    cookie=cookie_str, user_agent=DEFAULT_UA,
                )
                await download_url_to_file(
                    streams["audio_url"], audio_tmp, referer=referer,
                    cookie=cookie_str, user_agent=DEFAULT_UA,
                )
                streams["_video_tmp"] = str(video_tmp)
                streams["_audio_tmp"] = str(audio_tmp)
            else:
                # Progressive MP4 (durl) — single file.
                out_path = output_dir / f"{stem}.mp4"
                await download_url_to_file(
                    streams["video_url"], out_path, referer=referer,
                    cookie=cookie_str, user_agent=DEFAULT_UA,
                )
                streams["_final"] = str(out_path)
            streams["_stem"] = stem
            return streams

        streams = asyncio.run(_run())
        stem = streams["_stem"]

        if streams.get("_final"):
            final_path = Path(streams["_final"])
        else:
            # Mux DASH video + audio (StreamMerger needs ffmpeg).
            try:
                merger = StreamMerger()
            except FileNotFoundError as exc:
                raise NativeAPIError(
                    f"ffmpeg required to merge DASH streams: {exc}",
                    code="FFMPEG_MISSING",
                ) from exc
            final_path = output_dir / f"{stem}.mp4"
            merger.merge(
                Path(streams["_video_tmp"]),
                Path(streams["_audio_tmp"]),
                final_path,
            )
            Path(streams["_video_tmp"]).unlink(missing_ok=True)
            Path(streams["_audio_tmp"]).unlink(missing_ok=True)

        from loguru import logger as _logger

        _logger.info("[bilibili] native API download succeeded → {}", final_path)
        return DownloadResult(
            url=canonical_url,
            output_path=final_path,
            title=streams["title"],
            duration=streams["duration"],
            platform=self.platform,
            metadata={"source": "native_api", "original_url": original_url},
        )

    # ── yt-dlp fallback ─────────────────────────────────────────────────────────

    def _download_ytdlp(
        self,
        original_url: str,
        canonical_url: str,
        output_dir: Path,
        cookies: Optional[Path],
    ) -> DownloadResult:
        """Original yt-dlp download path (fallback)."""
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
                "source": "yt_dlp",
                "original_url": original_url,
                "stdout": result.stdout[-2000:] if result.stdout else "",
            },
        )
