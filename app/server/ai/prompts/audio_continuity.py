"""Layer 4 — Audio Continuity.

Provides per-scene audio hints that sync with the overall audio plan for a
project (BGM mood, voice tone, tempo).  The hints are used by the pipeline
to guide TTS and BGM selection so the audio track feels cohesive across all
clips.

The audio plan is loaded from a skill directory (``skill_dir/audio_plan.json``)
or constructed programmatically.

Usage::

    ac = AudioContinuity.from_skill(Path("skills/ecommerce-fashion"))
    hint = ac.get_scene_audio_hint(scene_order=0, total_scenes=5)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

# Canonical scene positions used for audio pacing hints.
_ScenePosition = Literal["intro", "main", "outro"]

# Filename looked up inside a skill directory.
_AUDIO_PLAN_FILENAME = "audio_plan.json"

# Default audio plan used when no skill file is found.
_DEFAULT_AUDIO_PLAN = {
    "bgm_mood": "upbeat",
    "voice_tone": "friendly",
    "tempo": "medium",
}


class AudioPlan(BaseModel):
    """Audio plan for a project.

    Attributes:
        bgm_mood:   Mood descriptor for background music (e.g. "upbeat", "calm").
        voice_tone: Desired TTS voice tone (e.g. "friendly", "professional").
        tempo:      Pacing hint (e.g. "fast", "medium", "slow").
    """

    bgm_mood: str
    voice_tone: str
    tempo: str


class AudioContinuity:
    """Layer 4 continuity — syncs audio hints with scene timing.

    Divides the scene list into three positions (intro / main / outro) and
    returns an appropriate audio hint for each scene so the pipeline can
    adjust TTS pacing and BGM intensity accordingly.
    """

    def __init__(self, plan: AudioPlan) -> None:
        self._plan = plan

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def from_skill(cls, skill_dir: Path) -> "AudioContinuity":
        """Load the audio plan from a skill directory.

        Looks for ``{skill_dir}/audio_plan.json``.  Falls back to the default
        plan if the file does not exist or cannot be parsed.

        Args:
            skill_dir: Path to the skill directory (e.g. ``skills/ecommerce-fashion``).

        Returns:
            An AudioContinuity instance with the loaded (or default) plan.
        """
        plan_path = skill_dir / _AUDIO_PLAN_FILENAME
        if plan_path.exists():
            try:
                raw = json.loads(plan_path.read_text(encoding="utf-8"))
                plan = AudioPlan.model_validate(raw)
                return cls(plan)
            except (json.JSONDecodeError, ValueError):
                pass  # Fall through to default

        plan = AudioPlan.model_validate(_DEFAULT_AUDIO_PLAN)
        return cls(plan)

    @classmethod
    def from_plan(cls, plan: AudioPlan) -> "AudioContinuity":
        """Construct directly from an AudioPlan instance."""
        return cls(plan)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def plan(self) -> AudioPlan:
        """The underlying AudioPlan (read-only)."""
        return self._plan

    def get_scene_position(self, scene_order: int, total_scenes: int) -> _ScenePosition:
        """Classify a scene as intro, main, or outro.

        Boundaries:
        - intro:  first scene (order == 0)
        - outro:  last scene  (order == total_scenes - 1)
        - main:   everything in between

        For a single-scene project every position is "intro".

        Args:
            scene_order:  0-based scene index.
            total_scenes: Total number of scenes in the project.

        Returns:
            ``"intro"``, ``"main"``, or ``"outro"``.
        """
        if total_scenes <= 0:
            return "intro"
        if scene_order <= 0:
            return "intro"
        if scene_order >= total_scenes - 1:
            return "outro"
        return "main"

    def get_scene_audio_hint(self, scene_order: int, total_scenes: int) -> str:
        """Return an audio hint string for the given scene position.

        The hint is used by the pipeline to guide TTS pacing and BGM
        intensity.  It references the project-level audio plan so all hints
        are consistent within a project.

        Args:
            scene_order:  0-based scene index.
            total_scenes: Total number of scenes in the project.

        Returns:
            A human-readable audio hint string, e.g.::

                "[Audio: intro] BGM mood: upbeat. Voice tone: friendly. "
                "Tempo: medium. Start with energy to hook the viewer."
        """
        position = self.get_scene_position(scene_order, total_scenes)
        return self._build_hint(position)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_hint(self, position: _ScenePosition) -> str:
        """Build the audio hint string for a given position."""
        p = self._plan
        base = (
            f"[Audio: {position}] "
            f"BGM mood: {p.bgm_mood}. "
            f"Voice tone: {p.voice_tone}. "
            f"Tempo: {p.tempo}."
        )

        guidance = _POSITION_GUIDANCE.get(position, "")
        if guidance:
            return f"{base} {guidance}"
        return base


# Position-specific guidance appended to the base hint.
_POSITION_GUIDANCE: dict[str, str] = {
    "intro": "Start with energy to hook the viewer.",
    "main": "Maintain consistent pacing and tone.",
    "outro": "Wind down naturally; leave a strong closing impression.",
}
