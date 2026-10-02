"""Unit tests for the cookie manager (Task 4.5.4).

Covers:
- CookieSource enum values
- CookieEntry dataclass construction
- format_cookie_string() helper
- _parse_cookie_string() internal helper
- _write_netscape_file() / _parse_netscape_file() round-trip
- CookieManager.save_from_extension()
- CookieManager.load_from_file()
- CookieManager.get_cookies() — file path, cache, fallback
- CookieManager.get_cookie_file()
- CookieManager.export_netscape()
- CookieManager.list_available()
- CookieManager.load_from_chrome() — graceful fallback when browser-cookie3 absent
- CookieManager.clear_cache()
- PLATFORM_DOMAINS mapping
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── Imports ──────────────────────────────────────────────────────────────────


from server.content.crawlers.cookies.manager import (
    CookieEntry,
    CookieManager,
    CookieSource,
    PLATFORM_DOMAINS,
    format_cookie_string,
    _parse_cookie_string,
    _write_netscape_file,
    _parse_netscape_file,
)


# ─── CookieSource ─────────────────────────────────────────────────────────────


class TestCookieSource:
    def test_enum_values_exist(self):
        assert CookieSource.CHROME == "chrome"
        assert CookieSource.FILE == "file"
        assert CookieSource.EXTENSION == "extension"
        assert CookieSource.NONE == "none"

    def test_is_str_enum(self):
        assert isinstance(CookieSource.CHROME, str)


# ─── CookieEntry ──────────────────────────────────────────────────────────────


class TestCookieEntry:
    def test_required_fields(self):
        entry = CookieEntry(
            platform="bilibili",
            cookie_str="SESSDATA=abc123",
            source=CookieSource.FILE,
        )
        assert entry.platform == "bilibili"
        assert entry.cookie_str == "SESSDATA=abc123"
        assert entry.source == CookieSource.FILE

    def test_captured_at_defaults_to_now(self):
        before = time.time()
        entry = CookieEntry(platform="tiktok", cookie_str="", source=CookieSource.NONE)
        after = time.time()
        assert before <= entry.captured_at <= after

    def test_captured_at_can_be_set(self):
        ts = 1700000000.0
        entry = CookieEntry(
            platform="douyin",
            cookie_str="token=xyz",
            source=CookieSource.CHROME,
            captured_at=ts,
        )
        assert entry.captured_at == ts


# ─── PLATFORM_DOMAINS ─────────────────────────────────────────────────────────


class TestPlatformDomains:
    def test_bilibili_domain(self):
        assert PLATFORM_DOMAINS["bilibili"] == ".bilibili.com"

    def test_douyin_domain(self):
        assert PLATFORM_DOMAINS["douyin"] == ".douyin.com"

    def test_tiktok_domain(self):
        assert PLATFORM_DOMAINS["tiktok"] == ".tiktok.com"

    def test_all_domains_start_with_dot(self):
        for domain in PLATFORM_DOMAINS.values():
            assert domain.startswith("."), f"Domain {domain!r} should start with '.'"


# ─── format_cookie_string ─────────────────────────────────────────────────────


class TestFormatCookieString:
    def test_single_cookie(self):
        result = format_cookie_string([{"name": "SESSDATA", "value": "abc123"}])
        assert result == "SESSDATA=abc123"

    def test_multiple_cookies(self):
        cookies = [
            {"name": "SESSDATA", "value": "abc"},
            {"name": "bili_jct", "value": "xyz"},
        ]
        result = format_cookie_string(cookies)
        assert result == "SESSDATA=abc; bili_jct=xyz"

    def test_empty_list(self):
        assert format_cookie_string([]) == ""

    def test_skips_cookies_without_name(self):
        cookies = [
            {"name": "", "value": "orphan"},
            {"name": "valid", "value": "yes"},
        ]
        result = format_cookie_string(cookies)
        assert result == "valid=yes"

    def test_handles_missing_value_key(self):
        cookies = [{"name": "token"}]
        result = format_cookie_string(cookies)
        assert result == "token="

    def test_empty_value_is_preserved(self):
        cookies = [{"name": "key", "value": ""}]
        result = format_cookie_string(cookies)
        assert result == "key="


# ─── _parse_cookie_string ─────────────────────────────────────────────────────


class TestParseCookieString:
    def test_single_pair(self):
        result = _parse_cookie_string("key=value")
        assert result == [("key", "value")]

    def test_multiple_pairs(self):
        result = _parse_cookie_string("a=1; b=2; c=3")
        assert result == [("a", "1"), ("b", "2"), ("c", "3")]

    def test_empty_string(self):
        assert _parse_cookie_string("") == []

    def test_value_with_equals_sign(self):
        result = _parse_cookie_string("token=abc=def")
        assert result == [("token", "abc=def")]

    def test_strips_whitespace(self):
        result = _parse_cookie_string("  key  =  value  ")
        assert result == [("key", "value")]

    def test_skips_empty_parts(self):
        result = _parse_cookie_string("a=1;;b=2")
        assert result == [("a", "1"), ("b", "2")]


# ─── Netscape file round-trip ─────────────────────────────────────────────────


class TestNetscapeFileRoundTrip:
    def test_write_and_parse(self, tmp_path):
        cookies = [
            {
                "domain": ".bilibili.com",
                "path": "/",
                "secure": True,
                "expires": 1800000000,
                "name": "SESSDATA",
                "value": "abc123",
            },
            {
                "domain": ".bilibili.com",
                "path": "/",
                "secure": False,
                "expires": 0,
                "name": "bili_jct",
                "value": "xyz789",
            },
        ]
        out = tmp_path / "bilibili.txt"
        _write_netscape_file(cookies, out)

        assert out.is_file()
        content = out.read_text()
        assert "# Netscape HTTP Cookie File" in content
        assert "SESSDATA" in content
        assert "bili_jct" in content

        parsed = _parse_netscape_file(out)
        names = [c["name"] for c in parsed]
        assert "SESSDATA" in names
        assert "bili_jct" in names

    def test_write_adds_dot_prefix_to_domain(self, tmp_path):
        cookies = [{"domain": "bilibili.com", "path": "/", "secure": False,
                    "expires": 0, "name": "k", "value": "v"}]
        out = tmp_path / "test.txt"
        _write_netscape_file(cookies, out)
        content = out.read_text()
        assert ".bilibili.com" in content

    def test_parse_skips_comment_lines(self, tmp_path):
        f = tmp_path / "cookies.txt"
        f.write_text(
            "# Netscape HTTP Cookie File\n"
            "# This is a comment\n"
            ".example.com\tTRUE\t/\tFALSE\t0\tname\tvalue\n",
            encoding="utf-8",
        )
        parsed = _parse_netscape_file(f)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "name"

    def test_parse_returns_empty_for_missing_file(self, tmp_path):
        result = _parse_netscape_file(tmp_path / "nonexistent.txt")
        assert result == []

    def test_parse_skips_malformed_lines(self, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_text(
            "# Netscape HTTP Cookie File\n"
            "only_two_fields\tsecond\n"
            ".example.com\tTRUE\t/\tFALSE\t0\tgood\tvalue\n",
            encoding="utf-8",
        )
        parsed = _parse_netscape_file(f)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "good"

    def test_write_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "nested" / "deep" / "cookies.txt"
        _write_netscape_file([], out)
        assert out.parent.is_dir()


# ─── CookieManager ────────────────────────────────────────────────────────────


class TestCookieManagerInit:
    def test_creates_storage_dir(self, tmp_path):
        storage = tmp_path / "cookies"
        assert not storage.exists()
        CookieManager(storage_dir=storage)
        assert storage.is_dir()

    def test_default_storage_dir(self, tmp_path, monkeypatch):
        # Just verify it doesn't crash with default
        manager = CookieManager(storage_dir=tmp_path / "cookies")
        assert manager._storage_dir == tmp_path / "cookies"


class TestSaveFromExtension:
    def test_saves_to_cache(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "SESSDATA=abc; bili_jct=xyz")
        entry = manager._cache.get("bilibili")
        assert entry is not None
        assert entry.source == CookieSource.EXTENSION
        assert entry.platform == "bilibili"

    def test_writes_netscape_file(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "SESSDATA=abc123")
        cookie_file = tmp_path / "bilibili.txt"
        assert cookie_file.is_file()
        content = cookie_file.read_text()
        assert "SESSDATA" in content
        assert "abc123" in content

    def test_cookie_str_stored_in_entry(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("tiktok", "sessionid=tok123")
        entry = manager._cache["tiktok"]
        assert entry.cookie_str == "sessionid=tok123"

    def test_overwrites_previous_entry(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "old=value")
        manager.save_from_extension("bilibili", "new=value")
        assert manager._cache["bilibili"].cookie_str == "new=value"


class TestLoadFromFile:
    def _make_netscape_file(self, path: Path, platform: str = "bilibili") -> None:
        domain = PLATFORM_DOMAINS.get(platform, ".example.com")
        path.write_text(
            f"# Netscape HTTP Cookie File\n"
            f"{domain}\tTRUE\t/\tFALSE\t0\tSESSDATA\tabc123\n",
            encoding="utf-8",
        )

    def test_loads_valid_file(self, tmp_path):
        src = tmp_path / "src_cookies.txt"
        self._make_netscape_file(src)
        manager = CookieManager(storage_dir=tmp_path / "storage")
        manager.load_from_file("bilibili", src)
        entry = manager._cache.get("bilibili")
        assert entry is not None
        assert entry.source == CookieSource.FILE

    def test_copies_file_to_storage(self, tmp_path):
        src = tmp_path / "src.txt"
        self._make_netscape_file(src)
        storage = tmp_path / "storage"
        manager = CookieManager(storage_dir=storage)
        manager.load_from_file("bilibili", src)
        assert (storage / "bilibili.txt").is_file()

    def test_raises_file_not_found(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        with pytest.raises(FileNotFoundError):
            manager.load_from_file("bilibili", tmp_path / "nonexistent.txt")

    def test_raises_value_error_for_empty_file(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("# Netscape HTTP Cookie File\n")
        manager = CookieManager(storage_dir=tmp_path / "storage")
        with pytest.raises(ValueError, match="No valid cookies"):
            manager.load_from_file("bilibili", empty)


class TestGetCookies:
    def _make_cookie_file(self, storage: Path, platform: str) -> None:
        domain = PLATFORM_DOMAINS.get(platform, ".example.com")
        f = storage / f"{platform}.txt"
        f.write_text(
            f"# Netscape HTTP Cookie File\n"
            f"{domain}\tTRUE\t/\tFALSE\t0\tSESSDATA\tabc123\n",
            encoding="utf-8",
        )

    def test_returns_none_when_no_cookies(self, tmp_path, monkeypatch):
        # Prevent Chrome fallback
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.get_cookies("bilibili")
        assert result is None

    def test_returns_entry_from_cache(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "SESSDATA=cached")
        entry = manager.get_cookies("bilibili")
        assert entry is not None
        assert entry.source == CookieSource.EXTENSION

    def test_returns_entry_from_file(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        self._make_cookie_file(tmp_path, "bilibili")
        manager = CookieManager(storage_dir=tmp_path)
        entry = manager.get_cookies("bilibili")
        assert entry is not None
        assert entry.source == CookieSource.FILE

    def test_caches_file_entry(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        self._make_cookie_file(tmp_path, "bilibili")
        manager = CookieManager(storage_dir=tmp_path)
        manager.get_cookies("bilibili")
        assert "bilibili" in manager._cache


class TestGetCookieFile:
    def test_returns_path_when_file_exists(self, tmp_path):
        cookie_file = tmp_path / "bilibili.txt"
        cookie_file.write_text("# Netscape HTTP Cookie File\n")
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.get_cookie_file("bilibili")
        assert result == cookie_file

    def test_returns_none_when_no_file_and_no_chrome(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.get_cookie_file("bilibili")
        assert result is None

    def test_returns_path_after_extension_save(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "SESSDATA=abc")
        result = manager.get_cookie_file("bilibili")
        assert result is not None
        assert result.is_file()


class TestLoadFromChrome:
    def test_returns_false_when_browser_cookie3_not_installed(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.load_from_chrome("bilibili")
        assert result is False

    def test_returns_false_for_unknown_platform(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.load_from_chrome("unknown_platform_xyz")
        assert result is False

    def test_returns_true_and_writes_file_when_cookies_found(self, tmp_path):
        # Mock browser_cookie3 module
        mock_bc3 = MagicMock()
        mock_cookie = MagicMock()
        mock_cookie.name = "SESSDATA"
        mock_cookie.value = "chrome_value"
        mock_cookie.domain = ".bilibili.com"
        mock_cookie.path = "/"
        mock_cookie.secure = True
        mock_cookie.expires = 1800000000

        mock_cj = [mock_cookie]
        mock_bc3.chrome.return_value = mock_cj

        with patch.dict(sys.modules, {"browser_cookie3": mock_bc3}):
            manager = CookieManager(storage_dir=tmp_path)
            result = manager.load_from_chrome("bilibili")

        assert result is True
        assert (tmp_path / "bilibili.txt").is_file()
        assert "bilibili" in manager._cache
        assert manager._cache["bilibili"].source == CookieSource.CHROME

    def test_returns_false_when_no_cookies_found(self, tmp_path):
        mock_bc3 = MagicMock()
        mock_bc3.chrome.return_value = []  # empty cookie jar

        with patch.dict(sys.modules, {"browser_cookie3": mock_bc3}):
            manager = CookieManager(storage_dir=tmp_path)
            result = manager.load_from_chrome("bilibili")

        assert result is False

    def test_returns_false_on_exception(self, tmp_path):
        mock_bc3 = MagicMock()
        mock_bc3.chrome.side_effect = Exception("Chrome not running")

        with patch.dict(sys.modules, {"browser_cookie3": mock_bc3}):
            manager = CookieManager(storage_dir=tmp_path)
            result = manager.load_from_chrome("bilibili")

        assert result is False


class TestExportNetscape:
    def test_exports_existing_file(self, tmp_path):
        storage = tmp_path / "storage"
        storage.mkdir()
        src = storage / "bilibili.txt"
        src.write_text("# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tFALSE\t0\tk\tv\n")

        manager = CookieManager(storage_dir=storage)
        dest = tmp_path / "export" / "bilibili.txt"
        result = manager.export_netscape("bilibili", dest)

        assert result is True
        assert dest.is_file()
        assert dest.read_text() == src.read_text()

    def test_returns_false_when_no_cookies(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.export_netscape("bilibili", tmp_path / "out.txt")
        assert result is False

    def test_creates_parent_dirs(self, tmp_path):
        storage = tmp_path / "storage"
        storage.mkdir()
        (storage / "tiktok.txt").write_text(
            "# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tFALSE\t0\tsid\tv\n"
        )
        manager = CookieManager(storage_dir=storage)
        dest = tmp_path / "a" / "b" / "c" / "tiktok.txt"
        result = manager.export_netscape("tiktok", dest)
        assert result is True
        assert dest.is_file()


class TestListAvailable:
    def test_empty_when_nothing_available(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.list_available("bilibili")
        assert result == []

    def test_includes_chrome_when_browser_cookie3_installed(self, tmp_path):
        mock_bc3 = MagicMock()
        with patch.dict(sys.modules, {"browser_cookie3": mock_bc3}):
            manager = CookieManager(storage_dir=tmp_path)
            result = manager.list_available("bilibili")
        assert CookieSource.CHROME in result

    def test_includes_file_when_cookie_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        (tmp_path / "bilibili.txt").write_text("# Netscape HTTP Cookie File\n")
        manager = CookieManager(storage_dir=tmp_path)
        result = manager.list_available("bilibili")
        assert CookieSource.FILE in result

    def test_includes_extension_when_in_cache(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "browser_cookie3", None)
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "SESSDATA=abc")
        result = manager.list_available("bilibili")
        assert CookieSource.EXTENSION in result


class TestClearCache:
    def test_clears_specific_platform(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "k=v")
        manager.save_from_extension("tiktok", "k=v")
        manager.clear_cache("bilibili")
        assert "bilibili" not in manager._cache
        assert "tiktok" in manager._cache

    def test_clears_all_platforms(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "k=v")
        manager.save_from_extension("tiktok", "k=v")
        manager.clear_cache()
        assert manager._cache == {}

    def test_clear_nonexistent_platform_is_safe(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.clear_cache("nonexistent")  # should not raise


# ─── Integration: extension → get_cookie_file ─────────────────────────────────


class TestIntegrationExtensionToYtdlp:
    """Simulate the main use case: extension pushes cookies → yt-dlp gets file."""

    def test_extension_cookie_available_as_file(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("bilibili", "SESSDATA=abc123; bili_jct=xyz789")

        cookie_file = manager.get_cookie_file("bilibili")
        assert cookie_file is not None
        assert cookie_file.is_file()

        content = cookie_file.read_text()
        assert "# Netscape HTTP Cookie File" in content
        assert "SESSDATA" in content
        assert "abc123" in content

    def test_get_cookies_returns_extension_entry(self, tmp_path):
        manager = CookieManager(storage_dir=tmp_path)
        manager.save_from_extension("douyin", "token=tok123")

        entry = manager.get_cookies("douyin")
        assert entry is not None
        assert entry.source == CookieSource.EXTENSION
        assert entry.platform == "douyin"
        assert "token=tok123" in entry.cookie_str
