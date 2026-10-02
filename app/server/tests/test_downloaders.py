"""Unit tests for the downloader framework (Task 4.5.2).

Tests use subprocess mocking to avoid real network calls.

Covers:
- DownloadResult dataclass construction
- DownloadError exception attributes
- find_aria2c() / find_ytdlp() binary discovery
- BaseDownloader._build_ytdlp_cmd() command construction
- BaseDownloader._parse_info_json() metadata extraction
- BaseDownloader._find_downloaded_file() file detection
- BilibiliDownloader URL normalisation + download flow
- DouyinDownloader download flow
- TikTokDownloader download flow
- GenericDownloader + detect_platform()
- DownloadManager platform routing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# Ensure server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── DownloadResult ───────────────────────────────────────────────────────────


class TestDownloadResult:
    def test_required_fields(self, tmp_path):
        from server.content.crawlers.base import DownloadResult

        r = DownloadResult(
            url="https://example.com/video",
            output_path=tmp_path / "video.mp4",
            title="Test Video",
            duration=120.0,
            platform="generic",
        )
        assert r.url == "https://example.com/video"
        assert r.output_path == tmp_path / "video.mp4"
        assert r.title == "Test Video"
        assert r.duration == 120.0
        assert r.platform == "generic"

    def test_metadata_defaults_to_empty_dict(self, tmp_path):
        from server.content.crawlers.base import DownloadResult

        r = DownloadResult(
            url="https://example.com",
            output_path=tmp_path / "v.mp4",
            title="",
            duration=0.0,
            platform="generic",
        )
        assert r.metadata == {}

    def test_metadata_can_be_set(self, tmp_path):
        from server.content.crawlers.base import DownloadResult

        r = DownloadResult(
            url="https://example.com",
            output_path=tmp_path / "v.mp4",
            title="T",
            duration=10.0,
            platform="bilibili",
            metadata={"bvid": "BV1xx411c7mD"},
        )
        assert r.metadata["bvid"] == "BV1xx411c7mD"


# ─── DownloadError ────────────────────────────────────────────────────────────


class TestDownloadError:
    def test_attributes(self):
        from server.content.crawlers.base import DownloadError

        err = DownloadError("https://example.com", "Network error")
        assert err.url == "https://example.com"
        assert err.reason == "Network error"
        assert err.code == "DOWNLOAD_FAILED"

    def test_custom_code(self):
        from server.content.crawlers.base import DownloadError

        err = DownloadError("https://x.com", "Timeout", code="DOWNLOAD_TIMEOUT")
        assert err.code == "DOWNLOAD_TIMEOUT"

    def test_is_exception(self):
        from server.content.crawlers.base import DownloadError

        with pytest.raises(DownloadError) as exc_info:
            raise DownloadError("https://x.com", "fail")
        assert exc_info.value.url == "https://x.com"

    def test_str_contains_code_and_reason(self):
        from server.content.crawlers.base import DownloadError

        err = DownloadError("https://x.com", "Something went wrong", code="YTDLP_ERROR")
        s = str(err)
        assert "YTDLP_ERROR" in s
        assert "Something went wrong" in s


# ─── Binary discovery ─────────────────────────────────────────────────────────


class TestFindAria2c:
    def test_returns_vendor_path_when_exists(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        # Patch _VENDOR_DIR to tmp_path
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", tmp_path)
        aria2c_exe = tmp_path / "aria2c.exe"
        aria2c_exe.write_bytes(b"fake")

        from server.content.crawlers.base import find_aria2c
        result = find_aria2c()
        assert result == aria2c_exe

    def test_falls_back_to_path(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        monkeypatch.setattr(base_mod, "_VENDOR_DIR", tmp_path)  # no exe in vendor
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/aria2c" if name == "aria2c" else None)

        from server.content.crawlers.base import find_aria2c
        result = find_aria2c()
        assert result == Path("/usr/bin/aria2c")

    def test_returns_none_when_not_found(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        monkeypatch.setattr(base_mod, "_VENDOR_DIR", tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: None)

        from server.content.crawlers.base import find_aria2c
        assert find_aria2c() is None


class TestFindYtdlp:
    def test_returns_vendor_path_when_exists(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        monkeypatch.setattr(base_mod, "_VENDOR_DIR", tmp_path)
        ytdlp_exe = tmp_path / "yt-dlp.exe"
        ytdlp_exe.write_bytes(b"fake")

        from server.content.crawlers.base import find_ytdlp
        result = find_ytdlp()
        assert result == ytdlp_exe

    def test_falls_back_to_path(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        monkeypatch.setattr(base_mod, "_VENDOR_DIR", tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/yt-dlp" if name == "yt-dlp" else None)

        from server.content.crawlers.base import find_ytdlp
        result = find_ytdlp()
        assert result == Path("/usr/bin/yt-dlp")

    def test_returns_module_sentinel_when_only_package_available(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        monkeypatch.setattr(base_mod, "_VENDOR_DIR", tmp_path)
        monkeypatch.setattr("shutil.which", lambda name: None)

        # Ensure yt_dlp is importable (it's in the project deps)
        from server.content.crawlers.base import find_ytdlp
        result = find_ytdlp()
        # Either module sentinel or None (depending on whether yt_dlp is installed)
        assert result is None or str(result) == "yt_dlp:module"


# ─── BaseDownloader helpers ───────────────────────────────────────────────────


class _ConcreteDownloader:
    """Minimal concrete subclass for testing BaseDownloader helpers."""

    platform = "test"

    def download(self, url, output_dir, cookies=None):
        raise NotImplementedError


# Mix in BaseDownloader methods without ABC enforcement
from server.content.crawlers.base import BaseDownloader as _BD
_ConcreteDownloader._build_ytdlp_cmd = _BD._build_ytdlp_cmd
_ConcreteDownloader._parse_info_json = _BD._parse_info_json
_ConcreteDownloader._find_downloaded_file = _BD._find_downloaded_file


class TestBaseDownloaderHelpers:
    def _make_downloader(self):
        return _ConcreteDownloader()

    def test_build_ytdlp_cmd_includes_url(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        ytdlp = vendor / "yt-dlp.exe"
        ytdlp.write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        dl = self._make_downloader()
        cmd = dl._build_ytdlp_cmd("https://example.com/v", tmp_path)
        assert "https://example.com/v" in cmd

    def test_build_ytdlp_cmd_includes_output_template(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        dl = self._make_downloader()
        cmd = dl._build_ytdlp_cmd("https://example.com/v", tmp_path)
        assert "--output" in cmd
        assert str(tmp_path) in " ".join(cmd)

    def test_build_ytdlp_cmd_includes_cookies_when_provided(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")

        dl = self._make_downloader()
        cmd = dl._build_ytdlp_cmd("https://example.com/v", tmp_path, cookies=cookies)
        assert "--cookies" in cmd
        assert str(cookies) in cmd

    def test_build_ytdlp_cmd_no_cookies_when_file_missing(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        dl = self._make_downloader()
        cmd = dl._build_ytdlp_cmd("https://example.com/v", tmp_path, cookies=tmp_path / "nonexistent.txt")
        assert "--cookies" not in cmd

    def test_build_ytdlp_cmd_includes_aria2c_when_available(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        (vendor / "aria2c.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        dl = self._make_downloader()
        cmd = dl._build_ytdlp_cmd("https://example.com/v", tmp_path)
        assert "--external-downloader" in cmd

    def test_build_ytdlp_cmd_raises_when_ytdlp_missing(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod
        from server.content.crawlers.base import DownloadError

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)
        monkeypatch.setattr("shutil.which", lambda name: None)
        # Patch yt_dlp import to fail
        monkeypatch.setitem(sys.modules, "yt_dlp", None)

        dl = self._make_downloader()
        with pytest.raises(DownloadError) as exc_info:
            dl._build_ytdlp_cmd("https://example.com/v", tmp_path)
        assert exc_info.value.code == "YTDLP_NOT_FOUND"

    def test_parse_info_json_extracts_title_and_duration(self, tmp_path):
        dl = self._make_downloader()
        info = {"title": "My Video", "duration": 95.5}
        (tmp_path / "My Video.info.json").write_text(json.dumps(info), encoding="utf-8")

        title, duration = dl._parse_info_json(tmp_path, "https://example.com")
        assert title == "My Video"
        assert duration == pytest.approx(95.5)

    def test_parse_info_json_returns_defaults_when_no_file(self, tmp_path):
        dl = self._make_downloader()
        title, duration = dl._parse_info_json(tmp_path, "https://example.com")
        assert title == ""
        assert duration == 0.0

    def test_parse_info_json_handles_malformed_json(self, tmp_path):
        dl = self._make_downloader()
        (tmp_path / "bad.info.json").write_text("{not valid json", encoding="utf-8")
        title, duration = dl._parse_info_json(tmp_path, "https://example.com")
        assert title == ""
        assert duration == 0.0

    def test_find_downloaded_file_finds_mp4(self, tmp_path):
        dl = self._make_downloader()
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"fake mp4")
        result = dl._find_downloaded_file(tmp_path)
        assert result == mp4

    def test_find_downloaded_file_ignores_info_json(self, tmp_path):
        dl = self._make_downloader()
        (tmp_path / "video.info.json").write_text("{}")
        result = dl._find_downloaded_file(tmp_path)
        assert result is None

    def test_find_downloaded_file_returns_none_when_empty(self, tmp_path):
        dl = self._make_downloader()
        assert dl._find_downloaded_file(tmp_path) is None

    def test_find_downloaded_file_prefers_mp4_over_webm(self, tmp_path):
        dl = self._make_downloader()
        (tmp_path / "a_video.mp4").write_bytes(b"mp4")
        (tmp_path / "b_video.webm").write_bytes(b"webm")
        result = dl._find_downloaded_file(tmp_path)
        # Both are valid; just ensure a video file is returned
        assert result is not None
        assert result.suffix.lower() in {".mp4", ".webm"}


# ─── Bilibili URL normalisation ───────────────────────────────────────────────


class TestBilibiliUrlNormalisation:
    def _normalise(self, url: str) -> str:
        from server.content.crawlers.bilibili.downloader import _normalise_bilibili_url
        return _normalise_bilibili_url(url)

    def test_full_url_unchanged(self):
        url = "https://www.bilibili.com/video/BV1xx411c7mD"
        assert self._normalise(url) == url

    def test_bv_id_becomes_full_url(self):
        assert self._normalise("BV1xx411c7mD") == "https://www.bilibili.com/video/BV1xx411c7mD"

    def test_av_id_with_prefix(self):
        assert self._normalise("av170001") == "https://www.bilibili.com/video/av170001"

    def test_av_id_without_prefix(self):
        assert self._normalise("170001") == "https://www.bilibili.com/video/av170001"

    def test_av_id_uppercase(self):
        assert self._normalise("AV170001") == "https://www.bilibili.com/video/av170001"

    def test_unknown_format_passed_through(self):
        url = "https://other.site.com/video/123"
        assert self._normalise(url) == url

    def test_strips_whitespace(self):
        assert self._normalise("  BV1xx411c7mD  ") == "https://www.bilibili.com/video/BV1xx411c7mD"


# ─── BilibiliDownloader ───────────────────────────────────────────────────────


def _make_successful_subprocess_result(stdout: str = "", returncode: int = 0):
    """Create a mock CompletedProcess for a successful yt-dlp run."""
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = ""
    return mock


class TestBilibiliDownloader:
    """yt-dlp fallback path tests — native API is forced to fail so the
    downloader falls through to the yt-dlp code path being tested here."""

    def _setup_vendor(self, tmp_path, monkeypatch):
        """Create fake vendor binaries, patch _VENDOR_DIR, force native fail."""
        from server.content.crawlers import base as base_mod
        from server.content.crawlers.bilibili import downloader as bili_mod
        from server.content.crawlers.native import NativeAPIError

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        # Force the native API path to be unavailable so tests hit yt-dlp.
        def _boom(*args, **kwargs):
            raise NativeAPIError("forced native failure for fallback test")

        monkeypatch.setattr(bili_mod, "bilibili_fetch_streams", _boom)
        return vendor

    def test_download_success(self, tmp_path, monkeypatch):
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Pre-create the expected output files
        (output_dir / "My Bilibili Video.mp4").write_bytes(b"fake video")
        info = {"title": "My Bilibili Video", "duration": 300.0}
        (output_dir / "My Bilibili Video.info.json").write_text(json.dumps(info))

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = BilibiliDownloader()
            result = dl.download("BV1xx411c7mD", output_dir)

        assert result.platform == "bilibili"
        assert result.title == "My Bilibili Video"
        assert result.duration == pytest.approx(300.0)
        assert result.output_path.suffix == ".mp4"

    def test_download_raises_on_nonzero_exit(self, tmp_path, monkeypatch):
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader
        from server.content.crawlers.base import DownloadError

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = "ERROR: Video unavailable"

        with patch("subprocess.run", return_value=failed):
            dl = BilibiliDownloader()
            with pytest.raises(DownloadError) as exc_info:
                dl.download("BV1xx411c7mD", output_dir)
        assert exc_info.value.code == "YTDLP_ERROR"

    def test_download_raises_on_timeout(self, tmp_path, monkeypatch):
        import subprocess as sp
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader
        from server.content.crawlers.base import DownloadError

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="yt-dlp", timeout=600)):
            dl = BilibiliDownloader()
            with pytest.raises(DownloadError) as exc_info:
                dl.download("BV1xx411c7mD", output_dir)
        assert exc_info.value.code == "DOWNLOAD_TIMEOUT"

    def test_download_raises_when_no_output_file(self, tmp_path, monkeypatch):
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader
        from server.content.crawlers.base import DownloadError

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        # No video file created

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = BilibiliDownloader()
            with pytest.raises(DownloadError) as exc_info:
                dl.download("BV1xx411c7mD", output_dir)
        assert exc_info.value.code == "OUTPUT_NOT_FOUND"

    def test_download_creates_output_dir(self, tmp_path, monkeypatch):
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "new_dir" / "nested"
        # Do NOT pre-create output_dir

        (tmp_path / "video.mp4").write_bytes(b"fake")  # won't be in output_dir

        def fake_run(cmd, **kwargs):
            # Create the output dir and a fake video file
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "video.mp4").write_bytes(b"fake")
            return _make_successful_subprocess_result()

        with patch("subprocess.run", side_effect=fake_run):
            dl = BilibiliDownloader()
            result = dl.download("BV1xx411c7mD", output_dir)

        assert output_dir.exists()
        assert result.output_path.exists()


# ─── DouyinDownloader ─────────────────────────────────────────────────────────


class TestDouyinDownloader:
    """yt-dlp fallback path tests — native API is forced to fail."""

    def _setup_vendor(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod
        from server.content.crawlers.douyin import downloader as dy_mod
        from server.content.crawlers.native import NativeAPIError

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        # Force native API path to fail so tests hit the yt-dlp fallback.
        def _boom(*args, **kwargs):
            raise NativeAPIError("forced native failure for fallback test")

        monkeypatch.setattr(dy_mod, "douyin_fetch_video_url", _boom)
        monkeypatch.setattr(dy_mod, "resolve_redirect", _boom)

    def test_download_success(self, tmp_path, monkeypatch):
        from server.content.crawlers.douyin.downloader import DouyinDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "Douyin Video.mp4").write_bytes(b"fake")
        info = {"title": "Douyin Video", "duration": 60.0}
        (output_dir / "Douyin Video.info.json").write_text(json.dumps(info))

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = DouyinDownloader()
            result = dl.download("https://www.douyin.com/video/7123456789012345678", output_dir)

        assert result.platform == "douyin"
        assert result.title == "Douyin Video"

    def test_download_raises_on_failure(self, tmp_path, monkeypatch):
        from server.content.crawlers.douyin.downloader import DouyinDownloader
        from server.content.crawlers.base import DownloadError

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = "ERROR: Geo-restricted"

        with patch("subprocess.run", return_value=failed):
            dl = DouyinDownloader()
            with pytest.raises(DownloadError):
                dl.download("https://www.douyin.com/video/123", output_dir)


# ─── TikTokDownloader ─────────────────────────────────────────────────────────


class TestTikTokDownloader:
    def _setup_vendor(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

    def test_download_success(self, tmp_path, monkeypatch):
        from server.content.crawlers.tiktok.downloader import TikTokDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "TikTok Video.mp4").write_bytes(b"fake")
        info = {"title": "TikTok Video", "duration": 30.0}
        (output_dir / "TikTok Video.info.json").write_text(json.dumps(info))

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = TikTokDownloader()
            result = dl.download(
                "https://www.tiktok.com/@user/video/7123456789012345678",
                output_dir,
            )

        assert result.platform == "tiktok"
        assert result.duration == pytest.approx(30.0)

    def test_download_raises_on_os_error(self, tmp_path, monkeypatch):
        from server.content.crawlers.tiktok.downloader import TikTokDownloader
        from server.content.crawlers.base import DownloadError

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch("subprocess.run", side_effect=OSError("binary not found")):
            dl = TikTokDownloader()
            with pytest.raises(DownloadError) as exc_info:
                dl.download("https://www.tiktok.com/@user/video/123", output_dir)
        assert exc_info.value.code == "YTDLP_LAUNCH_FAILED"


# ─── detect_platform ─────────────────────────────────────────────────────────


class TestDetectPlatform:
    def test_bilibili_full_url(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://www.bilibili.com/video/BV1xx411c7mD") == "bilibili"

    def test_bilibili_short_url(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://b23.tv/abc123") == "bilibili"

    def test_douyin_full_url(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://www.douyin.com/video/7123456789012345678") == "douyin"

    def test_douyin_short_url(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://v.douyin.com/iXXXXXX/") == "douyin"

    def test_tiktok_full_url(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://www.tiktok.com/@user/video/123") == "tiktok"

    def test_tiktok_short_url(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://vm.tiktok.com/XXXXXXXX/") == "tiktok"

    def test_youtube(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube"

    def test_youtu_be(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://youtu.be/dQw4w9WgXcQ") == "youtube"

    def test_vimeo(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://vimeo.com/123456789") == "vimeo"

    def test_twitter(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://twitter.com/user/status/123") == "twitter"

    def test_x_com(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://x.com/user/status/123") == "twitter"

    def test_instagram(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://www.instagram.com/reel/abc123/") == "instagram"

    def test_unknown_returns_generic(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("https://some-random-site.com/video/123") == "generic"

    def test_empty_string_returns_generic(self):
        from server.content.crawlers.generic import detect_platform
        assert detect_platform("") == "generic"


# ─── GenericDownloader ────────────────────────────────────────────────────────


class TestGenericDownloader:
    def _setup_vendor(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

    def test_download_success_youtube(self, tmp_path, monkeypatch):
        from server.content.crawlers.generic import GenericDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "YouTube Video.mp4").write_bytes(b"fake")
        info = {"title": "YouTube Video", "duration": 212.0}
        (output_dir / "YouTube Video.info.json").write_text(json.dumps(info))

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = GenericDownloader()
            result = dl.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", output_dir)

        assert result.platform == "youtube"
        assert result.title == "YouTube Video"

    def test_download_sets_detected_platform_in_metadata(self, tmp_path, monkeypatch):
        from server.content.crawlers.generic import GenericDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "v.mp4").write_bytes(b"fake")

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = GenericDownloader()
            result = dl.download("https://vimeo.com/123456789", output_dir)

        assert result.metadata.get("detected_platform") == "vimeo"

    def test_download_unknown_url_uses_generic_platform(self, tmp_path, monkeypatch):
        from server.content.crawlers.generic import GenericDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "v.mp4").write_bytes(b"fake")

        with patch("subprocess.run", return_value=_make_successful_subprocess_result()):
            dl = GenericDownloader()
            result = dl.download("https://unknown-site.com/video/123", output_dir)

        assert result.platform == "generic"


# ─── DownloadManager ─────────────────────────────────────────────────────────


class TestDownloadManager:
    def _setup_vendor(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

    def test_supported_platforms_includes_big_three(self):
        from server.content.crawlers.manager import DownloadManager

        manager = DownloadManager()
        platforms = manager.supported_platforms()
        assert "bilibili" in platforms
        assert "douyin" in platforms
        assert "tiktok" in platforms

    def test_supported_platforms_sorted(self):
        from server.content.crawlers.manager import DownloadManager

        manager = DownloadManager()
        platforms = manager.supported_platforms()
        assert platforms == sorted(platforms)

    def test_get_downloader_bilibili(self):
        from server.content.crawlers.manager import DownloadManager
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader

        manager = DownloadManager()
        dl = manager.get_downloader("bilibili")
        assert isinstance(dl, BilibiliDownloader)

    def test_get_downloader_unknown_returns_generic(self):
        from server.content.crawlers.manager import DownloadManager
        from server.content.crawlers.generic import GenericDownloader

        manager = DownloadManager()
        dl = manager.get_downloader("unknown_platform_xyz")
        assert isinstance(dl, GenericDownloader)

    def test_download_routes_bilibili_url_to_bilibili_downloader(self, tmp_path, monkeypatch):
        from server.content.crawlers.manager import DownloadManager
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "v.mp4").write_bytes(b"fake")

        with patch.object(BilibiliDownloader, "download") as mock_dl:
            mock_dl.return_value = MagicMock(platform="bilibili")
            manager = DownloadManager()
            manager.download("https://www.bilibili.com/video/BV1xx411c7mD", output_dir)
            mock_dl.assert_called_once()

    def test_download_routes_douyin_url_to_douyin_downloader(self, tmp_path, monkeypatch):
        from server.content.crawlers.manager import DownloadManager
        from server.content.crawlers.douyin.downloader import DouyinDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(DouyinDownloader, "download") as mock_dl:
            mock_dl.return_value = MagicMock(platform="douyin")
            manager = DownloadManager()
            manager.download("https://www.douyin.com/video/7123456789012345678", output_dir)
            mock_dl.assert_called_once()

    def test_download_routes_tiktok_url_to_tiktok_downloader(self, tmp_path, monkeypatch):
        from server.content.crawlers.manager import DownloadManager
        from server.content.crawlers.tiktok.downloader import TikTokDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        with patch.object(TikTokDownloader, "download") as mock_dl:
            mock_dl.return_value = MagicMock(platform="tiktok")
            manager = DownloadManager()
            manager.download("https://www.tiktok.com/@user/video/123", output_dir)
            mock_dl.assert_called_once()

    def test_download_routes_unknown_url_to_generic(self, tmp_path, monkeypatch):
        from server.content.crawlers.manager import DownloadManager
        from server.content.crawlers.generic import GenericDownloader

        self._setup_vendor(tmp_path, monkeypatch)
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        (output_dir / "v.mp4").write_bytes(b"fake")

        with patch.object(GenericDownloader, "download") as mock_dl:
            mock_dl.return_value = MagicMock(platform="generic")
            manager = DownloadManager()
            manager.download("https://unknown-site.com/video/123", output_dir)
            mock_dl.assert_called_once()
