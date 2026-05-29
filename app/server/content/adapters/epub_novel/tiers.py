"""3-tier processing mode for the epub-novel adapter.

Tier 1 — direct
    Short novels (≤ TIER1_MAX_WORDS words total) are processed in a single
    pass.  All chapters are concatenated and chunked into scenes.  Returns a
    single :class:`~server.content.base.SceneList`.

Tier 2 — episode
    Long novels (> TIER1_MAX_WORDS words) are automatically split into
    episodes.  Each episode covers a contiguous range of chapters whose
    combined word count stays within EPISODE_MAX_WORDS.  Returns an
    :class:`EpisodeList`.

Tier 3 — manual range
    The user explicitly selects a chapter range (``chapter_start`` /
    ``chapter_end`` indices, 0-based inclusive).  Only that range is
    processed.  Returns a single :class:`~server.content.base.SceneList`.

All three tiers share the same scene-building logic: each chapter becomes
one or more :class:`~server.content.base.SceneSpec` objects whose narration
is the chapter text and whose prompt is derived from the chapter title.

Usage::

    from server.content.adapters.epub_novel.tiers import (
        classify_tier,
        process_tier1,
        process_tier2,
        process_tier3,
        EpisodeList,
        ProcessingTier,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from server.content.base import AdapterError, SceneList, SceneSpec
from server.content.duration_estimator import estimate_scene_duration
from server.content.epub.parser import EpubBook, EpubChapter
from server.content.llm_chunking import chunk_by_paragraphs

logger = logging.getLogger(__name__)

# ─── Thresholds ───────────────────────────────────────────────────────────────

#: Maximum total word count for Tier 1 (direct) processing.
#: Novels with more words are routed to Tier 2 (episode) by default.
TIER1_MAX_WORDS: int = 15_000

#: Target maximum word count per episode in Tier 2.
#: Episodes are filled greedily until adding the next chapter would exceed
#: this limit.
EPISODE_MAX_WORDS: int = 10_000

#: Maximum number of scenes generated per chapter.
#: Longer chapters are split into multiple scenes using paragraph chunking.
MAX_SCENES_PER_CHAPTER: int = 5

#: Default scene duration when narration is empty.
_DEFAULT_DURATION: float = 8.0


# ─── Enums / data classes ─────────────────────────────────────────────────────


class ProcessingTier(str, Enum):
    """The three processing tiers for EPUB novels."""

    DIRECT = "direct"    # Tier 1 — short novel, single pass
    EPISODE = "episode"  # Tier 2 — long novel, auto-split
    MANUAL = "manual"    # Tier 3 — user-selected chapter range


@dataclass
class EpisodeList:
    """Output for long-form EPUB processing: one input → many SceneLists.

    Each element of *episodes* is a :class:`~server.content.base.SceneList`
    covering a contiguous range of chapters.

    Attributes:
        project_title: Title of the source EPUB book.
        episodes:      Ordered list of per-episode SceneLists.
        metadata:      Adapter-specific metadata (free-form dict).
    """

    project_title: str
    episodes: list[SceneList]
    metadata: dict = field(default_factory=dict)

    @property
    def episode_count(self) -> int:
        """Number of episodes."""
        return len(self.episodes)

    @property
    def total_scenes(self) -> int:
        """Total number of scenes across all episodes."""
        return sum(len(ep.scenes) for ep in self.episodes)


# ─── Tier classification ──────────────────────────────────────────────────────


def classify_tier(
    book: EpubBook,
    *,
    chapter_start: Optional[int] = None,
    chapter_end: Optional[int] = None,
    force_tier: Optional[ProcessingTier] = None,
) -> ProcessingTier:
    """Determine which processing tier to use for *book*.

    Decision logic:
    1. If *force_tier* is provided, return it immediately.
    2. If *chapter_start* or *chapter_end* is provided, return
       :attr:`ProcessingTier.MANUAL` (Tier 3).
    3. If ``book.total_words <= TIER1_MAX_WORDS``, return
       :attr:`ProcessingTier.DIRECT` (Tier 1).
    4. Otherwise return :attr:`ProcessingTier.EPISODE` (Tier 2).

    Args:
        book:          Parsed :class:`~server.content.epub.parser.EpubBook`.
        chapter_start: Optional 0-based start chapter index (Tier 3 signal).
        chapter_end:   Optional 0-based end chapter index (Tier 3 signal).
        force_tier:    Override the automatic classification.

    Returns:
        The :class:`ProcessingTier` to use.
    """
    if force_tier is not None:
        return force_tier

    if chapter_start is not None or chapter_end is not None:
        return ProcessingTier.MANUAL

    if book.total_words <= TIER1_MAX_WORDS:
        return ProcessingTier.DIRECT

    return ProcessingTier.EPISODE


# ─── Scene building helpers ───────────────────────────────────────────────────


def _chapter_to_scenes(
    chapter: EpubChapter,
    scene_offset: int,
) -> list[SceneSpec]:
    """Convert a single chapter into one or more :class:`SceneSpec` objects.

    Short chapters (≤ 500 chars) become a single scene.  Longer chapters are
    split into paragraph-based chunks (up to :data:`MAX_SCENES_PER_CHAPTER`).

    Args:
        chapter:      The chapter to convert.
        scene_offset: The ``order`` value for the first scene produced.

    Returns:
        List of :class:`SceneSpec` objects (at least one).
    """
    text = chapter.text.strip()
    if not text:
        # Empty chapter — produce a placeholder scene.
        return [
            SceneSpec(
                order=scene_offset,
                prompt=chapter.title or f"Chapter {chapter.order + 1}",
                duration=_DEFAULT_DURATION,
                narration=None,
            )
        ]

    # Split long chapters into paragraph chunks.
    if len(text) > 500:
        chunks = chunk_by_paragraphs(text, max_paragraphs_per_chunk=3)
        # Limit to MAX_SCENES_PER_CHAPTER
        chunks = chunks[:MAX_SCENES_PER_CHAPTER]
    else:
        chunks = [text]

    scenes: list[SceneSpec] = []
    for i, chunk in enumerate(chunks):
        # Build a visual prompt from the chapter title + chunk index.
        if i == 0:
            prompt = chapter.title or f"Chapter {chapter.order + 1}"
        else:
            prompt = f"{chapter.title or f'Chapter {chapter.order + 1}'} (part {i + 1})"

        duration = estimate_scene_duration(chunk)

        scenes.append(
            SceneSpec(
                order=scene_offset + i,
                prompt=prompt,
                duration=duration,
                narration=chunk,
            )
        )

    return scenes


def _chapters_to_scene_list(
    chapters: list[EpubChapter],
    project_id: str,
    voice: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> SceneList:
    """Build a :class:`SceneList` from a list of chapters.

    Args:
        chapters:   Chapters to include (must be non-empty).
        project_id: Identifier for the owning project.
        voice:      Optional TTS voice preference.
        metadata:   Optional extra metadata dict.

    Returns:
        A validated :class:`SceneList`.

    Raises:
        :class:`~server.content.base.AdapterError`: If no scenes are produced
            or the resulting SceneList fails validation.
    """
    if not chapters:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "Cannot build SceneList from empty chapter list.",
        )

    scenes: list[SceneSpec] = []
    offset = 0
    for chapter in chapters:
        new_scenes = _chapter_to_scenes(chapter, scene_offset=offset)
        scenes.extend(new_scenes)
        offset += len(new_scenes)

    scene_list = SceneList(
        project_id=project_id,
        scenes=scenes,
        voice=voice,
        metadata=metadata or {},
    )

    ok, errors = scene_list.validate()
    if not ok:
        raise AdapterError(
            "ADAPTER_INVALID_OUTPUT",
            f"Generated SceneList failed validation: {'; '.join(errors)}",
            details={"errors": errors},
        )

    return scene_list


# ─── Tier 1 — direct ─────────────────────────────────────────────────────────


def process_tier1(
    book: EpubBook,
    project_id: str,
    voice: Optional[str] = None,
) -> SceneList:
    """Tier 1 — direct processing for short novels.

    All chapters are processed in a single pass.  The result is a single
    :class:`~server.content.base.SceneList` covering the entire book.

    Args:
        book:       Parsed :class:`~server.content.epub.parser.EpubBook`.
        project_id: Identifier for the owning project.
        voice:      Optional TTS voice preference.

    Returns:
        A :class:`~server.content.base.SceneList` with all scenes.

    Raises:
        :class:`~server.content.base.AdapterError`: If the book has no
            chapters or scene generation fails.
    """
    if not book.chapters:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "EPUB book has no chapters.",
        )

    logger.debug(
        "Tier 1 (direct): processing %d chapters, %d words",
        len(book.chapters),
        book.total_words,
    )

    return _chapters_to_scene_list(
        chapters=book.chapters,
        project_id=project_id,
        voice=voice,
        metadata={
            "tier": ProcessingTier.DIRECT.value,
            "book_title": book.title,
            "book_author": book.author,
            "chapter_count": len(book.chapters),
            "total_words": book.total_words,
        },
    )


# ─── Tier 2 — episode ────────────────────────────────────────────────────────


def _split_into_episodes(
    chapters: list[EpubChapter],
    episode_max_words: int = EPISODE_MAX_WORDS,
) -> list[list[EpubChapter]]:
    """Greedily group chapters into episodes by word count.

    Each episode accumulates chapters until adding the next chapter would
    exceed *episode_max_words*.  A single chapter that exceeds the limit on
    its own is placed in its own episode.

    Args:
        chapters:          Ordered list of chapters.
        episode_max_words: Maximum word count per episode.

    Returns:
        List of chapter groups (each group is a list of chapters).
    """
    if not chapters:
        return []

    episodes: list[list[EpubChapter]] = []
    current_group: list[EpubChapter] = []
    current_words = 0

    for chapter in chapters:
        if current_group and current_words + chapter.word_count > episode_max_words:
            # Flush current group and start a new one.
            episodes.append(current_group)
            current_group = [chapter]
            current_words = chapter.word_count
        else:
            current_group.append(chapter)
            current_words += chapter.word_count

    if current_group:
        episodes.append(current_group)

    return episodes


def process_tier2(
    book: EpubBook,
    project_id: str,
    voice: Optional[str] = None,
    episode_max_words: int = EPISODE_MAX_WORDS,
) -> EpisodeList:
    """Tier 2 — episode processing for long novels.

    Chapters are automatically grouped into episodes based on word count.
    Each episode becomes a separate :class:`~server.content.base.SceneList`.

    Args:
        book:              Parsed :class:`~server.content.epub.parser.EpubBook`.
        project_id:        Identifier for the owning project.
        voice:             Optional TTS voice preference.
        episode_max_words: Maximum word count per episode (default
                           :data:`EPISODE_MAX_WORDS`).

    Returns:
        An :class:`EpisodeList` with one SceneList per episode.

    Raises:
        :class:`~server.content.base.AdapterError`: If the book has no
            chapters or episode generation fails.
    """
    if not book.chapters:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "EPUB book has no chapters.",
        )

    episode_groups = _split_into_episodes(book.chapters, episode_max_words)

    logger.debug(
        "Tier 2 (episode): %d chapters → %d episodes",
        len(book.chapters),
        len(episode_groups),
    )

    episodes: list[SceneList] = []
    for ep_idx, group in enumerate(episode_groups):
        ep_project_id = f"{project_id}_ep{ep_idx + 1:02d}"
        scene_list = _chapters_to_scene_list(
            chapters=group,
            project_id=ep_project_id,
            voice=voice,
            metadata={
                "tier": ProcessingTier.EPISODE.value,
                "book_title": book.title,
                "book_author": book.author,
                "episode_index": ep_idx,
                "episode_number": ep_idx + 1,
                "chapter_start": group[0].order,
                "chapter_end": group[-1].order,
                "chapter_count": len(group),
                "episode_words": sum(ch.word_count for ch in group),
            },
        )
        episodes.append(scene_list)

    return EpisodeList(
        project_title=book.title,
        episodes=episodes,
        metadata={
            "tier": ProcessingTier.EPISODE.value,
            "book_title": book.title,
            "book_author": book.author,
            "total_chapters": len(book.chapters),
            "total_words": book.total_words,
            "episode_count": len(episodes),
            "episode_max_words": episode_max_words,
        },
    )


# ─── Tier 3 — manual range ───────────────────────────────────────────────────


def process_tier3(
    book: EpubBook,
    project_id: str,
    chapter_start: int,
    chapter_end: int,
    voice: Optional[str] = None,
) -> SceneList:
    """Tier 3 — manual range processing.

    Only the chapters in the range ``[chapter_start, chapter_end]`` (both
    inclusive, 0-based) are processed.

    Args:
        book:          Parsed :class:`~server.content.epub.parser.EpubBook`.
        project_id:    Identifier for the owning project.
        chapter_start: 0-based index of the first chapter to include.
        chapter_end:   0-based index of the last chapter to include
                       (inclusive).
        voice:         Optional TTS voice preference.

    Returns:
        A :class:`~server.content.base.SceneList` covering the selected
        chapter range.

    Raises:
        :class:`~server.content.base.AdapterError`: On invalid range or if
            no chapters fall within the range.
    """
    n_chapters = len(book.chapters)

    # Validate range
    if chapter_start < 0:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"chapter_start must be >= 0, got {chapter_start}.",
        )
    if chapter_end < chapter_start:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"chapter_end ({chapter_end}) must be >= chapter_start ({chapter_start}).",
        )
    if chapter_start >= n_chapters:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"chapter_start ({chapter_start}) is out of range "
            f"(book has {n_chapters} chapters, indices 0–{n_chapters - 1}).",
        )

    # Clamp chapter_end to the last available chapter.
    effective_end = min(chapter_end, n_chapters - 1)
    if effective_end < chapter_end:
        logger.warning(
            "Tier 3: chapter_end %d clamped to %d (book has %d chapters)",
            chapter_end,
            effective_end,
            n_chapters,
        )

    selected = book.chapters[chapter_start : effective_end + 1]

    if not selected:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"No chapters found in range [{chapter_start}, {effective_end}].",
        )

    logger.debug(
        "Tier 3 (manual): chapters %d–%d (%d chapters, %d words)",
        chapter_start,
        effective_end,
        len(selected),
        sum(ch.word_count for ch in selected),
    )

    return _chapters_to_scene_list(
        chapters=selected,
        project_id=project_id,
        voice=voice,
        metadata={
            "tier": ProcessingTier.MANUAL.value,
            "book_title": book.title,
            "book_author": book.author,
            "chapter_start": chapter_start,
            "chapter_end": effective_end,
            "chapter_count": len(selected),
            "range_words": sum(ch.word_count for ch in selected),
        },
    )
