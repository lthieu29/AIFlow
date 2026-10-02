"""Native web-API download helpers (signing-based, no yt-dlp).

This module implements the *native-API-first* download strategy intended by
ADR-0004: instead of shelling out to yt-dlp, it talks to the Douyin / Bilibili
web APIs directly, using the anti-bot signatures from
``server.content.crawlers.signing`` (A-Bogus for Douyin, WBI for Bilibili).

Each platform downloader tries its native path first and falls back to yt-dlp
when:
- a required signing dependency is missing (``SigningUnavailableError``),
- the web API rejects the request (rate-limit / login wall), or
- any network/parse error occurs.

The native path is intentionally minimal and self-contained: it resolves the
direct media URL, then reuses :func:`server.flow.downloader.download_video`
(and :class:`~server.content.crawlers.stream_merger.StreamMerger` for Bilibili
DASH) to fetch bytes. Heavy/fragile pieces (msToken refresh, ttwid, full param
models) are kept optional — cookies supply those when present.
"""

from __future__ import annotations

import logging
import random
import re
import string
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class NativeAPIError(Exception):
    """Raised when the native web-API download path cannot complete.

    Downloaders catch this and fall back to yt-dlp.

    Attributes:
        reason: Human-readable failure reason.
        code:   Machine-readable error code.
    """

    def __init__(self, reason: str, code: str = "NATIVE_API_FAILED") -> None:
        self.reason = reason
        self.code = code
        super().__init__(f"[{code}] {reason}")


# ─── Shared constants ─────────────────────────────────────────────────────────

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# Network timeout for native JSON API calls (seconds).
API_TIMEOUT = 15.0


def gen_random_str(length: int) -> str:
    """Return a random alphanumeric string of *length* chars (msToken filler)."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(random.choice(alphabet) for _ in range(length))


def gen_false_ms_token() -> str:
    """Generate a locally-faked Douyin ``msToken`` (126 chars + ``==``).

    Mirrors the reference behaviour: when no real msToken is available from
    cookies, a random one of the expected length lets the request through more
    often than omitting it entirely.
    """
    return gen_random_str(126) + "=="


def require_httpx():
    """Import ``httpx`` lazily, converting absence into :class:`NativeAPIError`."""
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover
        raise NativeAPIError(
            "httpx is required for native API downloads.", code="HTTPX_MISSING"
        ) from exc
    return httpx


# ─── Douyin URL helpers ───────────────────────────────────────────────────────

_DOUYIN_AWEME_ID_RE = re.compile(r"/(?:video|note|share/video)/(\d+)")
_DOUYIN_MODAL_ID_RE = re.compile(r"modal_id=(\d+)")


def extract_douyin_aweme_id(url: str) -> Optional[str]:
    """Extract the numeric ``aweme_id`` from a (resolved) Douyin URL.

    Short links (``v.douyin.com/...``) must be resolved first via
    :func:`resolve_redirect`.

    Returns:
        The aweme_id string, or ``None`` if it cannot be found.
    """
    m = _DOUYIN_AWEME_ID_RE.search(url)
    if m:
        return m.group(1)
    m = _DOUYIN_MODAL_ID_RE.search(url)
    if m:
        return m.group(1)
    return None


async def resolve_redirect(url: str, cookie: str = "") -> str:
    """Follow redirects for a short URL and return the final URL.

    Returns the original URL unchanged on any error (best-effort).
    """
    httpx = require_httpx()
    headers = {"User-Agent": DEFAULT_UA}
    if cookie:
        headers["Cookie"] = cookie
    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=API_TIMEOUT, headers=headers
        ) as client:
            resp = await client.get(url)
            return str(resp.url)
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_redirect failed for %s: %s", url, exc)
        return url


# ─── Bilibili URL helpers ─────────────────────────────────────────────────────

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)


def extract_bilibili_id(url: str) -> tuple[Optional[str], Optional[int]]:
    """Extract ``(bvid, aid)`` from a Bilibili URL/ID. Either may be ``None``."""
    bv = _BV_RE.search(url)
    if bv:
        return bv.group(1), None
    av = _AV_RE.search(url)
    if av:
        return None, int(av.group(1))
    return None, None


# ─── Douyin native detail API ─────────────────────────────────────────────────

_DOUYIN_DETAIL_URL = "https://www.douyin.com/aweme/v1/web/aweme/detail/"


def _douyin_base_params(aweme_id: str, ms_token: str) -> dict:
    """Build the minimal Douyin web-API query params for the detail endpoint."""
    return {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "aweme_id": aweme_id,
        "pc_client_type": "1",
        "version_code": "290100",
        "version_name": "29.1.0",
        "cookie_enabled": "true",
        "screen_width": "1920",
        "screen_height": "1080",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "130.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "130.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "12",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "50",
        "msToken": ms_token,
    }


async def douyin_fetch_video_url(
    aweme_id: str,
    cookie: str = "",
    user_agent: str = DEFAULT_UA,
) -> tuple[str, str, float]:
    """Resolve a Douyin video's direct (no-watermark) URL via the web API.

    Signs the request with A-Bogus (``server.content.crawlers.signing``).

    Args:
        aweme_id:   Numeric Douyin video id.
        cookie:     Optional ``Cookie:`` header value.
        user_agent: User-Agent to send.

    Returns:
        ``(video_url, title, duration_sec)``.

    Raises:
        NativeAPIError: If signing is unavailable or the API response cannot be
            parsed into a playable URL.
    """
    from server.content.crawlers.signing import sign_a_bogus
    from server.content.crawlers.signing.errors import SigningUnavailableError

    httpx = require_httpx()

    ms_token = ""
    if "msToken=" in cookie:
        m = re.search(r"msToken=([^;]+)", cookie)
        if m:
            ms_token = m.group(1)
    if not ms_token:
        ms_token = gen_false_ms_token()

    params = _douyin_base_params(aweme_id, ms_token)

    try:
        a_bogus = sign_a_bogus(params, user_agent)
    except SigningUnavailableError as exc:
        raise NativeAPIError(str(exc), code="SIGNING_UNAVAILABLE") from exc
    except Exception as exc:  # noqa: BLE001
        raise NativeAPIError(f"A-Bogus signing failed: {exc}", code="SIGNING_ERROR") from exc

    params["a_bogus"] = a_bogus

    headers = {
        "User-Agent": user_agent,
        "Referer": f"https://www.douyin.com/video/{aweme_id}",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie:
        headers["Cookie"] = cookie

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(_DOUYIN_DETAIL_URL, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise NativeAPIError(
            f"Douyin detail request failed: {exc}", code="DOUYIN_API_ERROR"
        ) from exc

    detail = data.get("aweme_detail") if isinstance(data, dict) else None
    if not detail:
        raise NativeAPIError(
            "Douyin API returned no aweme_detail (login/cookie may be required).",
            code="DOUYIN_NO_DETAIL",
        )

    title = detail.get("desc", "") or aweme_id
    video = detail.get("video") or {}
    duration_ms = video.get("duration") or 0
    duration = float(duration_ms) / 1000.0 if duration_ms else 0.0

    # Prefer the no-watermark play_addr; fall back to download_addr.
    url_list: list[str] = []
    for key in ("play_addr", "play_addr_h264", "download_addr"):
        addr = video.get(key) or {}
        candidate = addr.get("url_list") or []
        if candidate:
            url_list = candidate
            break

    # Bit-rate variants sometimes hold higher quality URLs.
    if not url_list:
        for br in video.get("bit_rate") or []:
            addr = (br or {}).get("play_addr") or {}
            candidate = addr.get("url_list") or []
            if candidate:
                url_list = candidate
                break

    playable = [u for u in url_list if isinstance(u, str) and u.startswith("http")]
    if not playable:
        raise NativeAPIError(
            "Douyin API response contained no playable video URL.",
            code="DOUYIN_NO_URL",
        )

    # Prefer https + non-watermarked ('playwm' indicates watermarked).
    playable.sort(key=lambda u: ("playwm" in u, not u.startswith("https")))
    return playable[0], title, duration


# ─── Bilibili native playurl API ──────────────────────────────────────────────

_BILI_VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
_BILI_PLAYURL_URL = "https://api.bilibili.com/x/player/wbi/playurl"


async def bilibili_fetch_streams(
    bvid: Optional[str],
    aid: Optional[int],
    cookie: str = "",
    user_agent: str = DEFAULT_UA,
) -> dict:
    """Resolve Bilibili DASH video+audio stream URLs via the WBI-signed playurl API.

    Args:
        bvid:       BV id (e.g. ``BV1xx411c7mD``) — preferred.
        aid:        AV id (numeric) — used when *bvid* is ``None``.
        cookie:     Optional ``Cookie:`` header value (higher quality if logged in).
        user_agent: User-Agent to send.

    Returns:
        Dict with keys: ``video_url``, ``audio_url`` (may be ``None`` for
        non-DASH), ``title``, ``duration``, ``referer``.

    Raises:
        NativeAPIError: If WBI signing is unavailable or the API cannot be parsed.
    """
    from server.content.crawlers.signing import get_wbi_keys
    from server.content.crawlers.signing.errors import SigningUnavailableError
    from server.content.crawlers.signing.wbi import WbiSigner

    httpx = require_httpx()

    headers = {
        "User-Agent": user_agent,
        "Referer": "https://www.bilibili.com/",
    }
    if cookie:
        headers["Cookie"] = cookie

    # ── Step 1: view API → cid + title + duration ─────────────────────────────
    view_params: dict = {}
    if bvid:
        view_params["bvid"] = bvid
    elif aid is not None:
        view_params["aid"] = str(aid)
    else:
        raise NativeAPIError("No BV/AV id provided.", code="BILI_NO_ID")

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT, follow_redirects=True) as client:
            view_resp = await client.get(_BILI_VIEW_URL, params=view_params, headers=headers)
            view_resp.raise_for_status()
            view_data = view_resp.json()
    except Exception as exc:  # noqa: BLE001
        raise NativeAPIError(f"Bilibili view request failed: {exc}", code="BILI_VIEW_ERROR") from exc

    vdata = view_data.get("data") if isinstance(view_data, dict) else None
    if not vdata:
        raise NativeAPIError(
            f"Bilibili view API error: {view_data.get('message', 'unknown') if isinstance(view_data, dict) else 'no data'}",
            code="BILI_VIEW_NO_DATA",
        )

    cid = vdata.get("cid")
    title = vdata.get("title", "") or (bvid or f"av{aid}")
    duration = float(vdata.get("duration") or 0.0)
    resolved_bvid = vdata.get("bvid") or bvid

    if not cid:
        raise NativeAPIError("Bilibili view API returned no cid.", code="BILI_NO_CID")

    # ── Step 2: WBI-signed playurl (DASH, fnval=16) ───────────────────────────
    try:
        img_key, sub_key = get_wbi_keys(cookie)
    except SigningUnavailableError as exc:
        raise NativeAPIError(str(exc), code="SIGNING_UNAVAILABLE") from exc

    play_params = {
        "fnval": "4048",   # DASH + all codecs
        "fnver": "0",
        "fourk": "1",
        "cid": str(cid),
    }
    if resolved_bvid:
        play_params["bvid"] = resolved_bvid
    elif aid is not None:
        play_params["avid"] = str(aid)

    signed = WbiSigner(img_key, sub_key).sign(play_params)

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT, follow_redirects=True) as client:
            play_resp = await client.get(_BILI_PLAYURL_URL, params=signed, headers=headers)
            play_resp.raise_for_status()
            play_data = play_resp.json()
    except Exception as exc:  # noqa: BLE001
        raise NativeAPIError(f"Bilibili playurl request failed: {exc}", code="BILI_PLAYURL_ERROR") from exc

    pdata = play_data.get("data") if isinstance(play_data, dict) else None
    if not pdata:
        raise NativeAPIError(
            f"Bilibili playurl API error: {play_data.get('message', 'unknown') if isinstance(play_data, dict) else 'no data'}",
            code="BILI_PLAYURL_NO_DATA",
        )

    dash = pdata.get("dash")
    if dash:
        videos = dash.get("video") or []
        audios = dash.get("audio") or []
        if not videos:
            raise NativeAPIError("Bilibili DASH response had no video stream.", code="BILI_NO_VIDEO")
        best_video = max(videos, key=lambda v: v.get("id", 0) or 0)
        video_url = best_video.get("baseUrl") or best_video.get("base_url")
        audio_url = None
        if audios:
            best_audio = max(audios, key=lambda a: a.get("id", 0) or 0)
            audio_url = best_audio.get("baseUrl") or best_audio.get("base_url")
        if not video_url:
            raise NativeAPIError("Bilibili DASH video had no baseUrl.", code="BILI_NO_VIDEO_URL")
        return {
            "video_url": video_url,
            "audio_url": audio_url,
            "title": title,
            "duration": duration,
            "referer": "https://www.bilibili.com/",
        }

    # Fallback: legacy progressive MP4 (durl)
    durl = pdata.get("durl") or []
    if durl and durl[0].get("url"):
        return {
            "video_url": durl[0]["url"],
            "audio_url": None,
            "title": title,
            "duration": duration,
            "referer": "https://www.bilibili.com/",
        }

    raise NativeAPIError("Bilibili playurl returned neither dash nor durl.", code="BILI_NO_STREAM")


async def download_url_to_file(
    url: str,
    out_path: Path,
    referer: str = "",
    cookie: str = "",
    user_agent: str = DEFAULT_UA,
) -> Path:
    """Download bytes from a direct media *url* to *out_path* with platform headers.

    Bilibili/Douyin CDNs require a matching ``Referer`` (and sometimes cookies),
    which the generic :func:`server.flow.downloader.download_video` does not set,
    so this helper performs the fetch itself.

    Raises:
        NativeAPIError: On HTTP failure or implausibly small output.
    """
    httpx = require_httpx()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": user_agent}
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie

    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                with out_path.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(chunk_size=1 << 16):
                        fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        out_path.unlink(missing_ok=True)
        raise NativeAPIError(f"Media download failed: {exc}", code="MEDIA_DOWNLOAD_ERROR") from exc

    size = out_path.stat().st_size if out_path.exists() else 0
    if size < 10 * 1024:  # 10 KB sanity floor
        out_path.unlink(missing_ok=True)
        raise NativeAPIError(
            f"Downloaded media too small ({size} bytes).", code="MEDIA_TOO_SMALL"
        )
    return out_path
