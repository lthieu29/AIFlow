"""Unit tests for the native-API download path (signing-based, no network).

Covers:
- native.extract_douyin_aweme_id() / extract_bilibili_id() URL parsing
- DouyinDownloader native-first path (mocked fetch + byte download)
- DouyinDownloader falls back to yt-dlp on NativeAPIError
- BilibiliDownloader native DASH path (mocked fetch + merge)
- BilibiliDownloader falls back to yt-dlp on NativeAPIError

All network/disk side effects are mocked — no real HTTP calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── URL parsing ──────────────────────────────────────────────────────────────


class TestUrlExtraction:
    def test_extract_douyin_aweme_id_from_full_url(self):
        from server.content.crawlers.native import extract_douyin_aweme_id

        url = "https://www.douyin.com/video/7345492945006595379"
        assert extract_douyin_aweme_id(url) == "7345492945006595379"

    def test_extract_douyin_aweme_id_from_modal(self):
        from server.content.crawlers.native import extract_douyin_aweme_id

        url = "https://www.douyin.com/?modal_id=7345492945006595379"
        assert extract_douyin_aweme_id(url) == "7345492945006595379"

    def test_extract_douyin_aweme_id_none_when_absent(self):
        from server.content.crawlers.native import extract_douyin_aweme_id

        assert extract_douyin_aweme_id("https://www.douyin.com/user/abc") is None

    def test_extract_bilibili_bvid(self):
        from server.content.crawlers.native import extract_bilibili_id

        bvid, aid = extract_bilibili_id("https://www.bilibili.com/video/BV1xx411c7mD")
        assert bvid == "BV1xx411c7mD"
        assert aid is None

    def test_extract_bilibili_avid(self):
        from server.content.crawlers.native import extract_bilibili_id

        bvid, aid = extract_bilibili_id("https://www.bilibili.com/video/av170001")
        assert bvid is None
        assert aid == 170001


# ─── Douyin native path ───────────────────────────────────────────────────────


class TestDouyinNativePath:
    def test_native_success(self, tmp_path, monkeypatch):
        """Native path resolves a URL + downloads bytes without yt-dlp."""
        from server.content.crawlers.douyin import downloader as dy_mod
        from server.content.crawlers.douyin.downloader import DouyinDownloader

        output_dir = tmp_path / "out"

        async def fake_fetch(aweme_id, cookie="", user_agent=""):
            return ("https://cdn.douyin.com/video.mp4", "My Douyin Video", 12.5)

        async def fake_download(url, out_path, **kwargs):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"x" * 2048)
            return out_path

        monkeypatch.setattr(dy_mod, "douyin_fetch_video_url", fake_fetch)
        monkeypatch.setattr(dy_mod, "download_url_to_file", fake_download)
        monkeypatch.setattr(dy_mod, "read_cookie_string", lambda c: "")

        # subprocess.run must NOT be called on the native path.
        with patch("subprocess.run", side_effect=AssertionError("yt-dlp should not run")):
            dl = DouyinDownloader()
            result = dl.download(
                "https://www.douyin.com/video/7345492945006595379", output_dir
            )

        assert result.metadata["source"] == "native_api"
        assert result.title == "My Douyin Video"
        assert result.duration == pytest.approx(12.5)
        assert result.output_path.exists()

    def test_falls_back_to_ytdlp_on_native_error(self, tmp_path, monkeypatch):
        """When native fetch raises NativeAPIError, yt-dlp path runs."""
        from server.content.crawlers import base as base_mod
        from server.content.crawlers.douyin import downloader as dy_mod
        from server.content.crawlers.douyin.downloader import DouyinDownloader
        from server.content.crawlers.native import NativeAPIError

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        def _boom(*args, **kwargs):
            raise NativeAPIError("signing unavailable")

        monkeypatch.setattr(dy_mod, "douyin_fetch_video_url", _boom)
        monkeypatch.setattr(dy_mod, "read_cookie_string", lambda c: "")

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / "Fallback Video.mp4").write_bytes(b"fake")

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("subprocess.run", return_value=fake_proc):
            dl = DouyinDownloader()
            result = dl.download(
                "https://www.douyin.com/video/7345492945006595379", output_dir
            )

        assert result.metadata["source"] == "yt_dlp"
        assert result.platform == "douyin"


# ─── Bilibili native path ─────────────────────────────────────────────────────


class TestBilibiliNativePath:
    def test_native_dash_success(self, tmp_path, monkeypatch):
        """Native DASH path downloads video+audio and merges, no yt-dlp."""
        from server.content.crawlers.bilibili import downloader as bili_mod
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader

        output_dir = tmp_path / "out"

        async def fake_fetch(bvid, aid, cookie="", user_agent=""):
            return {
                "video_url": "https://cdn.bili.com/v.m4s",
                "audio_url": "https://cdn.bili.com/a.m4s",
                "title": "My Bili Video",
                "duration": 300.0,
                "referer": "https://www.bilibili.com/",
            }

        async def fake_download(url, out_path, **kwargs):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"x" * 2048)
            return out_path

        # Fake StreamMerger so no ffmpeg is needed.
        fake_merger_instance = MagicMock()

        def fake_merge(v, a, out):
            Path(out).write_bytes(b"merged")
            return MagicMock(output_path=out, duration=300.0, has_audio=True)

        fake_merger_instance.merge.side_effect = fake_merge
        fake_merger_cls = MagicMock(return_value=fake_merger_instance)

        monkeypatch.setattr(bili_mod, "bilibili_fetch_streams", fake_fetch)
        monkeypatch.setattr(bili_mod, "download_url_to_file", fake_download)
        monkeypatch.setattr(bili_mod, "read_cookie_string", lambda c: "")

        with patch(
            "server.content.crawlers.stream_merger.StreamMerger", fake_merger_cls
        ):
            with patch("subprocess.run", side_effect=AssertionError("yt-dlp should not run")):
                dl = BilibiliDownloader()
                result = dl.download("BV1xx411c7mD", output_dir)

        assert result.metadata["source"] == "native_api"
        assert result.title == "My Bili Video"
        assert result.output_path.exists()
        fake_merger_instance.merge.assert_called_once()

    def test_native_progressive_success(self, tmp_path, monkeypatch):
        """Progressive (durl) path writes a single file, no merge needed."""
        from server.content.crawlers.bilibili import downloader as bili_mod
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader

        output_dir = tmp_path / "out"

        async def fake_fetch(bvid, aid, cookie="", user_agent=""):
            return {
                "video_url": "https://cdn.bili.com/full.mp4",
                "audio_url": None,
                "title": "Progressive Video",
                "duration": 60.0,
                "referer": "https://www.bilibili.com/",
            }

        async def fake_download(url, out_path, **kwargs):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"x" * 2048)
            return out_path

        monkeypatch.setattr(bili_mod, "bilibili_fetch_streams", fake_fetch)
        monkeypatch.setattr(bili_mod, "download_url_to_file", fake_download)
        monkeypatch.setattr(bili_mod, "read_cookie_string", lambda c: "")

        with patch("subprocess.run", side_effect=AssertionError("yt-dlp should not run")):
            dl = BilibiliDownloader()
            result = dl.download("BV1xx411c7mD", output_dir)

        assert result.metadata["source"] == "native_api"
        assert result.title == "Progressive Video"
        assert result.output_path.exists()

    def test_falls_back_to_ytdlp_on_native_error(self, tmp_path, monkeypatch):
        from server.content.crawlers import base as base_mod
        from server.content.crawlers.bilibili import downloader as bili_mod
        from server.content.crawlers.bilibili.downloader import BilibiliDownloader
        from server.content.crawlers.native import NativeAPIError

        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "yt-dlp.exe").write_bytes(b"fake")
        monkeypatch.setattr(base_mod, "_VENDOR_DIR", vendor)

        def _boom(*args, **kwargs):
            raise NativeAPIError("WBI keys unavailable")

        monkeypatch.setattr(bili_mod, "bilibili_fetch_streams", _boom)
        monkeypatch.setattr(bili_mod, "read_cookie_string", lambda c: "")

        output_dir = tmp_path / "out"
        output_dir.mkdir()
        (output_dir / "Fallback.mp4").write_bytes(b"fake")

        fake_proc = MagicMock()
        fake_proc.returncode = 0
        fake_proc.stdout = ""
        fake_proc.stderr = ""

        with patch("subprocess.run", return_value=fake_proc):
            dl = BilibiliDownloader()
            result = dl.download("BV1xx411c7mD", output_dir)

        assert result.metadata["source"] == "yt_dlp"
        assert result.platform == "bilibili"
