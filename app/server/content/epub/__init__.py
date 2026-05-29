"""EPUB content adapter package.

Provides EPUB parsing utilities for extracting chapters and characters
from EPUB files for use in the AIFlow pipeline.

Public API::

    from server.content.epub import parse_epub, extract_characters
    from server.content.epub import EpubBook, EpubChapter, EpubParseError
"""

from server.content.epub.parser import (
    EpubBook,
    EpubChapter,
    EpubParseError,
    extract_characters,
    extract_text_from_html,
    parse_epub,
)

__all__ = [
    "EpubBook",
    "EpubChapter",
    "EpubParseError",
    "extract_characters",
    "extract_text_from_html",
    "parse_epub",
]
