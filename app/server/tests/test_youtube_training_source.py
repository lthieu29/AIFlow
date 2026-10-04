"""Offline safety boundaries for the Colab YouTube downloader."""
import sys
from types import SimpleNamespace

import pytest

from server.audio import youtube_source as source


@pytest.mark.parametrize("metadata", [{"duration": None}, {"duration": float("nan")}, {"duration": 10801},
    {"is_live": True}, {"live_status": "is_upcoming"}, {"id": "differentid"}, {"filesize": source.MAX_BYTES + 1}])
def test_metadata_bounds_prevent_audio_download(monkeypatch, tmp_path, metadata):
    info = {"id": "iaPiJZeJwQk", "duration": 30, **metadata}
    options = []
    class Downloader:
        def __init__(self, config):
            options.append(config)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            assert download is True
            assert options[0]["match_filter"](info) is not None
            return None
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=Downloader, utils=SimpleNamespace(DownloadError=type("DownloadError", (Exception,), {}))))
    with pytest.raises(RuntimeError, match="hợp lệ"):
        source.fetch_audio("https://youtu.be/iaPiJZeJwQk", tmp_path, tmp_path / "cancel.request")
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure", ["reported-bytes", "actual-bytes", "cancel"])
def test_download_hooks_stop_unknown_size_and_cancel(monkeypatch, tmp_path, failure):
    info = {"id": "iaPiJZeJwQk", "duration": 30, "title": "Podcast"}
    class Downloader:
        def __init__(self, config):
            self.config = config
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download):
            assert self.config["allowed_extractors"] == ["youtube"]
            assert self.config["noplaylist"] is True
            assert self.config["max_filesize"] == source.MAX_BYTES
            assert self.config["cachedir"] is False
            assert "cookiefile" not in self.config and "cookiesfrombrowser" not in self.config
            assert self.config["match_filter"](info) is None
            if failure == "actual-bytes":
                (tmp_path / "audio.webm.part").write_bytes(b"x" * 65)
                monkeypatch.setattr(source, "MAX_BYTES", 64)
            elif failure == "cancel":
                (tmp_path / "cancel.request").touch()
            self.config["progress_hooks"][0]({"downloaded_bytes": source.MAX_BYTES + 1 if failure == "reported-bytes" else 1})
            pytest.fail("Download must be stopped before completion")
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=Downloader, utils=SimpleNamespace(DownloadError=type("DownloadError", (Exception,), {}))))
    with pytest.raises(RuntimeError, match="512 MiB|hủy"):
        source.fetch_audio("https://youtu.be/iaPiJZeJwQk", tmp_path, tmp_path / "cancel.request")


def test_downloader_failure_is_sanitized_without_login_retry(monkeypatch, tmp_path):
    error = type("DownloadError", (Exception,), {})
    class Downloader:
        def __init__(self, config):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, *args, **kwargs):
            raise error("remote signed URL must not be disclosed")
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=Downloader, utils=SimpleNamespace(DownloadError=error)))
    with pytest.raises(RuntimeError) as exc:
        source.fetch_audio("https://youtu.be/iaPiJZeJwQk", tmp_path, tmp_path / "cancel.request")
    assert str(exc.value) == source.DOWNLOAD_ERROR
