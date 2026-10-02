"""Pydantic-style data models for CapCut/JianYing draft components.

All time values are in **microseconds** (µs) — same convention as the
upstream pyJianYingDraft library.  Use the ``SEC`` constant (= 1_000_000)
or the ``trange()`` / ``tim()`` helpers for convenience.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

SEC: int = 1_000_000
"""One second expressed in microseconds."""


def tim(value: "int | float | str") -> int:
    """Convert a time value to microseconds.

    Accepts:
    - ``int`` / ``float`` — treated as microseconds already
    - ``str`` — parsed as ``"1h30m5s"`` or ``"2.5s"`` etc.
    """
    if isinstance(value, (int, float)):
        return int(round(value))

    sign = 1
    s = value.strip().lower()
    if s.startswith("-"):
        sign = -1
        s = s[1:]

    last = 0
    total: float = 0.0
    for unit, factor in zip(["h", "m", "s"], [3600 * SEC, 60 * SEC, SEC]):
        idx = s.find(unit)
        if idx == -1:
            continue
        total += float(s[last:idx]) * factor
        last = idx + 1
    return int(round(total) * sign)


@dataclass
class Timerange:
    """A half-open time interval ``[start, start + duration)`` in microseconds."""

    start: int
    duration: int

    @property
    def end(self) -> int:
        return self.start + self.duration

    def export_json(self) -> Dict[str, int]:
        return {"start": self.start, "duration": self.duration}

    def overlaps(self, other: "Timerange") -> bool:
        return not (self.end <= other.start or other.end <= self.start)


def trange(start: "int | float | str", duration: "int | float | str") -> Timerange:
    """Convenience constructor for :class:`Timerange`."""
    return Timerange(tim(start), tim(duration))


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

@dataclass
class VideoMaterial:
    """A local video or image file that can be placed on a video track.

    Unlike the upstream class, this constructor does **not** call ffprobe.
    Callers must supply ``duration_us``, ``width``, and ``height`` explicitly
    (e.g. obtained via :func:`server.audio.ffmpeg_utils.probe_duration`).
    """

    path: str
    """Absolute path to the media file."""
    material_type: Literal["video", "photo"] = "video"
    duration_us: int = 0
    """Duration in microseconds.  For photos use a large value (e.g. 10_800_000_000)."""
    width: int = 1920
    height: int = 1080
    material_name: Optional[str] = None
    material_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.material_name is None:
            import os
            self.material_name = os.path.basename(self.path)
        # Stable ID derived from name so the same file always gets the same ID
        self.material_id = uuid.uuid3(uuid.NAMESPACE_DNS, self.material_name).hex

    def export_json(self) -> Dict[str, Any]:
        return {
            "audio_fade": None,
            "category_id": "",
            "category_name": "local",
            "check_flag": 63487,
            "crop": {
                "upper_left_x": 0.0, "upper_left_y": 0.0,
                "upper_right_x": 1.0, "upper_right_y": 0.0,
                "lower_left_x": 0.0, "lower_left_y": 1.0,
                "lower_right_x": 1.0, "lower_right_y": 1.0,
            },
            "crop_ratio": "free",
            "crop_scale": 1.0,
            "duration": self.duration_us,
            "height": self.height,
            "id": self.material_id,
            "local_material_id": "",
            "material_id": self.material_id,
            "material_name": self.material_name,
            "media_path": "",
            "path": self.path,
            "remote_url": None,
            "type": self.material_type,
            "width": self.width,
        }


@dataclass
class AudioMaterial:
    """A local audio file that can be placed on an audio track.

    Like :class:`VideoMaterial`, callers must supply ``duration_us``
    explicitly — no ffprobe call is made here.
    """

    path: str
    duration_us: int = 0
    material_name: Optional[str] = None
    material_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self) -> None:
        if self.material_name is None:
            import os
            self.material_name = os.path.basename(self.path)
        self.material_id = uuid.uuid3(uuid.NAMESPACE_DNS, self.material_name).hex

    def export_json(self) -> Dict[str, Any]:
        return {
            "app_id": 0,
            "category_id": "",
            "category_name": "local",
            "check_flag": 1,
            "copyright_limit_type": "none",
            "duration": self.duration_us,
            "effect_id": "",
            "formula_id": "",
            "id": self.material_id,
            "intensifies_path": "",
            "is_ai_clone_tone": False,
            "is_text_edit_overdub": False,
            "is_ugc": False,
            "local_material_id": self.material_id,
            "music_id": self.material_id,
            "name": self.material_name,
            "path": self.path,
            "remote_url": None,
            "query": "",
            "request_id": "",
            "resource_id": "",
            "search_id": "",
            "source_from": "",
            "source_platform": 0,
            "team_id": "",
            "text_id": "",
            "tone_category_id": "",
            "tone_category_name": "",
            "tone_effect_id": "",
            "tone_effect_name": "",
            "tone_platform": "",
            "tone_second_category_id": "",
            "tone_second_category_name": "",
            "tone_speaker": "",
            "tone_type": "",
            "type": "extract_music",
            "video_id": "",
            "wave_points": [],
        }


# ---------------------------------------------------------------------------
# Clip / speed helpers
# ---------------------------------------------------------------------------

@dataclass
class _Speed:
    speed: float
    global_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def export_json(self) -> Dict[str, Any]:
        return {
            "curve_speed": None,
            "id": self.global_id,
            "mode": 0,
            "speed": self.speed,
            "type": "speed",
        }


@dataclass
class ClipSettings:
    """Geometric transform applied to a visual segment."""

    alpha: float = 1.0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    transform_x: float = 0.0
    transform_y: float = 0.0

    def export_json(self) -> Dict[str, Any]:
        return {
            "alpha": self.alpha,
            "flip": {"horizontal": self.flip_horizontal, "vertical": self.flip_vertical},
            "rotation": self.rotation,
            "scale": {"x": self.scale_x, "y": self.scale_y},
            "transform": {"x": self.transform_x, "y": self.transform_y},
        }


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------

@dataclass
class VideoSegment:
    """A clip placed on a video track."""

    material: VideoMaterial
    target_timerange: Timerange
    source_timerange: Optional[Timerange] = None
    speed: float = 1.0
    volume: float = 1.0
    clip_settings: ClipSettings = field(default_factory=ClipSettings)

    segment_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _speed_obj: _Speed = field(init=False)

    def __post_init__(self) -> None:
        self._speed_obj = _Speed(self.speed)
        if self.source_timerange is None:
            self.source_timerange = Timerange(0, self.target_timerange.duration)

    @property
    def end(self) -> int:
        return self.target_timerange.end

    def export_json(self) -> Dict[str, Any]:
        return {
            "enable_adjust": True,
            "enable_color_correct_adjust": False,
            "enable_color_curves": True,
            "enable_color_match_adjust": False,
            "enable_color_wheels": True,
            "enable_lut": True,
            "enable_smart_color_adjust": False,
            "last_nonzero_volume": 1.0,
            "reverse": False,
            "track_attribute": 0,
            "track_render_index": 0,
            "visible": True,
            "id": self.segment_id,
            "material_id": self.material.material_id,
            "target_timerange": self.target_timerange.export_json(),
            "source_timerange": self.source_timerange.export_json() if self.source_timerange else None,
            "speed": self.speed,
            "volume": self.volume,
            "extra_material_refs": [self._speed_obj.global_id],
            "common_keyframes": [],
            "keyframe_refs": [],
            "clip": self.clip_settings.export_json(),
            "uniform_scale": {"on": True, "value": 1.0},
            "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
            "render_index": 0,
        }

    def speed_obj(self) -> _Speed:
        return self._speed_obj


@dataclass
class AudioSegment:
    """A clip placed on an audio track."""

    material: AudioMaterial
    target_timerange: Timerange
    source_timerange: Optional[Timerange] = None
    speed: float = 1.0
    volume: float = 1.0

    segment_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _speed_obj: _Speed = field(init=False)

    def __post_init__(self) -> None:
        self._speed_obj = _Speed(self.speed)
        if self.source_timerange is None:
            self.source_timerange = Timerange(0, self.target_timerange.duration)

    @property
    def end(self) -> int:
        return self.target_timerange.end

    def export_json(self) -> Dict[str, Any]:
        return {
            "enable_adjust": True,
            "enable_color_correct_adjust": False,
            "enable_color_curves": True,
            "enable_color_match_adjust": False,
            "enable_color_wheels": True,
            "enable_lut": True,
            "enable_smart_color_adjust": False,
            "last_nonzero_volume": 1.0,
            "reverse": False,
            "track_attribute": 0,
            "track_render_index": 0,
            "visible": True,
            "id": self.segment_id,
            "material_id": self.material.material_id,
            "target_timerange": self.target_timerange.export_json(),
            "source_timerange": self.source_timerange.export_json() if self.source_timerange else None,
            "speed": self.speed,
            "volume": self.volume,
            "extra_material_refs": [self._speed_obj.global_id],
            "common_keyframes": [],
            "keyframe_refs": [],
            "clip": None,
            "hdr_settings": None,
            "render_index": 0,
        }

    def speed_obj(self) -> _Speed:
        return self._speed_obj


# ---------------------------------------------------------------------------
# Text segment
# ---------------------------------------------------------------------------

@dataclass
class TextStyle:
    """Font / layout style for a text segment."""

    size: float = 8.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    alpha: float = 1.0
    align: Literal[0, 1, 2] = 1  # 0=left, 1=center, 2=right
    letter_spacing: int = 0
    line_spacing: int = 0


@dataclass
class TextBorder:
    """Stroke / outline for text."""

    alpha: float = 1.0
    color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    width: float = 40.0  # 0-100 scale, same as CapCut UI

    def export_json(self) -> Dict[str, Any]:
        return {
            "content": {
                "solid": {
                    "alpha": self.alpha,
                    "color": list(self.color),
                }
            },
            "width": self.width / 100.0 * 0.2,
        }


@dataclass
class TextSegment:
    """A subtitle / caption placed on a text track."""

    text: str
    target_timerange: Timerange
    style: TextStyle = field(default_factory=TextStyle)
    border: Optional[TextBorder] = None
    clip_settings: ClipSettings = field(default_factory=lambda: ClipSettings(transform_y=-0.8))

    segment_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    material_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def end(self) -> int:
        return self.target_timerange.end

    def export_material(self) -> Dict[str, Any]:
        """Serialise the text material (goes into ``materials.texts``)."""
        check_flag = 7
        if self.border:
            check_flag |= 8

        style_item: Dict[str, Any] = {
            "fill": {
                "alpha": 1.0,
                "content": {
                    "render_type": "solid",
                    "solid": {
                        "alpha": self.style.alpha,
                        "color": list(self.style.color),
                    },
                },
            },
            "range": [0, len(self.text)],
            "size": self.style.size,
            "bold": self.style.bold,
            "italic": self.style.italic,
            "underline": self.style.underline,
            "strokes": [self.border.export_json()] if self.border else [],
        }

        content_json = {"styles": [style_item], "text": self.text}

        return {
            "id": self.material_id,
            "content": json.dumps(content_json, ensure_ascii=False),
            "typesetting": 0,
            "alignment": self.style.align,
            "letter_spacing": self.style.letter_spacing * 0.05,
            "line_spacing": 0.02 + self.style.line_spacing * 0.05,
            "line_feed": 1,
            "line_max_width": 0.82,
            "force_apply_line_max_width": False,
            "check_flag": check_flag,
            "type": "text",
            "fixed_width": -1,
            "fixed_height": -1,
            "font_category_id": "",
            "font_category_name": "",
            "font_id": "",
            "font_name": "",
            "font_path": "",
            "font_resource_id": "",
            "font_size": 15.0,
            "font_source_platform": 0,
            "font_team_id": "",
            "font_title": "none",
            "font_url": "",
            "fonts": [],
        }

    def export_json(self) -> Dict[str, Any]:
        """Serialise the segment (goes into the track's ``segments`` list)."""
        return {
            "enable_adjust": True,
            "enable_color_correct_adjust": False,
            "enable_color_curves": True,
            "enable_color_match_adjust": False,
            "enable_color_wheels": True,
            "enable_lut": True,
            "enable_smart_color_adjust": False,
            "last_nonzero_volume": 1.0,
            "reverse": False,
            "track_attribute": 0,
            "track_render_index": 0,
            "visible": True,
            "id": self.segment_id,
            "material_id": self.material_id,
            "target_timerange": self.target_timerange.export_json(),
            "source_timerange": None,
            "speed": 1.0,
            "volume": 1.0,
            "extra_material_refs": [],
            "common_keyframes": [],
            "keyframe_refs": [],
            "clip": self.clip_settings.export_json(),
            "uniform_scale": {"on": True, "value": 1.0},
            "render_index": 0,
        }


# ---------------------------------------------------------------------------
# Track type enum
# ---------------------------------------------------------------------------

class TrackType(str, Enum):
    video = "video"
    audio = "audio"
    text = "text"
