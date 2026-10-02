"""Standalone SRT exporter for AIFlow projects.

Generates valid SRT subtitle files from:
  - A list of subtitle segments (text + start_time + end_time in seconds)
  - Scene narrations with timing derived from scene durations
  - Whisper transcription output (:class:`~server.audio.transcribe.SRTSegment`)

The module is intentionally dependency-light: it only imports from the
standard library and from :mod:`server.content.srt_utils` (which is always
available).

Usage::

    from server.export.srt_exporter import SrtExporter, SubtitleSegment

    # Build from raw segments
    segments = [
        SubtitleSegment(text="Hello world", start_sec=0.0, end_sec=2.5),
        SubtitleSegment(text="Second line", start_sec=2.5, end_sec=5.0),
    ]
    exporter = SrtExporter()
    srt_string = exporter.generate(segments)
    exporter.write(segments, "/path/to/output.srt")

Phase 7 — Task 7.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from server.content.srt_utils import SrtSegment, format_srt, seconds_to_srt_time

if TYPE_CHECKING:
    from server.audio.transcribe import SRTSegment as WhisperSRTSegment

logger = logging.getLogger(__name__)


# ─── Data class ───────────────────────────────────────────────────────────────


@dataclass
class SubtitleSegment:
    """A single subtitle segment for SRT export.

    Attributes:
        text:      Subtitle text (may contain newlines for multi-line subs).
        start_sec: Start time in seconds (non-negative float).
        end_sec:   End time in seconds (must be > start_sec).
    """

    text: str
    start_sec: float
    end_sec: float


# ─── SrtExporter ──────────────────────────────────────────────────────────────


class SrtExporter:
    """Generates SRT subtitle files from various input sources.

    All public methods are pure functions of their inputs — the class holds
    no mutable state and is safe to reuse across calls.
    """

    # ── Core generation ───────────────────────────────────────────────────────

    def generate(self, segments: list[SubtitleSegment]) -> str:
        """Generate an SRT-formatted string from a list of :class:`SubtitleSegment`.

        Segments are re-numbered from 1 in the output regardless of any
        existing index values.  Empty text segments are silently skipped.

        Args:
            segments: List of subtitle segments (order is preserved).

        Returns:
            SRT-formatted string.  Returns an empty string when *segments*
            is empty or all segments have empty text.

        Example::

            >>> exporter = SrtExporter()
            >>> segs = [SubtitleSegment("Hello", 0.0, 2.0)]
            >>> print(exporter.generate(segs))
            1
            00:00:00,000 --> 00:00:02,000
            Hello
        """
        srt_segments = self._to_srt_segments(segments)
        return format_srt(srt_segments)

    def write(
        self,
        segments: list[SubtitleSegment],
        output_path: Union[str, Path],
        *,
        encoding: str = "utf-8",
    ) -> Path:
        """Generate an SRT file and write it to *output_path*.

        Parent directories are created automatically.

        Args:
            segments:    List of subtitle segments.
            output_path: Destination file path (``*.srt`` recommended).
            encoding:    File encoding (default ``"utf-8"``).

        Returns:
            Resolved :class:`~pathlib.Path` of the written file.

        Raises:
            OSError: If the file cannot be written.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = self.generate(segments)
        output_path.write_text(content, encoding=encoding)

        logger.info(
            "[SrtExporter] wrote %d segment(s) to %s",
            len([s for s in segments if s.text.strip()]),
            output_path,
        )
        return output_path.resolve()

    # ── Source adapters ───────────────────────────────────────────────────────

    @staticmethod
    def from_scene_narrations(
        narrations: list[str],
        durations: list[float],
        *,
        gap_sec: float = 0.0,
    ) -> list[SubtitleSegment]:
        """Build subtitle segments from scene narration texts and durations.

        Each narration occupies the full duration of its corresponding scene.
        An optional *gap_sec* is subtracted from the end of each segment to
        avoid subtitle overlap at scene boundaries.

        Args:
            narrations: List of narration strings (one per scene).
            durations:  List of scene durations in seconds (one per scene).
                        Must have the same length as *narrations*.
            gap_sec:    Seconds to trim from the end of each segment
                        (default 0.0 — no gap).

        Returns:
            List of :class:`SubtitleSegment` objects.

        Raises:
            ValueError: If *narrations* and *durations* have different lengths.

        Example::

            >>> segs = SrtExporter.from_scene_narrations(
            ...     ["Scene one text", "Scene two text"],
            ...     [8.0, 8.0],
            ...     gap_sec=0.2,
            ... )
        """
        if len(narrations) != len(durations):
            raise ValueError(
                f"narrations ({len(narrations)}) and durations ({len(durations)}) "
                "must have the same length."
            )

        segments: list[SubtitleSegment] = []
        cursor = 0.0

        for text, duration in zip(narrations, durations):
            start = cursor
            end = cursor + max(0.0, duration - gap_sec)
            # Ensure end > start even after gap subtraction
            if end <= start:
                end = start + max(0.0, duration)
            if text.strip():
                segments.append(SubtitleSegment(text=text.strip(), start_sec=start, end_sec=end))
            cursor += duration

        return segments

    @staticmethod
    def from_whisper_segments(
        whisper_segments: "list[WhisperSRTSegment]",
    ) -> list[SubtitleSegment]:
        """Convert Whisper transcription output to :class:`SubtitleSegment` list.

        Accepts :class:`~server.audio.transcribe.SRTSegment` objects produced
        by :func:`~server.audio.transcribe.transcribe`.

        Args:
            whisper_segments: List of ``SRTSegment`` objects from the Whisper
                              transcriber.

        Returns:
            List of :class:`SubtitleSegment` objects.

        Example::

            >>> from server.audio.transcribe import transcribe
            >>> raw = transcribe(Path("audio.mp3"), language="vi")
            >>> segs = SrtExporter.from_whisper_segments(raw)
            >>> SrtExporter().write(segs, "output.srt")
        """
        return [
            SubtitleSegment(
                text=seg.text,
                start_sec=seg.start_time,
                end_sec=seg.end_time,
            )
            for seg in whisper_segments
            if seg.text.strip()
        ]

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _to_srt_segments(segments: list[SubtitleSegment]) -> list[SrtSegment]:
        """Convert :class:`SubtitleSegment` list to :class:`SrtSegment` list.

        Skips segments with empty text and re-numbers from 1.

        Args:
            segments: Input subtitle segments.

        Returns:
            List of :class:`~server.content.srt_utils.SrtSegment` objects.
        """
        result: list[SrtSegment] = []
        idx = 1
        for seg in segments:
            if not seg.text.strip():
                continue
            result.append(
                SrtSegment(
                    index=idx,
                    start_sec=seg.start_sec,
                    end_sec=seg.end_sec,
                    text=seg.text,
                )
            )
            idx += 1
        return result


# ─── Module-level convenience functions ───────────────────────────────────────

_default_exporter = SrtExporter()


def generate_srt(segments: list[SubtitleSegment]) -> str:
    """Module-level convenience wrapper around :meth:`SrtExporter.generate`.

    Args:
        segments: List of subtitle segments.

    Returns:
        SRT-formatted string.
    """
    return _default_exporter.generate(segments)


def write_srt(
    segments: list[SubtitleSegment],
    output_path: Union[str, Path],
    *,
    encoding: str = "utf-8",
) -> Path:
    """Module-level convenience wrapper around :meth:`SrtExporter.write`.

    Args:
        segments:    List of subtitle segments.
        output_path: Destination file path.
        encoding:    File encoding (default ``"utf-8"``).

    Returns:
        Resolved :class:`~pathlib.Path` of the written file.
    """
    return _default_exporter.write(segments, output_path, encoding=encoding)
