"""An existing broken vendor executable must not be reported as ready."""
import pytest

from scripts import download_vendor


@pytest.mark.parametrize("name", ["ffmpeg", "ffprobe", "aria2c"])
def test_broken_existing_vendor_fails(tmp_path, monkeypatch, name):
    for binary in ("ffmpeg", "ffprobe", "aria2c"):
        (tmp_path / f"{binary}.exe").touch()
    monkeypatch.setattr(download_vendor, "_VENDOR_DIR", tmp_path)
    monkeypatch.setattr(download_vendor, "_verify_binary", lambda path, *args: path.stem != name)
    download = download_vendor.download_aria2c if name == "aria2c" else download_vendor.download_ffmpeg
    assert download() is False
