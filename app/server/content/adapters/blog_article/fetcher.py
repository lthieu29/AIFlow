"""URL fetcher and HTML-to-text extractor for the blog_article adapter.

Provides:
- :class:`FetchedArticle` — dataclass holding the fetched article data.
- :func:`fetch_article` — fetch a URL with httpx and extract readable text.
- :func:`extract_text_from_html` — extract (title, text) from raw HTML.

The extractor tries ``readability-lxml`` first; if it is not installed it
falls back to a simple stdlib ``html.parser`` implementation that strips
tags and collapses whitespace.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# ─── Data class ──────────────────────────────────────────────────────────────


@dataclass
class FetchedArticle:
    """Result of fetching and parsing a blog article URL.

    Attributes:
        url:   The original URL that was fetched.
        title: Extracted article title (may be empty string if not found).
        text:  Plain-text body of the article.
        html:  Raw HTML response body.
    """

    url: str
    title: str
    text: str
    html: str = field(repr=False)


# ─── HTML extraction ─────────────────────────────────────────────────────────


class _TextExtractor(HTMLParser):
    """Minimal HTML → plain-text extractor using stdlib html.parser.

    Skips ``<script>``, ``<style>`` and similar non-content tags.
    The ``<head>`` section is skipped for body text but the ``<title>``
    tag inside it is captured separately.
    Collapses consecutive whitespace.
    """

    # Tags whose content should be excluded from body text
    _SKIP_TAGS = frozenset(
        {"script", "style", "noscript", "template", "svg", "iframe"}
    )
    # Tags that are part of <head> but not body content
    _HEAD_TAGS = frozenset({"head", "meta", "link", "base"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth: int = 0
        self._head_depth: int = 0
        self.title: str = ""
        self._in_title: bool = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag_lower == "head":
            self._head_depth += 1
        if tag_lower == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag_lower == "head":
            self._head_depth = max(0, self._head_depth - 1)
        if tag_lower == "title":
            self._in_title = False
        # Add a newline after block-level elements for readability
        if tag_lower in {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        # Always capture title text regardless of head/skip depth
        if self._in_title and not self.title:
            self.title = data.strip()
            return
        # Skip content inside skip tags or head (but not title — handled above)
        if self._skip_depth > 0 or self._head_depth > 0:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of whitespace (but preserve paragraph breaks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _extract_with_readability(html: str) -> tuple[str, str]:
    """Try to extract (title, text) using readability-lxml."""
    from readability import Document  # type: ignore[import]

    doc = Document(html)
    title = doc.title() or ""
    # doc.summary() returns simplified HTML; strip tags for plain text
    summary_html = doc.summary()
    extractor = _TextExtractor()
    extractor.feed(summary_html)
    text = extractor.get_text()
    return title.strip(), text


def _extract_with_stdlib(html: str) -> tuple[str, str]:
    """Extract (title, text) using stdlib html.parser (fallback)."""
    extractor = _TextExtractor()
    extractor.feed(html)
    title = extractor.title
    text = extractor.get_text()
    return title.strip(), text


def extract_text_from_html(html: str) -> tuple[str, str]:
    """Extract (title, plain_text) from raw HTML.

    Tries ``readability-lxml`` first for better article extraction.
    Falls back to a simple stdlib parser if readability is not installed
    or raises an error.

    Args:
        html: Raw HTML string.

    Returns:
        A ``(title, text)`` tuple.  Both values are stripped strings.
        Either may be empty if the HTML contains no relevant content.
    """
    if not html or not html.strip():
        return "", ""

    try:
        return _extract_with_readability(html)
    except ImportError:
        logger.debug("readability-lxml not available; using stdlib fallback")
    except Exception as exc:  # noqa: BLE001
        logger.warning("readability extraction failed (%s); using stdlib fallback", exc)

    return _extract_with_stdlib(html)


# ─── URL fetcher ─────────────────────────────────────────────────────────────


async def fetch_article(url: str, timeout: int = 30) -> FetchedArticle:
    """Fetch *url* with httpx and extract readable article text.

    Args:
        url:     The URL to fetch.
        timeout: HTTP request timeout in seconds.

    Returns:
        A :class:`FetchedArticle` with the extracted title and text.

    Raises:
        :exc:`ValueError`: If *url* is empty or does not start with
            ``http://`` or ``https://``.
        :exc:`httpx.HTTPStatusError`: If the server returns a 4xx/5xx
            response.
        :exc:`httpx.RequestError`: On network-level errors (timeout,
            connection refused, etc.).
    """
    if not url or not url.strip():
        raise ValueError("url must not be empty")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"url must start with http:// or https://, got: {url!r}")

    import httpx  # imported here so the module is importable without httpx installed

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout,
        headers=headers,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        raw_html = response.text

    title, text = extract_text_from_html(raw_html)

    # If title is still empty, try to extract from <title> tag via a quick regex
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
        if m:
            title = html_module.unescape(m.group(1)).strip()

    logger.debug("fetch_article: fetched %r — title=%r, text_len=%d", url, title, len(text))

    return FetchedArticle(url=url, title=title, text=text, html=raw_html)
