"""Video download helper — fetch a signed URL and save to disk.

Usage::

    from pathlib import Path
    from server.flow.downloader import download_video

    out = await download_video(
        signed_url="https://flow-content.googleapis.com/...",
        out_path=Path("storage/media/proj-123/video_1234567890.mp4"),
    )
    print(f"Saved {out.stat().st_size:,} bytes to {out}")
"""

from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger

# Minimum acceptable video file size (100 KB).
# Anything smaller is almost certainly a corrupt or empty response.
MIN_VIDEO_SIZE_BYTES = 100 * 1024


async def download_video(signed_url: str, out_path: Path) -> Path:
    """Download video bytes from a signed URL and write them to *out_path*.

    Creates parent directories as needed. Verifies the downloaded file is
    larger than MIN_VIDEO_SIZE_BYTES (100 KB) to catch silent failures.

    Args:
        signed_url: Signed FIFE / CDN URL returned by the Flow API.
        out_path: Destination file path (will be created or overwritten).

    Returns:
        *out_path* after successful download and size verification.

    Raises:
        RuntimeError: If the HTTP request fails, or the downloaded file is
                      smaller than MIN_VIDEO_SIZE_BYTES.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"downloader: downloading video → {out_path}")
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as http:
            resp = await http.get(signed_url)
            resp.raise_for_status()
            video_bytes = resp.content
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"downloader: failed to download video from signed URL: {exc}"
        ) from exc

    out_path.write_bytes(video_bytes)
    file_size = out_path.stat().st_size
    logger.info(f"downloader: saved {file_size:,} bytes to {out_path}")

    if file_size < MIN_VIDEO_SIZE_BYTES:
        out_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"downloader: downloaded video is too small "
            f"({file_size} bytes < {MIN_VIDEO_SIZE_BYTES} bytes). "
            "The video may be corrupt or the generation failed silently."
        )

    return out_path
