"""ContentAdapter interface — base dataclasses and Protocol.

Defines the standard interface that all input adapters must implement.
The pipeline orchestrator works exclusively with SceneList; it does not
know or care about the source input type.

Architecture:
    Input (file/URL/text)
        ↓
    ContentAdapter.adapt(AdapterInput) → SceneList
        ↓
    [Skill applier] — apply prefix/style from skills/{skill_id}/
        ↓
    Pipeline orchestrator (gen scenes, audio, render)
        ↓
    final.mp4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable


# ─── Exceptions ──────────────────────────────────────────────────────────────


class AdapterError(Exception):
    """Adapter error with a structured error code.

    Attributes:
        code:    Machine-readable error code (e.g. "ADAPTER_NOT_FOUND",
                 "ADAPTER_INVALID_INPUT").
        message: Human-readable description.
        details: Optional dict with extra context (field names, values, etc.).
    """

    def __init__(self, code: str, message: str, details: dict | None = None) -> None:
        self.code = code
        self.message = message
        self.details: dict = details or {}
        super().__init__(message)

    def __repr__(self) -> str:  # pragma: no cover
        return f"AdapterError(code={self.code!r}, message={self.message!r})"


# ─── Input dataclass ─────────────────────────────────────────────────────────


@dataclass
class AdapterInput:
    """Input payload passed to a ContentAdapter.

    Attributes:
        source_type:  Identifies the kind of input, e.g. "product", "narrative",
                      "blog", "storyboard", "video".
        raw_content:  Raw input content — plain text, URL, JSON string, etc.
        assets:       Named asset files keyed by a logical name (e.g.
                      ``{"product_image": Path("img.jpg")}``).
        skill_name:   Optional skill to apply after adaptation.
        options:      Adapter-specific options (free-form dict).
    """

    source_type: str
    raw_content: str
    assets: dict[str, Path] = field(default_factory=dict)
    skill_name: Optional[str] = None
    options: dict = field(default_factory=dict)


# ─── Output dataclasses ──────────────────────────────────────────────────────


@dataclass
class SceneSpec:
    """Specification for a single scene (one Veo3 clip).

    Attributes:
        order:          0-based position in the scene list.
        prompt:         Veo3 generation prompt (raw, before skill prefix is applied).
        duration:       Desired clip duration in seconds (typically 8.0).
        start_image:    Optional path to a start-frame image for scene chaining
                        (Layer 3 continuity).
        location_hint:  Optional location hint for continuity chain reset detection.
                        Should use the canonical ``LocationCategory`` values from
                        ``docs/05-content-adapter-spec.md`` when possible.
        narration:      Optional TTS narration text for this scene.
    """

    order: int
    prompt: str
    duration: float = 8.0
    start_image: Optional[Path] = None
    location_hint: Optional[str] = None
    narration: Optional[str] = None


@dataclass
class SceneList:
    """Normalised output of a ContentAdapter.

    This is the canonical representation that the pipeline orchestrator
    consumes.  Adapters produce a SceneList; the pipeline does not know
    what the original input was.

    Attributes:
        project_id: Identifier for the owning project.
        scenes:     Ordered list of scene specifications.
        style_ref:  Optional reference to a skill ``style.json`` path.
        voice:      Optional TTS voice preference (e.g. "vi-VN-HoaiMyNeural").
        metadata:   Adapter-specific metadata (free-form dict).
    """

    project_id: str
    scenes: list[SceneSpec]
    style_ref: Optional[str] = None
    voice: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> tuple[bool, list[str]]:
        """Validate the SceneList structure.

        Returns:
            A ``(ok, errors)`` tuple.  ``ok`` is ``True`` when ``errors`` is
            empty.

        Checks:
        - ``scenes`` is non-empty.
        - ``scenes[i].order`` is contiguous starting from 0.
        - ``scenes[i].duration`` is in [3, 30].
        """
        errors: list[str] = []

        if not self.scenes:
            errors.append("scenes must not be empty")
            return False, errors

        # Check order is contiguous from 0
        for expected, scene in enumerate(self.scenes):
            if scene.order != expected:
                errors.append(
                    f"scenes[{expected}].order is {scene.order}, expected {expected}"
                )

        # Check duration bounds
        for scene in self.scenes:
            if not (3.0 <= scene.duration <= 30.0):
                errors.append(
                    f"scenes[{scene.order}].duration={scene.duration} is outside [3, 30]"
                )

        return len(errors) == 0, errors

    # ── Cost estimate ─────────────────────────────────────────────────────────

    def estimate_cost(self) -> dict:
        """Rough cost estimate for the pipeline run.

        Returns a dict with:
        - ``veo3_clips``: number of Veo3 generation calls.
        - ``tts_duration_sec``: total narration duration (sum of scene durations
          that have narration text).
        - ``total_video_duration_sec``: sum of all scene durations.
        """
        narration_duration = sum(
            s.duration for s in self.scenes if s.narration
        )
        return {
            "veo3_clips": len(self.scenes),
            "tts_duration_sec": narration_duration,
            "total_video_duration_sec": sum(s.duration for s in self.scenes),
        }


# ─── Protocol ────────────────────────────────────────────────────────────────


@runtime_checkable
class ContentAdapter(Protocol):
    """Protocol that every content adapter must satisfy.

    Adapters are discovered and instantiated by :class:`AdapterRegistry`.
    Each adapter class must expose:

    - A class-level ``adapter_type`` string that uniquely identifies it
      (e.g. ``"script_direct"``, ``"ecommerce_product"``).
    - An async ``adapt`` method that converts an :class:`AdapterInput` into
      a :class:`SceneList`.
    - A synchronous ``validate_input`` method for cheap pre-flight checks
      (no LLM calls).

    Adapters must NOT know about Veo3, Gemini, TTS, FFmpeg, or the database
    schema — they are independently testable.
    """

    #: Unique identifier for this adapter type.
    adapter_type: str

    async def adapt(self, input: AdapterInput) -> SceneList:
        """Parse/transform *input* into a normalised :class:`SceneList`.

        This is the main entry point.  Implementations may call LLM APIs,
        read files, fetch URLs, etc.

        Args:
            input: The adapter input payload.

        Returns:
            A :class:`SceneList` ready for the pipeline orchestrator.

        Raises:
            :class:`AdapterError`: On any unrecoverable parse/validation error.
        """
        ...  # pragma: no cover

    def validate_input(self, input: AdapterInput) -> list[str]:
        """Perform cheap pre-flight validation of *input*.

        This method must NOT call external APIs or read large files.  It is
        intended for fast structural checks (required fields present, types
        correct, etc.).

        Args:
            input: The adapter input payload.

        Returns:
            A list of human-readable error strings.  An empty list means the
            input is valid.
        """
        ...  # pragma: no cover
