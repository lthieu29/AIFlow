"""G1 — SceneList structure validation gate.

Validates the structure of a scene list before the pipeline proceeds to
asset generation. This is a synchronous, auto-run gate (no user interaction).

Checks performed:
    - At least 1 scene exists
    - All scenes have non-empty prompts (visual_prompt or narration fields)
    - Scene orders are sequential starting from 0 (0, 1, 2, ...)
    - No duplicate scene orders

Returns a GateResult with status "passed" or "failed".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from server.pipeline.quality_gate import GateResult

if TYPE_CHECKING:
    from server.db.models.scene import Scene


def validate_scene_list(scenes: list["Scene"]) -> GateResult:
    """Validate the structure of a SceneList.

    Args:
        scenes: List of Scene model instances to validate.

    Returns:
        GateResult with gate_id="G1", status="passed" or "failed".
        On failure, message describes the first critical issue found.
    """
    # G1.1 — at least 1 scene
    if not scenes:
        return GateResult(
            gate_id="G1",
            status="failed",
            message="G1.1: SceneList is empty — at least 1 scene is required.",
        )

    # G1.4 — all scenes have non-empty prompts
    # Scene model may have visual_prompt, narration, or prompt fields depending on phase.
    # We check any prompt-like attribute that is present and non-empty.
    for scene in scenes:
        prompt_value = _get_prompt(scene)
        if prompt_value is not None and not prompt_value.strip():
            return GateResult(
                gate_id="G1",
                status="failed",
                message=(
                    f"G1.4: Scene order={scene.order} has an empty prompt field. "
                    "All scenes must have non-empty prompts."
                ),
            )

    # Collect orders for sequential + duplicate checks
    orders = [scene.order for scene in scenes]

    # No duplicate orders
    if len(orders) != len(set(orders)):
        seen: set[int] = set()
        duplicates: list[int] = []
        for o in orders:
            if o in seen:
                duplicates.append(o)
            seen.add(o)
        return GateResult(
            gate_id="G1",
            status="failed",
            message=(
                f"G1: Duplicate scene orders detected: {sorted(set(duplicates))}. "
                "Each scene must have a unique order."
            ),
        )

    # Sequential orders starting from 0
    sorted_orders = sorted(orders)
    expected = list(range(len(scenes)))
    if sorted_orders != expected:
        return GateResult(
            gate_id="G1",
            status="failed",
            message=(
                f"G1: Scene orders are not sequential. "
                f"Expected {expected}, got {sorted_orders}."
            ),
        )

    return GateResult(gate_id="G1", status="passed")


def _get_prompt(scene: "Scene") -> str | None:
    """Extract the prompt value from a scene, checking multiple field names.

    Returns the prompt string if a prompt field exists, or None if the scene
    model has no prompt-like field (in which case the check is skipped).
    """
    for attr in ("visual_prompt", "narration", "prompt"):
        if hasattr(scene, attr):
            return getattr(scene, attr)
    return None
