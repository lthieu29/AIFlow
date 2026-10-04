"""Default remaster workdirs must not delete the returned deliverables."""
import asyncio
from pathlib import Path

from server.content.adapters.video_remaster import adapter
from server.content.base import AdapterInput
from server.content.crawlers.base import DownloadResult
from server.content.crawlers.remaster import RemasterPreset, RemasterResult


def test_default_workdir_persists_output_and_subtitles(tmp_path, monkeypatch):
    monkeypatch.setenv("AIFLOW_DATA_DIR", str(tmp_path / "storage"))
    working = []

    class Manager:
        def download(self, url, output_dir, cookies=None):
            working.append(output_dir)
            source = output_dir / "source.mp4"
            source.write_bytes(b"downloaded")
            return DownloadResult(url=url, output_path=source, title="Test", duration=12, platform="generic")

    class Remaster:
        def __init__(self, config):
            pass

        async def remaster(self, source, folder):
            output, translated, original = [folder / name for name in ("output.mp4", "translated.srt", "original.srt")]
            output.write_bytes(b"rendered")
            translated.write_text("translated", encoding="utf-8")
            original.write_text("original", encoding="utf-8")
            return RemasterResult(output_path=output, translated_srt=translated, original_srt=original, preset=RemasterPreset.LIGHT)

    monkeypatch.setattr(adapter, "DownloadManager", Manager)
    monkeypatch.setattr(adapter, "VideoRemaster", Remaster)
    result = asyncio.run(adapter.VideoRemasterAdapter().adapt(AdapterInput(source_type="video", raw_content="https://example.com/test.mp4")))
    assert not working[0].exists()
    assert result.scenes[0].duration == 12
    for key, content in (("output_path", b"rendered"), ("translated_srt", b"translated"), ("original_srt", b"original")):
        output = Path(result.metadata[key])
        assert output.is_relative_to(tmp_path / "storage")
        assert output.read_bytes() == content
