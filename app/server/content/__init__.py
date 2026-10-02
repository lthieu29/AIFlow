"""server.content — ContentAdapter framework public API.

Exports the core interface, dataclasses, registry, skill manifest loader,
skill loader, style validator, and shared adapter utilities so that callers
only need to import from this package.

Example::

    from server.content import (
        AdapterInput,
        AdapterError,
        ContentAdapter,
        SceneSpec,
        SceneList,
        REGISTRY,
        register_adapter,
        SkillManifest,
        load_skill_manifest,
        # skill loader
        LoadedSkill,
        SkillLoader,
        apply_skill_to_scene,
        # style validator
        validate_style_json,
        load_style_json,
        # shared utilities
        CharacterRef,
        dedup_characters,
        extract_character_names,
        normalize_name,
        estimate_scene_duration,
        estimate_total_duration,
        distribute_duration,
        WORDS_PER_MINUTE,
        ChunkResult,
        chunk_by_sentences,
        chunk_by_paragraphs,
        llm_chunk_to_scenes,
        estimate_scene_count,
        SrtSegment,
        parse_srt,
        format_srt,
        seconds_to_srt_time,
        srt_time_to_seconds,
        merge_short_segments,
        shift_segments,
    )
"""

from server.content.base import (
    AdapterError,
    AdapterInput,
    ContentAdapter,
    SceneList,
    SceneSpec,
)
from server.content.registry import (
    REGISTRY,
    AdapterRegistry,
    register_adapter,
)
from server.content.skill_manifest import (
    SkillManifest,
    load_skill_manifest,
)
from server.content.skill_loader import (
    LoadedSkill,
    SkillLoader,
    apply_skill_to_scene,
)
from server.content.style_validator import (
    load_style_json,
    validate_style_json,
)
from server.content.character_dedup import (
    CharacterRef,
    dedup_characters,
    extract_character_names,
    normalize_name,
)
from server.content.duration_estimator import (
    WORDS_PER_MINUTE,
    distribute_duration,
    estimate_scene_duration,
    estimate_total_duration,
)
from server.content.llm_chunking import (
    ChunkResult,
    chunk_by_paragraphs,
    chunk_by_sentences,
    estimate_scene_count,
    llm_chunk_to_scenes,
)
from server.content.srt_utils import (
    SrtSegment,
    format_srt,
    merge_short_segments,
    parse_srt,
    seconds_to_srt_time,
    shift_segments,
    srt_time_to_seconds,
)

__all__ = [
    # base
    "AdapterError",
    "AdapterInput",
    "ContentAdapter",
    "SceneList",
    "SceneSpec",
    # registry
    "REGISTRY",
    "AdapterRegistry",
    "register_adapter",
    # skill manifest
    "SkillManifest",
    "load_skill_manifest",
    # skill loader
    "LoadedSkill",
    "SkillLoader",
    "apply_skill_to_scene",
    # style validator
    "load_style_json",
    "validate_style_json",
    # character deduplication
    "CharacterRef",
    "dedup_characters",
    "extract_character_names",
    "normalize_name",
    # duration estimation
    "WORDS_PER_MINUTE",
    "distribute_duration",
    "estimate_scene_duration",
    "estimate_total_duration",
    # llm chunking
    "ChunkResult",
    "chunk_by_paragraphs",
    "chunk_by_sentences",
    "estimate_scene_count",
    "llm_chunk_to_scenes",
    # srt utilities
    "SrtSegment",
    "format_srt",
    "merge_short_segments",
    "parse_srt",
    "seconds_to_srt_time",
    "shift_segments",
    "srt_time_to_seconds",
]
