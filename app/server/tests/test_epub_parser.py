"""Unit tests for Task 6.1 — EPUB parser.

Covers:
- extract_text_from_html: HTML stripping, block element newlines, empty input
- detect_chapter_title: H1, H2, first-line fallback, empty input
- parse_epub: metadata extraction, chapter ordering, title detection,
              TOC title lookup, empty-document skipping, missing file error,
              no-chapters error
- extract_characters: name extraction and deduplication from book text
- EpubChapter: word_count auto-calculation
- EpubBook: total_words auto-calculation
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_epub(
    title: str = "Test Book",
    author: str = "Test Author",
    chapters: list[tuple[str, str, str]] | None = None,
    *,
    include_nav: bool = True,
) -> Path:
    """Create a minimal EPUB file in a temp directory and return its path.

    Args:
        title:    Book title.
        author:   Book author.
        chapters: List of (file_name, chapter_title, html_body) tuples.
                  Defaults to a single chapter with basic content.
        include_nav: Whether to include the nav/ncx items.

    Returns:
        Path to the written ``.epub`` file (caller must clean up).
    """
    from ebooklib import epub

    if chapters is None:
        chapters = [
            (
                "chap1.xhtml",
                "Chapter One",
                "<h1>Chapter One</h1><p>Hello world. This is the first chapter.</p>",
            )
        ]

    book = epub.EpubBook()
    book.set_title(title)
    book.add_author(author)

    epub_items = []
    toc_links = []

    for file_name, chap_title, body in chapters:
        item = epub.EpubHtml(
            title=chap_title,
            file_name=file_name,
            lang="en",
        )
        item.content = f"<html><body>{body}</body></html>"
        book.add_item(item)
        epub_items.append(item)
        toc_links.append(epub.Link(file_name, chap_title, file_name.replace(".", "_")))

    book.toc = tuple(toc_links)

    if include_nav:
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav"] + epub_items
    else:
        book.spine = epub_items

    tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    tmp.close()
    epub.write_epub(tmp.name, book)
    return Path(tmp.name)


# ═════════════════════════════════════════════════════════════════════════════
# extract_text_from_html
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractTextFromHtml:
    def test_empty_string_returns_empty(self):
        from server.content.epub.parser import extract_text_from_html

        assert extract_text_from_html("") == ""

    def test_whitespace_only_returns_empty(self):
        from server.content.epub.parser import extract_text_from_html

        assert extract_text_from_html("   \n  ") == ""

    def test_strips_simple_tags(self):
        from server.content.epub.parser import extract_text_from_html

        result = extract_text_from_html("<p>Hello world</p>")
        assert "Hello world" in result
        assert "<p>" not in result

    def test_paragraph_tags_produce_newlines(self):
        from server.content.epub.parser import extract_text_from_html

        result = extract_text_from_html("<p>First</p><p>Second</p>")
        assert "First" in result
        assert "Second" in result
        # They should be separated by whitespace/newlines, not concatenated
        assert "FirstSecond" not in result

    def test_heading_tags_produce_newlines(self):
        from server.content.epub.parser import extract_text_from_html

        result = extract_text_from_html("<h1>Title</h1><p>Body text.</p>")
        assert "Title" in result
        assert "Body text." in result

    def test_br_tag_produces_newline(self):
        from server.content.epub.parser import extract_text_from_html

        result = extract_text_from_html("Line one<br/>Line two")
        assert "Line one" in result
        assert "Line two" in result

    def test_nested_html_stripped(self):
        from server.content.epub.parser import extract_text_from_html

        html = "<div><p><strong>Bold</strong> and <em>italic</em></p></div>"
        result = extract_text_from_html(html)
        assert "Bold" in result
        assert "italic" in result
        assert "<" not in result

    def test_multiple_blank_lines_collapsed(self):
        from server.content.epub.parser import extract_text_from_html

        html = "<p>A</p><p></p><p></p><p>B</p>"
        result = extract_text_from_html(html)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result

    def test_full_html_document(self):
        from server.content.epub.parser import extract_text_from_html

        html = """
        <html>
          <head><title>Chapter</title></head>
          <body>
            <h1>Chapter One</h1>
            <p>The story begins here.</p>
            <p>It continues on the next paragraph.</p>
          </body>
        </html>
        """
        result = extract_text_from_html(html)
        assert "Chapter One" in result
        assert "The story begins here." in result
        assert "It continues on the next paragraph." in result


# ═════════════════════════════════════════════════════════════════════════════
# detect_chapter_title
# ═════════════════════════════════════════════════════════════════════════════


class TestDetectChapterTitle:
    def test_empty_string_returns_empty(self):
        from server.content.epub.parser import detect_chapter_title

        assert detect_chapter_title("") == ""

    def test_whitespace_only_returns_empty(self):
        from server.content.epub.parser import detect_chapter_title

        assert detect_chapter_title("   ") == ""

    def test_h1_heading_extracted(self):
        from server.content.epub.parser import detect_chapter_title

        html = "<html><body><h1>Chapter One</h1><p>Content.</p></body></html>"
        assert detect_chapter_title(html) == "Chapter One"

    def test_h2_heading_extracted_when_no_h1(self):
        from server.content.epub.parser import detect_chapter_title

        html = "<html><body><h2>Section Title</h2><p>Content.</p></body></html>"
        assert detect_chapter_title(html) == "Section Title"

    def test_h1_preferred_over_h2(self):
        from server.content.epub.parser import detect_chapter_title

        html = "<html><body><h1>Main Title</h1><h2>Sub Title</h2></body></html>"
        assert detect_chapter_title(html) == "Main Title"

    def test_first_line_fallback_when_no_heading(self):
        from server.content.epub.parser import detect_chapter_title

        html = "<html><body><p>First line of text.</p><p>Second line.</p></body></html>"
        result = detect_chapter_title(html)
        assert "First line of text." in result

    def test_title_truncated_to_80_chars(self):
        from server.content.epub.parser import detect_chapter_title

        long_text = "A" * 100
        html = f"<html><body><p>{long_text}</p></body></html>"
        result = detect_chapter_title(html)
        assert len(result) <= 80

    def test_heading_whitespace_stripped(self):
        from server.content.epub.parser import detect_chapter_title

        html = "<h1>  Spaced Title  </h1>"
        result = detect_chapter_title(html)
        assert result == "Spaced Title"


# ═════════════════════════════════════════════════════════════════════════════
# EpubChapter — word_count
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubChapter:
    def test_word_count_calculated_on_init(self):
        from server.content.epub.parser import EpubChapter

        ch = EpubChapter(title="Ch1", order=0, text="Hello world foo bar")
        assert ch.word_count == 4

    def test_word_count_empty_text(self):
        from server.content.epub.parser import EpubChapter

        ch = EpubChapter(title="Ch1", order=0, text="")
        assert ch.word_count == 0

    def test_word_count_whitespace_only(self):
        from server.content.epub.parser import EpubChapter

        ch = EpubChapter(title="Ch1", order=0, text="   \n  ")
        assert ch.word_count == 0

    def test_word_count_single_word(self):
        from server.content.epub.parser import EpubChapter

        ch = EpubChapter(title="Ch1", order=0, text="Hello")
        assert ch.word_count == 1


# ═════════════════════════════════════════════════════════════════════════════
# EpubBook — total_words
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubBook:
    def test_total_words_is_sum_of_chapters(self):
        from server.content.epub.parser import EpubBook, EpubChapter

        ch1 = EpubChapter(title="Ch1", order=0, text="one two three")
        ch2 = EpubChapter(title="Ch2", order=1, text="four five")
        book = EpubBook(title="T", author="A", chapters=[ch1, ch2])
        assert book.total_words == 5

    def test_total_words_empty_chapters(self):
        from server.content.epub.parser import EpubBook

        book = EpubBook(title="T", author="A", chapters=[])
        assert book.total_words == 0


# ═════════════════════════════════════════════════════════════════════════════
# parse_epub
# ═════════════════════════════════════════════════════════════════════════════


class TestParseEpub:
    def test_missing_file_raises_epub_parse_error(self):
        from server.content.epub.parser import EpubParseError, parse_epub

        with pytest.raises(EpubParseError) as exc_info:
            parse_epub(Path("/nonexistent/path/book.epub"))
        assert "not found" in exc_info.value.message.lower()

    def test_returns_epub_book_instance(self, tmp_path):
        from server.content.epub.parser import EpubBook, parse_epub

        epub_path = _make_epub()
        try:
            result = parse_epub(epub_path)
            assert isinstance(result, EpubBook)
        finally:
            epub_path.unlink(missing_ok=True)

    def test_title_extracted_from_metadata(self, tmp_path):
        from server.content.epub.parser import parse_epub

        epub_path = _make_epub(title="My Novel")
        try:
            result = parse_epub(epub_path)
            assert result.title == "My Novel"
        finally:
            epub_path.unlink(missing_ok=True)

    def test_author_extracted_from_metadata(self, tmp_path):
        from server.content.epub.parser import parse_epub

        epub_path = _make_epub(author="Jane Doe")
        try:
            result = parse_epub(epub_path)
            assert result.author == "Jane Doe"
        finally:
            epub_path.unlink(missing_ok=True)

    def test_single_chapter_parsed(self):
        from server.content.epub.parser import parse_epub

        epub_path = _make_epub()
        try:
            result = parse_epub(epub_path)
            assert len(result.chapters) == 1
        finally:
            epub_path.unlink(missing_ok=True)

    def test_multiple_chapters_parsed_in_order(self):
        from server.content.epub.parser import parse_epub

        chapters = [
            ("chap1.xhtml", "Chapter 1", "<h1>Chapter 1</h1><p>First chapter content.</p>"),
            ("chap2.xhtml", "Chapter 2", "<h1>Chapter 2</h1><p>Second chapter content.</p>"),
            ("chap3.xhtml", "Chapter 3", "<h1>Chapter 3</h1><p>Third chapter content.</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            assert len(result.chapters) == 3
            for i, ch in enumerate(result.chapters):
                assert ch.order == i
        finally:
            epub_path.unlink(missing_ok=True)

    def test_chapter_order_is_sequential(self):
        from server.content.epub.parser import parse_epub

        chapters = [
            ("c1.xhtml", "C1", "<p>Content one with enough words here.</p>"),
            ("c2.xhtml", "C2", "<p>Content two with enough words here.</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            orders = [ch.order for ch in result.chapters]
            assert orders == list(range(len(result.chapters)))
        finally:
            epub_path.unlink(missing_ok=True)

    def test_chapter_text_is_plain_text(self):
        from server.content.epub.parser import parse_epub

        chapters = [
            ("chap1.xhtml", "Ch1", "<h1>Title</h1><p>Plain text content here.</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            assert len(result.chapters) >= 1
            # Find the chapter with our content
            content_ch = next(
                (ch for ch in result.chapters if "Plain text content" in ch.text), None
            )
            assert content_ch is not None
            assert "<p>" not in content_ch.text
            assert "<h1>" not in content_ch.text
            assert "Plain text content here." in content_ch.text
        finally:
            epub_path.unlink(missing_ok=True)

    def test_chapter_title_from_toc(self):
        from server.content.epub.parser import parse_epub

        chapters = [
            ("chap1.xhtml", "TOC Title Here", "<p>Some content in this chapter.</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            content_ch = next(
                (ch for ch in result.chapters if "Some content in this chapter" in ch.text),
                None,
            )
            assert content_ch is not None
            assert content_ch.title == "TOC Title Here"
        finally:
            epub_path.unlink(missing_ok=True)

    def test_chapter_title_from_h1_when_no_toc_entry(self):
        from server.content.epub.parser import parse_epub

        # Create EPUB without TOC entries for the chapter
        from ebooklib import epub as epub_lib

        book = epub_lib.EpubBook()
        book.set_title("Test")
        book.add_author("Author")

        item = epub_lib.EpubHtml(title="", file_name="chap1.xhtml", lang="en")
        item.content = "<html><body><h1>Heading Title</h1><p>Content here.</p></body></html>"
        book.add_item(item)

        # Empty TOC — no entries
        book.toc = ()
        book.add_item(epub_lib.EpubNcx())
        book.add_item(epub_lib.EpubNav())
        book.spine = ["nav", item]

        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
        tmp.close()
        epub_lib.write_epub(tmp.name, book)
        epub_path = Path(tmp.name)

        try:
            result = parse_epub(epub_path)
            content_ch = next(
                (ch for ch in result.chapters if "Content here." in ch.text), None
            )
            assert content_ch is not None
            assert content_ch.title == "Heading Title"
        finally:
            epub_path.unlink(missing_ok=True)

    def test_word_count_populated(self):
        from server.content.epub.parser import parse_epub

        chapters = [
            ("chap1.xhtml", "Ch1", "<p>one two three four five</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            content_ch = next(
                (ch for ch in result.chapters if "one two three" in ch.text), None
            )
            assert content_ch is not None
            assert content_ch.word_count >= 5
        finally:
            epub_path.unlink(missing_ok=True)

    def test_total_words_is_sum_of_chapters(self):
        from server.content.epub.parser import parse_epub

        chapters = [
            ("c1.xhtml", "C1", "<p>one two three</p>"),
            ("c2.xhtml", "C2", "<p>four five six seven</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            assert result.total_words == sum(ch.word_count for ch in result.chapters)
        finally:
            epub_path.unlink(missing_ok=True)

    def test_empty_documents_skipped(self):
        from server.content.epub.parser import parse_epub

        # One chapter with content, one that is effectively empty (only whitespace/tags)
        chapters = [
            ("chap1.xhtml", "Real Chapter", "<h1>Real</h1><p>Real content here.</p>"),
            ("empty.xhtml", "Empty", "<html><body><p>   </p></body></html>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            result = parse_epub(epub_path)
            # Only the non-empty chapter should be included
            assert all(ch.text.strip() for ch in result.chapters)
        finally:
            epub_path.unlink(missing_ok=True)

    def test_epub_parse_error_has_path(self):
        from server.content.epub.parser import EpubParseError, parse_epub

        missing = Path("/no/such/file.epub")
        with pytest.raises(EpubParseError) as exc_info:
            parse_epub(missing)
        assert exc_info.value.path == missing


# ═════════════════════════════════════════════════════════════════════════════
# extract_characters
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractCharacters:
    def _make_book_with_text(self, text: str) -> "EpubBook":
        from server.content.epub.parser import EpubBook, EpubChapter

        ch = EpubChapter(title="Ch1", order=0, text=text)
        return EpubBook(title="T", author="A", chapters=[ch])

    def test_returns_list(self):
        from server.content.epub.parser import extract_characters

        book = self._make_book_with_text("Some plain text with no names.")
        result = extract_characters(book)
        assert isinstance(result, list)

    def test_extracts_capitalised_names(self):
        from server.content.epub.parser import extract_characters

        book = self._make_book_with_text(
            "John Smith walked into the room. Mary Johnson followed him."
        )
        result = extract_characters(book)
        names = [r.name for r in result]
        assert any("John Smith" in n for n in names)

    def test_deduplicates_same_name(self):
        from server.content.epub.parser import extract_characters

        # Same name repeated many times should appear once
        book = self._make_book_with_text(
            "Alice Brown said hello. Alice Brown smiled. Alice Brown left."
        )
        result = extract_characters(book)
        names = [r.name for r in result]
        alice_count = sum(1 for n in names if "Alice Brown" in n)
        assert alice_count == 1

    def test_empty_book_returns_empty_list(self):
        from server.content.epub.parser import EpubBook, extract_characters

        book = EpubBook(title="T", author="A", chapters=[])
        result = extract_characters(book)
        assert result == []

    def test_returns_character_ref_objects(self):
        from server.content.epub.parser import extract_characters

        book = self._make_book_with_text(
            "Robert Chen entered the building. He greeted everyone."
        )
        result = extract_characters(book)
        from server.content.character_dedup import CharacterRef

        for item in result:
            assert isinstance(item, CharacterRef)

    def test_multiple_chapters_combined(self):
        from server.content.epub.parser import EpubBook, EpubChapter, extract_characters

        ch1 = EpubChapter(title="Ch1", order=0, text="Emma Watson arrived first.")
        ch2 = EpubChapter(title="Ch2", order=1, text="Emma Watson spoke to the crowd.")
        book = EpubBook(title="T", author="A", chapters=[ch1, ch2])
        result = extract_characters(book)
        names = [r.name for r in result]
        emma_count = sum(1 for n in names if "Emma Watson" in n)
        assert emma_count == 1


# ═════════════════════════════════════════════════════════════════════════════
# EpubParseError
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubParseError:
    def test_is_exception(self):
        from server.content.epub.parser import EpubParseError

        err = EpubParseError("test error")
        assert isinstance(err, Exception)

    def test_message_attribute(self):
        from server.content.epub.parser import EpubParseError

        err = EpubParseError("something went wrong")
        assert err.message == "something went wrong"

    def test_path_attribute_default_none(self):
        from server.content.epub.parser import EpubParseError

        err = EpubParseError("error")
        assert err.path is None

    def test_path_attribute_set(self):
        from server.content.epub.parser import EpubParseError

        p = Path("/some/file.epub")
        err = EpubParseError("error", path=p)
        assert err.path == p

    def test_str_representation(self):
        from server.content.epub.parser import EpubParseError

        err = EpubParseError("bad file")
        assert "bad file" in str(err)
