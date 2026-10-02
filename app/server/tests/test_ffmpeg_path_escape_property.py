"""Task 5.3 — **Property 11**: FFmpeg SRT path escape on Windows.

**Validates: Requirement 7.8**

For any Windows-style path (drive letter ``X:`` + ``\\`` separators),
:func:`_escape_srt_path_for_ffmpeg` must:

- Convert all backslashes to forward slashes (no raw ``\\`` left).
- Escape the drive-letter colon as ``X\\:`` (i.e. backslash + colon).

Without this escape, FFmpeg's ``subtitles=`` filter on Windows misinterprets
the colon as an option separator and the burn-subtitles step fails.
"""

from __future__ import annotations

import sys
from pathlib import PureWindowsPath

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from server.content.crawlers.remaster import _escape_srt_path_for_ffmpeg


# ─── Strategies ──────────────────────────────────────────────────────────────


_DRIVE = st.sampled_from([f"{c}:" for c in "CDEFGHIJZ"])

_PATH_PART = st.text(
    alphabet=st.characters(
        whitelist_categories=["Ll", "Lu", "Nd"],
        whitelist_characters="_-. ",
    ),
    min_size=1,
    max_size=12,
).filter(lambda s: s.strip() not in ("", ".", ".."))


def _windows_path_strategy() -> st.SearchStrategy[str]:
    """Build a Windows path with drive letter and ``\\`` separators."""
    parts = st.lists(_PATH_PART, min_size=1, max_size=5)
    return st.builds(
        lambda drive, segments: drive + "\\" + "\\".join(segments) + ".srt",
        _DRIVE,
        parts,
    )


# ─── Property 11 ─────────────────────────────────────────────────────────────


@given(win_path=_windows_path_strategy())
@settings(
    max_examples=150,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_property11_escape_windows_path_for_ffmpeg(win_path: str) -> None:
    """**Property 11 — Validates: R7.8**

    Returns a string that:
    - contains no raw ``\\`` (every backslash becomes ``/``);
    - has the drive-letter colon escaped as ``X\\:``.
    """
    out = _escape_srt_path_for_ffmpeg(PureWindowsPath(win_path))

    # 1. No raw backslashes (separators or otherwise) other than the one used
    #    to escape the drive-letter colon.
    raw_backslashes_outside_escape = out.replace("\\:", "")
    assert "\\" not in raw_backslashes_outside_escape, (
        f"Output still contains raw backslashes: {out!r}"
    )

    # 2. Drive letter colon must be escaped — given the input always has X:
    assert out[:3] == win_path[0] + "\\:", (
        f"Drive letter colon not escaped: {out!r}"
    )

    # 3. Path uses forward slashes
    assert "/" in out, f"Expected forward slashes in output: {out!r}"


# ─── Sanity / regression unit tests ──────────────────────────────────────────


def test_drive_letter_colon_escaped() -> None:
    """Concrete example: ``C:\\foo\\bar.srt`` → ``C\\:/foo/bar.srt``."""
    out = _escape_srt_path_for_ffmpeg(PureWindowsPath(r"C:\foo\bar.srt"))
    assert out == "C\\:/foo/bar.srt"


def test_no_drive_letter_unchanged() -> None:
    """A POSIX-style path without a drive letter does not get a colon escape."""
    out = _escape_srt_path_for_ffmpeg(PureWindowsPath("/abs/path.srt"))
    # No drive letter → the function only converts backslashes to slashes.
    assert "\\:" not in out
    assert "/" in out


def test_path_with_spaces_handled() -> None:
    out = _escape_srt_path_for_ffmpeg(
        PureWindowsPath(r"D:\My Videos\subtitles.srt")
    )
    assert out == "D\\:/My Videos/subtitles.srt"
