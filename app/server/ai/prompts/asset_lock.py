"""Layer 2 — Asset Lock.

Pins character, product, and location references into every Veo3 prompt so
that the same identity is preserved across all clips in a project.

Usage::

    lock = AssetLock.from_assets(db_assets)
    final_prompt = lock.inject(scene_prompt)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Role priority order for Veo3 reference image selection.
# Veo3 i2v supports ~3-4 reference images per call; we drop lower-priority
# extras when the limit is exceeded.
_ROLE_PRIORITY: dict[str, int] = {
    "main_character": 0,
    "character": 1,
    "product": 2,
    "bg_location": 3,
    "location": 4,
    "extra": 5,
}

# Maximum number of reference anchors to include in a single prompt.
# Matches the Veo3 i2v reference image limit (empirically ~3-4).
MAX_ANCHORS = 4


@dataclass
class AssetAnchor:
    """A single asset reference anchor to be injected into a Veo3 prompt.

    Attributes:
        name:        Human-readable asset name (e.g. "Hùng", "Áo trắng").
        type:        Asset category: "character" | "product" | "location" | "style".
        description: Short description used in the prompt anchor text.
        ref_url:     URL or media_id of the reference image (may be empty).
        role:        Scene role for priority ordering (e.g. "main_character").
    """

    name: str
    type: str
    description: str
    ref_url: str = ""
    role: str = "extra"

    @property
    def priority(self) -> int:
        """Lower number = higher priority."""
        return _ROLE_PRIORITY.get(self.role, 99)

    def to_anchor_text(self) -> str:
        """Format this anchor as a prompt fragment.

        Returns a string like::

            Character: Hùng, young Vietnamese man in white shirt
            Product: Áo trắng, cotton shirt with minimalist design
            Location: Quán cafe, modern minimalist coffee shop
        """
        label = self.type.capitalize()
        parts = [f"{label}: {self.name}"]
        if self.description:
            parts.append(self.description)
        return ", ".join(parts)


class AssetLock:
    """Layer 2 continuity — hard-anchors asset identities in Veo3 prompts.

    Typical usage::

        lock = AssetLock.from_assets(db_assets)
        final_prompt = lock.inject(scene_prompt)
    """

    def __init__(self, anchors: list[AssetAnchor]) -> None:
        # Sort by priority so the most important refs come first
        self._anchors: list[AssetAnchor] = sorted(anchors, key=lambda a: a.priority)

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    def from_assets(cls, assets: list) -> "AssetLock":
        """Build an AssetLock from a list of DB Asset records.

        Accepts SQLModel ``Asset`` instances (from ``server.db.models.asset``)
        or any object with ``name``, ``type``, ``ref_url`` attributes.

        Args:
            assets: List of Asset ORM objects.

        Returns:
            An AssetLock ready to inject anchors into prompts.
        """
        anchors: list[AssetAnchor] = []
        for asset in assets:
            # Map Asset.type to a role for priority ordering.
            # "character" → "character", "product" → "product", etc.
            role = _infer_role(getattr(asset, "type", "extra"))
            anchor = AssetAnchor(
                name=getattr(asset, "name", ""),
                type=getattr(asset, "type", "extra"),
                description=getattr(asset, "description", ""),
                ref_url=getattr(asset, "ref_url", "") or "",
                role=role,
            )
            anchors.append(anchor)
        return cls(anchors)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def anchors(self) -> list[AssetAnchor]:
        """All anchors sorted by priority (read-only copy)."""
        return list(self._anchors)

    def top_anchors(self, limit: int = MAX_ANCHORS) -> list[AssetAnchor]:
        """Return the top-priority anchors up to ``limit``.

        Drops lower-priority extras when the Veo3 reference image limit is
        exceeded (main_character > product > bg_location > extra).
        """
        return self._anchors[:limit]

    def inject(self, prompt: str) -> str:
        """Inject asset anchors into a Veo3 prompt.

        Appends a ``[Asset References]`` block after the main prompt text.
        Only the top ``MAX_ANCHORS`` anchors are included.

        Args:
            prompt: The raw (or style-locked) scene visual prompt.

        Returns:
            The prompt with an asset anchor block appended, or the original
            prompt unchanged if there are no anchors.
        """
        top = self.top_anchors()
        if not top:
            return prompt

        anchor_lines = "\n".join(a.to_anchor_text() for a in top)
        anchor_block = f"[Asset References]\n{anchor_lines}"

        if prompt:
            return f"{prompt}\n\n{anchor_block}"
        return anchor_block


# ── Helpers ───────────────────────────────────────────────────────────────────

def _infer_role(asset_type: str) -> str:
    """Map an Asset.type value to a scene role for priority ordering."""
    mapping = {
        "character": "character",
        "product": "product",
        "location": "bg_location",
        "style": "extra",
    }
    return mapping.get(asset_type.lower(), "extra")
