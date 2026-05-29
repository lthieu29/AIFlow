"""Quality gates package — re-export all gate functions.

Gates:
    G1 — SceneList structure validation (auto)
    G2 — User approve asset refs (manual, with SLA timeout)
    G3 — Per-scene quality check (auto, max 2 retries)
    G4 — Audio quality check (auto)
    G5 — Subtitle quality check (auto)

EPUB checkpoints (Task 6.3):
    EG1 — Character gate (manual, EPUB only)
    EG2 — Plot gate (manual, EPUB only)
    EG3 — Style gate (manual, EPUB only)
"""

from server.pipeline.gates.epub_checkpoints import (
    EPUB_ALLOWED_SKILL,
    EPUB_GATE_DEFAULT_TIMEOUT_HOURS,
    EPUB_GATE_NAMES,
    EpubSkillRestrictionError,
    approve_epub_gate,
    check_epub_gate_status,
    create_epub_character_gate,
    create_epub_plot_gate,
    create_epub_style_gate,
    override_epub_gate,
    validate_epub_skill,
)
from server.pipeline.gates.g1_scene_list import validate_scene_list
from server.pipeline.gates.g2_asset_approval import (
    approve_g2,
    check_g2_status,
    create_g2_gate,
    override_g2,
)
from server.pipeline.gates.g3_scene_quality import (
    MAX_RETRIES,
    check_scene_quality,
    get_scene_retry_count,
    should_retry_scene,
)
from server.pipeline.gates.g4_audio_quality import check_audio_quality
from server.pipeline.gates.g5_subtitle_quality import check_subtitle_quality

__all__ = [
    # G1
    "validate_scene_list",
    # G2
    "create_g2_gate",
    "check_g2_status",
    "approve_g2",
    "override_g2",
    # G3
    "check_scene_quality",
    "get_scene_retry_count",
    "should_retry_scene",
    "MAX_RETRIES",
    # G4
    "check_audio_quality",
    # G5
    "check_subtitle_quality",
    # EPUB checkpoints (EG1, EG2, EG3)
    "EPUB_ALLOWED_SKILL",
    "EPUB_GATE_DEFAULT_TIMEOUT_HOURS",
    "EPUB_GATE_NAMES",
    "EpubSkillRestrictionError",
    "validate_epub_skill",
    "create_epub_character_gate",
    "create_epub_plot_gate",
    "create_epub_style_gate",
    "check_epub_gate_status",
    "approve_epub_gate",
    "override_epub_gate",
]
