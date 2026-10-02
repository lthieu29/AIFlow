"""Shared pipeline-limit guard for all ContentAdapters.

``SceneList.validate()`` only checks structural correctness (non-empty,
contiguous order, duration ∈ [3, 30]).  It does NOT enforce the project-level
caps ``Max_Scenes`` (50) and ``Max_Duration`` (600 s) defined in
``Settings.max_scenes_per_project`` / ``Settings.max_video_duration_sec``.

Every adapter (new or wrapped) must call :func:`enforce_pipeline_limits` AFTER
``SceneList.validate()`` and BEFORE returning, to satisfy R4.9, R6.2, R6.3.

Usage::

    from server.content.pipeline_limits import enforce_pipeline_limits

    ok, errors = scene_list.validate()
    if not ok:
        raise AdapterError("ADAPTER_INVALID_OUTPUT", "; ".join(errors))
    enforce_pipeline_limits(scene_list)          # uses Settings defaults
    # — or —
    enforce_pipeline_limits(scene_list, max_scenes=settings.max_scenes_per_project,
                            max_duration_sec=settings.max_video_duration_sec)
    return scene_list
"""

from __future__ import annotations

from server.content.base import AdapterError, SceneList

# ─── Defaults (mirror Settings.max_scenes_per_project / max_video_duration_sec)

DEFAULT_MAX_SCENES: int = 50
DEFAULT_MAX_DURATION_SEC: float = 600.0


# ─── Public API ───────────────────────────────────────────────────────────────


def enforce_pipeline_limits(
    scene_list: SceneList,
    *,
    max_scenes: int = DEFAULT_MAX_SCENES,
    max_duration_sec: float = DEFAULT_MAX_DURATION_SEC,
) -> None:
    """Raise :class:`~server.content.base.AdapterError` if pipeline limits are exceeded.

    Checks:
    - Number of scenes must not exceed *max_scenes*.
    - Sum of all scene durations must not exceed *max_duration_sec*.

    Call this AFTER ``SceneList.validate()`` and BEFORE the adapter returns.
    The default values match ``Settings.max_scenes_per_project`` (50) and
    ``Settings.max_video_duration_sec`` (600).  Adapters that have access to a
    live ``Settings`` instance should pass the actual configured values::

        enforce_pipeline_limits(
            scene_list,
            max_scenes=settings.max_scenes_per_project,
            max_duration_sec=float(settings.max_video_duration_sec),
        )

    Args:
        scene_list:       The :class:`~server.content.base.SceneList` to check.
        max_scenes:       Maximum allowed number of scenes (default 50).
        max_duration_sec: Maximum allowed total duration in seconds (default 600.0).

    Raises:
        :class:`~server.content.base.AdapterError`: With code
            ``"ADAPTER_INVALID_OUTPUT"`` when either limit is exceeded.
    """
    n = len(scene_list.scenes)
    if n > max_scenes:
        raise AdapterError(
            "ADAPTER_INVALID_OUTPUT",
            f"Scene count {n} exceeds Max_Scenes ({max_scenes})",
            details={"scene_count": n, "max_scenes": max_scenes},
        )

    total = sum(s.duration for s in scene_list.scenes)
    if total > max_duration_sec:
        raise AdapterError(
            "ADAPTER_INVALID_OUTPUT",
            f"Total duration {total:.1f}s exceeds Max_Duration ({max_duration_sec}s)",
            details={"total_duration_sec": total, "max_duration_sec": max_duration_sec},
        )
