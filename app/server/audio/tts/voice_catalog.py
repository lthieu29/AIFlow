"""Voice catalog — preset voice metadata and lookup helpers.

Defines ``VoiceInfo`` as a Pydantic BaseModel (NOT dataclass) so it can be
used directly as a FastAPI ``response_model``.

Preset voices:
    - Binh       (VieNeu, male, Vietnamese, default)
    - Lan        (VieNeu, female, Vietnamese)
    - Nam        (VieNeu, male, Vietnamese, energetic)
    - vi-VN-HoaiMyNeural  (edge_tts, female, Vietnamese, default edge fallback)
    - vi-VN-NamMinhNeural (edge_tts, male, Vietnamese)

Phase 3.2 — Task 3.2.2
REVIEW-02 #12: VoiceInfo MUST be Pydantic BaseModel, NOT dataclass.
"""

from typing import Optional
from pydantic import BaseModel


# ─── VoiceInfo ────────────────────────────────────────────────────────────────


class VoiceInfo(BaseModel):
    """Unified voice descriptor for catalog, API responses, and UI display.

    Used as FastAPI ``response_model`` — must be Pydantic BaseModel (REVIEW-02 #12).

    Attributes:
        id: Unique voice identifier (e.g. "Binh", "vi-VN-HoaiMyNeural").
        name: Human-readable display name.
        backend: TTS backend — "vieneu" or "edge_tts".
        language: BCP-47 language tag, e.g. "vi-VN".
        gender: "male" or "female".
        description: Short description of voice style and use case.
        demo_audio_path: Path to pre-generated demo MP3 (None if not yet generated).
        is_custom: True for user-uploaded custom voices; False for presets.
    """

    id: str
    name: str
    backend: str
    language: str
    gender: str
    description: str
    demo_audio_path: Optional[str] = None
    is_custom: bool = False


# ─── Preset voice metadata ────────────────────────────────────────────────────

PRESET_VOICE_METADATA: list[VoiceInfo] = [
    VoiceInfo(
        id="Binh",
        name="Bình",
        backend="vieneu",
        language="vi-VN",
        gender="male",
        description="Bình — nam miền Bắc, ấm, mặc định khuyên dùng cho narration",
        demo_audio_path=None,
        is_custom=False,
    ),
    VoiceInfo(
        id="Lan",
        name="Lan",
        backend="vieneu",
        language="vi-VN",
        gender="female",
        description="Lan — nữ miền Bắc, mềm, phù hợp podcast và storytelling",
        demo_audio_path=None,
        is_custom=False,
    ),
    VoiceInfo(
        id="Nam",
        name="Nam",
        backend="vieneu",
        language="vi-VN",
        gender="male",
        description="Nam — nam miền Nam, năng lượng, phù hợp vlog và social media",
        demo_audio_path=None,
        is_custom=False,
    ),
    VoiceInfo(
        id="vi-VN-HoaiMyNeural",
        name="Hoài My (Edge)",
        backend="edge_tts",
        language="vi-VN",
        gender="female",
        description="HoàiMy — nữ ấm, neutral, default edge_tts fallback",
        demo_audio_path=None,
        is_custom=False,
    ),
    VoiceInfo(
        id="vi-VN-NamMinhNeural",
        name="Nam Minh (Edge)",
        backend="edge_tts",
        language="vi-VN",
        gender="male",
        description="NamMinh — nam trẻ, năng lượng, edge_tts",
        demo_audio_path=None,
        is_custom=False,
    ),
]


# ─── Lookup helpers ───────────────────────────────────────────────────────────


def get_preset_voices() -> list[VoiceInfo]:
    """Return all preset voices.

    Returns a new list each call so callers cannot mutate the module-level
    ``PRESET_VOICE_METADATA`` list.

    Returns:
        List of all 5 preset ``VoiceInfo`` entries.
    """
    return list(PRESET_VOICE_METADATA)


def get_voice_by_id(voice_id: str) -> Optional[VoiceInfo]:
    """Look up a preset voice by its unique identifier.

    Args:
        voice_id: The ``id`` field of the voice to find (case-sensitive).

    Returns:
        The matching ``VoiceInfo`` if found, otherwise ``None``.
    """
    for voice in PRESET_VOICE_METADATA:
        if voice.id == voice_id:
            return voice
    return None
