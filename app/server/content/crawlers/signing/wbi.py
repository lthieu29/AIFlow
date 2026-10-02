"""WBI signing module for Bilibili web API requests.

CLEAN-ROOM IMPLEMENTATION
=========================
Unlike ``a_bogus.py`` (GPL v3) and ``x_bogus.py`` (Apache 2.0), this WBI signer
is a **clean-room** implementation written for AIFlow from the publicly
documented Bilibili WBI algorithm. It does not copy third-party source code, so
it carries the project's own license.

Algorithm (public knowledge)
-----------------------------
Bilibili's web API requires two extra query parameters on many endpoints:

- ``wts``  : current Unix timestamp in seconds.
- ``w_rid``: ``md5(sorted_encoded_params + mixin_key)``.

The ``mixin_key`` is derived from two rotating keys (``img_key`` + ``sub_key``)
fetched from the navigation API, reordered through a fixed 64-entry permutation
table (``MIXIN_KEY_ENC_TAB``) and truncated to 32 chars.

``httpx`` is an OPTIONAL runtime dependency for :func:`get_wbi_keys` (it is a
core dependency of AIFlow, but the import is kept lazy so the signer works in
environments without network access).
"""

from __future__ import annotations

import hashlib
import time
import urllib.parse
from functools import reduce

from .a_bogus import UPSTREAM_COMMIT, UPSTREAM_REPO  # shared reference metadata
from .errors import SigningUnavailableError

__all__ = ["WbiSigner", "get_wbi_keys", "MIXIN_KEY_ENC_TAB", "UPSTREAM_REPO", "UPSTREAM_COMMIT"]

# Public Bilibili WBI mixin-key permutation table (64 indices).
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_NAV_API = "https://api.bilibili.com/x/web-interface/nav"

# Characters Bilibili strips from parameter values before signing.
_FILTER_CHARS = "!'()*"


def _get_mixin_key(orig: str) -> str:
    """Reorder *orig* (img_key + sub_key) via the table, truncated to 32 chars.

    The permutation indices go up to 63, so *orig* must be at least 64 chars
    (real keys are 32 + 32). Out-of-range indices are skipped defensively so a
    malformed/short key yields a best-effort result instead of an IndexError.
    """
    return reduce(
        lambda s, i: s + (orig[i] if i < len(orig) else ""),
        MIXIN_KEY_ENC_TAB,
        "",
    )[:32]


class WbiSigner:
    """Signs Bilibili web API request parameters using the WBI algorithm.

    Example::

        img_key, sub_key = get_wbi_keys(cookies)
        signer = WbiSigner(img_key, sub_key)
        signed = signer.sign({"mid": "12345678"})
        # {"mid": "12345678", "wts": "1700000000", "w_rid": "abc123..."}
    """

    def __init__(self, img_key: str, sub_key: str) -> None:
        self._img_key = img_key
        self._sub_key = sub_key
        self._mixed_key: str = _get_mixin_key(img_key + sub_key)

    def sign(self, params: dict) -> dict:
        """Return a new dict with ``wts`` and ``w_rid`` WBI fields added.

        The original *params* dict is not mutated. Values are stringified and
        the reserved characters ``!'()*`` are stripped (per the public WBI
        spec) before hashing.

        Args:
            params: Original query parameters dict.

        Returns:
            New dict containing the original params plus ``wts`` and ``w_rid``.
        """
        signed = dict(params)
        wts = int(time.time())
        signed["wts"] = wts

        # Sort by key, stringify + strip reserved chars from values.
        sorted_params = {}
        for key in sorted(signed.keys()):
            value = "".join(ch for ch in str(signed[key]) if ch not in _FILTER_CHARS)
            sorted_params[key] = value

        query = urllib.parse.urlencode(sorted_params)
        w_rid = hashlib.md5((query + self._mixed_key).encode("utf-8")).hexdigest()
        signed["w_rid"] = w_rid
        return signed


def get_wbi_keys(cookies: str = "") -> tuple[str, str]:
    """Fetch the current WBI keys (img_key, sub_key) from the Bilibili nav API.

    Args:
        cookies: Optional ``Cookie:`` header value for an authenticated session.

    Returns:
        ``(img_key, sub_key)`` tuple of 32-char hex strings.

    Raises:
        SigningUnavailableError: If ``httpx`` is unavailable or the network
            request fails. Callers can fall back to yt-dlp.
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:  # pragma: no cover
        raise SigningUnavailableError(
            "WBI key fetching requires 'httpx' (a core AIFlow dependency)."
        ) from exc

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }
    if cookies:
        headers["Cookie"] = cookies

    try:
        resp = httpx.get(_NAV_API, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise SigningUnavailableError(
            f"Failed to fetch Bilibili WBI keys: {exc}"
        ) from exc

    wbi_img = (data.get("data") or {}).get("wbi_img") or {}
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")
    if not img_url or not sub_url:
        raise SigningUnavailableError(
            "Bilibili nav API response did not contain WBI keys "
            "(login may be required)."
        )

    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key
