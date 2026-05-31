"""PodcastCaptionAdapter — turns a podcast/audio file into a captioned SceneList.

Input (``AdapterInput.assets["audio"]``): path to an audio file (wav/mp3/m4a…).

Processing:
1. ``validate_input()`` — local-only checks (audio asset present + file
   exists).  No network/LLM (R4.6).
2. Transcribe the audio to timed segments via
   :func:`server.audio.transcribe.transcribe` (Whisper, lazy import).
3. Each transcript segment → one caption scene; duration derived from the
   segment span (clamped to [3, 30]).

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import logging
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
_AUDIO_ASSET_KEY = "audio"

_SCENE_PROMPT_TEMPLATE = (
    "Podcast caption scene. Waveform / abstract audio-reactive background with "
    "large readable caption text for the line: {line!r}."
)


class PodcastCaptionAdapter:
    """ContentAdapter that captions a podcast/audio file.

    Attributes:
        adapter_type: Registry key — ``"podcast_caption"``.
    """

    adapter_type: str = "podcast_caption"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Transcribe audio and return a captioned :class:`SceneList`."""
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid podcast_caption input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        audio_path = Path(input.assets[_AUDIO_ASSET_KEY])
        language = input.options.get("language")
        model_size = input.options.get("model_size", "base")

        segments = self._transcribe(audio_path, language, model_size)
        if not segments:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "Transcription produced no segments (silent audio or unsupported file).",
                details={"audio_path": str(audio_path)},
            )

        scenes = [
            self._segment_to_scene(order, seg)
            for order, seg in enumerate(segments)
        ]

        if input.skill_name:
            scenes = _apply_skill(scenes, input.skill_name, self.adapter_type)

        scene_list = SceneList(
            project_id=input.options.get("project_id", "podcast_caption"),
            scenes=scenes,
            voice=input.options.get("voice", _DEFAULT_VOICE),
            metadata={
                "adapter": self.adapter_type,
                "scene_count": len(scenes),
                "skill_name": input.skill_name,
                "audio_path": str(audio_path),
            },
        )

        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )
        enforce_pipeline_limits(scene_list)

        logger.debug("PodcastCaptionAdapter: generated %d scenes", len(scenes))
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Cheap local validation — no network/LLM calls (R4.6)."""
        errors: list[str] = []

        audio = input.assets.get(_AUDIO_ASSET_KEY)
        if audio is None:
            errors.append("assets['audio'] is required — provide an audio file path")
            return errors

        path = Path(audio)
        if not path.exists():
            errors.append(f"Audio file not found: {path}")

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _transcribe(
        self,
        audio_path: Path,
        language: str | None,
        model_size: str,
    ) -> list[object]:
        """Transcribe *audio_path* into timed segments (lazy Whisper import)."""
        try:
            from server.audio.transcribe import transcribe
        except ImportError as exc:  # pragma: no cover - exercised when extra missing
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "faster-whisper is required to transcribe audio. "
                "Install it with: pip install faster-whisper",
                details={"missing_package": "faster-whisper"},
            ) from exc

        try:
            return transcribe(
                audio_path=audio_path,
                language=language,
                model_size=model_size,
            )
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Transcription failed for {audio_path.name!r}: {exc}",
                details={"audio_path": str(audio_path), "error": str(exc)},
            ) from exc

    def _segment_to_scene(self, order: int, seg: object) -> SceneSpec:
        text = str(getattr(seg, "text", "")).strip()
        start = float(getattr(seg, "start_time", 0.0) or 0.0)
        end = float(getattr(seg, "end_time", 0.0) or 0.0)
        span = end - start
        duration = max(_MIN_DURATION, min(_MAX_DURATION, span if span > 0 else _DEFAULT_DURATION))

        return SceneSpec(
            order=order,
            prompt=_SCENE_PROMPT_TEMPLATE.format(line=text or "(caption)"),
            duration=duration,
            narration=text if text else None,
        )


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

ADAPTER: PodcastCaptionAdapter = PodcastCaptionAdapter()
ADAPTER_CLASS = PodcastCaptionAdapter
