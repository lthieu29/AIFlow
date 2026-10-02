"""Auto-update check for the GPL/Apache signing modules.

Checks whether the upstream Douyin_TikTok_Download_API repository has published
new commits since the pinned commit recorded here. Used to know when the
A-Bogus / X-Bogus algorithms may need re-lifting after Douyin rotates them.

Usage (CLI)::

    python -m server.content.crawlers.signing.update_check

Usage (programmatic)::

    from server.content.crawlers.signing.update_check import check_upstream_updates
    result = check_upstream_updates()
    if result["has_update"]:
        print(f"New commit available: {result['latest_commit']}")

GPL v3 NOTICE
=============
The A-Bogus module this script monitors is GPL v3 (see ``a_bogus.py``).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ─── Upstream reference ───────────────────────────────────────────────────────

_UPSTREAM_OWNER = "Evil0ctal"
_UPSTREAM_REPO = "Douyin_TikTok_Download_API"
_GITHUB_API_BASE = "https://api.github.com"

# ─── Pinned commits ───────────────────────────────────────────────────────────

#: Mapping of module name → pinned upstream commit SHA (short).
#: Update these after reviewing and re-lifting a new upstream commit.
PINNED_COMMITS: dict[str, str] = {
    "a_bogus": "0b8b8d3",
    "x_bogus": "0b8b8d3",
    # wbi is a clean-room AIFlow implementation; not pinned to upstream.
}


# ─── Public API ───────────────────────────────────────────────────────────────


def check_upstream_updates(timeout: float = 10.0) -> dict[str, Any]:
    """Check whether the upstream repository has new commits.

    Queries the GitHub API for the latest commit on the default branch of
    ``Evil0ctal/Douyin_TikTok_Download_API`` and compares it against the pinned
    commits in :data:`PINNED_COMMITS`.

    Network failures (offline, rate-limited, ``httpx`` missing) are handled
    gracefully: the function returns ``has_update=False`` with an ``error``
    key explaining why, rather than raising.

    Returns:
        Dict with keys ``has_update`` (bool), ``latest_commit`` (str),
        ``pinned_commit`` (str), ``modules`` (dict[str, bool]) and an optional
        ``error`` (str) when the check could not be performed.
    """
    pinned = PINNED_COMMITS.get("a_bogus", "")
    base_result: dict[str, Any] = {
        "has_update": False,
        "latest_commit": "",
        "pinned_commit": pinned,
        "modules": {mod: False for mod in PINNED_COMMITS},
    }

    try:
        import httpx  # type: ignore[import]
    except ImportError:
        base_result["error"] = "httpx not installed — cannot check upstream."
        return base_result

    url = f"{_GITHUB_API_BASE}/repos/{_UPSTREAM_OWNER}/{_UPSTREAM_REPO}/commits"
    try:
        resp = httpx.get(url, params={"per_page": 1}, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        latest_sha = payload[0]["sha"] if payload else ""
    except Exception as exc:
        base_result["error"] = f"Upstream check failed: {exc}"
        return base_result

    if not latest_sha:
        base_result["error"] = "GitHub API returned no commits."
        return base_result

    # Compare using short-SHA prefix (pinned commits are stored short).
    modules = {
        mod: not latest_sha.startswith(pinned_sha)
        for mod, pinned_sha in PINNED_COMMITS.items()
        if pinned_sha
    }
    base_result["latest_commit"] = latest_sha
    base_result["modules"] = {mod: modules.get(mod, False) for mod in PINNED_COMMITS}
    base_result["has_update"] = any(base_result["modules"].values())
    return base_result


# ─── CLI entry point ─────────────────────────────────────────────────────────


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = check_upstream_updates()
    print(json.dumps(result, indent=2))
    if result.get("error"):
        logger.warning("Update check incomplete: %s", result["error"])
    elif result["has_update"]:
        logger.warning(
            "Upstream has new commits. Latest: %s. Review and update PINNED_COMMITS.",
            result["latest_commit"],
        )
    else:
        logger.info("Signing modules are up-to-date with pinned commit.")
