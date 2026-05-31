"""Task 8.6 — smoke test for the 5 new content-expansion adapters.

Validates Requirements 4.1 / 4.2 / 4.3 / 4.4 / 4.5:
- All 5 new adapter types are auto-discovered by AdapterRegistry.
- Each adapter exposes an ``ADAPTER`` instance + ``adapter_type`` (R4.3).
- Each adapter satisfies the ``ContentAdapter`` Protocol (R4.4).
- ``adapt()`` produces a valid ``SceneList`` with sample input + mocked I/O (R4.5).
- ``validate_input()`` returns ``[]`` for valid input and a non-empty list for
  obviously bad input.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.base import AdapterInput, ContentAdapter, SceneList
from server.content.registry import AdapterRegistry

NEW_ADAPTER_TYPES = {
    "document_summary",
    "lyric_video",
    "news_bulletin",
    "podcast_caption",
    "photo_slideshow",
}


# ─── Auto-discovery (R4.1, R4.2, R4.3) ───────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> AdapterRegistry:
    """Fresh AdapterRegistry with auto_discover run once for the whole module."""
    reg = AdapterRegistry()
    reg.auto_discover("server.content.adapters")
    return reg


def test_all_five_new_adapters_discovered(registry: AdapterRegistry) -> None:
    """**R4.1, R4.2** — All 5 new adapter types are present after auto-discovery."""
    discovered = set(registry.list_types())
    missing = NEW_ADAPTER_TYPES - discovered
    assert not missing, (
        f"Missing adapter types after auto_discover: {missing}. "
        f"Found: {sorted(discovered)}"
    )


@pytest.mark.parametrize("adapter_type", sorted(NEW_ADAPTER_TYPES))
def test_adapter_exposes_module_level_instance(adapter_type: str) -> None:
    """**R4.3** — Each new adapter exposes a module-level ``ADAPTER`` instance
    whose ``adapter_type`` matches the directory name (and a unique value)."""
    import importlib

    module = importlib.import_module(
        f"server.content.adapters.{adapter_type}.adapter"
    )
    assert hasattr(module, "ADAPTER"), f"{adapter_type} must expose ADAPTER"
    assert getattr(module.ADAPTER, "adapter_type", None) == adapter_type


@pytest.mark.parametrize("adapter_type", sorted(NEW_ADAPTER_TYPES))
def test_adapter_satisfies_content_adapter_protocol(
    registry: AdapterRegistry, adapter_type: str
) -> None:
    """**R4.4** — Each new adapter satisfies the ``ContentAdapter`` Protocol."""
    adapter = registry.get(adapter_type)
    # Protocol is runtime_checkable
    assert isinstance(adapter, ContentAdapter), (
        f"{adapter_type} does not satisfy ContentAdapter Protocol"
    )
    # Spot-check Protocol surface
    assert callable(getattr(adapter, "adapt", None))
    assert callable(getattr(adapter, "validate_input", None))


def test_no_duplicate_adapter_types(registry: AdapterRegistry) -> None:
    """All adapter_type strings registered after auto_discover are unique."""
    types_ = registry.list_types()
    assert len(types_) == len(set(types_))


# ─── document_summary (R4.5) ─────────────────────────────────────────────────


def test_document_summary_adapt_with_raw_text(
    registry: AdapterRegistry,
) -> None:
    """``document_summary`` produces a valid SceneList from raw_content text
    when no document asset is provided (no ``gemini_client`` → sentence chunking)."""
    import asyncio

    adapter = registry.get("document_summary")
    raw_text = (
        "AIFlow is a personal AI video tool. It combines Veo3 for visuals, "
        "Gemini for scripting, and edge_tts for narration. The pipeline runs "
        "natively on Windows. Output is a polished short-form video. "
        "All processing happens locally except for Veo3 generation. "
        "The user supplies an idea or asset and the system handles the rest."
    )
    inp = AdapterInput(source_type="document", raw_content=raw_text)

    scene_list = asyncio.run(adapter.adapt(inp))

    assert isinstance(scene_list, SceneList)
    ok, errors = scene_list.validate()
    assert ok, f"SceneList validation errors: {errors}"
    assert len(scene_list.scenes) >= 1
    # narration text should reflect the source
    assert any(
        s.narration and "AIFlow" in s.narration for s in scene_list.scenes
    ) or any("AIFlow" in s.prompt for s in scene_list.scenes)


def test_document_summary_validate_input_rejects_empty(
    registry: AdapterRegistry,
) -> None:
    adapter = registry.get("document_summary")
    inp = AdapterInput(source_type="document", raw_content="")
    errors = adapter.validate_input(inp)
    assert errors, "expected non-empty error list for empty input"


# ─── lyric_video (R4.5) ──────────────────────────────────────────────────────


def test_lyric_video_adapt_plain_text(registry: AdapterRegistry) -> None:
    import asyncio

    adapter = registry.get("lyric_video")
    raw = "Em ơi anh nhớ\nNgày mình bên nhau\nMùa thu lá vàng"
    inp = AdapterInput(source_type="lyric", raw_content=raw)

    scene_list = asyncio.run(adapter.adapt(inp))
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 3
    # narration matches each line in order
    for i, expected in enumerate(raw.splitlines()):
        assert scene_list.scenes[i].narration == expected
    # plain-text path → metadata.synced is False
    assert scene_list.metadata.get("synced") is False


def test_lyric_video_adapt_lrc_timed(registry: AdapterRegistry) -> None:
    """LRC input → ``synced=True`` and durations derived from timestamp gaps."""
    import asyncio

    adapter = registry.get("lyric_video")
    lrc = (
        "[00:00.00]Line one\n"
        "[00:05.00]Line two\n"
        "[00:12.50]Line three\n"
    )
    inp = AdapterInput(source_type="lyric", raw_content=lrc)
    scene_list = asyncio.run(adapter.adapt(inp))

    ok, errors = scene_list.validate()
    assert ok, errors
    assert scene_list.metadata.get("synced") is True
    assert len(scene_list.scenes) == 3
    # gap between line 1 and 2 is 5.0 → clamped to min 3.0? No, 5.0 is in range
    assert scene_list.scenes[0].duration == pytest.approx(5.0)
    # gap between line 2 and 3 is 7.5
    assert scene_list.scenes[1].duration == pytest.approx(7.5)


def test_lyric_video_validate_input_rejects_empty(
    registry: AdapterRegistry,
) -> None:
    adapter = registry.get("lyric_video")
    errors = adapter.validate_input(
        AdapterInput(source_type="lyric", raw_content="")
    )
    assert errors


# ─── news_bulletin (R4.5) ────────────────────────────────────────────────────


_RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Feed</title>
    <link>https://example.com</link>
    <description>Sample</description>
    <item>
      <title>Headline One</title>
      <description>First item summary.</description>
      <link>https://example.com/1</link>
    </item>
    <item>
      <title>Headline Two</title>
      <description>Second item summary.</description>
      <link>https://example.com/2</link>
    </item>
  </channel>
</rss>
"""


def test_news_bulletin_adapt_raw_xml(registry: AdapterRegistry) -> None:
    pytest.importorskip("feedparser")
    import asyncio

    adapter = registry.get("news_bulletin")
    inp = AdapterInput(source_type="news", raw_content=_RSS_SAMPLE)
    scene_list = asyncio.run(adapter.adapt(inp))
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 2
    assert any(
        s.narration and "Headline One" in s.narration
        for s in scene_list.scenes
    )


def test_news_bulletin_validate_input_well_formed_url(
    registry: AdapterRegistry,
) -> None:
    """For a URL ``validate_input`` only checks well-formedness (R4.6)."""
    adapter = registry.get("news_bulletin")
    errors = adapter.validate_input(
        AdapterInput(
            source_type="news", raw_content="https://example.com/feed.xml"
        )
    )
    assert errors == []


def test_news_bulletin_validate_input_rejects_bad_url(
    registry: AdapterRegistry,
) -> None:
    adapter = registry.get("news_bulletin")
    errors = adapter.validate_input(
        AdapterInput(source_type="news", raw_content="ftp://nope")
    )
    assert errors


# ─── podcast_caption (R4.5) ──────────────────────────────────────────────────


def test_podcast_caption_validate_input_missing_audio(
    registry: AdapterRegistry,
) -> None:
    adapter = registry.get("podcast_caption")
    errors = adapter.validate_input(
        AdapterInput(source_type="audio", raw_content="")
    )
    assert errors
    assert any("audio" in e.lower() for e in errors)


def test_podcast_caption_validate_input_missing_file(
    registry: AdapterRegistry, tmp_path: Path
) -> None:
    adapter = registry.get("podcast_caption")
    errors = adapter.validate_input(
        AdapterInput(
            source_type="audio",
            raw_content="",
            assets={"audio": tmp_path / "missing.wav"},
        )
    )
    assert errors


def test_podcast_caption_adapt_with_mocked_transcribe(
    registry: AdapterRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``podcast_caption`` produces SceneList from mocked transcription segments."""
    import asyncio
    from dataclasses import dataclass

    adapter = registry.get("podcast_caption")

    audio = tmp_path / "podcast.wav"
    audio.write_bytes(b"RIFF\x00\x00\x00\x00WAVE")  # placeholder

    @dataclass
    class _Seg:
        start_time: float
        end_time: float
        text: str

    fake_segments = [
        _Seg(0.0, 4.0, "Hello listeners"),
        _Seg(4.0, 10.0, "Welcome to AIFlow"),
    ]

    def fake_transcribe(audio_path: Path, language: str | None = None,
                        model_size: str = "base") -> list[Any]:
        assert audio_path == audio
        return fake_segments

    # Provide a fake ``server.audio.transcribe`` module so the lazy import in
    # PodcastCaptionAdapter._transcribe picks it up regardless of whether
    # faster-whisper is installed.
    fake_module = types.ModuleType("server.audio.transcribe")
    fake_module.transcribe = fake_transcribe  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "server.audio.transcribe", fake_module)

    inp = AdapterInput(
        source_type="audio", raw_content="", assets={"audio": audio}
    )
    scene_list = asyncio.run(adapter.adapt(inp))
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 2
    assert scene_list.scenes[0].narration == "Hello listeners"
    assert scene_list.scenes[1].narration == "Welcome to AIFlow"
    # duration: span 4.0 stays, span 6.0 stays (both within [3, 30])
    assert scene_list.scenes[0].duration == pytest.approx(4.0)
    assert scene_list.scenes[1].duration == pytest.approx(6.0)


# ─── photo_slideshow (R4.5) ──────────────────────────────────────────────────


def _make_png(path: Path) -> None:
    """Write a minimal valid 1x1 PNG file at *path*.

    Uses Pillow when available (so the adapter's PIL-based header verification
    accepts the file); falls back to a raw byte sequence otherwise (validation
    still passes when Pillow is not installed because the adapter then skips
    the structural check).
    """
    try:
        from PIL import Image

        img = Image.new("RGB", (4, 4), color=(255, 0, 0))
        img.save(path, format="PNG")
    except ImportError:  # pragma: no cover - exercised only without Pillow
        path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A0000000D49484452000000010000000108020000"
                "00907753DE0000000C49444154789C63F8FFFF3F0005FE02FE9C5DC8"
                "5B0000000049454E44AE426082"
            )
        )


def test_photo_slideshow_adapt_basic(
    registry: AdapterRegistry, tmp_path: Path
) -> None:
    import asyncio

    adapter = registry.get("photo_slideshow")
    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    _make_png(img1)
    _make_png(img2)

    inp = AdapterInput(
        source_type="album",
        raw_content="",
        assets={"img_0": img1, "img_1": img2},
    )
    scene_list = asyncio.run(adapter.adapt(inp))
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 2
    # start_image is set on each scene
    assert scene_list.scenes[0].start_image == img1
    assert scene_list.scenes[1].start_image == img2


def test_photo_slideshow_validate_input_no_images(
    registry: AdapterRegistry,
) -> None:
    adapter = registry.get("photo_slideshow")
    errors = adapter.validate_input(
        AdapterInput(source_type="album", raw_content="")
    )
    assert errors


def test_photo_slideshow_raw_content_json_array(
    registry: AdapterRegistry, tmp_path: Path
) -> None:
    """Raw-content JSON array of paths is also a valid input shape."""
    import asyncio

    adapter = registry.get("photo_slideshow")
    img = tmp_path / "x.png"
    _make_png(img)

    inp = AdapterInput(
        source_type="album",
        raw_content=json.dumps([str(img)]),
    )
    scene_list = asyncio.run(adapter.adapt(inp))
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 1


# ─── adapt() validates input first (defence-in-depth) ────────────────────────


@pytest.mark.parametrize("adapter_type", sorted(NEW_ADAPTER_TYPES))
def test_adapt_rejects_obviously_invalid_input(
    registry: AdapterRegistry, adapter_type: str
) -> None:
    """An obviously invalid input must raise ``AdapterError`` from ``adapt``,
    not return a half-formed SceneList."""
    import asyncio

    from server.content.base import AdapterError

    adapter = registry.get(adapter_type)
    inp = AdapterInput(source_type="x", raw_content="")  # empty for all

    with pytest.raises(AdapterError):
        asyncio.run(adapter.adapt(inp))