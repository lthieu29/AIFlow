"""Task 5.4 — Integration test for the remaster chain on a LOCAL video file.

**Validates: Requirements 7.1, 7.2, 7.3, 7.7, 7.9**

When live download is blocked (anti-bot signing failure or network), R7.9
allows the remaining ``subs → translate → burn`` chain to be exercised
against a locally provided file.  These tests do exactly that:

- ``LIGHT`` end-to-end (with FFmpeg subprocess.run mocked) — output video
  exists, translated SRT exists.
- ``TRANSLATE_ONLY`` end-to-end — original video path returned unchanged,
  ``_vi.srt`` exists.
- Empty-SRT fallback (R7.3) — when extract + transcribe both fail,
  ``VideoRemaster`` writes an empty SRT and continues without crashing.

A clear failure surfaces when the *download* layer fails (mocked).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.adapters.video_remaster.adapter import VideoRemasterAdapter
from server.content.base import AdapterError, AdapterInput
from server.content.crawlers.base import DownloadError, DownloadResult
from server.content.crawlers.remaster import (
    RemasterConfig,
    RemasterPreset,
    VideoRemaster,
)


def _run(coro):
    return asyncio.run(coro)


def _make_local_video(tmp: Path, name: str = "local.mp4") -> Path:
    p = tmp / name
    p.write_bytes(b"\x00" * 16)
    return p


def _zh_srt() -> str:
    return (
        "1\n00:00:01,000 --> 00:00:03,000\nXin chao\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nThe gioi\n\n"
    )


# ─── R7.1 — LIGHT preset on a local video file ───────────────────────────────


def test_light_chain_runs_on_local_video(tmp_path: Path) -> None:
    """**R7.1** — With LIGHT preset on a local video, the chain extracts subs,
    translates (no client → keeps source), burns subs, and the output exists.
    """
    src_video = _make_local_video(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_zh = out_dir / f"{src_video.stem}_zh.srt"
    fake_zh.write_text(_zh_srt(), encoding="utf-8")

    cfg = RemasterConfig(
        preset=RemasterPreset.LIGHT,
        source_language="zh",
        target_language="vi",
        gemini_client=None,  # graceful: keeps source SRT
    )

    fake_merger = MagicMock()
    fake_merger.extract_subs.return_value = fake_zh
    # transcribe must not be called when extract_subs succeeds
    fake_merger.transcribe.side_effect = AssertionError(
        "transcribe must not run when extract_subs returns a path"
    )

    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"fake")

    def fake_subprocess_run(cmd, *args, **kwargs):
        # Last argument in our cmd is the output path; just touch it
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00")
        m = MagicMock()
        m.returncode = 0
        return m

    with patch(
        "server.content.crawlers.remaster.StreamMerger", return_value=fake_merger
    ), patch(
        "server.content.crawlers.remaster.find_ffmpeg", return_value=fake_ffmpeg
    ), patch(
        "server.content.crawlers.remaster.subprocess.run",
        side_effect=fake_subprocess_run,
    ):
        result = _run(VideoRemaster(cfg).remaster(src_video, out_dir))

    assert result.preset == RemasterPreset.LIGHT
    assert result.output_path.exists(), "Remastered video must exist on disk"
    assert result.translated_srt.exists()


# ─── R7.2 — TRANSLATE_ONLY preset on a local video file ─────────────────────


def test_translate_only_returns_original_video(tmp_path: Path) -> None:
    """**R7.2** — With TRANSLATE_ONLY preset, the original video path is
    returned unchanged and only a ``_vi.srt`` is produced (when a Gemini
    client is configured).  Without a client the source SRT path is reused.
    """
    src_video = _make_local_video(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    fake_zh = out_dir / f"{src_video.stem}_zh.srt"
    fake_zh.write_text(_zh_srt(), encoding="utf-8")

    class _OkClient:
        def generate_text(self, prompt: str) -> str:
            return "ban dich"

    cfg = RemasterConfig(
        preset=RemasterPreset.TRANSLATE_ONLY,
        source_language="zh",
        target_language="vi",
        gemini_client=_OkClient(),
    )

    fake_merger = MagicMock()
    fake_merger.extract_subs.return_value = fake_zh

    with patch(
        "server.content.crawlers.remaster.StreamMerger", return_value=fake_merger
    ):
        result = _run(VideoRemaster(cfg).remaster(src_video, out_dir))

    assert result.output_path == src_video, (
        "TRANSLATE_ONLY must return the original video path unchanged"
    )
    # _vi.srt was written
    vi_srt = out_dir / f"{src_video.stem}_vi.srt"
    assert vi_srt.exists()
    assert "ban dich" in vi_srt.read_text(encoding="utf-8")


# ─── R7.3 — empty SRT fallback when extract + transcribe both fail ──────────


def test_empty_srt_fallback_continues_without_crash(tmp_path: Path) -> None:
    """**R7.3** — If embedded extraction AND transcription both fail, an
    empty SRT is written and the remaining pipeline continues without crashing.
    """
    src_video = _make_local_video(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    cfg = RemasterConfig(
        preset=RemasterPreset.TRANSLATE_ONLY,  # avoids needing FFmpeg
        source_language="zh",
        target_language="vi",
        gemini_client=None,
    )

    fake_merger = MagicMock()
    fake_merger.extract_subs.return_value = None  # fail
    fake_merger.transcribe.return_value = None    # fail

    with patch(
        "server.content.crawlers.remaster.StreamMerger", return_value=fake_merger
    ):
        result = _run(VideoRemaster(cfg).remaster(src_video, out_dir))

    # Pipeline did not crash — result is returned
    assert result is not None
    # An (empty) SRT exists at the expected path
    empty_srt = out_dir / f"{src_video.stem}_zh.srt"
    assert empty_srt.exists()
    assert empty_srt.read_text(encoding="utf-8") == ""


# ─── R7.7 — download failure surfaces a clear error ─────────────────────────


def test_adapter_download_failure_clear_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**R7.7** — When the download layer fails, the adapter emits a clear
    ``ADAPTER_DOWNLOAD_FAILED`` error rather than producing an empty output."""
    import server.content.adapters.video_remaster.adapter as adapter_mod

    class _AlwaysFails:
        def download(self, url, output_dir, cookies=None):
            raise DownloadError(url, "anti-bot signing rejected", code="YTDLP_ERROR")

    monkeypatch.setattr(adapter_mod, "DownloadManager", _AlwaysFails)
    # Make the retry sleep a no-op for fast tests
    monkeypatch.setattr(adapter_mod, "_DEFAULT_SLEEP_SEC", 0.0)

    adapter = VideoRemasterAdapter()

    with pytest.raises(AdapterError) as exc_info:
        _run(
            adapter.adapt(
                AdapterInput(
                    source_type="video",
                    raw_content="https://www.bilibili.com/video/BV1xx411c7mD",
                    options={"workdir": str(tmp_path / "work")},
                )
            )
        )
    err = exc_info.value
    assert err.code == "ADAPTER_DOWNLOAD_FAILED"
    assert "anti-bot signing rejected" in err.message
    assert err.details.get("code") == "YTDLP_ERROR"


# ─── R7.9 — full local fallback (download mocked, chain runs on local file) ──


def test_local_fallback_chain_via_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**R7.9** — When live download is blocked, a fixed local file can be
    fed in by mocking ``DownloadManager`` so the rest of the chain proves it
    runs end-to-end (extract → translate → burn) for the LIGHT preset."""
    import server.content.adapters.video_remaster.adapter as adapter_mod

    src_video = _make_local_video(tmp_path)

    class _FakeManager:
        def download(self, url, output_dir, cookies=None):
            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / src_video.name
            if not target.exists():
                target.write_bytes(src_video.read_bytes())
            return DownloadResult(
                url=url,
                output_path=target,
                title="Local",
                duration=12.0,
                platform="generic",
            )

    monkeypatch.setattr(adapter_mod, "DownloadManager", _FakeManager)

    fake_merger = MagicMock()

    def _extract_then_write(video_path, srt_path, language):
        srt_path.write_text(_zh_srt(), encoding="utf-8")
        return srt_path

    fake_merger.extract_subs.side_effect = _extract_then_write
    fake_merger.transcribe.side_effect = AssertionError(
        "transcribe must not run when extract_subs succeeds"
    )

    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffmpeg.write_bytes(b"fake")

    def fake_run(cmd, *args, **kwargs):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00")
        m = MagicMock()
        m.returncode = 0
        return m

    with patch(
        "server.content.crawlers.remaster.StreamMerger", return_value=fake_merger
    ), patch(
        "server.content.crawlers.remaster.find_ffmpeg", return_value=fake_ffmpeg
    ), patch(
        "server.content.crawlers.remaster.subprocess.run", side_effect=fake_run
    ):
        scene_list = _run(
            VideoRemasterAdapter().adapt(
                AdapterInput(
                    source_type="video",
                    raw_content="https://example.com/local-fallback",
                    options={
                        "workdir": str(tmp_path / "work"),
                        "preset": "light",
                    },
                )
            )
        )

    assert scene_list.metadata["passthrough"] is True
    output_path = Path(scene_list.metadata["output_path"])
    assert output_path.exists()
    translated = Path(scene_list.metadata["translated_srt"])
    assert translated.exists()
