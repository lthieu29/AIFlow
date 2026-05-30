"""High-level CapCut exporter — builds a JianYing draft from a completed project.

Takes a ``Project`` (from DB) with its scenes, audio files, and subtitle SRT,
then writes a CapCut-compatible draft folder using the capcut package.

Usage::

    from server.export.capcut_exporter import CapCutExporter
    from server.config import load_settings

    settings = load_settings()
    exporter = CapCutExporter(settings)
    draft_path = exporter.export(
        project=project,
        scenes=scenes,
        tts_audio_path="/abs/path/narration.mp3",
        bgm_audio_path="/abs/path/bgm.mp3",   # optional
        srt_path="/abs/path/subtitles.srt",    # optional
    )
    print(f"Draft written to: {draft_path}")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from loguru import logger

from server.export.capcut import (
    AudioMaterial,
    DraftWriter,
    JianYingDraft,
    Timerange,
    VideoMaterial,
)
from server.export.capcut.models import SEC

if TYPE_CHECKING:
    from server.config import Settings
    from server.db.models.project import Project
    from server.db.models.scene import Scene

# Default canvas dimensions for portrait 9:16 video
_DEFAULT_WIDTH = 1080
_DEFAULT_HEIGHT = 1920

# Fallback scene duration when not stored on the scene object (seconds)
_FALLBACK_SCENE_DURATION_S = 8.0

# Sub-directory inside settings.data_dir where CapCut drafts are written
_DRAFTS_SUBDIR = "capcut_drafts"


class CapCutExporter:
    """Builds and writes a CapCut draft for a completed AIFlow project.

    Args:
        settings: Application settings (used for storage paths and draft root).
        draft_root: Override the directory where drafts are written.
            Defaults to ``{settings.data_dir}/capcut_drafts/``.
    """

    def __init__(
        self,
        settings: "Settings",
        draft_root: Optional[str] = None,
    ) -> None:
        self._settings = settings
        if draft_root is not None:
            self._draft_root = Path(draft_root)
        else:
            self._draft_root = Path(settings.data_dir) / _DRAFTS_SUBDIR
        self._draft_root.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def export(
        self,
        project: "Project",
        scenes: "list[Scene]",
        *,
        tts_audio_path: Optional[str] = None,
        bgm_audio_path: Optional[str] = None,
        srt_path: Optional[str] = None,
        draft_name: Optional[str] = None,
    ) -> str:
        """Build and write a CapCut draft for *project*.

        Steps:
        1. Create a ``JianYingDraft`` with the project's canvas dimensions.
        2. Add a video clip for each scene (from ``storage/media/{project_id}/``).
        3. Add TTS narration audio track (if *tts_audio_path* is provided).
        4. Add BGM audio track (if *bgm_audio_path* is provided).
        5. Import subtitles from SRT file (if *srt_path* is provided).
        6. Write the draft folder via ``DraftWriter``.

        Args:
            project: The ``Project`` ORM object.
            scenes: Ordered list of ``Scene`` ORM objects for this project.
            tts_audio_path: Absolute path to the TTS narration MP3 file.
            bgm_audio_path: Absolute path to the BGM audio file (optional).
            srt_path: Absolute path to the subtitle SRT file (optional).
            draft_name: Override the draft folder name.  Defaults to
                ``"{project.title}_{project.short_id}"``.

        Returns:
            Absolute path to the created draft folder.

        Raises:
            ValueError: If no scenes are provided.
            FileNotFoundError: If a required media file is missing.
        """
        if not scenes:
            raise ValueError(
                f"Project {project.id} has no scenes — cannot export CapCut draft."
            )

        name = draft_name or f"{project.title}_{project.short_id}"
        logger.info(
            "[CapCutExporter] exporting project_id={} scenes={} draft_name={!r}",
            project.id,
            len(scenes),
            name,
        )

        # Determine canvas dimensions from project aspect ratio
        width, height = _aspect_to_dimensions(getattr(project, "aspect", "9:16"))
        draft = JianYingDraft(name=name, width=width, height=height)

        # ── Step 1: Add video clips ───────────────────────────────────────────
        sorted_scenes = sorted(scenes, key=lambda s: s.order)
        timeline_cursor = 0  # microseconds

        for scene in sorted_scenes:
            video_path = self._resolve_scene_video(project, scene)
            if video_path is None:
                logger.warning(
                    "[CapCutExporter] scene order={} has no video file — skipping",
                    scene.order,
                )
                continue

            duration_us = _scene_duration_us(scene)
            mat = VideoMaterial(
                path=str(video_path),
                material_type="video",
                duration_us=duration_us,
                width=width,
                height=height,
            )
            target = Timerange(timeline_cursor, duration_us)
            draft.add_video_clip(mat, target, track="video")
            logger.debug(
                "[CapCutExporter] added scene order={} path={} duration_us={}",
                scene.order,
                video_path,
                duration_us,
            )
            timeline_cursor += duration_us

        if timeline_cursor == 0:
            raise ValueError(
                f"Project {project.id}: no valid video files found for any scene."
            )

        total_duration_us = timeline_cursor

        # ── Step 2: TTS narration audio ───────────────────────────────────────
        if tts_audio_path and os.path.exists(tts_audio_path):
            tts_duration_us = _probe_duration_us(tts_audio_path, total_duration_us)
            tts_mat = AudioMaterial(
                path=tts_audio_path,
                duration_us=tts_duration_us,
            )
            draft.add_audio_clip(
                tts_mat,
                Timerange(0, min(tts_duration_us, total_duration_us)),
                track="narration",
                volume=1.0,
            )
            logger.info(
                "[CapCutExporter] added TTS narration: {} ({:.2f}s)",
                tts_audio_path,
                tts_duration_us / SEC,
            )
        elif tts_audio_path:
            logger.warning(
                "[CapCutExporter] TTS audio path not found: {}", tts_audio_path
            )

        # ── Step 3: BGM audio ─────────────────────────────────────────────────
        if bgm_audio_path and os.path.exists(bgm_audio_path):
            bgm_duration_us = _probe_duration_us(bgm_audio_path, total_duration_us)
            bgm_mat = AudioMaterial(
                path=bgm_audio_path,
                duration_us=bgm_duration_us,
            )
            draft.add_audio_clip(
                bgm_mat,
                Timerange(0, min(bgm_duration_us, total_duration_us)),
                track="bgm",
                volume=0.3,  # BGM at 30% volume by default
            )
            logger.info(
                "[CapCutExporter] added BGM: {} ({:.2f}s)",
                bgm_audio_path,
                bgm_duration_us / SEC,
            )
        elif bgm_audio_path:
            logger.warning(
                "[CapCutExporter] BGM audio path not found: {}", bgm_audio_path
            )

        # ── Step 4: Subtitles from SRT ────────────────────────────────────────
        if srt_path and os.path.exists(srt_path):
            try:
                draft.import_srt(srt_path)
                logger.info("[CapCutExporter] imported subtitles from: {}", srt_path)
            except Exception as exc:
                logger.warning(
                    "[CapCutExporter] failed to import SRT {}: {}", srt_path, exc
                )
        elif srt_path:
            logger.warning(
                "[CapCutExporter] SRT path not found: {}", srt_path
            )

        # ── Step 5: Write draft ───────────────────────────────────────────────
        writer = DraftWriter(draft_root=str(self._draft_root))

        # Handle name collision by appending a suffix
        final_name = name
        attempt = 0
        while True:
            try:
                output_dir = writer.write(draft, draft_name=final_name)
                break
            except FileExistsError:
                attempt += 1
                final_name = f"{name}_{attempt}"
                logger.info(
                    "[CapCutExporter] draft name collision, retrying as {!r}",
                    final_name,
                )

        logger.info(
            "[CapCutExporter] draft written to: {} (duration={:.2f}s)",
            output_dir,
            total_duration_us / SEC,
        )
        return output_dir

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_scene_video(
        self,
        project: "Project",
        scene: "Scene",
    ) -> Optional[Path]:
        """Return the video file path for a scene, or None if not found.

        Checks (in order):
        1. ``scene.video_path`` attribute (set by orchestrator after gen).
        2. ``storage/media/{project_id}/`` directory — picks the file whose
           name contains the scene order index.
        3. Any ``*.mp4`` file in the media directory (fallback for single-scene
           projects or when ordering is implicit).
        """
        # 1. Explicit path stored on scene
        video_path = getattr(scene, "video_path", None)
        if video_path and os.path.exists(video_path):
            return Path(video_path)

        # 2. Look in storage/media/{project_id}/
        media_dir = Path(self._settings.data_dir) / "media" / str(project.id)
        if not media_dir.exists():
            return None

        # Try to find a file matching the scene order
        candidates = sorted(media_dir.glob("*.mp4"))
        if not candidates:
            return None

        # Match by scene order index in filename (e.g. "scene_0_*.mp4")
        order_str = str(scene.order)
        for candidate in candidates:
            if f"scene_{order_str}" in candidate.name or f"_{order_str}_" in candidate.name:
                return candidate

        # 3. Fallback: assign files by sorted order
        if scene.order < len(candidates):
            return candidates[scene.order]

        return None


# ── Module-level helpers ──────────────────────────────────────────────────────


def _aspect_to_dimensions(aspect: str) -> tuple[int, int]:
    """Convert an aspect ratio string to (width, height) in pixels.

    Supported: ``"9:16"`` (portrait), ``"16:9"`` (landscape).
    Defaults to 1080×1920 for unknown values.
    """
    mapping = {
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "1:1": (1080, 1080),
        "4:3": (1440, 1080),
    }
    return mapping.get(aspect, (1080, 1920))


def _scene_duration_us(scene: "Scene") -> int:
    """Return the scene duration in microseconds.

    Uses ``scene.duration`` (seconds) if available, otherwise falls back to
    the default 8-second Veo3 clip duration.
    """
    duration_s = getattr(scene, "duration", _FALLBACK_SCENE_DURATION_S)
    try:
        return int(float(duration_s) * SEC)
    except (TypeError, ValueError):
        return int(_FALLBACK_SCENE_DURATION_S * SEC)


def _probe_duration_us(audio_path: str, fallback_us: int) -> int:
    """Probe the duration of an audio file using ffmpeg_utils.

    Falls back to *fallback_us* if probing fails (e.g. ffprobe not available).
    """
    try:
        from server.audio.ffmpeg_utils import probe_duration

        duration_s = probe_duration(Path(audio_path))
        if duration_s and duration_s > 0:
            return int(duration_s * SEC)
    except Exception as exc:
        logger.debug(
            "[CapCutExporter] probe_duration failed for {}: {}", audio_path, exc
        )
    return fallback_us
