"""LLM-based text chunking utilities for content adapters.

Provides helpers to split long-form text into scene-sized chunks, either
via simple heuristics (sentence / paragraph boundaries) or via a Gemini
LLM call for smarter semantic splitting.

The LLM path gracefully falls back to sentence chunking when the Gemini
client is unavailable or returns an unusable response.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

#: Default target duration per scene used when estimating scene count.
_DEFAULT_TARGET_DURATION_PER_SCENE: float = 8.0

#: Approximate words per second for a typical narrator (150 wpm / 60).
_WORDS_PER_SECOND: float = 150.0 / 60.0


# ─── Data class ──────────────────────────────────────────────────────────────


@dataclass
class ChunkResult:
    """Result of a text chunking operation.

    Attributes:
        chunks:      List of text chunks (one per scene).
        scene_count: Number of chunks produced.
        total_chars: Total character count across all chunks.
    """

    chunks: list[str] = field(default_factory=list)
    scene_count: int = 0
    total_chars: int = 0

    def __post_init__(self) -> None:
        # Keep scene_count and total_chars consistent if not explicitly set.
        if not self.scene_count:
            self.scene_count = len(self.chunks)
        if not self.total_chars:
            self.total_chars = sum(len(c) for c in self.chunks)


# ─── Sentence-based chunking ─────────────────────────────────────────────────

# Sentence boundary: period / exclamation / question mark followed by
# whitespace or end-of-string.  Handles common abbreviations poorly but is
# good enough for narration text.
_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')


def chunk_by_sentences(
    text: str,
    max_chars_per_chunk: int = 500,
) -> list[str]:
    """Split *text* into chunks at sentence boundaries.

    Sentences are accumulated into a chunk until adding the next sentence
    would exceed *max_chars_per_chunk*.  A single sentence that is longer
    than the limit is placed in its own chunk.

    Args:
        text:               Input text to split.
        max_chars_per_chunk: Maximum character count per chunk.

    Returns:
        List of non-empty text chunks.
    """
    if not text or not text.strip():
        return []

    sentences = _SENTENCE_END_RE.split(text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for sentence in sentences:
        # +1 for the space separator between sentences
        added_len = len(sentence) + (1 if current_parts else 0)
        if current_parts and current_len + added_len > max_chars_per_chunk:
            chunks.append(" ".join(current_parts))
            current_parts = [sentence]
            current_len = len(sentence)
        else:
            current_parts.append(sentence)
            current_len += added_len

    if current_parts:
        chunks.append(" ".join(current_parts))

    return chunks


# ─── Paragraph-based chunking ────────────────────────────────────────────────


def chunk_by_paragraphs(
    text: str,
    max_paragraphs_per_chunk: int = 3,
) -> list[str]:
    """Split *text* into chunks at paragraph boundaries.

    Paragraphs are separated by one or more blank lines.  Up to
    *max_paragraphs_per_chunk* paragraphs are grouped into a single chunk.

    Args:
        text:                    Input text to split.
        max_paragraphs_per_chunk: Maximum number of paragraphs per chunk.

    Returns:
        List of non-empty text chunks.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]

    if not paragraphs:
        return []

    chunks: list[str] = []
    for i in range(0, len(paragraphs), max_paragraphs_per_chunk):
        group = paragraphs[i : i + max_paragraphs_per_chunk]
        chunks.append("\n\n".join(group))

    return chunks


# ─── Scene count estimation ──────────────────────────────────────────────────


def estimate_scene_count(
    text: str,
    target_duration_per_scene: float = _DEFAULT_TARGET_DURATION_PER_SCENE,
) -> int:
    """Estimate how many scenes a *text* needs.

    Uses word count and a fixed speaking rate to estimate total narration
    duration, then divides by *target_duration_per_scene*.

    Args:
        text:                    Input text.
        target_duration_per_scene: Target duration per scene in seconds.

    Returns:
        Estimated scene count (minimum 1).
    """
    if not text or not text.strip():
        return 1

    word_count = len(text.split())
    total_seconds = word_count / _WORDS_PER_SECOND
    count = max(1, round(total_seconds / target_duration_per_scene))
    return count


# ─── LLM-based chunking ──────────────────────────────────────────────────────

_LLM_CHUNK_PROMPT_TEMPLATE = """\
You are a video script editor. Split the following text into exactly {n_scenes} scenes for a short video.

Rules:
- Each scene should be a self-contained narrative unit.
- Preserve the original wording as much as possible.
- Return ONLY a JSON array of strings, one string per scene.
- Do not add any explanation or markdown formatting.

Text to split:
\"\"\"
{text}
\"\"\"

Return JSON array with exactly {n_scenes} elements:"""


async def llm_chunk_to_scenes(
    text: str,
    gemini_client,
    n_scenes: int = 5,
) -> ChunkResult:
    """Use Gemini to intelligently chunk *text* into *n_scenes* scenes.

    Sends a structured prompt to the Gemini client asking it to split the
    text into exactly *n_scenes* chunks.  If the LLM call fails or returns
    an unparseable response, falls back to :func:`chunk_by_sentences`.

    Args:
        text:          Input text to chunk.
        gemini_client: A :class:`~server.ai.gemini.GeminiClient` instance
                       (or any object with a ``generate_text(prompt) -> str``
                       method).
        n_scenes:      Desired number of output scenes.

    Returns:
        A :class:`ChunkResult` with the chunks and metadata.
    """
    if not text or not text.strip():
        return ChunkResult(chunks=[], scene_count=0, total_chars=0)

    # Try LLM path first.
    if gemini_client is not None:
        try:
            prompt = _LLM_CHUNK_PROMPT_TEMPLATE.format(
                n_scenes=n_scenes,
                text=text.strip(),
            )
            raw_response = gemini_client.generate_text(prompt)
            chunks = _parse_llm_chunks(raw_response, n_scenes)
            if chunks:
                return ChunkResult(
                    chunks=chunks,
                    scene_count=len(chunks),
                    total_chars=sum(len(c) for c in chunks),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM chunking failed (%s), falling back to sentence chunking.",
                exc,
            )

    # Fallback: sentence-based chunking.
    logger.debug("Using sentence-based fallback chunking for %d scenes.", n_scenes)
    fallback_chunks = _sentence_fallback(text, n_scenes)
    return ChunkResult(
        chunks=fallback_chunks,
        scene_count=len(fallback_chunks),
        total_chars=sum(len(c) for c in fallback_chunks),
    )


def _parse_llm_chunks(response: str, expected_n: int) -> list[str]:
    """Parse a JSON array of strings from the LLM response.

    Returns an empty list if parsing fails or the result is not a list of
    strings with at least one element.
    """
    if not response:
        return []

    # Strip markdown code fences if present.
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last fence lines.
        inner = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
        cleaned = "\n".join(inner).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to extract a JSON array from somewhere in the response.
        match = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

    if not isinstance(parsed, list):
        return []

    chunks = [str(item).strip() for item in parsed if str(item).strip()]
    return chunks if chunks else []


def _sentence_fallback(text: str, n_scenes: int) -> list[str]:
    """Split *text* into approximately *n_scenes* chunks using sentences."""
    # Estimate chars per chunk based on total length.
    total_chars = len(text.strip())
    max_chars = max(50, total_chars // max(1, n_scenes))
    chunks = chunk_by_sentences(text, max_chars_per_chunk=max_chars)

    if not chunks:
        return [text.strip()]

    # If we got more chunks than needed, merge the excess.
    while len(chunks) > n_scenes and len(chunks) > 1:
        # Merge the two shortest adjacent chunks.
        min_len = min(len(chunks[i]) + len(chunks[i + 1]) for i in range(len(chunks) - 1))
        for i in range(len(chunks) - 1):
            if len(chunks[i]) + len(chunks[i + 1]) == min_len:
                chunks[i] = chunks[i] + " " + chunks[i + 1]
                del chunks[i + 1]
                break

    return chunks
