"""Unit tests for the signing modules (Task 4.5.3).

Covers:
- a_bogus.sign_a_bogus() — stub returns empty string, correct signature
- x_bogus.sign_x_bogus() — stub returns empty string, correct signature
- wbi.WbiSigner — init, sign() returns dict copy without mutation
- wbi.get_wbi_keys() — stub returns ("", "")
- update_check.check_upstream_updates() — stub returns no-update dict
- update_check.PINNED_COMMITS — structure validation
- Package __init__ re-exports
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── a_bogus ─────────────────────────────────────────────────────────────────


class TestSignABogus:
    def test_returns_string(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        result = sign_a_bogus({"aweme_id": "7123456789012345678"}, "Mozilla/5.0")
        assert isinstance(result, str)

    def test_stub_returns_empty_string(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        result = sign_a_bogus({"aweme_id": "7123456789012345678"}, "Mozilla/5.0")
        assert result == ""

    def test_accepts_empty_params(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        result = sign_a_bogus({}, "")
        assert isinstance(result, str)

    def test_accepts_multiple_params(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        result = sign_a_bogus(
            {"aweme_id": "123", "device_platform": "webapp", "aid": "6383"},
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        )
        assert isinstance(result, str)

    def test_upstream_repo_constant(self):
        from server.content.crawlers.signing.a_bogus import UPSTREAM_REPO

        assert "Evil0ctal" in UPSTREAM_REPO
        assert "Douyin_TikTok_Download_API" in UPSTREAM_REPO
        assert UPSTREAM_REPO.startswith("https://")

    def test_upstream_commit_constant_is_string(self):
        from server.content.crawlers.signing.a_bogus import UPSTREAM_COMMIT

        assert isinstance(UPSTREAM_COMMIT, str)
        assert len(UPSTREAM_COMMIT) > 0


# ─── x_bogus ─────────────────────────────────────────────────────────────────


class TestSignXBogus:
    def test_returns_string(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        result = sign_x_bogus({"aweme_id": "7123456789012345678"}, "Mozilla/5.0")
        assert isinstance(result, str)

    def test_stub_returns_empty_string(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        result = sign_x_bogus({"aweme_id": "7123456789012345678"}, "Mozilla/5.0")
        assert result == ""

    def test_accepts_empty_params(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        result = sign_x_bogus({}, "")
        assert isinstance(result, str)

    def test_accepts_multiple_params(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        result = sign_x_bogus(
            {"aweme_id": "123", "device_platform": "webapp"},
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        )
        assert isinstance(result, str)

    def test_shares_upstream_reference_with_a_bogus(self):
        from server.content.crawlers.signing import a_bogus, x_bogus

        assert x_bogus.UPSTREAM_REPO == a_bogus.UPSTREAM_REPO
        assert x_bogus.UPSTREAM_COMMIT == a_bogus.UPSTREAM_COMMIT


# ─── WbiSigner ───────────────────────────────────────────────────────────────


class TestWbiSigner:
    def test_init_accepts_keys(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img_key_abc", "sub_key_xyz")
        assert signer._img_key == "img_key_abc"
        assert signer._sub_key == "sub_key_xyz"

    def test_init_accepts_empty_keys(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("", "")
        assert signer._img_key == ""
        assert signer._sub_key == ""

    def test_sign_returns_dict(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img", "sub")
        result = signer.sign({"mid": "12345678"})
        assert isinstance(result, dict)

    def test_sign_stub_preserves_original_params(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img", "sub")
        params = {"mid": "12345678", "platform": "web"}
        result = signer.sign(params)
        assert result["mid"] == "12345678"
        assert result["platform"] == "web"

    def test_sign_returns_copy_not_same_object(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img", "sub")
        params = {"mid": "12345678"}
        result = signer.sign(params)
        assert result is not params

    def test_sign_does_not_mutate_original_params(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img", "sub")
        params = {"mid": "12345678"}
        original_keys = set(params.keys())
        signer.sign(params)
        assert set(params.keys()) == original_keys

    def test_sign_accepts_empty_params(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img", "sub")
        result = signer.sign({})
        assert isinstance(result, dict)

    def test_sign_accepts_complex_params(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner("img", "sub")
        params = {"mid": "12345678", "token": "", "platform": "web", "web_location": "1550101"}
        result = signer.sign(params)
        assert isinstance(result, dict)


# ─── get_wbi_keys ─────────────────────────────────────────────────────────────


class TestGetWbiKeys:
    def test_returns_tuple(self):
        from server.content.crawlers.signing.wbi import get_wbi_keys

        result = get_wbi_keys("some_cookie_string")
        assert isinstance(result, tuple)

    def test_returns_two_elements(self):
        from server.content.crawlers.signing.wbi import get_wbi_keys

        result = get_wbi_keys("some_cookie_string")
        assert len(result) == 2

    def test_stub_returns_empty_strings(self):
        from server.content.crawlers.signing.wbi import get_wbi_keys

        img_key, sub_key = get_wbi_keys("some_cookie_string")
        assert img_key == ""
        assert sub_key == ""

    def test_accepts_empty_cookies(self):
        from server.content.crawlers.signing.wbi import get_wbi_keys

        img_key, sub_key = get_wbi_keys("")
        assert isinstance(img_key, str)
        assert isinstance(sub_key, str)

    def test_return_values_are_strings(self):
        from server.content.crawlers.signing.wbi import get_wbi_keys

        img_key, sub_key = get_wbi_keys("SESSDATA=abc123; bili_jct=xyz")
        assert isinstance(img_key, str)
        assert isinstance(sub_key, str)


# ─── check_upstream_updates ───────────────────────────────────────────────────


class TestCheckUpstreamUpdates:
    def test_returns_dict(self):
        from server.content.crawlers.signing.update_check import check_upstream_updates

        result = check_upstream_updates()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        from server.content.crawlers.signing.update_check import check_upstream_updates

        result = check_upstream_updates()
        assert "has_update" in result
        assert "latest_commit" in result
        assert "pinned_commit" in result
        assert "modules" in result

    def test_stub_has_update_is_false(self):
        from server.content.crawlers.signing.update_check import check_upstream_updates

        result = check_upstream_updates()
        assert result["has_update"] is False

    def test_stub_latest_commit_is_string(self):
        from server.content.crawlers.signing.update_check import check_upstream_updates

        result = check_upstream_updates()
        assert isinstance(result["latest_commit"], str)

    def test_stub_pinned_commit_matches_pinned_commits_dict(self):
        from server.content.crawlers.signing.update_check import (
            PINNED_COMMITS,
            check_upstream_updates,
        )

        result = check_upstream_updates()
        assert result["pinned_commit"] == PINNED_COMMITS.get("a_bogus", "")

    def test_modules_dict_contains_all_modules(self):
        from server.content.crawlers.signing.update_check import (
            PINNED_COMMITS,
            check_upstream_updates,
        )

        result = check_upstream_updates()
        modules = result["modules"]
        assert isinstance(modules, dict)
        for mod in PINNED_COMMITS:
            assert mod in modules

    def test_stub_all_module_flags_are_false(self):
        from server.content.crawlers.signing.update_check import check_upstream_updates

        result = check_upstream_updates()
        for mod, flag in result["modules"].items():
            assert flag is False, f"Module {mod!r} unexpectedly has has_update=True"


# ─── PINNED_COMMITS ───────────────────────────────────────────────────────────


class TestPinnedCommits:
    def test_is_dict(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        assert isinstance(PINNED_COMMITS, dict)

    def test_contains_a_bogus(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        assert "a_bogus" in PINNED_COMMITS

    def test_contains_x_bogus(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        assert "x_bogus" in PINNED_COMMITS

    def test_contains_wbi(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        assert "wbi" in PINNED_COMMITS

    def test_all_values_are_strings(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        for mod, commit in PINNED_COMMITS.items():
            assert isinstance(commit, str), f"PINNED_COMMITS[{mod!r}] is not a string"
            assert len(commit) > 0, f"PINNED_COMMITS[{mod!r}] is empty"


# ─── Package __init__ re-exports ─────────────────────────────────────────────


class TestPackageExports:
    def test_sign_a_bogus_importable_from_package(self):
        from server.content.crawlers.signing import sign_a_bogus

        assert callable(sign_a_bogus)

    def test_sign_x_bogus_importable_from_package(self):
        from server.content.crawlers.signing import sign_x_bogus

        assert callable(sign_x_bogus)

    def test_wbi_signer_importable_from_package(self):
        from server.content.crawlers.signing import WbiSigner

        assert WbiSigner is not None

    def test_get_wbi_keys_importable_from_package(self):
        from server.content.crawlers.signing import get_wbi_keys

        assert callable(get_wbi_keys)

    def test_check_upstream_updates_importable_from_package(self):
        from server.content.crawlers.signing import check_upstream_updates

        assert callable(check_upstream_updates)

    def test_pinned_commits_importable_from_package(self):
        from server.content.crawlers.signing import PINNED_COMMITS

        assert isinstance(PINNED_COMMITS, dict)
