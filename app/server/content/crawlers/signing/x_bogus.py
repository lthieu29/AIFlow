"""X-Bogus signing module for Douyin API requests.

GPL v3 NOTICE
=============
The actual X-Bogus signing algorithm is derived from
Douyin_TikTok_Download_API by Evil0ctal, licensed under GPL v3.

To use the real implementation:
1. Clone the upstream repository (see a_bogus.UPSTREAM_REPO).
2. Checkout the pinned commit (see a_bogus.UPSTREAM_COMMIT).
3. Copy the relevant signing logic here, respecting GPL v3 obligations.
4. Personal use does not require source disclosure.

This file is a STUB/PLACEHOLDER. It returns an empty string for all
inputs. The rest of the AIFlow pipeline works without a valid X-Bogus
signature (requests may be rate-limited or rejected by Douyin's servers).

Upstream reference
------------------
UPSTREAM_REPO   : https://github.com/Evil0ctal/Douyin_TikTok_Download_API
UPSTREAM_COMMIT : pinned_commit_hash_here  (update after lifting)
"""

from __future__ import annotations

from .a_bogus import UPSTREAM_COMMIT, UPSTREAM_REPO  # shared upstream reference

__all__ = ["sign_x_bogus", "UPSTREAM_REPO", "UPSTREAM_COMMIT"]


# ─── Public API ───────────────────────────────────────────────────────────────


def sign_x_bogus(params: dict, user_agent: str) -> str:
    """Compute the X-Bogus signature for a Douyin API request.

    X-Bogus is an alternative/complementary query-parameter signature used
    by some Douyin API endpoints alongside (or instead of) A-Bogus.
    It is computed from the serialised query string and the User-Agent header.

    .. note::
        **STUB IMPLEMENTATION** — returns an empty string.
        Replace the body of this function with the actual GPL v3 algorithm
        from the upstream repository (see module docstring).

    Args:
        params:     Query parameters dict (will be URL-encoded in canonical
                    order by the real implementation).
        user_agent: User-Agent string sent with the request.

    Returns:
        X-Bogus signature string, or ``""`` when the stub is active.

    Example::

        sig = sign_x_bogus({"aweme_id": "7123456789012345678"}, "Mozilla/5.0 ...")
        # Real implementation returns something like "DFSzswVYahNBIHJKLMNO..."
    """
    # TODO: Replace with actual GPL v3 implementation from upstream.
    # See: UPSTREAM_REPO / app/api/endpoints/douyin/web/utils/xbogus.py
    _ = params       # suppress unused-variable warnings until real impl lands
    _ = user_agent
    return ""
