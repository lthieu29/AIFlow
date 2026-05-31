"""LyricVideoAdapter — turns song lyrics into a lyric-video SceneList.

Input (``AdapterInput.raw_content``):
- ``.lrc`` style lyrics with ``[mm:ss.xx]`` timestamps, OR
- plain-text lyrics (one line per lyric line).

Optional ``AdapterInput.assets["audio"]`` — the song audio (kept in metadata
for downstream muxing; not required to build scenes).

Processing:
1. ``validate_input()`` — local-only checks (non-empty text). No network/LLM.
2. Parse lyrics:
   - LRC with timestamps → one scene per timed line, duration = gap to next
     timestamp (clamped to [3, 30]).
   - Plain text → one scene per non-empty line, default duration.
3. Each line becomes a :class:`~server.content.base.SceneSpec` whose narration
   is the lyric line.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from server.content.base import (
    AdapterError,
    AdapterInput,
    SceneList,
    SceneSpec,
)
from server.content.pipeline_limits import enforce_pipeline_limits

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION = 8.0
_MIN_DURATION = 3.0
_MAX_DURATION = 30.0
_DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

# [mm:ss.xx] or [mm:ss] timestamp tag
_LRC_TAG_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]")

_SCENE_PROMPT_TEMPLATE = (
    "Lyric video scene. Stylised typographic background for the line: {line!r}. "
    "Rhythmic, atmospheric, music-video aesthetic."
)


class LyricVideoAdapter:
    """ContentAdapter for song lyrics (LRC or plain text).

    Attributes:
        adapter_type: Registry key — ``"lyric_video"``.
    """

    adapter_type: str = "lyric_video"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse lyrics and return a :class:`SceneList`."""
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid lyric_video input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        raw = input.raw_content
        timed = _parse_lrc(raw)

        if timed:
            scenes = self._scenes_from_timed(timed)
        else:
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                raise AdapterError(
                    "ADAPTER_INVALID_INPUT",
                    "Lyrics produced no usable lines.",
                )
            scenes = [
                self._line_to_scene(order, line, _DEFAULT_DURATION)
                for order, line in enumerate(lines)
            ]

        if input.skill_name:
            scenes = _apply_skill(scenes, input.skill_name, self.adapter_type)

        metadata: dict = {
            "adapter": self.adapter_type,
            "scene_count": len(scenes),
            "skill_name": input.skill_name,
            "synced": bool(timed),
        }
        audio = input.assets.get("audio")
        if audio is not None:
            metadata["audio_path"] = str(audio)

        scene_list = SceneList(
            project_id=input.options.get("project_id", "lyric_video"),
            scenes=scenes,
            voice=input.options.get("voice", _DEFAULT_VOICE),
            metadata=metadata,
        )

        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )
        enforce_pipeline_limits(scene_list)

        logger.debug("LyricVideoAdapter: generated %d scenes", len(scenes))
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Cheap local validation — no network/LLM calls (R4.6)."""
        errors: list[str] = []
        if not input.raw_content or not input.raw_content.strip():
            errors.append("raw_content must not be empty — expected song lyrics")
        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _scenes_from_timed(
        self, timed: list[tuple[float, str]]
    ) -> list[SceneSpec]:
        scenes: list[SceneSpec] = []
        for idx, (start, line) in enumerate(timed):
            if idx + 1 < len(timed):
                gap = timed[idx + 1][0] - start
            else:
                gap = _DEFAULT_DURATION
            duration = max(_MIN_DURATION, min(_MAX_DURATION, gap if gap > 0 else _DEFAULT_DURATION))
            scenes.append(self._line_to_scene(idx, line, duration))
        return scenes

    def _line_to_scene(self, order: int, line: str, duration: float) -> SceneSpec:
        return SceneSpec(
            order=order,
            prompt=_SCENE_PROMPT_TEMPLATE.format(line=line),
            duration=duration,
            narration=line,
        )


def _parse_lrc(text: str) -> list[tuple[float, str]]:
    """Parse LRC-style lyrics into ``(start_sec, line)`` tuples, sorted by time.

    Lines without a timestamp tag are ignored.  A line may carry multiple
    timestamp tags (repeated lyric) — each yields its own entry.

    Returns an empty list when no timestamped lines are present (caller then
    treats the input as plain text).
    """
    entries: list[tuple[float, str]] = []
    for raw_line in text.splitlines():
        tags = list(_LRC_TAG_RE.finditer(raw_line))
        if not tags:
            continue
        lyric = _LRC_TAG_RE.sub("", raw_line).strip()
        if not lyric:
            continue
        for tag in tags:
            minutes = int(tag.group(1))
            seconds = int(tag.group(2))
            frac_raw = tag.group(3) or "0"
            frac = int(frac_raw) / (10 ** len(frac_raw))
            start = minutes * 60 + seconds + frac
            entries.append((start, lyric))

    entries.sort(key=lambda e: e[0])
    return entries


def _apply_skill(
    scenes: list[SceneSpec],
    skill_name: str,
    adapter_type: str,
) -> list[SceneSpec]:
    """Apply a skill's prefix to all scene prompts (best-effort)."""
    try:
        from server.content.skill_loader import SkillLoader, apply_skill_to_scene

        adapter_dir = Path(__file__).resolve().parent
        app_dir = adapter_dir.parents[3]
        skills_dir = app_dir / "skills"

        loader = SkillLoader(skills_dir)
        skill = loader.load(skill_name)
        return [apply_skill_to_scene(scene, skill) for scene in scenes]
    except FileNotFoundError:
        logger.warning(
            "%s: skill %r not found — skipping skill application",
            adapter_type, skill_name,
        )
        return scenes
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s: failed to apply skill %r: %s — skipping",
            adapter_type, skill_name, exc,
        )
        return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

ADAPTER: LyricVideoAdapter = LyricVideoAdapter()
ADAPTER_CLASS = LyricVideoAdapter
