"""CapCut / JianYing draft export package.

Lifted and adapted from VectCutAPI/pyJianYingDraft (MIT licence).
Key changes vs upstream:
- Removed external `settings`, `json5`, `imageio` dependencies
- Hardcoded IS_CAPCUT_ENV = True (CapCut international format)
- Simplified material constructors to accept pre-probed metadata
- Added high-level `JianYingDraft` builder and `DraftWriter`
"""

from .models import (
    Timerange,
    VideoMaterial,
    AudioMaterial,
    VideoSegment,
    AudioSegment,
    TextSegment,
    TextStyle,
    TextBorder,
    TrackType,
)
from .draft import JianYingDraft
from .writer import DraftWriter

__all__ = [
    "Timerange",
    "VideoMaterial",
    "AudioMaterial",
    "VideoSegment",
    "AudioSegment",
    "TextSegment",
    "TextStyle",
    "TextBorder",
    "TrackType",
    "JianYingDraft",
    "DraftWriter",
]
