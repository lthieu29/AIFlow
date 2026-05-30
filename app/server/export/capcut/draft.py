"""Core JianYingDraft builder.

Provides a high-level API for constructing a CapCut / JianYing draft
programmatically.  The resulting draft can be serialised to JSON via
:meth:`JianYingDraft.dumps` and written to disk via
:class:`~server.export.capcut.writer.DraftWriter`.

Usage example::

    from server.export.capcut import (
        JianYingDraft, VideoMaterial, AudioMaterial, TextSegment,
        Timerange, SEC,
    )

    draft = JianYingDraft(name="My Project", width=1080, height=1920)

    # Add a video clip
    vid = VideoMaterial(path="/abs/path/clip.mp4", duration_us=8 * SEC,
                        width=1080, height=1920)
    draft.add_video_clip(vid, Timerange(0, 8 * SEC))

    # Add TTS narration
    tts = AudioMaterial(path="/abs/path/narration.mp3", duration_us=8 * SEC)
    draft.add_audio_clip(tts, Timerange(0, 8 * SEC), track="narration")

    # Add subtitle
    draft.add_subtitle("Hello world", Timerange(0, 3 * SEC))

    json_str = draft.dumps()
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from .models import (
    AudioMaterial,
    AudioSegment,
    ClipSettings,
    TextBorder,
    TextSegment,
    TextStyle,
    Timerange,
    TrackType,
    VideoMaterial,
    VideoSegment,
    _Speed,
)

# ---------------------------------------------------------------------------
# Internal track representation
# ---------------------------------------------------------------------------

class _Track:
    """Internal track container."""

    def __init__(self, track_type: TrackType, name: str, render_index: int, mute: bool = False) -> None:
        self.track_type = track_type
        self.name = name
        self.track_id = uuid.uuid4().hex
        self.render_index = render_index
        self.mute = mute
        self.segments: List[Any] = []

    @property
    def end_time(self) -> int:
        if not self.segments:
            return 0
        return max(seg.end for seg in self.segments)

    def export_json(self) -> Dict[str, Any]:
        seg_exports = []
        for seg in self.segments:
            j = seg.export_json()
            j["render_index"] = self.render_index
            seg_exports.append(j)
        return {
            "attribute": int(self.mute),
            "flag": 0,
            "id": self.track_id,
            "is_default_name": len(self.name) == 0,
            "name": self.name,
            "segments": seg_exports,
            "type": self.track_type.value,
        }


# ---------------------------------------------------------------------------
# Draft template (minimal, no external file dependency)
# ---------------------------------------------------------------------------

_DRAFT_TEMPLATE: Dict[str, Any] = {
    "canvas_config": {"height": 1080, "ratio": "original", "width": 1920},
    "color_space": 0,
    "config": {
        "adjust_max_index": 1,
        "attachment_info": [],
        "combination_max_index": 1,
        "export_range": None,
        "extract_audio_last_index": 1,
        "lyrics_recognition_id": "",
        "lyrics_sync": True,
        "lyrics_taskinfo": [],
        "maintrack_adsorb": True,
        "material_save_mode": 0,
        "multi_language_current": "none",
        "multi_language_list": [],
        "multi_language_main": "none",
        "multi_language_mode": "none",
        "original_sound_last_index": 1,
        "record_audio_last_index": 1,
        "sticker_max_index": 1,
        "subtitle_keywords_config": None,
        "subtitle_recognition_id": "",
        "subtitle_sync": True,
        "subtitle_taskinfo": [],
        "system_font_list": [],
        "video_mute": False,
        "zoom_info_params": None,
    },
    "cover": None,
    "create_time": 0,
    "duration": 0,
    "extra_info": None,
    "fps": 30.0,
    "free_render_index_mode_on": False,
    "group_container": None,
    "id": "",
    "keyframe_graph_list": [],
    "keyframes": {
        "adjusts": [], "audios": [], "effects": [], "filters": [],
        "handwrites": [], "stickers": [], "texts": [], "videos": [],
    },
    "last_modified_platform": {
        "app_id": 359289,
        "app_source": "cc",
        "app_version": "6.5.0",
        "device_id": "c4ca4238a0b923820dcc509a6f75849b",
        "hard_disk_id": "307563e0192a94465c0e927fbc482942",
        "mac_address": "c3371f2d4fb02791c067ce44d8fb4ed5",
        "os": "mac",
        "os_version": "15.5",
    },
    "materials": {
        "ai_translates": [], "audio_balances": [], "audio_effects": [],
        "audio_fades": [], "audio_track_indexes": [], "audios": [],
        "beats": [], "canvases": [], "chromas": [], "color_curves": [],
        "digital_humans": [], "drafts": [], "effects": [], "flowers": [],
        "green_screens": [], "handwrites": [], "hsl": [], "images": [],
        "log_color_wheels": [], "loudnesses": [], "manual_deformations": [],
        "common_mask": [],  # CapCut uses common_mask, not masks
        "material_animations": [], "material_colors": [],
        "multi_language_refs": [], "placeholders": [], "plugin_effects": [],
        "primary_color_wheels": [], "realtime_denoises": [], "shapes": [],
        "smart_crops": [], "smart_relights": [], "sound_channel_mappings": [],
        "speeds": [], "stickers": [], "tail_leaders": [], "text_templates": [],
        "texts": [], "time_marks": [], "transitions": [], "video_effects": [],
        "video_trackings": [], "videos": [], "vocal_beautifys": [],
        "vocal_separations": [],
    },
    "mutable_config": None,
    "name": "",
    "new_version": "110.0.0",
    "relationships": [],
    "render_index_track_mode_on": True,
    "retouch_cover": None,
    "source": "default",
    "static_cover_image_path": "",
    "time_marks": None,
    "tracks": [],
    "update_time": 0,
    "version": 360000,
}

# Render index constants (higher = closer to foreground)
_RENDER_INDEX_VIDEO = 0
_RENDER_INDEX_AUDIO = 0
_RENDER_INDEX_TEXT = 15000


# ---------------------------------------------------------------------------
# JianYingDraft
# ---------------------------------------------------------------------------

class JianYingDraft:
    """High-level builder for a CapCut / JianYing draft.

    Tracks are created lazily on first use.  Multiple audio tracks are
    supported (e.g. ``track="narration"`` vs ``track="bgm"``).

    Args:
        name: Human-readable project name shown in CapCut.
        width: Canvas width in pixels (default 1080 for portrait 9:16).
        height: Canvas height in pixels (default 1920 for portrait 9:16).
        fps: Frame rate (default 30).
    """

    def __init__(
        self,
        name: str = "AIFlow Draft",
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
    ) -> None:
        self.name = name
        self.width = width
        self.height = height
        self.fps = fps
        self.duration: int = 0

        # Tracks keyed by name
        self._tracks: Dict[str, _Track] = {}

        # Material registries (deduped by material_id)
        self._video_materials: Dict[str, VideoMaterial] = {}
        self._audio_materials: Dict[str, AudioMaterial] = {}
        self._speed_objects: List[_Speed] = []
        self._text_materials: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Track management
    # ------------------------------------------------------------------

    def _get_or_create_track(
        self,
        track_type: TrackType,
        name: str,
        render_index: int,
        mute: bool = False,
    ) -> _Track:
        if name not in self._tracks:
            self._tracks[name] = _Track(track_type, name, render_index, mute)
        return self._tracks[name]

    # ------------------------------------------------------------------
    # Public API — video
    # ------------------------------------------------------------------

    def add_video_clip(
        self,
        material: VideoMaterial,
        target_timerange: Timerange,
        *,
        source_timerange: Optional[Timerange] = None,
        speed: float = 1.0,
        volume: float = 1.0,
        clip_settings: Optional[ClipSettings] = None,
        track: str = "video",
    ) -> "JianYingDraft":
        """Add a video (or image) clip to the video track.

        Args:
            material: The :class:`~.models.VideoMaterial` to use.
            target_timerange: Where on the timeline to place the clip.
            source_timerange: Which portion of the source file to use.
                Defaults to the full clip duration.
            speed: Playback speed multiplier.
            volume: Volume (0.0–1.0).
            clip_settings: Geometric transform.  Defaults to identity.
            track: Track name.  Use different names for overlay tracks.
        """
        if clip_settings is None:
            clip_settings = ClipSettings()

        seg = VideoSegment(
            material=material,
            target_timerange=target_timerange,
            source_timerange=source_timerange,
            speed=speed,
            volume=volume,
            clip_settings=clip_settings,
        )

        t = self._get_or_create_track(TrackType.video, track, _RENDER_INDEX_VIDEO)
        t.segments.append(seg)
        self.duration = max(self.duration, seg.end)

        # Register material and speed
        self._video_materials[material.material_id] = material
        self._speed_objects.append(seg.speed_obj())

        return self

    # ------------------------------------------------------------------
    # Public API — audio
    # ------------------------------------------------------------------

    def add_audio_clip(
        self,
        material: AudioMaterial,
        target_timerange: Timerange,
        *,
        source_timerange: Optional[Timerange] = None,
        speed: float = 1.0,
        volume: float = 1.0,
        mute: bool = False,
        track: str = "audio",
    ) -> "JianYingDraft":
        """Add an audio clip (TTS narration, BGM, etc.) to an audio track.

        Args:
            material: The :class:`~.models.AudioMaterial` to use.
            target_timerange: Where on the timeline to place the clip.
            source_timerange: Which portion of the source file to use.
            speed: Playback speed multiplier.
            volume: Volume (0.0–1.0).
            mute: Whether the track should be muted.
            track: Track name.  Use ``"narration"`` and ``"bgm"`` to keep
                TTS and background music on separate tracks.
        """
        seg = AudioSegment(
            material=material,
            target_timerange=target_timerange,
            source_timerange=source_timerange,
            speed=speed,
            volume=volume,
        )

        t = self._get_or_create_track(TrackType.audio, track, _RENDER_INDEX_AUDIO, mute=mute)
        t.segments.append(seg)
        self.duration = max(self.duration, seg.end)

        self._audio_materials[material.material_id] = material
        self._speed_objects.append(seg.speed_obj())

        return self

    # ------------------------------------------------------------------
    # Public API — text / subtitles
    # ------------------------------------------------------------------

    def add_subtitle(
        self,
        text: str,
        target_timerange: Timerange,
        *,
        style: Optional[TextStyle] = None,
        border: Optional[TextBorder] = None,
        clip_settings: Optional[ClipSettings] = None,
        track: str = "subtitle",
    ) -> "JianYingDraft":
        """Add a subtitle / caption to a text track.

        Args:
            text: The subtitle text.
            target_timerange: When the subtitle is visible.
            style: Font style.  Defaults to white, centred, size 8.
            border: Text stroke / outline.  Defaults to no border.
            clip_settings: Position on screen.  Defaults to bottom-centre
                (``transform_y=-0.8``).
            track: Track name.
        """
        if style is None:
            style = TextStyle()
        if clip_settings is None:
            clip_settings = ClipSettings(transform_y=-0.8)

        seg = TextSegment(
            text=text,
            target_timerange=target_timerange,
            style=style,
            border=border,
            clip_settings=clip_settings,
        )

        t = self._get_or_create_track(TrackType.text, track, _RENDER_INDEX_TEXT)
        t.segments.append(seg)
        self.duration = max(self.duration, seg.end)

        self._text_materials.append(seg.export_material())

        return self

    def import_srt(
        self,
        srt_content: str,
        *,
        style: Optional[TextStyle] = None,
        border: Optional[TextBorder] = None,
        clip_settings: Optional[ClipSettings] = None,
        track: str = "subtitle",
    ) -> "JianYingDraft":
        """Import subtitles from an SRT string or file path.

        Args:
            srt_content: Either the raw SRT text or an absolute path to an
                ``.srt`` file.
            style: Font style for all subtitles.
            border: Text stroke for all subtitles.
            clip_settings: Screen position for all subtitles.
            track: Track name.
        """
        if os.path.exists(srt_content):
            with open(srt_content, encoding="utf-8-sig") as fh:
                lines = fh.readlines()
        else:
            lines = srt_content.splitlines()

        from .models import SEC, tim

        def _parse_ts(ts: str) -> int:
            """Parse ``HH:MM:SS,mmm`` → microseconds."""
            sec_part, ms_part = ts.strip().split(",")
            h, m, s = sec_part.split(":")
            return (int(h) * 3600 + int(m) * 60 + int(s)) * SEC + int(ms_part) * 1000

        idx = 0
        state = "index"
        text_buf = ""
        t_range: Optional[Timerange] = None

        while idx < len(lines):
            line = lines[idx].strip()
            if state == "index":
                if line == "":
                    idx += 1
                    continue
                if not line.isdigit():
                    raise ValueError(f"Expected subtitle index at line {idx + 1}, got {line!r}")
                idx += 1
                state = "timestamp"
            elif state == "timestamp":
                start_str, end_str = line.split(" --> ")
                start_us = _parse_ts(start_str)
                end_us = _parse_ts(end_str)
                t_range = Timerange(start_us, end_us - start_us)
                idx += 1
                state = "content"
            elif state == "content":
                if line == "":
                    if text_buf.strip() and t_range is not None:
                        self.add_subtitle(
                            text_buf.strip(),
                            t_range,
                            style=style,
                            border=border,
                            clip_settings=clip_settings,
                            track=track,
                        )
                    text_buf = ""
                    t_range = None
                    state = "index"
                else:
                    text_buf += line + "\n"
                idx += 1

        # Flush last entry (no trailing blank line)
        if text_buf.strip() and t_range is not None:
            self.add_subtitle(
                text_buf.strip(),
                t_range,
                style=style,
                border=border,
                clip_settings=clip_settings,
                track=track,
            )

        return self

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def dumps(self) -> str:
        """Serialise the draft to a JSON string (``draft_info.json`` content)."""
        content = copy.deepcopy(_DRAFT_TEMPLATE)

        content["id"] = uuid.uuid4().hex.upper()
        content["name"] = self.name
        content["fps"] = float(self.fps)
        content["duration"] = self.duration
        content["canvas_config"] = {
            "width": self.width,
            "height": self.height,
            "ratio": "original",
        }

        # Materials
        mats = content["materials"]
        mats["videos"] = [m.export_json() for m in self._video_materials.values()]
        mats["audios"] = [m.export_json() for m in self._audio_materials.values()]
        mats["speeds"] = [s.export_json() for s in self._speed_objects]
        mats["texts"] = list(self._text_materials)

        # Tracks — sorted by render_index (lowest = background)
        sorted_tracks = sorted(self._tracks.values(), key=lambda t: t.render_index)
        content["tracks"] = [t.export_json() for t in sorted_tracks]

        return json.dumps(content, ensure_ascii=False, indent=4)

    def dump(self, file_path: str) -> None:
        """Write the draft JSON to *file_path*."""
        with open(file_path, "w", encoding="utf-8") as fh:
            fh.write(self.dumps())
