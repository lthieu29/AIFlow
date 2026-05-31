"""Task 8.9 — Integration test: ``NewsBulletinAdapter`` URL-not-a-feed.

**Validates: Requirement 4.6**

A URL that points to a perfectly well-formed page that is NOT an RSS/Atom
feed (e.g. plain HTML) cannot be detected by ``validate_input`` (which is
forbidden from making network calls).  The error must surface in
``adapt`` once the URL is fetched: the adapter raises
``ADAPTER_FETCH_ERROR``.

We mock ``feedparser.parse`` so the test runs without any real network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.adapters.news_bulletin.adapter import NewsBulletinAdapter
from server.content.base import AdapterError, AdapterInput


def _run(coro):
    return asyncio.run(coro)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _patch_feedparser_to_return(
    monkeypatch: pytest.MonkeyPatch,
    *,
    version: str = "",
    entries: list | None = None,
):
    """Patch the ``feedparser`` symbol used inside the adapter module so
    ``feedparser.parse(...)`` returns a controlled object."""
    import server.content.adapters.news_bulletin.adapter as mod

    pytest.importorskip("feedparser")  # ensure adapter import path works

    fake = SimpleNamespace(
        parse=lambda src: SimpleNamespace(
            version=version,
            entries=entries or [],
            feed=SimpleNamespace(get=lambda *_: ""),
        )
    )
    monkeypatch.setattr(mod, "_import_feedparser", lambda: fake)
    return fake


# ─── R4.6 — validate_input passes well-formed URL without network ───────────


def test_validate_input_passes_well_formed_url() -> None:
    """A well-formed http(s) URL passes ``validate_input`` regardless of
    whether the URL is actually a feed (R4.6 — no network calls)."""
    adapter = NewsBulletinAdapter()
    errors = adapter.validate_input(
        AdapterInput(
            source_type="news",
            raw_content="https://example.com/page-that-is-not-a-feed",
        )
    )
    assert errors == []


def test_validate_input_rejects_bad_url() -> None:
    adapter = NewsBulletinAdapter()
    errors = adapter.validate_input(
        AdapterInput(source_type="news", raw_content="ftp://example.com/x")
    )
    assert errors


# ─── R4.6 — URL points to non-feed → adapt() raises ADAPTER_FETCH_ERROR ─────


def test_adapt_url_not_a_feed_raises_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**R4.6** — When the URL fetches successfully but the response is not a
    feed (no version, no entries), ``adapt`` raises ``ADAPTER_FETCH_ERROR``."""
    _patch_feedparser_to_return(monkeypatch, version="", entries=[])

    adapter = NewsBulletinAdapter()
    with pytest.raises(AdapterError) as exc_info:
        _run(
            adapter.adapt(
                AdapterInput(
                    source_type="news",
                    raw_content="https://example.com/looks-like-html",
                )
            )
        )
    assert exc_info.value.code == "ADAPTER_FETCH_ERROR"


# ─── happy path with mocked feedparser entries ──────────────────────────────


def test_adapt_url_returns_scene_list_when_feed_has_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the URL fetches a real feed, ``adapt`` returns a SceneList with
    one scene per item."""
    entries = [
        SimpleNamespace(
            get=lambda key, default="": {
                "title": "Headline A",
                "summary": "Summary A.",
            }.get(key, default)
        ),
        SimpleNamespace(
            get=lambda key, default="": {
                "title": "Headline B",
                "summary": "Summary B.",
            }.get(key, default)
        ),
    ]
    _patch_feedparser_to_return(monkeypatch, version="rss20", entries=entries)

    adapter = NewsBulletinAdapter()
    scene_list = _run(
        adapter.adapt(
            AdapterInput(
                source_type="news",
                raw_content="https://example.com/feed.xml",
            )
        )
    )
    ok, errors = scene_list.validate()
    assert ok, errors
    assert len(scene_list.scenes) == 2
    narrations = [s.narration for s in scene_list.scenes]
    assert any(n and "Headline A" in n for n in narrations)
    assert any(n and "Headline B" in n for n in narrations)


def test_adapt_max_items_truncates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``options['max_items']`` truncates the feed to the first N items."""
    entries = [
        SimpleNamespace(
            get=lambda key, default="", _t=t: {
                "title": f"Item {_t}",
                "summary": "...",
            }.get(key, default)
        )
        for t in range(5)
    ]
    _patch_feedparser_to_return(monkeypatch, version="rss20", entries=entries)

    adapter = NewsBulletinAdapter()
    scene_list = _run(
        adapter.adapt(
            AdapterInput(
                source_type="news",
                raw_content="https://example.com/feed.xml",
                options={"max_items": 2},
            )
        )
    )
    assert len(scene_list.scenes) == 2
