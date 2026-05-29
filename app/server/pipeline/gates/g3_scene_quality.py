"""G3 — Per-scene quality check gate.

Phase 2 implementation: checks that the generated video file exists and has
a minimum size (> 100KB). Full LLM-judge checks (G3.4 brightness, G3.6 motion,
G3.9 prompt match) are deferred to Phase 3+.

Bounded cascade (REVIEW-01 #6):
    MAX_RETRIES = 2 — a scene is retried at most 2 times before being marked
    failed and triggering the cascade logic in the orchestrator.

Functions:
    check_scene_quality   — run G3 checks on a scene's video file
    get_scene_retry_count — count failed G3 gates for a scene
    should_retry_scene    — True if retry_count < MAX_RETRIES
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from server.pipeline.quality_gate import GateResult

if TYPE_CHECKING:
    from sqlmodel import Session

    from server.db.models.scene import Scene

# Bounded cascade: max retries per scene (REVIEW-01 #6)
MAX_RETRIES: int = 2

# Minimum acceptable video file size (Phase 2 heuristic)
_MIN_VIDEO_SIZE_BYTES: int = 100 * 1024  # 100 KB


def check_scene_quality(scene: "Scene", video_path: Path) -> GateResult:
    """Run G3 quality checks on a scene's generated video file.

    Phase 2 checks:
        - Video file exists at video_path
        - File size > 100 KB (not a placeholder / empty file)

    Phase 3+ checks (deferred):
        - ffprobe duration ≈ scene.duration ± 0.5s (G3.2)
        - First/last frame brightness > 10 (G3.4, G3.5)
        - Video not stuck — frames differ visually (G3.6)
        - LLM-as-judge prompt match (G3.9)

    Args:
        scene:      The Scene model instance being validated.
        video_path: Path to the generated video file.

    Returns:
        GateResult with gate_id="G3", status="passed" or "failed".
    """
    # G3.1 — file must exist
    if not video_path.exists():
        return GateResult(
            gate_id="G3",
            status="failed",
            message=(
                f"G3.1: Video file not found for scene order={scene.order}: "
                f"{video_path}"
            ),
        )

    # G3.1 — file size > 100 KB
    file_size = video_path.stat().st_size
    if file_size <= _MIN_VIDEO_SIZE_BYTES:
        return GateResult(
            gate_id="G3",
            status="failed",
            message=(
                f"G3.1: Video file too small for scene order={scene.order}: "
                f"{file_size} bytes (minimum {_MIN_VIDEO_SIZE_BYTES} bytes / 100 KB). "
                "File may be a placeholder or corrupt."
            ),
        )

    return GateResult(gate_id="G3", status="passed")


def get_scene_retry_count(session: "Session", scene_id: int) -> int:
    """Count the number of failed G3 gate records for a scene.

    Each failed G3 evaluation creates a QualityGate row with status="failed".
    This count drives the bounded cascade logic.

    Args:
        session:  Active SQLModel session.
        scene_id: ID of the scene to check.

    Returns:
        Number of failed G3 gate records for this scene (0 if none).
    """
    from sqlmodel import func, select

    from server.db.models.quality_gate import QualityGate

    statement = (
        select(func.count())  # type: ignore[call-overload]
        .select_from(QualityGate)
        .where(QualityGate.gate_id == "G3")
        .where(QualityGate.scene_id == scene_id)
        .where(QualityGate.status == "failed")
    )
    result = session.exec(statement).one()
    return result if result is not None else 0


def should_retry_scene(session: "Session", scene_id: int) -> bool:
    """Return True if the scene has not yet exhausted its retry budget.

    A scene may be retried up to MAX_RETRIES (2) times. Once the failed G3
    count reaches MAX_RETRIES, the orchestrator should stop retrying and
    trigger the cascade logic instead.

    Args:
        session:  Active SQLModel session.
        scene_id: ID of the scene to check.

    Returns:
        True if retry_count < MAX_RETRIES, False otherwise.
    """
    return get_scene_retry_count(session, scene_id) < MAX_RETRIES
