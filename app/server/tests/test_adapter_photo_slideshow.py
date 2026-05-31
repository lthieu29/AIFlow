"""Task 8.8 — Integration test: ``PhotoSlideshowAdapter`` strict on bad images.

**Validates: Requirement 4.6**

When N images are supplied and ANY one of them is corrupt or unreadable,
the adapter must:

- Return a non-empty list of errors from ``validate_input`` (with the
  failing path / index in the message).
- Fail-fast in ``adapt`` with ``ADAPTER_INVALID_INPUT`` (no silent drop).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.adapters.photo_slideshow.adapter import (
    PhotoSlideshowAdapter,
)
from server.content.base import AdapterError, AdapterInput


def _run(coro):
    return asyncio.run(coro)


def _make_valid_png(path: Path) -> None:
    """Write a real 4x4 RGB PNG using Pillow when available."""
    pytest.importorskip("PIL")
    from PIL import Image

    Image.new("RGB", (4, 4), color=(0, 200, 0)).save(path, format="PNG")


def _make_corrupt_png(path: Path) -> None:
    """Write a file that *looks* like a PNG (correct magic bytes) but whose
    body is corrupt, so a Pillow header check raises."""
    # PNG magic + garbage payload — Pillow ``.verify()`` will fail on this.
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x42\x42\x42" * 10)


# ─── R4.6 — strict fail-fast on corrupt image ───────────────────────────────


def test_validate_input_flags_corrupt_image_with_index(tmp_path: Path) -> None:
    """**R4.6** — One corrupt image among N → ``validate_input`` returns a
    non-empty error list whose message references the failing index/path."""
    _ = pytest.importorskip("PIL")  # adapter only enforces with Pillow installed

    img_ok = tmp_path / "ok.png"
    img_bad = tmp_path / "bad.png"
    _make_valid_png(img_ok)
    _make_corrupt_png(img_bad)

    adapter = PhotoSlideshowAdapter()
    inp = AdapterInput(
        source_type="album",
        raw_content="",
        assets={"img_0": img_ok, "img_1": img_bad},
    )
    errors = adapter.validate_input(inp)
    assert errors, "Expected validate_input to flag the corrupt image"
    joined = " | ".join(errors)
    # Path or 1-based/0-based index of the failing image must surface
    assert "bad.png" in joined
    assert "[1]" in joined or "1:" in joined or "1 " in joined


def test_adapt_fails_fast_on_corrupt_image(tmp_path: Path) -> None:
    """**R4.6** — ``adapt`` raises ``ADAPTER_INVALID_INPUT`` rather than
    silently dropping the bad image and rendering N-1 scenes."""
    _ = pytest.importorskip("PIL")

    img_ok1 = tmp_path / "a.png"
    img_ok2 = tmp_path / "b.png"
    img_bad = tmp_path / "broken.png"
    _make_valid_png(img_ok1)
    _make_valid_png(img_ok2)
    _make_corrupt_png(img_bad)

    adapter = PhotoSlideshowAdapter()
    inp = AdapterInput(
        source_type="album",
        raw_content="",
        assets={"img_0": img_ok1, "img_1": img_bad, "img_2": img_ok2},
    )
    with pytest.raises(AdapterError) as exc_info:
        _run(adapter.adapt(inp))
    err = exc_info.value
    assert err.code == "ADAPTER_INVALID_INPUT"
    assert "broken.png" in err.message


def test_adapt_succeeds_when_all_images_valid(tmp_path: Path) -> None:
    """Sanity counter-test: with all images valid, ``adapt`` returns N scenes."""
    _ = pytest.importorskip("PIL")
    img_a = tmp_path / "a.png"
    img_b = tmp_path / "b.png"
    img_c = tmp_path / "c.png"
    for p in (img_a, img_b, img_c):
        _make_valid_png(p)

    adapter = PhotoSlideshowAdapter()
    scene_list = _run(
        adapter.adapt(
            AdapterInput(
                source_type="album",
                raw_content="",
                assets={"img_0": img_a, "img_1": img_b, "img_2": img_c},
            )
        )
    )
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 3


def test_validate_input_flags_missing_file(tmp_path: Path) -> None:
    """A path that does not exist on disk produces an error with the path text."""
    img_missing = tmp_path / "ghost.png"  # never created
    adapter = PhotoSlideshowAdapter()
    errors = adapter.validate_input(
        AdapterInput(
            source_type="album",
            raw_content="",
            assets={"img_0": img_missing},
        )
    )
    assert errors
    assert any("ghost.png" in e for e in errors)


def test_validate_input_flags_unsupported_extension(tmp_path: Path) -> None:
    """An unsupported extension is rejected even before any header check."""
    odd = tmp_path / "movie.mp4"
    odd.write_bytes(b"\x00")
    adapter = PhotoSlideshowAdapter()
    errors = adapter.validate_input(
        AdapterInput(
            source_type="album", raw_content="", assets={"img_0": odd}
        )
    )
    assert errors
    assert any("unsupported extension" in e.lower() for e in errors)
