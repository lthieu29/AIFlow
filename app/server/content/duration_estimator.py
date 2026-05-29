"""Duration estimation utilities for content adapters.

Provides helpers to estimate scene durations from narration text and to
distribute a total duration evenly across a set of scenes.
"""

from __future__ import annotations

import math

from server.content.base import SceneSpec


# ─── Constants ───────────────────────────────────────────────────────────────

#: Default speaking rate used when no explicit value is provided.
WORDS_PER_MINUTE: int = 150

#: Hard lower bound for a single scene duration (seconds).
_MIN_DURATION: float = 3.0

#: Hard upper bound for a single scene duration (seconds).
_MAX_DURATION: float = 30.0


# ─── Per-scene estimation ────────────────────────────────────────────────────


def estimate_scene_duration(
    narration: str,
    words_per_minute: int = WORDS_PER_MINUTE,
) -> float:
    """Estimate the duration of a single scene from its narration text.

    The estimate is based on word count divided by the speaking rate.
    The result is clamped to the range ``[3, 30]`` seconds.

    Args:
        narration:        The TTS narration text for the scene.
        words_per_minute: Speaking rate in words per minute.  Defaults to
                          :data:`WORDS_PER_MINUTE` (150 wpm).

    Returns:
        Estimated duration in seconds, clamped to ``[3.0, 30.0]``.

    Example::

        >>> estimate_scene_duration("Hello world")  # 2 words / 150 wpm * 60 ≈ 0.8 → clamped to 3.0
        3.0
    """
    if not narration or not narration.strip():
        return _MIN_DURATION

    wpm = max(1, words_per_minute)  # guard against zero / negative
    word_count = len(narration.split())
    raw_seconds = (word_count / wpm) * 60.0
    return max(_MIN_DURATION, min(_MAX_DURATION, raw_seconds))


# ─── Total duration ──────────────────────────────────────────────────────────


def estimate_total_duration(scenes: list[SceneSpec]) -> float:
    """Return the sum of all scene durations in *scenes*.

    Scenes without narration use their ``duration`` field directly.
    Scenes with narration use :func:`estimate_scene_duration` to compute
    the duration from the narration text.

    Args:
        scenes: List of :class:`~server.content.base.SceneSpec` objects.

    Returns:
        Total estimated duration in seconds.  Returns ``0.0`` for an empty
        list.
    """
    total = 0.0
    for scene in scenes:
        if scene.narration:
            total += estimate_scene_duration(scene.narration)
        else:
            total += scene.duration
    return total


# ─── Duration distribution ───────────────────────────────────────────────────


def distribute_duration(
    total_duration: float,
    n_scenes: int,
    min_duration: float = _MIN_DURATION,
    max_duration: float = _MAX_DURATION,
) -> list[float]:
    """Distribute *total_duration* evenly across *n_scenes*.

    Each scene receives an equal share of the total, clamped to
    ``[min_duration, max_duration]``.  If the even share falls below
    *min_duration*, all scenes get *min_duration*.  If it exceeds
    *max_duration*, all scenes get *max_duration*.

    Args:
        total_duration: Total video duration in seconds.
        n_scenes:       Number of scenes to distribute across.
        min_duration:   Minimum duration per scene (default 3.0 s).
        max_duration:   Maximum duration per scene (default 30.0 s).

    Returns:
        List of *n_scenes* floats, each clamped to
        ``[min_duration, max_duration]``.

    Raises:
        ValueError: If *n_scenes* is less than 1.

    Example::

        >>> distribute_duration(40.0, 5)
        [8.0, 8.0, 8.0, 8.0, 8.0]
    """
    if n_scenes < 1:
        raise ValueError(f"n_scenes must be >= 1, got {n_scenes}")

    per_scene = total_duration / n_scenes
    clamped = max(min_duration, min(max_duration, per_scene))
    return [clamped] * n_scenes
