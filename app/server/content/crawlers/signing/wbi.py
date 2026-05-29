"""WBI signing module for Bilibili API requests.

GPL v3 NOTICE
=============
The WBI signing algorithm is derived from Douyin_TikTok_Download_API by
Evil0ctal (which in turn references the Bilibili community reverse-engineering
effort), licensed under GPL v3.

To use the real implementation:
1. Clone the upstream repository (see a_bogus.UPSTREAM_REPO).
2. Checkout the pinned commit (see a_bogus.UPSTREAM_COMMIT).
3. Copy the relevant signing logic here, respecting GPL v3 obligations.
4. Personal use does not require source disclosure.

This file is a STUB/PLACEHOLDER.
- ``WbiSigner.sign()`` returns the params dict unchanged (no w_rid/wts added).
- ``get_wbi_keys()`` returns empty strings.

The rest of the AIFlow pipeline works without valid WBI signatures
(Bilibili requests may be rejected for some endpoints).

Upstream reference
------------------
UPSTREAM_REPO   : https://github.com/Evil0ctal/Douyin_TikTok_Download_API
UPSTREAM_COMMIT : pinned_commit_hash_here  (update after lifting)
"""

from __future__ import annotations

from .a_bogus import UPSTREAM_COMMIT, UPSTREAM_REPO  # shared upstream reference

__all__ = ["WbiSigner", "get_wbi_keys", "UPSTREAM_REPO", "UPSTREAM_COMMIT"]


# ─── WbiSigner ────────────────────────────────────────────────────────────────


class WbiSigner:
    """Signs Bilibili API request parameters using the WBI algorithm.

    WBI signing adds two query parameters to every Bilibili API request:
    - ``w_rid``: MD5 hash of the sorted, encoded parameters + mixed key.
    - ``wts``:   Current Unix timestamp (seconds).

    The mixed key is derived from ``img_key`` and ``sub_key`` obtained from
    the Bilibili navigation API (see :func:`get_wbi_keys`).

    .. note::
        **STUB IMPLEMENTATION** — :meth:`sign` returns the params dict
        unchanged (no ``w_rid`` or ``wts`` are added).
        Replace the body of :meth:`sign` with the actual GPL v3 algorithm.

    Args:
        img_key: First half of the WBI key (from Bilibili nav API).
        sub_key: Second half of the WBI key (from Bilibili nav API).

    Example::

        img_key, sub_key = await get_wbi_keys(cookies)
        signer = WbiSigner(img_key, sub_key)
        signed_params = signer.sign({"mid": "12345678"})
        # Real: {"mid": "12345678", "wts": "1700000000", "w_rid": "abc123..."}
        # Stub: {"mid": "12345678"}
    """

    def __init__(self, img_key: str, sub_key: str) -> None:
        self._img_key = img_key
        self._sub_key = sub_key
        # TODO: Derive mixed_key from img_key + sub_key using the upstream
        # character-index table (see upstream wbi.py for the MIXIN_KEY_ENC_TAB).
        self._mixed_key: str = ""

    def sign(self, params: dict) -> dict:
        """Add WBI signature fields (``w_rid``, ``wts``) to *params*.

        .. note::
            **STUB** — returns a shallow copy of *params* without modification.

        Args:
            params: Original query parameters dict.

        Returns:
            New dict with ``w_rid`` and ``wts`` added (stub: unchanged copy).
        """
        # TODO: Replace with actual GPL v3 implementation from upstream.
        # Steps:
        #   1. Add wts = int(time.time()) to params.
        #   2. Sort params by key, URL-encode, concatenate with mixed_key.
        #   3. Compute MD5 of the concatenated string → w_rid.
        #   4. Return params with wts and w_rid added.
        return dict(params)


# ─── Key fetching ─────────────────────────────────────────────────────────────


def get_wbi_keys(cookies: str) -> tuple[str, str]:
    """Fetch the current WBI keys from the Bilibili navigation API.

    The WBI keys rotate periodically. This function calls:
        ``https://api.bilibili.com/x/web-interface/nav``
    and extracts ``data.wbi_img.img_url`` and ``data.wbi_img.sub_url``.

    The key is the filename (without extension) of each URL, e.g.:
        ``https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077d.png``
        → ``img_key = "7cd084941338484aae1ad9425b84077d"``

    .. note::
        **STUB IMPLEMENTATION** — returns ``("", "")`` without making any
        network request.  Replace with the actual GPL v3 implementation.

    Args:
        cookies: Netscape-format cookie string (or ``Cookie:`` header value)
                 for an authenticated Bilibili session.

    Returns:
        ``(img_key, sub_key)`` tuple of WBI key strings, or ``("", "")``
        when the stub is active.

    Example::

        img_key, sub_key = get_wbi_keys(my_cookies)
        signer = WbiSigner(img_key, sub_key)
    """
    # TODO: Replace with actual GPL v3 implementation from upstream.
    # Steps:
    #   1. GET https://api.bilibili.com/x/web-interface/nav with cookies.
    #   2. Parse JSON response.
    #   3. Extract img_url and sub_url from data.wbi_img.
    #   4. Return (Path(img_url).stem, Path(sub_url).stem).
    _ = cookies  # suppress unused-variable warning until real impl lands
    return ("", "")
