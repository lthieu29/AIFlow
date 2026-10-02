"""Layer 3 — Scene Chain.

Ensures visual continuity between consecutive Veo3 clips by using the last
frame of scene N-1 as the start image for scene N.

The chain is reset when the ``location_hint`` changes between two consecutive
scenes (REVIEW-02 #6).  The reset logic is *defensive*: if either scene has
``location_hint == "unspecified"`` the chain is NOT reset (we keep the default
behaviour rather than breaking continuity unnecessarily).

Usage::

    chain = SceneChain()
    start_frame = chain.get_start_frame(scene_order=2, scenes=all_scenes)
    if chain.should_reset_chain(prev_scene, curr_scene):
        start_frame = None  # Veo3 will use character ref instead
    prefix = chain.get_chain_prompt_prefix(start_frame)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class SceneChain:
    """Layer 3 continuity — manages the start-frame chain between scenes.

    Each method is stateless and operates on the scene list passed in, so
    multiple SceneChain instances can coexist without interference.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def get_start_frame(
        self,
        scene_order: int,
        scenes: list,
    ) -> Optional[Path]:
        """Return the last-frame path of the previous scene (scene N-1).

        The last frame is stored as ``scene.last_frame_path`` on the scene
        object (set by the pipeline after each clip is generated).

        Args:
            scene_order: 0-based order of the *current* scene.
            scenes:      Full ordered list of Scene ORM objects.

        Returns:
            ``Path`` to the last-frame PNG of scene N-1, or ``None`` if:
            - ``scene_order`` is 0 (no previous scene), or
            - the previous scene has no ``last_frame_path`` set yet.
        """
        if scene_order <= 0:
            return None

        # Find the scene with order == scene_order - 1
        prev_scene = _find_scene_by_order(scenes, scene_order - 1)
        if prev_scene is None:
            return None

        last_frame = getattr(prev_scene, "last_frame_path", None)
        if last_frame is None:
            return None

        path = Path(last_frame)
        return path if path.exists() else None

    def should_reset_chain(self, prev_scene, curr_scene) -> bool:
        """Return True if the scene chain should be reset between two scenes.

        The chain resets when both scenes have a *known* (non-``"unspecified"``)
        ``location_hint`` AND those hints differ.

        This implements REVIEW-02 #6: be defensive — if either scene's
        location is unspecified, keep the chain (do not reset).

        Args:
            prev_scene: The preceding Scene ORM object.
            curr_scene: The current Scene ORM object.

        Returns:
            ``True`` if the chain should be reset (location changed),
            ``False`` otherwise.
        """
        prev_hint: str = getattr(prev_scene, "location_hint", "unspecified") or "unspecified"
        curr_hint: str = getattr(curr_scene, "location_hint", "unspecified") or "unspecified"

        # Defensive: if either side is unspecified, keep the chain
        if prev_hint == "unspecified" or curr_hint == "unspecified":
            return False

        return prev_hint != curr_hint

    def get_chain_prompt_prefix(
        self,
        start_frame_path: Optional[Path],
    ) -> str:
        """Return a prompt prefix that hints at scene chain continuity.

        When a start frame is available, the prefix instructs Veo3 to
        maintain pose, position, and wardrobe from the previous clip.

        When there is no start frame (first scene or chain reset), an empty
        string is returned so the caller can handle it gracefully.

        Args:
            start_frame_path: Path to the last-frame PNG, or ``None``.

        Returns:
            A prompt prefix string, or ``""`` if no start frame is available.
        """
        if start_frame_path is None:
            return ""

        return (
            "[Continuity]\n"
            "This clip continues directly from the previous scene. "
            "Maintain the subject's pose, position, wardrobe, and expression "
            "from the final frame of the previous clip. "
            "Do not change location, lighting, or camera angle mid-clip unless "
            "explicitly stated in the action description below."
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_scene_by_order(scenes: list, order: int):
    """Return the scene with the given ``order`` value, or ``None``."""
    for scene in scenes:
        if getattr(scene, "order", None) == order:
            return scene
    return None
