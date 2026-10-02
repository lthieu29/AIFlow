"""Tasks 2.3–2.9 — Property + unit tests for ``ScriptDirectAdapter``.

Combines all six property-based tests for ``script_direct`` (Properties 1–6
in ``design.md``) and the supplementary unit / edge-case tests required by
tasks 2.3–2.9 in ``tasks.md``.

Properties (≥ 100 iteration each):
- **Property 1** — Mapping bảo toàn — script_direct map đúng và đầy đủ.
- **Property 2** — JSON không hợp lệ bị từ chối.
- **Property 3** — Thiếu field bắt buộc bị từ chối kèm chỉ số.
- **Property 4** — Duration được xác thực TRƯỚC khi gán order.
- **Property 5** — Áp skill thêm prefix vào mọi prompt.
- **Property 6** — Field thừa được bỏ qua, không làm fail.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.base import AdapterError, AdapterInput, SceneList
from server.content.registry import AdapterRegistry


# ─── Helpers ─────────────────────────────────────────────────────────────────

_MIN_DUR = 3.0
_MAX_DUR = 30.0
_DEFAULT_DUR = 8.0


def _adapter():
    """Return a fresh ScriptDirectAdapter instance (no registry side-effects)."""
    from server.content.adapters.script_direct.adapter import ScriptDirectAdapter

    return ScriptDirectAdapter()


def _make_input(payload_obj: Any, **kwargs: Any) -> AdapterInput:
    return AdapterInput(
        source_type="script",
        raw_content=json.dumps(payload_obj) if not isinstance(payload_obj, str) else payload_obj,
        **kwargs,
    )


def _run(coro):
    return asyncio.run(coro)


# ─── Strategies ──────────────────────────────────────────────────────────────

# A non-blank, printable string suitable for narration / visual_prompt
_text_strategy = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

_dur_in_range = st.floats(min_value=_MIN_DUR, max_value=_MAX_DUR, allow_nan=False, allow_infinity=False)


def _scene_strategy(include_duration: bool = True) -> st.SearchStrategy[dict]:
    keys = {"narration": _text_strategy, "visual_prompt": _text_strategy}
    if include_duration:
        keys["duration_sec"] = st.one_of(st.none(), _dur_in_range)
    return st.fixed_dictionaries(keys)


# ─── Property 1 — Mapping bảo toàn (R1.4, R1.5, R1.6, R6.4) ──────────────────


@given(scenes=st.lists(_scene_strategy(), min_size=1, max_size=8))
@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
def test_property1_mapping_preserves(scenes: list[dict]) -> None:
    """**Property 1** — All input scenes are mapped 1:1 to SceneSpec, in order,
    with prompt = visual_prompt, narration preserved, and duration defaulting
    to 8.0 when ``duration_sec`` is absent."""
    # Strip None duration_sec so adapter sees absence (default 8.0)
    cleaned = [
        {k: v for k, v in s.items() if not (k == "duration_sec" and v is None)}
        for s in scenes
    ]
    payload = {"scenes": cleaned}
    scene_list = _run(_adapter().adapt(_make_input(payload)))

    assert isinstance(scene_list, SceneList)
    assert len(scene_list.scenes) == len(cleaned)
    for i, (out, src) in enumerate(zip(scene_list.scenes, cleaned)):
        assert out.order == i, f"scenes[{i}].order should be {i}, got {out.order}"
        assert src["visual_prompt"] in out.prompt
        assert out.narration == src["narration"]
        expected_dur = src.get("duration_sec", _DEFAULT_DUR)
        assert out.duration == pytest.approx(expected_dur)


# ─── Property 2 — JSON không hợp lệ bị từ chối (R1.7) ───────────────────────


@given(
    bad=st.text(min_size=1, max_size=80).filter(
        lambda s: not _is_parseable_json(s)
    )
)
@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
def test_property2_invalid_json_rejected(bad: str) -> None:
    """**Property 2** — Any non-parseable JSON raw_content raises
    ``AdapterError(code='ADAPTER_INVALID_INPUT')``."""
    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input(bad)))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


def _is_parseable_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError, TypeError):
        return False


# ─── Property 3 — Thiếu field bắt buộc bị từ chối kèm chỉ số (R1.9, R1.16) ───


@given(
    scenes=st.lists(_scene_strategy(include_duration=False), min_size=1, max_size=6),
    drop_index=st.integers(min_value=0),
    drop_field=st.sampled_from(["narration", "visual_prompt"]),
)
@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
def test_property3_missing_required_field_indexed(
    scenes: list[dict], drop_index: int, drop_field: str
) -> None:
    """**Property 3** — Removing a required field at index *i* raises
    ``ADAPTER_INVALID_INPUT`` and ``details`` references that index."""
    i = drop_index % len(scenes)
    mutated = [dict(s) for s in scenes]
    mutated[i].pop(drop_field, None)

    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input({"scenes": mutated})))
    err = exc_info.value
    assert err.code == "ADAPTER_INVALID_INPUT"
    # Details must reference the failing index
    assert err.details.get("scene_index") == i or f"scenes[{i}]" in err.message


# ─── Property 4 — Duration validated BEFORE order assignment (R1.6, R1.10) ───


@given(
    scenes=st.lists(_scene_strategy(include_duration=False), min_size=2, max_size=6),
    bad_index=st.integers(min_value=0),
    bad_value=st.one_of(
        st.just(0.0),
        st.floats(min_value=-100.0, max_value=2.99, allow_nan=False, allow_infinity=False),
        st.floats(min_value=30.01, max_value=100.0, allow_nan=False, allow_infinity=False),
    ),
)
@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
def test_property4_duration_validated_before_order(
    scenes: list[dict], bad_index: int, bad_value: float
) -> None:
    """**Property 4** — A scene with duration ∉ [3, 30] (incl. 0.0) raises
    ``ADAPTER_INVALID_INPUT`` at the duration validation step.  No partial
    SceneSpec output is produced.

    The contract is checked indirectly: the adapter must raise — meaning no
    SceneList is returned, hence no ``order`` was assigned.
    """
    idx = bad_index % len(scenes)
    mutated = [dict(s) for s in scenes]
    mutated[idx]["duration_sec"] = bad_value

    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input({"scenes": mutated})))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


# ─── Property 5 — Skill prefix is applied to every prompt (R1.14) ────────────


@given(scenes=st.lists(_scene_strategy(include_duration=False), min_size=1, max_size=4))
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
def test_property5_skill_prefix_applied_to_every_prompt(
    scenes: list[dict],
) -> None:
    """**Property 5** — When ``skill_name`` is set, the loaded skill's prefix
    appears in every output ``SceneSpec.prompt``.

    Uses the existing ``ecommerce-fashion`` skill (which extends ``_base``) so
    we know the prefix is non-empty and skill loading works without mocks.
    """
    payload = {"scenes": scenes}
    inp = _make_input(payload, skill_name="ecommerce-fashion")
    scene_list = _run(_adapter().adapt(inp))

    # Load the same skill manually to compare prefix text
    from server.content.skill_loader import SkillLoader

    skills_dir = Path(__file__).resolve().parents[2] / "skills"
    skill = SkillLoader(skills_dir).load("ecommerce-fashion")
    assert skill.prefix.strip(), "Test setup error: ecommerce-fashion has empty prefix"

    # Take a stable substring of the prefix — first 30 non-blank chars
    sample = skill.prefix.strip()[:30]
    assert sample, "Test setup error: prefix sample is empty"
    for spec in scene_list.scenes:
        assert sample in spec.prompt, (
            f"Skill prefix not found in scene {spec.order}.prompt"
        )


# ─── Property 6 — Extra fields are silently ignored (R1.19) ──────────────────


@given(
    scenes=st.lists(_scene_strategy(include_duration=False), min_size=1, max_size=4),
    extras=st.dictionaries(
        keys=st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=4,
            max_size=10,
        ).filter(
            lambda k: k not in {"narration", "visual_prompt", "duration_sec", "asset_ids"}
        ),
        values=st.one_of(
            st.integers(),
            st.text(max_size=10),
            st.booleans(),
            st.lists(st.integers(), max_size=3),
        ),
        max_size=4,
    ),
)
@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow])
def test_property6_extra_fields_ignored(
    scenes: list[dict], extras: dict
) -> None:
    """**Property 6** — Extra keys outside the contract are ignored, not
    rejected; the adapter still produces a valid SceneList."""
    mutated = [dict(s, **extras) for s in scenes]
    scene_list = _run(_adapter().adapt(_make_input({"scenes": mutated})))
    ok, errors = scene_list.validate()
    assert ok, errors
    # Extra keys must not leak onto the output as core fields
    for spec in scene_list.scenes:
        # The dataclass attribute set is fixed — extras can only live in metadata.
        assert "duration" in dir(spec)
        # Extras keys must not become SceneSpec attributes
        for key in extras:
            assert not hasattr(spec, key), (
                f"Unexpected extra field {key!r} on SceneSpec"
            )


# ═════════════════════════════════════════════════════════════════════════════
# Task 2.9 — discover + edge-case unit tests
# ═════════════════════════════════════════════════════════════════════════════


# ─── R1.1 / R1.2 / R1.3 — auto-discovery convention ──────────────────────────


def test_adapter_type_class_attribute() -> None:
    """**R1.1** — class attribute ``adapter_type`` is exactly ``"script_direct"``."""
    from server.content.adapters.script_direct.adapter import ScriptDirectAdapter

    assert ScriptDirectAdapter.adapter_type == "script_direct"


def test_module_level_adapter_instance() -> None:
    """**R1.2** — module exposes a module-level ``ADAPTER`` instance."""
    import server.content.adapters.script_direct.adapter as mod

    assert hasattr(mod, "ADAPTER")
    assert mod.ADAPTER.adapter_type == "script_direct"


def test_auto_discover_registers_script_direct() -> None:
    """**R1.3** — ``auto_discover`` registers ``script_direct``."""
    reg = AdapterRegistry()
    reg.auto_discover("server.content.adapters")
    assert "script_direct" in reg.list_types()
    assert reg.get("script_direct").adapter_type == "script_direct"


# ─── R1.8 — missing or empty ``scenes`` ──────────────────────────────────────


def test_missing_scenes_key_raises() -> None:
    """**R1.8** — JSON without a ``scenes`` key raises ``ADAPTER_INVALID_INPUT``."""
    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input({"foo": 1})))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


def test_empty_scenes_array_raises() -> None:
    """**R1.8** — empty ``scenes`` array raises ``ADAPTER_INVALID_INPUT``."""
    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input({"scenes": []})))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


def test_scenes_null_raises() -> None:
    """**R1.8** — ``scenes: null`` raises ``ADAPTER_INVALID_INPUT``."""
    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input({"scenes": None})))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


# ─── R1.11 — validate_input on valid input returns [] ────────────────────────


def test_validate_input_returns_empty_for_valid() -> None:
    """**R1.11** — ``validate_input`` returns ``[]`` for valid input."""
    payload = json.dumps(
        {"scenes": [{"narration": "Hi.", "visual_prompt": "A scene."}]}
    )
    errors = _adapter().validate_input(_make_input(payload))
    assert errors == []


# ─── R1.13 — output validation (defensive) ───────────────────────────────────


def test_invalid_output_raises_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """**R1.13** — If somehow an invalid SceneList is constructed (e.g. order
    not contiguous), the adapter raises ``ADAPTER_INVALID_OUTPUT``.

    We force the failure by patching ``SceneList.validate`` to always fail.
    """
    from server.content import base as base_mod

    real_validate = base_mod.SceneList.validate

    def always_fail(self):
        return False, ["forced failure for test"]

    monkeypatch.setattr(base_mod.SceneList, "validate", always_fail)

    payload = json.dumps(
        {"scenes": [{"narration": "Hi.", "visual_prompt": "A scene."}]}
    )
    try:
        with pytest.raises(AdapterError) as exc_info:
            _run(_adapter().adapt(_make_input(payload)))
        assert exc_info.value.code == "ADAPTER_INVALID_OUTPUT"
    finally:
        # explicit restore for safety
        monkeypatch.setattr(base_mod.SceneList, "validate", real_validate)


# ─── R1.15 — minimum valid object ────────────────────────────────────────────


def test_minimum_valid_object() -> None:
    """**R1.15** — a top-level object with a single-element ``scenes`` array
    containing the two required fields is valid."""
    scene_list = _run(
        _adapter().adapt(
            _make_input(
                {
                    "scenes": [
                        {"narration": "X", "visual_prompt": "Y"},
                    ]
                }
            )
        )
    )
    assert len(scene_list.scenes) == 1
    assert scene_list.scenes[0].duration == _DEFAULT_DUR


# ─── R1.17 / R1.18 — wrong types for optional fields ─────────────────────────


def test_duration_sec_wrong_type_raises() -> None:
    """**R1.17** — ``duration_sec`` of wrong type raises ``ADAPTER_INVALID_INPUT``."""
    payload = {
        "scenes": [
            {"narration": "X", "visual_prompt": "Y", "duration_sec": "not-a-number"},
        ]
    }
    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input(payload)))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


def test_asset_ids_wrong_type_raises() -> None:
    """**R1.18** — ``asset_ids`` not an array raises ``ADAPTER_INVALID_INPUT``."""
    payload = {
        "scenes": [
            {"narration": "X", "visual_prompt": "Y", "asset_ids": "not-a-list"},
        ]
    }
    with pytest.raises(AdapterError) as exc_info:
        _run(_adapter().adapt(_make_input(payload)))
    assert exc_info.value.code == "ADAPTER_INVALID_INPUT"


# ─── duration default + boundary ─────────────────────────────────────────────


def test_default_duration_when_missing() -> None:
    """**R1.5 / R6.4** — missing ``duration_sec`` defaults to 8.0."""
    scene_list = _run(
        _adapter().adapt(
            _make_input(
                {
                    "scenes": [{"narration": "Hi.", "visual_prompt": "A scene."}]
                }
            )
        )
    )
    assert scene_list.scenes[0].duration == _DEFAULT_DUR


def test_duration_boundary_values_accepted() -> None:
    """**R1.6** — durations exactly at the boundary [3, 30] are accepted."""
    scene_list = _run(
        _adapter().adapt(
            _make_input(
                {
                    "scenes": [
                        {"narration": "A", "visual_prompt": "B", "duration_sec": 3.0},
                        {"narration": "C", "visual_prompt": "D", "duration_sec": 30.0},
                    ]
                }
            )
        )
    )
    assert scene_list.scenes[0].duration == 3.0
    assert scene_list.scenes[1].duration == 30.0
    assert [s.order for s in scene_list.scenes] == [0, 1]
