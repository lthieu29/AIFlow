"""EPUB parser for AIFlow content pipeline.

Parses EPUB files into structured chapter data and extracts character names
for use in the video generation pipeline.

Usage::

    from pathlib import Path
    from server.content.epub.parser import parse_epub, extract_characters

    book = parse_epub(Path("novel.epub"))
    characters = extract_characters(book)
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import ebooklib
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from ebooklib import epub

# Suppress the XMLParsedAsHTMLWarning that ebooklib XHTML triggers with lxml.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from server.content.character_dedup import (
    CharacterRef,
    dedup_characters,
    extract_character_names,
)


# ─── Exceptions ──────────────────────────────────────────────────────────────


class EpubParseError(Exception):
    """Raised when an EPUB file cannot be parsed.

    Attributes:
        message: Human-readable description of the error.
        path:    Optional path to the EPUB file that caused the error.
    """

    def __init__(self, message: str, path: Optional[Path] = None) -> None:
        self.message = message
        self.path = path
        super().__init__(message)

    def __repr__(self) -> str:  # pragma: no cover
        return f"EpubParseError(message={self.message!r}, path={self.path!r})"


# ─── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class EpubChapter:
    """A single chapter extracted from an EPUB file.

    Attributes:
        title:      Chapter title (from heading or TOC).
        order:      0-based position in the book spine.
        text:       Plain text content (HTML tags stripped).
        word_count: Number of whitespace-separated words in *text*.
    """

    title: str
    order: int
    text: str
    word_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.text.split()) if self.text.strip() else 0


@dataclass
class EpubBook:
    """Parsed representation of an EPUB file.

    Attributes:
        title:       Book title from EPUB metadata.
        author:      Primary author from EPUB metadata.
        chapters:    Ordered list of chapters extracted from the spine.
        total_words: Sum of word counts across all chapters.
    """

    title: str
    author: str
    chapters: list[EpubChapter]
    total_words: int = field(init=False)

    def __post_init__(self) -> None:
        self.total_words = sum(ch.word_count for ch in self.chapters)


# ─── HTML utilities ───────────────────────────────────────────────────────────


def extract_text_from_html(html_content: str) -> str:
    """Strip HTML tags and return plain text.

    Converts block-level elements (p, div, br, h1-h6, li) to newlines
    before stripping tags so that words from adjacent elements are not
    concatenated.

    Args:
        html_content: Raw HTML string.

    Returns:
        Plain text with normalised whitespace.  Multiple blank lines are
        collapsed to a single blank line.

    Example::

        >>> extract_text_from_html("<p>Hello</p><p>World</p>")
        'Hello\\n\\nWorld'
    """
    if not html_content or not html_content.strip():
        return ""

    soup = BeautifulSoup(html_content, "lxml")

    # Insert newlines before block-level elements so words don't run together.
    for tag in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
        tag.insert_before("\n\n")

    for br in soup.find_all("br"):
        br.replace_with("\n")

    text = soup.get_text()

    # Normalise: collapse runs of blank lines to a single blank line.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def detect_chapter_title(html_content: str) -> str:
    """Extract a chapter title from HTML content.

    Tries the following strategies in order:
    1. First ``<h1>`` element.
    2. First ``<h2>`` element.
    3. First non-empty line of plain text (truncated to 80 chars).

    Args:
        html_content: Raw HTML string for a single chapter/document.

    Returns:
        Detected title string, or an empty string if nothing is found.
    """
    if not html_content or not html_content.strip():
        return ""

    soup = BeautifulSoup(html_content, "lxml")

    # Try H1 first, then H2.
    for tag_name in ("h1", "h2"):
        heading = soup.find(tag_name)
        if heading:
            title = heading.get_text(separator=" ", strip=True)
            if title:
                return title

    # Fall back to first non-empty line of plain text.
    text = extract_text_from_html(html_content)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]

    return ""


# ─── EPUB parsing ─────────────────────────────────────────────────────────────


def _get_toc_titles(book: epub.EpubBook) -> dict[str, str]:
    """Build a mapping from spine item IDs / hrefs to TOC titles.

    Walks the EPUB TOC recursively and maps each link href (without fragment)
    to its label.

    Args:
        book: Parsed ``ebooklib.epub.EpubBook`` object.

    Returns:
        Dict mapping ``item.file_name`` → title string.
    """
    titles: dict[str, str] = {}

    def _walk(items: object) -> None:
        # Normalise: a single item (not a list) is wrapped in a list.
        if not isinstance(items, (list, tuple)):
            items = [items]

        for item in items:
            if isinstance(item, epub.Link):
                # href may contain a fragment (#section-id); strip it.
                href = item.href.split("#")[0]
                if href and item.title:
                    titles[href] = item.title
            elif isinstance(item, tuple) and len(item) == 2:
                # (Section, [children]) tuple
                section, children = item
                if isinstance(section, epub.Link) and section.href and section.title:
                    href = section.href.split("#")[0]
                    titles[href] = section.title
                _walk(children)

    _walk(book.toc)
    return titles


def parse_epub(epub_path: Path) -> EpubBook:
    """Parse an EPUB file and return a structured :class:`EpubBook`.

    Reads the EPUB spine in order, extracts plain text from each HTML
    document, and detects chapter titles from headings or the TOC.
    Spine items that contain no readable text are skipped (e.g. cover
    images, CSS-only documents).

    Args:
        epub_path: Path to the ``.epub`` file.

    Returns:
        :class:`EpubBook` with ordered chapters.

    Raises:
        :class:`EpubParseError`: If the file does not exist, cannot be read,
            or contains no readable chapters.
    """
    if not epub_path.exists():
        raise EpubParseError(f"File not found: {epub_path}", path=epub_path)

    try:
        book = epub.read_epub(str(epub_path), options={"ignore_ncx": False})
    except Exception as exc:
        raise EpubParseError(
            f"Failed to read EPUB: {exc}", path=epub_path
        ) from exc

    # Extract metadata.
    raw_title = book.get_metadata("DC", "title")
    title = raw_title[0][0] if raw_title else epub_path.stem

    raw_author = book.get_metadata("DC", "creator")
    author = raw_author[0][0] if raw_author else "Unknown"

    # Build TOC title map for fallback title detection.
    toc_titles = _get_toc_titles(book)

    chapters: list[EpubChapter] = []
    order = 0

    for spine_id, _linear in book.spine:
        item = book.get_item_with_id(spine_id)
        if item is None:
            continue
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        # Skip navigation documents (nav.xhtml, toc.ncx) — they contain
        # structural text (book title, chapter list) that is not content.
        if isinstance(item, epub.EpubNav):
            continue

        try:
            html_bytes = item.get_content()
            html_content = html_bytes.decode("utf-8", errors="replace")
        except Exception:
            continue

        text = extract_text_from_html(html_content)
        if not text.strip():
            # Skip empty documents (cover, nav, etc.)
            continue

        # Determine chapter title: TOC → heading → first line.
        file_name = item.file_name
        if file_name in toc_titles:
            chapter_title = toc_titles[file_name]
        else:
            chapter_title = detect_chapter_title(html_content)
            if not chapter_title:
                chapter_title = f"Chapter {order + 1}"

        chapters.append(
            EpubChapter(
                title=chapter_title,
                order=order,
                text=text,
            )
        )
        order += 1

    if not chapters:
        raise EpubParseError(
            "No readable chapters found in EPUB", path=epub_path
        )

    return EpubBook(
        title=title,
        author=author,
        chapters=chapters,
    )


# ─── Character extraction ─────────────────────────────────────────────────────


def extract_characters(book: EpubBook) -> list[CharacterRef]:
    """Extract and deduplicate character names from an :class:`EpubBook`.

    Concatenates all chapter text, runs :func:`extract_character_names`
    to find candidate names, wraps them as :class:`CharacterRef` objects,
    then deduplicates with :func:`dedup_characters`.

    Args:
        book: Parsed :class:`EpubBook`.

    Returns:
        Deduplicated list of :class:`CharacterRef` objects, one per
        distinct character found in the text.
    """
    full_text = "\n\n".join(ch.text for ch in book.chapters)
    raw_names = extract_character_names(full_text)

    refs = [CharacterRef(name=name) for name in raw_names]
    return dedup_characters(refs)
