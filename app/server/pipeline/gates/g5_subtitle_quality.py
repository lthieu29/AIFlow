"""G5 — Subtitle quality check gate.

Phase 3.2 implementation: validates subtitle segments produced by Whisper
transcription before the pipeline proceeds to final composition.

Checks performed (per spec 07 §G5):
    G5.1 — Subtitle segments list is non-empty (Critical)
    G5.x — No segment has start_sec >= end_sec (Critical — invalid timing)
    G5.x — No overlapping segments (Critical — would cause render issues)
    G5.x — Total subtitle coverage vs video duration (Warning if < 50%)

Critical failures block the pipeline.
Warnings are logged but do not block.

The subtitle segments are expected to be objects with ``start_sec`` and
``end_sec`` float attributes (matching ``SubtitleSegment`` from composer.py),
but any object with those attributes is accepted (duck typing).

Functions:
    check_subtitle_quality — run G5 checks on a list of subtitle segments
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from loguru import logger

from server.pipeline.quality_gate import GateResult

if TYPE_CHECKING:
    pass

# ─── Constants ────────────────────────────────────────────────────────────────

# G5.x — minimum subtitle coverage ratio (warning threshold)
_MIN_COVERAGE_RATIO: float = 0.50  # 50%


# ─── Protocol ─────────────────────────────────────────────────────────────────

@runtime_checkable
class SubtitleSegmentLike(Protocol):
    """Duck-type protocol for subtitle segment objects.

    Accepts ``SubtitleSegment`` from composer.py or any object with
    ``start_sec`` and ``end_sec`` float attributes.
    """
    start_sec: float
    end_sec: float


# ─── Public API ───────────────────────────────────────────────────────────────

def check_subtitle_quality(
    segments: list,
    video_duration: Optional[float] = None,
) -> GateResult:
    """Run G5 quality checks on a list of subtitle segments.

    Args:
        segments:       List of subtitle segment objects. Each must have
                        ``start_sec`` and ``end_sec`` float attributes.
        video_duration: Total video duration in seconds (used for coverage
                        check). If None, coverage check is skipped.

    Returns:
        GateResult with gate_id="G5", status="passed" or "failed".
        On failure, message describes the first critical issue found.
        Warnings are logged but do not cause a "failed" status.
    """
    # G5.1 — segments must be non-empty
    if not segments:
        return GateResult(
            gate_id="G5",
            status="failed",
            message="G5.1: Subtitle segments list is empty — at least 1 segment is required.",
        )

    # Validate each segment has the required attributes
    for i, seg in enumerate(segments):
        if not (hasattr(seg, "start_sec") and hasattr(seg, "end_sec")):
            return GateResult(
                gate_id="G5",
                status="failed",
                message=(
                    f"G5: Segment at index {i} is missing 'start_sec' or 'end_sec' attributes."
                ),
            )

    # G5.x — no segment with start_sec >= end_sec (invalid timing)
    for i, seg in enumerate(segments):
        if seg.start_sec >= seg.end_sec:
            return GateResult(
                gate_id="G5",
                status="failed",
                message=(
                    f"G5: Segment {i} has invalid timing: "
                    f"start_sec={seg.start_sec:.3f} >= end_sec={seg.end_sec:.3f}. "
                    "Each segment must have start_sec < end_sec."
                ),
            )

    # G5.x — no overlapping segments
    # Sort by start_sec to detect overlaps efficiently
    sorted_segs = sorted(enumerate(segments), key=lambda x: x[1].start_sec)
    for idx in range(len(sorted_segs) - 1):
        orig_i, seg_a = sorted_segs[idx]
        orig_j, seg_b = sorted_segs[idx + 1]
        if seg_a.end_sec > seg_b.start_sec:
            return GateResult(
                gate_id="G5",
                status="failed",
                message=(
                    f"G5: Overlapping segments detected: "
                    f"segment {orig_i} ends at {seg_a.end_sec:.3f}s but "
                    f"segment {orig_j} starts at {seg_b.start_sec:.3f}s."
                ),
            )

    # G5.x — coverage check (warning only — does not block)
    if video_duration is not None and video_duration > 0:
        total_covered = sum(
            max(0.0, seg.end_sec - seg.start_sec) for seg in segments
        )
        coverage_ratio = total_covered / video_duration
        if coverage_ratio < _MIN_COVERAGE_RATIO:
            logger.warning(
                "G5: Subtitle coverage {:.1f}% is below {:.0f}% threshold "
                "(covered {:.2f}s of {:.2f}s video duration)",
                coverage_ratio * 100,
                _MIN_COVERAGE_RATIO * 100,
                total_covered,
                video_duration,
            )
        else:
            logger.debug(
                "G5: Subtitle coverage {:.1f}% ({:.2f}s / {:.2f}s)",
                coverage_ratio * 100,
                total_covered,
                video_duration,
            )

    logger.info("G5: Subtitle quality check passed — {} segment(s)", len(segments))
    return GateResult(gate_id="G5", status="passed")
