"""Duration estimation utilities for content adapters.

Provides helpers to estimate scene durations from narration text, split
long narration into multiple clips, and distribute a total duration evenly
across a set of scenes.

The maximum duration per scene is governed by ``Settings.flow.clip_duration``
(default 8.0s, matching Veo3's current limit). When Veo3 supports longer
clips, update ``AIFLOW_FLOW_CLIP_DURATION`` in ``.env`` — no code changes
needed.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from server.content.base import SceneSpec

if TYPE_CHECKING:
    pass


# ─── Constants ───────────────────────────────────────────────────────────────

#: Default speaking rate used when no explicit value is provided.
WORDS_PER_MINUTE: int = 150

#: Hard lower bound for a single scene duration (seconds).
MIN_DURATION: float = 3.0

#: Fallback max duration if no config is available (matches Veo3 8s clip).
_FALLBACK_MAX_DURATION: float = 8.0


def _get_clip_duration() -> float:
    """Read clip_duration from settings (lazy import to avoid circular deps).

    Returns the configured clip_duration or falls back to 8.0 if settings
    cannot be loaded (e.g. during tests without .env).
    """
    try:
        from server.config import load_settings
        settings = load_settings()
        return float(settings.flow.clip_duration)
    except Exception:
        return _FALLBACK_MAX_DURATION


def get_max_scene_duration(clip_duration: float | None = None) -> float:
    """Return the effective max duration per scene.

    Args:
        clip_duration: Explicit override. If None, reads from config.

    Returns:
        Max duration in seconds (>= MIN_DURATION).
    """
    if clip_duration is not None:
        return max(MIN_DURATION, clip_duration)
    return max(MIN_DURATION, _get_clip_duration())


# ─── Per-scene estimation ────────────────────────────────────────────────────


def estimate_scene_duration(
    narration: str,
    words_per_minute: int = WORDS_PER_MINUTE,
    clip_duration: float | None = None,
) -> float:
    """Estimate the duration of a single scene from its narration text.

    The estimate is based on word count divided by the speaking rate.
    The result is clamped to ``[MIN_DURATION, clip_duration]``.

    Args:
        narration:        The TTS narration text for the scene.
        words_per_minute: Speaking rate in words per minute.  Defaults to
                          :data:`WORDS_PER_MINUTE` (150 wpm).
        clip_duration:    Max seconds per clip.  If None, reads from config
                          (``AIFLOW_FLOW_CLIP_DURATION``, default 8.0).

    Returns:
        Estimated duration in seconds, clamped to
        ``[MIN_DURATION, clip_duration]``.

    Example::

        >>> estimate_scene_duration("Hello world")  # 2 words → clamped to MIN
        3.0
    """
    max_dur = get_max_scene_duration(clip_duration)

    if not narration or not narration.strip():
        return MIN_DURATION

    wpm = max(1, words_per_minute)  # guard against zero / negative
    word_count = len(narration.split())
    raw_seconds = (word_count / wpm) * 60.0
    return max(MIN_DURATION, min(max_dur, raw_seconds))


# ─── Split long narration into multiple scenes ──────────────────────────────


def split_long_narration(
    narration: str,
    prompt: str,
    words_per_minute: int = WORDS_PER_MINUTE,
    clip_duration: float | None = None,
) -> list[dict]:
    """Split narration that exceeds clip_duration into multiple scene chunks.

    Each chunk will have a narration segment that fits within clip_duration
    when spoken at the given words_per_minute rate. The split tries to break
    at sentence boundaries (. ! ?) for natural speech.

    Args:
        narration:        Full narration text.
        prompt:           Base visual prompt (reused/varied per chunk).
        words_per_minute: Speaking rate (default 150 wpm).
        clip_duration:    Max seconds per clip. If None, reads from config.

    Returns:
        List of dicts with keys: ``narration``, ``prompt``, ``duration``.
        If the narration fits in one clip, returns a single-element list.
    """
    max_dur = get_max_scene_duration(clip_duration)
    wpm = max(1, words_per_minute)

    # Max words that fit in one clip
    max_words_per_clip = int((max_dur / 60.0) * wpm)

    if not narration or not narration.strip():
        return [{"narration": "", "prompt": prompt, "duration": MIN_DURATION}]

    words = narration.split()
    total_words = len(words)

    # Fast path: fits in one clip
    if total_words <= max_words_per_clip:
        dur = max(MIN_DURATION, min(max_dur, (total_words / wpm) * 60.0))
        return [{"narration": narration.strip(), "prompt": prompt, "duration": dur}]

    # Split at sentence boundaries
    chunks = _split_text_by_sentences(narration, max_words_per_clip)

    results = []
    for i, chunk_text in enumerate(chunks):
        chunk_words = len(chunk_text.split())
        dur = max(MIN_DURATION, min(max_dur, (chunk_words / wpm) * 60.0))
        # Vary prompt slightly for continuation clips
        chunk_prompt = prompt if i == 0 else f"{prompt} (continuation {i + 1})"
        results.append({
            "narration": chunk_text.strip(),
            "prompt": chunk_prompt,
            "duration": dur,
        })

    return results


def _split_text_by_sentences(text: str, max_words: int) -> list[str]:
    """Split text into chunks of at most max_words, preferring sentence boundaries.

    Sentence boundaries are: . ! ? followed by whitespace or end of string.
    If a single sentence exceeds max_words, it is split at word boundaries.
    """
    import re

    # Split into sentences (keep the delimiter attached)
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_word_count = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())

        if current_word_count + sentence_words <= max_words:
            current_chunk.append(sentence)
            current_word_count += sentence_words
        else:
            # Flush current chunk if non-empty
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_word_count = 0

            # If single sentence exceeds max_words, force-split by words
            if sentence_words > max_words:
                words = sentence.split()
                for j in range(0, len(words), max_words):
                    chunk_slice = words[j:j + max_words]
                    chunks.append(" ".join(chunk_slice))
            else:
                current_chunk.append(sentence)
                current_word_count = sentence_words

    # Flush remaining
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


# ─── Total duration ──────────────────────────────────────────────────────────


def estimate_total_duration(
    scenes: list[SceneSpec],
    clip_duration: float | None = None,
) -> float:
    """Return the sum of all scene durations in *scenes*.

    Scenes without narration use their ``duration`` field directly.
    Scenes with narration use :func:`estimate_scene_duration` to compute
    the duration from the narration text.

    Args:
        scenes:        List of :class:`~server.content.base.SceneSpec` objects.
        clip_duration: Max per-clip duration. If None, reads from config.

    Returns:
        Total estimated duration in seconds.  Returns ``0.0`` for an empty
        list.
    """
    total = 0.0
    for scene in scenes:
        if scene.narration:
            total += estimate_scene_duration(scene.narration, clip_duration=clip_duration)
        else:
            total += scene.duration
    return total


# ─── Duration distribution ───────────────────────────────────────────────────


# ─── Expand scenes that exceed clip duration ─────────────────────────────────


def expand_scene_specs(
    scenes: list[SceneSpec],
    clip_duration: float | None = None,
) -> list[SceneSpec]:
    """Expand a list of SceneSpecs, splitting any that exceed clip_duration.

    Scenes whose narration would take longer than clip_duration are split into
    multiple sub-scenes (each with narration fitting within clip_duration).
    Scenes without narration that exceed clip_duration are clamped to
    clip_duration.

    The returned list has corrected ``order`` values (0-based, contiguous).

    Args:
        scenes:        Original scene list from an adapter.
        clip_duration: Max seconds per clip. If None, reads from config.

    Returns:
        Expanded list of SceneSpec with all durations ≤ clip_duration.
    """
    max_dur = get_max_scene_duration(clip_duration)
    expanded: list[SceneSpec] = []

    for scene in scenes:
        if scene.narration:
            chunks = split_long_narration(
                narration=scene.narration,
                prompt=scene.prompt,
                clip_duration=clip_duration,
            )
            for chunk in chunks:
                expanded.append(SceneSpec(
                    order=0,  # will be reindexed below
                    prompt=chunk["prompt"],
                    duration=chunk["duration"],
                    start_image=scene.start_image,
                    location_hint=scene.location_hint,
                    narration=chunk["narration"] if chunk["narration"] else None,
                ))
        else:
            # No narration — clamp duration to clip_duration
            clamped_dur = min(scene.duration, max_dur)
            clamped_dur = max(MIN_DURATION, clamped_dur)
            expanded.append(SceneSpec(
                order=0,
                prompt=scene.prompt,
                duration=clamped_dur,
                start_image=scene.start_image,
                location_hint=scene.location_hint,
                narration=None,
            ))

    # Reindex order
    for i, s in enumerate(expanded):
        s.order = i

    return expanded


# ─── Duration distribution ───────────────────────────────────────────────────


def distribute_duration(
    total_duration: float,
    n_scenes: int,
    min_duration: float = MIN_DURATION,
    max_duration: float | None = None,
) -> list[float]:
    """Distribute *total_duration* evenly across *n_scenes*.

    Each scene receives an equal share of the total, clamped to
    ``[min_duration, max_duration]``.  If the even share falls below
    *min_duration*, all scenes get *min_duration*.  If it exceeds
    *max_duration*, all scenes get *max_duration*.

    Args:
        total_duration: Total video duration in seconds.
        n_scenes:       Number of scenes to distribute across.
        min_duration:   Minimum duration per scene (default 3.0 s).
        max_duration:   Maximum duration per scene. If None, reads from
                        config (default: clip_duration = 8.0 s).

    Returns:
        List of *n_scenes* floats, each clamped to
        ``[min_duration, max_duration]``.

    Raises:
        ValueError: If *n_scenes* is less than 1.

    Example::

        >>> distribute_duration(40.0, 5)
        [8.0, 8.0, 8.0, 8.0, 8.0]
    """
    if n_scenes < 1:
        raise ValueError(f"n_scenes must be >= 1, got {n_scenes}")

    if max_duration is None:
        max_duration = get_max_scene_duration()

    per_scene = total_duration / n_scenes
    clamped = max(min_duration, min(max_duration, per_scene))
    return [clamped] * n_scenes
