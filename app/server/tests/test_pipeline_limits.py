"""Property-based tests for enforce_pipeline_limits — Task 1.3.

**Property 7: Bất biến giới hạn pipeline được enforce**

Sinh SceneList quanh biên 50 scene / 600s và xác minh rằng
``enforce_pipeline_limits`` raise ``AdapterError("ADAPTER_INVALID_OUTPUT", ...)``
đúng khi và chỉ khi giới hạn bị vượt.

**Validates: Requirements 4.9, 6.2, 6.3**
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.base import AdapterError, SceneList, SceneSpec
from server.content.pipeline_limits import (
    DEFAULT_MAX_DURATION_SEC,
    DEFAULT_MAX_SCENES,
    enforce_pipeline_limits,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

# Valid scene duration range as defined by SceneList.validate()
_MIN_DUR = 3.0
_MAX_DUR = 30.0


def _make_scene(order: int, duration: float) -> SceneSpec:
    """Create a minimal valid SceneSpec."""
    return SceneSpec(order=order, prompt=f"scene {order}", duration=duration)


def _make_scene_list(durations: list[float]) -> SceneList:
    """Build a SceneList from a list of durations (order assigned automatically)."""
    scenes = [_make_scene(i, d) for i, d in enumerate(durations)]
    return SceneList(project_id="test-project", scenes=scenes)


# ─── Strategies ──────────────────────────────────────────────────────────────

# A single valid scene duration ∈ [3, 30]
valid_duration = st.floats(min_value=_MIN_DUR, max_value=_MAX_DUR, allow_nan=False, allow_infinity=False)

# Scene count strategies around the boundary of 50
# Below limit: 1..50 scenes
scene_count_ok = st.integers(min_value=1, max_value=DEFAULT_MAX_SCENES)
# Above limit: 51..70 scenes (small overshoot to keep tests fast)
scene_count_over = st.integers(min_value=DEFAULT_MAX_SCENES + 1, max_value=DEFAULT_MAX_SCENES + 20)


def _durations_with_total(n: int, total: float) -> list[float]:
    """Return n durations that sum to exactly *total*, each clamped to [3, 30]."""
    per = total / n
    per = max(_MIN_DUR, min(_MAX_DUR, per))
    return [per] * n


# ─── Property 7a: SceneList within both limits → no error ────────────────────


@given(
    n=scene_count_ok,
    dur=valid_duration,
)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_property7_within_limits_no_error(n: int, dur: float) -> None:
    """**Property 7a — Validates: Requirements 4.9, 6.2, 6.3**

    For any SceneList where scene_count ≤ 50 AND total_duration ≤ 600,
    enforce_pipeline_limits MUST NOT raise.
    """
    # Ensure total duration stays within 600 s
    # Use a duration per scene that keeps total ≤ 600
    max_per_scene = DEFAULT_MAX_DURATION_SEC / n
    safe_dur = min(dur, max_per_scene)
    safe_dur = max(_MIN_DUR, safe_dur)  # keep ≥ 3.0

    scene_list = _make_scene_list([safe_dur] * n)
    # Pre-condition: SceneList must be structurally valid
    ok, errors = scene_list.validate()
    assert ok, f"Test setup error — invalid SceneList: {errors}"

    # Property: must not raise
    enforce_pipeline_limits(scene_list)


# ─── Property 7b: scene_count > max_scenes → AdapterError ───────────────────


@given(n=scene_count_over)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_property7_scene_count_exceeded_raises(n: int) -> None:
    """**Property 7b — Validates: Requirements 4.9, 6.2**

    For any SceneList where scene_count > 50, enforce_pipeline_limits MUST
    raise AdapterError with code "ADAPTER_INVALID_OUTPUT".
    """
    # Use a small fixed duration so total duration doesn't accidentally
    # trigger the duration limit before the scene-count limit
    dur = _MIN_DUR  # 3.0 s — smallest valid duration
    scene_list = _make_scene_list([dur] * n)

    ok, errors = scene_list.validate()
    assert ok, f"Test setup error — invalid SceneList: {errors}"

    with pytest.raises(AdapterError) as exc_info:
        enforce_pipeline_limits(scene_list)

    err = exc_info.value
    assert err.code == "ADAPTER_INVALID_OUTPUT", (
        f"Expected ADAPTER_INVALID_OUTPUT, got {err.code!r}"
    )
    assert err.details.get("scene_count") == n
    assert err.details.get("max_scenes") == DEFAULT_MAX_SCENES


# ─── Property 7c: total_duration > max_duration → AdapterError ───────────────


@given(
    n=scene_count_ok,
    extra_sec=st.floats(min_value=0.01, max_value=300.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_property7_total_duration_exceeded_raises(n: int, extra_sec: float) -> None:
    """**Property 7c — Validates: Requirements 4.9, 6.3**

    For any SceneList where total_duration > 600 s (and scene_count ≤ 50),
    enforce_pipeline_limits MUST raise AdapterError with code
    "ADAPTER_INVALID_OUTPUT".
    """
    target_total = DEFAULT_MAX_DURATION_SEC + extra_sec  # strictly > 600

    # Distribute target_total across n scenes, clamped to [3, 30] per scene
    per = target_total / n
    per = max(_MIN_DUR, min(_MAX_DUR, per))
    durations = [per] * n
    actual_total = sum(durations)

    # If clamping made total ≤ 600 (e.g. n=50, per=30 → total=1500 > 600 ✓),
    # skip this example — the generator can't produce a valid over-limit case
    # with these parameters.
    if actual_total <= DEFAULT_MAX_DURATION_SEC:
        return  # skip — can't construct an over-limit list with these params

    scene_list = _make_scene_list(durations)
    ok, errors = scene_list.validate()
    assert ok, f"Test setup error — invalid SceneList: {errors}"

    with pytest.raises(AdapterError) as exc_info:
        enforce_pipeline_limits(scene_list)

    err = exc_info.value
    assert err.code == "ADAPTER_INVALID_OUTPUT", (
        f"Expected ADAPTER_INVALID_OUTPUT, got {err.code!r}"
    )
    assert err.details.get("total_duration_sec") == pytest.approx(actual_total)
    assert err.details.get("max_duration_sec") == DEFAULT_MAX_DURATION_SEC


# ─── Property 7d: custom limits respected ────────────────────────────────────


@given(
    max_s=st.integers(min_value=1, max_value=100),
    n=st.integers(min_value=1, max_value=120),
)
@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
def test_property7_custom_max_scenes_respected(max_s: int, n: int) -> None:
    """**Property 7d — Validates: Requirements 4.9, 6.2**

    enforce_pipeline_limits with a custom max_scenes parameter raises iff
    scene_count > max_scenes, regardless of the default (50).
    """
    # Use a small duration to avoid triggering duration limit
    dur = _MIN_DUR
    # Ensure total duration stays within a generous custom limit
    custom_max_dur = float(n * _MAX_DUR + 1.0)  # always above total
    scene_list = _make_scene_list([dur] * n)

    ok, errors = scene_list.validate()
    assert ok, f"Test setup error — invalid SceneList: {errors}"

    if n > max_s:
        with pytest.raises(AdapterError) as exc_info:
            enforce_pipeline_limits(scene_list, max_scenes=max_s, max_duration_sec=custom_max_dur)
        assert exc_info.value.code == "ADAPTER_INVALID_OUTPUT"
    else:
        # Should not raise (duration is well within custom_max_dur)
        enforce_pipeline_limits(scene_list, max_scenes=max_s, max_duration_sec=custom_max_dur)


# ─── Property 7e: boundary — exactly at limit → no error ─────────────────────


def test_property7_exactly_at_scene_limit_no_error() -> None:
    """**Property 7e — Validates: Requirements 6.2**

    A SceneList with exactly 50 scenes must NOT raise (boundary is inclusive).
    """
    scene_list = _make_scene_list([_MIN_DUR] * DEFAULT_MAX_SCENES)
    ok, _ = scene_list.validate()
    assert ok
    enforce_pipeline_limits(scene_list)  # must not raise


def test_property7_exactly_at_duration_limit_no_error() -> None:
    """**Property 7f — Validates: Requirements 6.3**

    A SceneList whose total duration equals exactly 600 s must NOT raise
    (boundary is inclusive).
    """
    # 20 scenes × 30 s = 600 s exactly
    n = 20
    dur = DEFAULT_MAX_DURATION_SEC / n  # 30.0 s
    scene_list = _make_scene_list([dur] * n)
    ok, _ = scene_list.validate()
    assert ok
    enforce_pipeline_limits(scene_list)  # must not raise


def test_property7_one_over_scene_limit_raises() -> None:
    """**Property 7g — Validates: Requirements 4.9, 6.2**

    A SceneList with 51 scenes (one over the limit) MUST raise.
    """
    scene_list = _make_scene_list([_MIN_DUR] * (DEFAULT_MAX_SCENES + 1))
    ok, _ = scene_list.validate()
    assert ok
    with pytest.raises(AdapterError) as exc_info:
        enforce_pipeline_limits(scene_list)
    assert exc_info.value.code == "ADAPTER_INVALID_OUTPUT"


def test_property7_one_over_duration_limit_raises() -> None:
    """**Property 7h — Validates: Requirements 4.9, 6.3**

    A SceneList whose total duration is 600.01 s (just over the limit) MUST raise.
    """
    # 20 scenes × 30.0005 s ≈ 600.01 s
    n = 20
    dur = (DEFAULT_MAX_DURATION_SEC + 0.01) / n
    scene_list = _make_scene_list([dur] * n)
    ok, _ = scene_list.validate()
    assert ok
    with pytest.raises(AdapterError) as exc_info:
        enforce_pipeline_limits(scene_list)
    assert exc_info.value.code == "ADAPTER_INVALID_OUTPUT"
