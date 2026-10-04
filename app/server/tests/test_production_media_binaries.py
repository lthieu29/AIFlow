"""Production media must use the bundled binaries without a PATH installation."""
import subprocess

import pytest

from server.production import media
from server.render import ffmpeg_utils


def test_production_uses_vendor_without_path(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    for name in ("ffmpeg", "ffprobe"):
        (vendor / f"{name}.exe").touch()
    monkeypatch.setattr(ffmpeg_utils, "_VENDOR_DIR", vendor)
    monkeypatch.setattr(ffmpeg_utils.shutil, "which", lambda _: None)
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, b'{"format":{"duration":"8"},"streams":[]}')

    monkeypatch.setattr(media.subprocess, "run", run)
    assert media.probe(tmp_path / "source.mp4")["duration"] == 8
    media.ffmpeg(["-i", "source.mp4", "output.mp4"])
    assert [call[0] for call in calls] == [str(vendor / "ffprobe.exe"), str(vendor / "ffmpeg.exe")]


@pytest.mark.parametrize("operation", ["probe", "ffmpeg"])
def test_missing_binaries_explain_vendor_install(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(ffmpeg_utils, "_VENDOR_DIR", tmp_path)
    monkeypatch.setattr(ffmpeg_utils.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="vendor"):
        getattr(media, operation)(tmp_path / "source.mp4" if operation == "probe" else [])
