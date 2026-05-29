"""A-Bogus signing module for Douyin API requests.

GPL v3 NOTICE
=============
The actual A-Bogus signing algorithm is derived from
Douyin_TikTok_Download_API by Evil0ctal, licensed under GPL v3.

To use the real implementation:
1. Clone the upstream repository (see UPSTREAM_REPO below).
2. Checkout the pinned commit (see UPSTREAM_COMMIT below).
3. Copy the relevant signing logic here, respecting GPL v3 obligations.
4. Personal use does not require source disclosure.

This file is a STUB/PLACEHOLDER. It returns an empty string for all
inputs. The rest of the AIFlow pipeline works without a valid A-Bogus
signature (requests may be rate-limited or rejected by Douyin's servers).

Upstream reference
------------------
UPSTREAM_REPO   : https://github.com/Evil0ctal/Douyin_TikTok_Download_API
UPSTREAM_COMMIT : pinned_commit_hash_here  (update after lifting)
"""

from __future__ import annotations

# ─── Upstream reference ───────────────────────────────────────────────────────

UPSTREAM_REPO: str = "https://github.com/Evil0ctal/Douyin_TikTok_Download_API"

# Pin the exact upstream commit that was reviewed and lifted.
# Update this value after running update_check.py and verifying the new commit.
UPSTREAM_COMMIT: str = "pinned_commit_hash_here"


# ─── Public API ───────────────────────────────────────────────────────────────


def sign_a_bogus(params: dict, user_agent: str) -> str:
    """Compute the A-Bogus signature for a Douyin API request.

    A-Bogus is a query-parameter signature required by Douyin's web API.
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
        A-Bogus signature string, or ``""`` when the stub is active.

    Example::

        sig = sign_a_bogus({"aweme_id": "7123456789012345678"}, "Mozilla/5.0 ...")
        # Real implementation returns something like "DFSzswVYahNBIHJKLMNO..."
    """
    # TODO: Replace with actual GPL v3 implementation from upstream.
    # See: UPSTREAM_REPO / app/api/endpoints/douyin/web/utils/abogus.py
    _ = params       # suppress unused-variable warnings until real impl lands
    _ = user_agent
    return ""
