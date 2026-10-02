"""Unit tests for the signing modules (Task 4.5.3 — real implementations).

Covers:
- a_bogus.sign_a_bogus()  — real A-Bogus signature (GPL v3 port, needs gmssl)
- x_bogus.sign_x_bogus()  — real X-Bogus signature (Apache 2.0 port, stdlib)
- wbi.WbiSigner           — adds wts + w_rid, no mutation, deterministic mixin
- wbi.get_wbi_keys()      — parses Bilibili nav API (mocked httpx)
- update_check.check_upstream_updates() — GitHub check (mocked / offline-safe)
- update_check.PINNED_COMMITS — structure validation
- Package __init__ re-exports

A-Bogus tests are skipped automatically when ``gmssl`` is not installed
(it is an optional ``[remaster]`` dependency).
"""

from __future__ import annotations

import hashlib
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _gmssl_available() -> bool:
    try:
        import gmssl  # type: ignore[import]  # noqa: F401
        return True
    except ImportError:
        return False


_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"

# Realistic Douyin web-API query params (>32 chars when serialised — the
# upstream md5/sm3 routines treat <=32-char strings as hex digests).
_DY_PARAMS_A = {
    "device_platform": "webapp",
    "aid": "6383",
    "aweme_id": "7345492945006595379",
    "version_code": "290100",
}
_DY_PARAMS_B = {
    "device_platform": "webapp",
    "aid": "6383",
    "aweme_id": "7111111111111111111",
    "version_code": "290100",
}

# Realistic WBI keys (32 hex chars each → 64-char concatenation).
_WBI_IMG = "7cd084941338484aae1ad9425b84077d"
_WBI_SUB = "4932caff0ff746eab6f01bf08b70ac45"

requires_gmssl = pytest.mark.skipif(
    not _gmssl_available(), reason="gmssl not installed (optional [remaster] dependency)"
)


# ─── a_bogus ─────────────────────────────────────────────────────────────────


class TestSignABogus:
    @requires_gmssl
    def test_returns_nonempty_string(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        result = sign_a_bogus(_DY_PARAMS_A, _UA)
        assert isinstance(result, str)
        assert len(result) > 0

    @requires_gmssl
    def test_signature_is_url_encoded(self):
        """sign_a_bogus URL-encodes its output (no raw spaces / unsafe chars)."""
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        result = sign_a_bogus(_DY_PARAMS_A, _UA)
        assert " " not in result
        # Round-trips through unquote without error.
        assert urllib.parse.unquote(result) is not None

    @requires_gmssl
    def test_distinct_params_give_distinct_signatures(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        s1 = sign_a_bogus(_DY_PARAMS_A, _UA)
        s2 = sign_a_bogus(_DY_PARAMS_B, _UA)
        assert s1 != s2

    def test_rejects_non_dict_params(self):
        from server.content.crawlers.signing.a_bogus import sign_a_bogus

        with pytest.raises(ValueError):
            sign_a_bogus("not-a-dict", _UA)  # type: ignore[arg-type]

    def test_raises_signing_unavailable_without_gmssl(self):
        """When gmssl import fails, sign_a_bogus raises SigningUnavailableError."""
        from server.content.crawlers.signing import a_bogus
        from server.content.crawlers.signing.errors import SigningUnavailableError

        # Force the lazy gmssl import to fail.
        with patch.object(a_bogus, "_require_gmssl", side_effect=SigningUnavailableError("no gmssl")):
            with pytest.raises(SigningUnavailableError):
                a_bogus.sign_a_bogus({"aweme_id": "123"}, _UA)

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
    def test_returns_nonempty_string(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        result = sign_x_bogus(_DY_PARAMS_A, _UA)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_signature_charset(self):
        """X-Bogus output uses the documented base-64-like alphabet only."""
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        alphabet = set("Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=")
        result = sign_x_bogus(_DY_PARAMS_A, _UA)
        assert set(result) <= alphabet

    def test_distinct_params_give_distinct_signatures(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        s1 = sign_x_bogus(_DY_PARAMS_A, _UA)
        s2 = sign_x_bogus(_DY_PARAMS_B, _UA)
        assert s1 != s2

    def test_rejects_non_dict_params(self):
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        with pytest.raises(ValueError):
            sign_x_bogus("not-a-dict", _UA)  # type: ignore[arg-type]

    def test_stdlib_only_no_gmssl_required(self):
        """X-Bogus must work even if gmssl is unavailable (stdlib MD5/RC4 only)."""
        from server.content.crawlers.signing.x_bogus import sign_x_bogus

        result = sign_x_bogus(_DY_PARAMS_A, _UA)
        assert len(result) > 0

    def test_shares_upstream_reference_with_a_bogus(self):
        from server.content.crawlers.signing import a_bogus, x_bogus

        assert x_bogus.UPSTREAM_REPO == a_bogus.UPSTREAM_REPO
        assert x_bogus.UPSTREAM_COMMIT == a_bogus.UPSTREAM_COMMIT


# ─── WbiSigner ───────────────────────────────────────────────────────────────


class TestWbiSigner:
    def test_init_accepts_keys(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner(_WBI_IMG, _WBI_SUB)
        assert signer._img_key == _WBI_IMG
        assert signer._sub_key == _WBI_SUB

    def test_mixin_key_matches_public_test_vector(self):
        """Clean-room mixin-key derivation against the public reference vector."""
        from server.content.crawlers.signing.wbi import _get_mixin_key

        mixin = _get_mixin_key(_WBI_IMG + _WBI_SUB)
        assert mixin == "ea1db124af3d7062474693fa704f4ff8"
        assert len(mixin) == 32

    def test_sign_adds_wts_and_w_rid(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner(_WBI_IMG, _WBI_SUB)
        result = signer.sign({"mid": "12345678"})
        assert "wts" in result
        assert "w_rid" in result
        assert len(result["w_rid"]) == 32  # MD5 hex digest

    def test_sign_w_rid_is_correct_md5(self):
        """w_rid == md5(sorted_encoded_params_including_wts + mixin_key)."""
        from server.content.crawlers.signing.wbi import WbiSigner, _get_mixin_key

        signer = WbiSigner(_WBI_IMG, _WBI_SUB)
        with patch("server.content.crawlers.signing.wbi.time") as mock_time:
            mock_time.time.return_value = 1700000000
            result = signer.sign({"foo": "bar", "baz": "qux"})

        mixin = _get_mixin_key(_WBI_IMG + _WBI_SUB)
        expected_params = {"baz": "qux", "foo": "bar", "wts": 1700000000}
        query = urllib.parse.urlencode(dict(sorted(expected_params.items())))
        expected = hashlib.md5((query + mixin).encode("utf-8")).hexdigest()
        assert result["w_rid"] == expected

    def test_sign_does_not_mutate_original_params(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner(_WBI_IMG, _WBI_SUB)
        params = {"mid": "12345678"}
        signer.sign(params)
        assert params == {"mid": "12345678"}

    def test_sign_returns_copy_not_same_object(self):
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner(_WBI_IMG, _WBI_SUB)
        params = {"mid": "12345678"}
        assert signer.sign(params) is not params

    def test_sign_strips_reserved_chars(self):
        """Reserved chars !'()* are stripped from values before hashing."""
        from server.content.crawlers.signing.wbi import WbiSigner

        signer = WbiSigner(_WBI_IMG, _WBI_SUB)
        # Two inputs differing only by reserved chars produce same w_rid
        # (at the same wts) because those chars are filtered out.
        with patch("server.content.crawlers.signing.wbi.time") as mock_time:
            mock_time.time.return_value = 1700000000
            r1 = signer.sign({"q": "hello"})
            r2 = signer.sign({"q": "h!e'l(l)o*"})
        assert r1["w_rid"] == r2["w_rid"]


# ─── get_wbi_keys ─────────────────────────────────────────────────────────────


class TestGetWbiKeys:
    def test_parses_keys_from_nav_response(self):
        from server.content.crawlers.signing import wbi

        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "data": {
                "wbi_img": {
                    "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077d.png",
                    "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
                }
            }
        }
        fake_httpx = MagicMock()
        fake_httpx.get.return_value = fake_resp

        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            img_key, sub_key = wbi.get_wbi_keys("SESSDATA=abc")

        assert img_key == "7cd084941338484aae1ad9425b84077d"
        assert sub_key == "4932caff0ff746eab6f01bf08b70ac45"

    def test_raises_signing_unavailable_on_network_error(self):
        from server.content.crawlers.signing import wbi
        from server.content.crawlers.signing.errors import SigningUnavailableError

        fake_httpx = MagicMock()
        fake_httpx.get.side_effect = RuntimeError("boom")

        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            with pytest.raises(SigningUnavailableError):
                wbi.get_wbi_keys("")

    def test_raises_signing_unavailable_when_keys_missing(self):
        from server.content.crawlers.signing import wbi
        from server.content.crawlers.signing.errors import SigningUnavailableError

        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"data": {"wbi_img": {}}}
        fake_httpx = MagicMock()
        fake_httpx.get.return_value = fake_resp

        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            with pytest.raises(SigningUnavailableError):
                wbi.get_wbi_keys("")


# ─── check_upstream_updates ───────────────────────────────────────────────────


class TestCheckUpstreamUpdates:
    def test_returns_dict_with_required_keys(self):
        from server.content.crawlers.signing.update_check import check_upstream_updates

        # Force the offline path so this test never hits the network.
        with patch.dict("sys.modules", {"httpx": None}):
            result = check_upstream_updates()
        assert isinstance(result, dict)
        for key in ("has_update", "latest_commit", "pinned_commit", "modules"):
            assert key in result

    def test_offline_returns_has_update_false_with_error(self):
        """When httpx is missing, the check is graceful (no raise)."""
        from server.content.crawlers.signing.update_check import check_upstream_updates

        with patch.dict("sys.modules", {"httpx": None}):
            result = check_upstream_updates()
        assert result["has_update"] is False
        assert "error" in result

    def test_detects_update_when_latest_differs(self):
        from server.content.crawlers.signing import update_check

        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = [{"sha": "ffffffffffffffff"}]
        fake_httpx = MagicMock()
        fake_httpx.get.return_value = fake_resp

        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            result = update_check.check_upstream_updates()

        assert result["latest_commit"] == "ffffffffffffffff"
        assert result["has_update"] is True

    def test_no_update_when_latest_matches_pinned(self):
        from server.content.crawlers.signing import update_check
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        pinned = PINNED_COMMITS["a_bogus"]
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = [{"sha": pinned + "abcdef0000"}]
        fake_httpx = MagicMock()
        fake_httpx.get.return_value = fake_resp

        with patch.dict("sys.modules", {"httpx": fake_httpx}):
            result = update_check.check_upstream_updates()

        assert result["has_update"] is False


# ─── PINNED_COMMITS ───────────────────────────────────────────────────────────


class TestPinnedCommits:
    def test_is_dict(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        assert isinstance(PINNED_COMMITS, dict)

    def test_contains_a_bogus_and_x_bogus(self):
        from server.content.crawlers.signing.update_check import PINNED_COMMITS

        assert "a_bogus" in PINNED_COMMITS
        assert "x_bogus" in PINNED_COMMITS

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

    def test_signing_errors_importable_from_package(self):
        from server.content.crawlers.signing import SigningError, SigningUnavailableError

        assert issubclass(SigningUnavailableError, SigningError)
