"""Task 5.2 — **Property 10**: SRT translation preserves source on failure.

**Validates: Requirement 7.4**

For any list of SRT segments, when:
- ``gemini_client`` is ``None``, OR
- the client raises an exception for every segment,

``translate_srt`` must produce a result whose every segment keeps the
original ``text`` and the original ``start_sec``/``end_sec`` unchanged.

The current implementation of :func:`translate_srt` returns the source
SRT path unchanged when ``gemini_client`` is ``None`` (no rewrite at all),
which trivially satisfies the property.  When the client is present but
fails on every segment, ``translate_srt`` writes a NEW ``_<lang>.srt`` file
whose segments must have the same text + timestamps as the input.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.crawlers.remaster import (
    RemasterConfig,
    RemasterPreset,
    translate_srt,
)
from server.content.srt_utils import SrtSegment, format_srt, parse_srt


# ─── Strategies ──────────────────────────────────────────────────────────────


def _segment_strategy() -> st.SearchStrategy[SrtSegment]:
    """Build a syntactically valid SRT segment with start < end."""
    text = st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126),
        min_size=1,
        max_size=40,
    ).filter(lambda s: s.strip() != "")

    start = st.floats(min_value=0.0, max_value=3590.0, allow_nan=False, allow_infinity=False)
    span = st.floats(min_value=0.5, max_value=10.0, allow_nan=False, allow_infinity=False)

    @st.composite
    def _build(draw) -> SrtSegment:
        s = draw(start)
        sp = draw(span)
        return SrtSegment(
            index=1,  # rewritten below
            start_sec=s,
            end_sec=s + sp,
            text=draw(text),
        )

    return _build()


def _segments_strategy() -> st.SearchStrategy[list[SrtSegment]]:
    return st.lists(_segment_strategy(), min_size=1, max_size=8).map(_renumber)


def _renumber(segs: list[SrtSegment]) -> list[SrtSegment]:
    return [
        SrtSegment(index=i + 1, start_sec=s.start_sec, end_sec=s.end_sec, text=s.text)
        for i, s in enumerate(segs)
    ]


# ─── Helper writers ──────────────────────────────────────────────────────────


def _write_srt(tmp: Path, segs: list[SrtSegment]) -> Path:
    path = tmp / "video_zh.srt"
    path.write_text(format_srt(segs), encoding="utf-8")
    return path


# ─── Property 10a — gemini_client=None → return original SRT path ────────────


@given(segments=_segments_strategy())
@settings(
    max_examples=120,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_property10a_no_client_returns_source_path(
    segments: list[SrtSegment], tmp_path: Path
) -> None:
    """**Property 10a — Validates: R7.4**

    With ``gemini_client=None``, ``translate_srt`` returns the source path
    unchanged.  The on-disk content remains identical to the input.
    """
    src = _write_srt(tmp_path, segments)
    cfg = RemasterConfig(
        preset=RemasterPreset.LIGHT,
        source_language="zh",
        target_language="vi",
        gemini_client=None,
    )

    out = translate_srt(src, cfg)
    assert out == src

    parsed_after = parse_srt(out.read_text(encoding="utf-8"))
    assert len(parsed_after) == len(segments)
    for got, expected in zip(parsed_after, segments):
        assert got.text == expected.text
        assert got.start_sec == pytest.approx(expected.start_sec, abs=1e-3)
        assert got.end_sec == pytest.approx(expected.end_sec, abs=1e-3)


# ─── Property 10b — failing client per segment → text preserved ──────────────


class _AlwaysFailClient:
    """A fake Gemini client whose ``generate_text`` raises for every call."""

    def __init__(self) -> None:
        self.calls: int = 0

    def generate_text(self, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("simulated translation failure")


@given(segments=_segments_strategy())
@settings(
    max_examples=120,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_property10b_failing_client_preserves_text(
    segments: list[SrtSegment], tmp_path: Path
) -> None:
    """**Property 10b — Validates: R7.4**

    With a Gemini client that raises for every segment, ``translate_srt`` must
    write a translated SRT whose segments preserve the original text and
    timestamps exactly (no segment dropped, no timestamps shifted)."""
    src = _write_srt(tmp_path, segments)
    cfg = RemasterConfig(
        preset=RemasterPreset.LIGHT,
        source_language="zh",
        target_language="vi",
        gemini_client=_AlwaysFailClient(),
    )

    out = translate_srt(src, cfg)
    assert out != src
    assert out.parent == src.parent
    assert out.name.endswith("_vi.srt")

    parsed_after = parse_srt(out.read_text(encoding="utf-8"))
    assert len(parsed_after) == len(segments)
    for got, expected in zip(parsed_after, segments):
        assert got.text == expected.text
        assert got.start_sec == pytest.approx(expected.start_sec, abs=1e-3)
        assert got.end_sec == pytest.approx(expected.end_sec, abs=1e-3)
