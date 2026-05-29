"""SRT subtitle utilities for content adapters and the render pipeline.

Provides helpers to parse, format, and manipulate SRT subtitle files.
SRT is the simplest subtitle format: numbered segments with start/end
timestamps and text.

SRT time format: ``HH:MM:SS,mmm``  (comma as decimal separator)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ─── Data class ──────────────────────────────────────────────────────────────


@dataclass
class SrtSegment:
    """A single subtitle segment in an SRT file.

    Attributes:
        index:     1-based segment index (as written in the SRT file).
        start_sec: Start time in seconds (float).
        end_sec:   End time in seconds (float).
        text:      Subtitle text (may contain newlines for multi-line subs).
    """

    index: int
    start_sec: float
    end_sec: float
    text: str


# ─── Time conversion ─────────────────────────────────────────────────────────


def seconds_to_srt_time(seconds: float) -> str:
    """Convert a float number of seconds to SRT time format ``HH:MM:SS,mmm``.

    Args:
        seconds: Time in seconds (non-negative).

    Returns:
        String in ``HH:MM:SS,mmm`` format.

    Example::

        >>> seconds_to_srt_time(3661.5)
        '01:01:01,500'
    """
    seconds = max(0.0, seconds)
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_time_to_seconds(time_str: str) -> float:
    """Parse an SRT time string ``HH:MM:SS,mmm`` to float seconds.

    Args:
        time_str: Time string in ``HH:MM:SS,mmm`` format.

    Returns:
        Time in seconds as a float.

    Raises:
        ValueError: If *time_str* does not match the expected format.

    Example::

        >>> srt_time_to_seconds("01:01:01,500")
        3661.5
    """
    # Accept both comma and period as decimal separator.
    normalised = time_str.strip().replace(",", ".")
    match = re.fullmatch(
        r'(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,3})',
        normalised,
    )
    if not match:
        raise ValueError(
            f"Invalid SRT time format: {time_str!r}. Expected HH:MM:SS,mmm"
        )
    h, m, s, ms_str = match.groups()
    # Pad ms to 3 digits (e.g. "5" → "500", "50" → "500")
    ms = int(ms_str.ljust(3, "0"))
    return int(h) * 3600 + int(m) * 60 + int(s) + ms / 1000.0


# ─── Parsing ─────────────────────────────────────────────────────────────────

# Matches the timestamp line: "00:00:01,000 --> 00:00:04,000"
_TIMESTAMP_RE = re.compile(
    r'(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})'
)


def parse_srt(srt_content: str) -> list[SrtSegment]:
    """Parse an SRT format string into a list of :class:`SrtSegment` objects.

    Handles Windows (``\\r\\n``) and Unix (``\\n``) line endings.  Empty or
    malformed blocks are silently skipped.

    Args:
        srt_content: Full SRT file content as a string.

    Returns:
        List of :class:`SrtSegment` objects in file order.
    """
    segments: list[SrtSegment] = []

    # Normalise line endings and split into blocks separated by blank lines.
    normalised = srt_content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r'\n\s*\n', normalised.strip())

    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 3:
            continue  # Need at least: index, timestamp, text

        # First line should be the segment index.
        try:
            index = int(lines[0])
        except ValueError:
            continue

        # Second line should be the timestamp.
        ts_match = _TIMESTAMP_RE.match(lines[1])
        if not ts_match:
            continue

        try:
            start_sec = srt_time_to_seconds(ts_match.group(1))
            end_sec = srt_time_to_seconds(ts_match.group(2))
        except ValueError:
            continue

        # Remaining lines are the subtitle text.
        text = "\n".join(lines[2:])

        segments.append(
            SrtSegment(index=index, start_sec=start_sec, end_sec=end_sec, text=text)
        )

    return segments


# ─── Formatting ──────────────────────────────────────────────────────────────


def format_srt(segments: list[SrtSegment]) -> str:
    """Format a list of :class:`SrtSegment` objects to an SRT string.

    Args:
        segments: List of segments to format.

    Returns:
        SRT-formatted string with ``\\n\\n`` between blocks and a trailing
        newline.
    """
    if not segments:
        return ""

    blocks: list[str] = []
    for seg in segments:
        block = (
            f"{seg.index}\n"
            f"{seconds_to_srt_time(seg.start_sec)} --> {seconds_to_srt_time(seg.end_sec)}\n"
            f"{seg.text}"
        )
        blocks.append(block)

    return "\n\n".join(blocks) + "\n"


# ─── Segment manipulation ────────────────────────────────────────────────────


def merge_short_segments(
    segments: list[SrtSegment],
    min_duration: float = 1.0,
) -> list[SrtSegment]:
    """Merge subtitle segments shorter than *min_duration* with adjacent ones.

    Short segments are merged with the *next* segment when possible, or with
    the *previous* segment if they are the last one.  Indices are
    re-numbered from 1 after merging.

    Args:
        segments:     Input list of :class:`SrtSegment` objects.
        min_duration: Minimum acceptable segment duration in seconds.

    Returns:
        New list of segments with short segments merged.
    """
    if not segments:
        return []

    # Work on a mutable copy.
    result: list[SrtSegment] = [
        SrtSegment(
            index=seg.index,
            start_sec=seg.start_sec,
            end_sec=seg.end_sec,
            text=seg.text,
        )
        for seg in segments
    ]

    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result):
            seg = result[i]
            duration = seg.end_sec - seg.start_sec
            if duration < min_duration:
                if i + 1 < len(result):
                    # Merge with next segment.
                    next_seg = result[i + 1]
                    merged = SrtSegment(
                        index=seg.index,
                        start_sec=seg.start_sec,
                        end_sec=next_seg.end_sec,
                        text=seg.text + " " + next_seg.text,
                    )
                    result[i] = merged
                    del result[i + 1]
                    changed = True
                elif i > 0:
                    # Merge with previous segment.
                    prev_seg = result[i - 1]
                    merged = SrtSegment(
                        index=prev_seg.index,
                        start_sec=prev_seg.start_sec,
                        end_sec=seg.end_sec,
                        text=prev_seg.text + " " + seg.text,
                    )
                    result[i - 1] = merged
                    del result[i]
                    changed = True
                else:
                    # Single segment that is too short — leave as-is.
                    i += 1
            else:
                i += 1

    # Re-number indices from 1.
    for new_idx, seg in enumerate(result, start=1):
        seg.index = new_idx

    return result


def shift_segments(
    segments: list[SrtSegment],
    offset_sec: float,
) -> list[SrtSegment]:
    """Shift all segment timestamps by *offset_sec*.

    Negative offsets are allowed but timestamps are clamped to 0.

    Args:
        segments:   Input list of :class:`SrtSegment` objects.
        offset_sec: Number of seconds to add to every start and end time.

    Returns:
        New list of :class:`SrtSegment` objects with shifted timestamps.
        The original list is not modified.
    """
    return [
        SrtSegment(
            index=seg.index,
            start_sec=max(0.0, seg.start_sec + offset_sec),
            end_sec=max(0.0, seg.end_sec + offset_sec),
            text=seg.text,
        )
        for seg in segments
    ]
