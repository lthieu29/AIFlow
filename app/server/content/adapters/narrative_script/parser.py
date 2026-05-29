"""Markdown parser for narrative script input.

Parses a markdown vlog/narrative script into a list of :class:`NarrativeScene`
objects.  Each H2 heading (``## Scene Title``) defines a scene boundary.

Parsing rules:
- ``## Heading`` → new scene, heading becomes the scene title.
- Body text under the heading → scene description / visual prompt.
- ``**Narration:** text`` or ``> blockquote text`` → narration for the scene.
- ``**Location:** value`` → sets ``location_hint`` for the scene.
- If no H2 headings are found, the text is split by paragraphs (fallback).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Data class ──────────────────────────────────────────────────────────────


@dataclass
class NarrativeScene:
    """A single scene parsed from a markdown narrative script.

    Attributes:
        order:         0-based position in the scene list.
        heading:       Scene title (from H2 heading, or auto-generated).
        body:          Scene description / visual context text.
        narration:     TTS narration text for this scene.
        location_hint: Optional location hint (from ``**Location:**`` tag).
    """

    order: int
    heading: str
    body: str
    narration: str
    location_hint: Optional[str] = None


# ─── Regex patterns ───────────────────────────────────────────────────────────

# H2 heading: ## Title
_H2_RE = re.compile(r'^##\s+(.+)$', re.MULTILINE)

# Narration block: **Narration:** text (rest of line)
_NARRATION_BOLD_RE = re.compile(
    r'^\*\*Narration:\*\*\s*(.+)$',
    re.MULTILINE | re.IGNORECASE,
)

# Blockquote narration: > text (one or more lines)
_BLOCKQUOTE_RE = re.compile(r'^>\s*(.+)$', re.MULTILINE)

# Location tag: **Location:** value
_LOCATION_RE = re.compile(
    r'^\*\*Location:\*\*\s*(.+)$',
    re.MULTILINE | re.IGNORECASE,
)

# Lines to strip from body (narration markers, location tags, blockquotes)
_STRIP_FROM_BODY_RE = re.compile(
    r'(^\*\*Narration:\*\*.*$|^\*\*Location:\*\*.*$|^>.*$)',
    re.MULTILINE | re.IGNORECASE,
)

# Markdown bold/italic markers for cleaning body text
_MARKDOWN_INLINE_RE = re.compile(r'\*{1,3}([^*]+)\*{1,3}')


# ─── Public API ───────────────────────────────────────────────────────────────


def parse_markdown_script(markdown: str) -> list[NarrativeScene]:
    """Parse a markdown narrative script into a list of :class:`NarrativeScene`.

    Scenes are delimited by H2 headings (``## Title``).  If no H2 headings
    are found, the text is split by paragraphs as a fallback.

    Args:
        markdown: Raw markdown string.

    Returns:
        List of :class:`NarrativeScene` objects, ordered by appearance.
        Returns an empty list if *markdown* is empty or whitespace-only.
    """
    if not markdown or not markdown.strip():
        return []

    # Check for H2 headings
    h2_matches = list(_H2_RE.finditer(markdown))

    if h2_matches:
        return _parse_by_headings(markdown, h2_matches)
    else:
        return _parse_by_paragraphs(markdown)


def extract_location_hint(text: str) -> Optional[str]:
    """Extract a location hint from *text*.

    Looks for a ``**Location:** value`` tag.  Returns the value stripped of
    whitespace, or ``None`` if not found.

    Args:
        text: Text to search in.

    Returns:
        Location hint string, or ``None``.
    """
    match = _LOCATION_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


# ─── Private helpers ──────────────────────────────────────────────────────────


def _parse_by_headings(
    markdown: str,
    h2_matches: list[re.Match],
) -> list[NarrativeScene]:
    """Parse markdown into scenes using H2 headings as boundaries."""
    scenes: list[NarrativeScene] = []

    for idx, match in enumerate(h2_matches):
        heading = match.group(1).strip()

        # Determine the text block for this scene
        start = match.end()
        end = h2_matches[idx + 1].start() if idx + 1 < len(h2_matches) else len(markdown)
        block = markdown[start:end]

        narration = _extract_narration(block)
        location_hint = extract_location_hint(block)
        body = _clean_body(block)

        scenes.append(
            NarrativeScene(
                order=idx,
                heading=heading,
                body=body,
                narration=narration,
                location_hint=location_hint,
            )
        )

    return scenes


def _parse_by_paragraphs(markdown: str) -> list[NarrativeScene]:
    """Fallback: split markdown by blank lines into paragraph-based scenes."""
    from server.content.llm_chunking import chunk_by_paragraphs

    paragraphs = chunk_by_paragraphs(markdown, max_paragraphs_per_chunk=1)
    scenes: list[NarrativeScene] = []

    for idx, para in enumerate(paragraphs):
        narration = _extract_narration(para)
        location_hint = extract_location_hint(para)
        body = _clean_body(para)

        # Use first sentence as heading if no explicit heading
        heading = _first_sentence(body) or f"Scene {idx + 1}"

        scenes.append(
            NarrativeScene(
                order=idx,
                heading=heading,
                body=body,
                narration=narration,
                location_hint=location_hint,
            )
        )

    return scenes


def _extract_narration(block: str) -> str:
    """Extract narration text from a scene block.

    Priority:
    1. ``**Narration:** text`` lines (joined).
    2. ``> blockquote`` lines (joined).
    3. Falls back to the cleaned body text itself.

    Args:
        block: Raw text block for a single scene.

    Returns:
        Narration string (may be empty if block is empty).
    """
    # Try **Narration:** tags first
    bold_matches = _NARRATION_BOLD_RE.findall(block)
    if bold_matches:
        return " ".join(m.strip() for m in bold_matches)

    # Try blockquote lines
    bq_matches = _BLOCKQUOTE_RE.findall(block)
    if bq_matches:
        return " ".join(m.strip() for m in bq_matches)

    # Fallback: use cleaned body text as narration
    return _clean_body(block)


def _clean_body(block: str) -> str:
    """Remove narration markers, location tags, and blockquotes from *block*.

    Returns the remaining text stripped of leading/trailing whitespace.
    """
    cleaned = _STRIP_FROM_BODY_RE.sub('', block)
    # Collapse multiple blank lines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def _first_sentence(text: str) -> str:
    """Return the first sentence of *text* (up to 80 chars), or the full text."""
    if not text:
        return ""
    # Split on sentence-ending punctuation
    match = re.search(r'[.!?]', text)
    if match:
        sentence = text[: match.start() + 1].strip()
    else:
        sentence = text.strip()
    # Truncate to 80 chars
    if len(sentence) > 80:
        sentence = sentence[:77].rstrip() + "..."
    return sentence
