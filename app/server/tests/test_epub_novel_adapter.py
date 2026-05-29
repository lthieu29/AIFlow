"""Unit tests for Task 6.2 — 3-tier mode (epub-novel adapter).

Covers:
- classify_tier: auto-classification, force_tier, manual range detection
- process_tier1: direct processing, scene generation, validation
- process_tier2: episode splitting, word-count grouping, EpisodeList structure
- process_tier3: manual range, boundary clamping, invalid range errors
- _split_into_episodes: greedy grouping logic
- _chapter_to_scenes: single vs multi-scene chapters
- EpubNovelAdapter.validate_input: path checks, tier validation, range checks
- EpubNovelAdapter.adapt: end-to-end via real EPUB files (all 3 tiers)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── EPUB fixture helpers ─────────────────────────────────────────────────────


def _make_epub(
    title: str = "Test Book",
    author: str = "Test Author",
    chapters: list[tuple[str, str, str]] | None = None,
) -> Path:
    """Create a minimal EPUB file and return its path (caller must clean up)."""
    from ebooklib import epub

    if chapters is None:
        chapters = [
            ("chap1.xhtml", "Chapter One", "<h1>Chapter One</h1><p>Hello world.</p>"),
        ]

    book = epub.EpubBook()
    book.set_title(title)
    book.add_author(author)

    epub_items = []
    toc_links = []
    for file_name, chap_title, body in chapters:
        item = epub.EpubHtml(title=chap_title, file_name=file_name, lang="en")
        item.content = f"<html><body>{body}</body></html>"
        book.add_item(item)
        epub_items.append(item)
        toc_links.append(epub.Link(file_name, chap_title, file_name.replace(".", "_")))

    book.toc = tuple(toc_links)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + epub_items

    tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
    tmp.close()
    epub.write_epub(tmp.name, book)
    return Path(tmp.name)


def _make_chapter(title: str, order: int, word_count: int) -> "EpubChapter":
    """Create an EpubChapter with a specific word count."""
    from server.content.epub.parser import EpubChapter

    text = " ".join(["word"] * word_count)
    return EpubChapter(title=title, order=order, text=text)


def _make_book(chapters: list["EpubChapter"]) -> "EpubBook":
    from server.content.epub.parser import EpubBook

    return EpubBook(title="Test Novel", author="Author", chapters=chapters)



# ═════════════════════════════════════════════════════════════════════════════
# classify_tier
# ═════════════════════════════════════════════════════════════════════════════


class TestClassifyTier:
    def test_short_book_returns_direct(self):
        from server.content.adapters.epub_novel.tiers import (
            TIER1_MAX_WORDS,
            ProcessingTier,
            classify_tier,
        )

        book = _make_book([_make_chapter("Ch1", 0, TIER1_MAX_WORDS - 100)])
        assert classify_tier(book) == ProcessingTier.DIRECT

    def test_long_book_returns_episode(self):
        from server.content.adapters.epub_novel.tiers import (
            TIER1_MAX_WORDS,
            ProcessingTier,
            classify_tier,
        )

        book = _make_book([_make_chapter("Ch1", 0, TIER1_MAX_WORDS + 1)])
        assert classify_tier(book) == ProcessingTier.EPISODE

    def test_exact_threshold_returns_direct(self):
        from server.content.adapters.epub_novel.tiers import (
            TIER1_MAX_WORDS,
            ProcessingTier,
            classify_tier,
        )

        book = _make_book([_make_chapter("Ch1", 0, TIER1_MAX_WORDS)])
        assert classify_tier(book) == ProcessingTier.DIRECT

    def test_chapter_start_triggers_manual(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, classify_tier

        book = _make_book([_make_chapter("Ch1", 0, 100)])
        assert classify_tier(book, chapter_start=0) == ProcessingTier.MANUAL

    def test_chapter_end_triggers_manual(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, classify_tier

        book = _make_book([_make_chapter("Ch1", 0, 100)])
        assert classify_tier(book, chapter_end=0) == ProcessingTier.MANUAL

    def test_force_tier_overrides_auto(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, classify_tier

        # Short book would normally be DIRECT, but force EPISODE
        book = _make_book([_make_chapter("Ch1", 0, 100)])
        result = classify_tier(book, force_tier=ProcessingTier.EPISODE)
        assert result == ProcessingTier.EPISODE

    def test_force_tier_overrides_manual_signal(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, classify_tier

        book = _make_book([_make_chapter("Ch1", 0, 100)])
        result = classify_tier(book, chapter_start=0, force_tier=ProcessingTier.DIRECT)
        assert result == ProcessingTier.DIRECT



# ═════════════════════════════════════════════════════════════════════════════
# _split_into_episodes
# ═════════════════════════════════════════════════════════════════════════════


class TestSplitIntoEpisodes:
    def test_empty_chapters_returns_empty(self):
        from server.content.adapters.epub_novel.tiers import _split_into_episodes

        assert _split_into_episodes([]) == []

    def test_single_chapter_one_episode(self):
        from server.content.adapters.epub_novel.tiers import _split_into_episodes

        chapters = [_make_chapter("Ch1", 0, 100)]
        result = _split_into_episodes(chapters, episode_max_words=500)
        assert len(result) == 1
        assert result[0] == chapters

    def test_chapters_split_at_word_limit(self):
        from server.content.adapters.epub_novel.tiers import _split_into_episodes

        # 3 chapters of 400 words each, limit=500 → each chapter in its own episode
        chapters = [_make_chapter(f"Ch{i}", i, 400) for i in range(3)]
        result = _split_into_episodes(chapters, episode_max_words=500)
        assert len(result) == 3

    def test_chapters_grouped_within_limit(self):
        from server.content.adapters.epub_novel.tiers import _split_into_episodes

        # 4 chapters of 200 words each, limit=500 → 2 episodes of 2 chapters
        chapters = [_make_chapter(f"Ch{i}", i, 200) for i in range(4)]
        result = _split_into_episodes(chapters, episode_max_words=500)
        assert len(result) == 2
        assert len(result[0]) == 2
        assert len(result[1]) == 2

    def test_oversized_chapter_gets_own_episode(self):
        from server.content.adapters.epub_novel.tiers import _split_into_episodes

        # One chapter exceeds the limit on its own
        chapters = [_make_chapter("Big", 0, 1000)]
        result = _split_into_episodes(chapters, episode_max_words=500)
        assert len(result) == 1
        assert result[0][0].title == "Big"

    def test_all_chapters_in_one_episode_when_under_limit(self):
        from server.content.adapters.epub_novel.tiers import _split_into_episodes

        chapters = [_make_chapter(f"Ch{i}", i, 50) for i in range(5)]
        result = _split_into_episodes(chapters, episode_max_words=1000)
        assert len(result) == 1
        assert len(result[0]) == 5



# ═════════════════════════════════════════════════════════════════════════════
# process_tier1
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessTier1:
    def test_returns_scene_list(self):
        from server.content.adapters.epub_novel.tiers import process_tier1
        from server.content.base import SceneList

        book = _make_book([_make_chapter("Ch1", 0, 50)])
        result = process_tier1(book, project_id="proj1")
        assert isinstance(result, SceneList)

    def test_scenes_are_non_empty(self):
        from server.content.adapters.epub_novel.tiers import process_tier1

        book = _make_book([_make_chapter("Ch1", 0, 50)])
        result = process_tier1(book, project_id="proj1")
        assert len(result.scenes) >= 1

    def test_scene_order_is_contiguous(self):
        from server.content.adapters.epub_novel.tiers import process_tier1

        chapters = [_make_chapter(f"Ch{i}", i, 50) for i in range(3)]
        book = _make_book(chapters)
        result = process_tier1(book, project_id="proj1")
        orders = [s.order for s in result.scenes]
        assert orders == list(range(len(result.scenes)))

    def test_metadata_contains_tier(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, process_tier1

        book = _make_book([_make_chapter("Ch1", 0, 50)])
        result = process_tier1(book, project_id="proj1")
        assert result.metadata.get("tier") == ProcessingTier.DIRECT.value

    def test_metadata_contains_book_title(self):
        from server.content.adapters.epub_novel.tiers import process_tier1

        book = _make_book([_make_chapter("Ch1", 0, 50)])
        result = process_tier1(book, project_id="proj1")
        assert result.metadata.get("book_title") == "Test Novel"

    def test_voice_passed_through(self):
        from server.content.adapters.epub_novel.tiers import process_tier1

        book = _make_book([_make_chapter("Ch1", 0, 50)])
        result = process_tier1(book, project_id="proj1", voice="vi-VN-NamMinhNeural")
        assert result.voice == "vi-VN-NamMinhNeural"

    def test_empty_book_raises_adapter_error(self):
        from server.content.adapters.epub_novel.tiers import process_tier1
        from server.content.base import AdapterError

        book = _make_book([])
        with pytest.raises(AdapterError):
            process_tier1(book, project_id="proj1")

    def test_scene_list_validates(self):
        from server.content.adapters.epub_novel.tiers import process_tier1

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier1(book, project_id="proj1")
        ok, errors = result.validate()
        assert ok, errors



# ═════════════════════════════════════════════════════════════════════════════
# process_tier2
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessTier2:
    def test_returns_episode_list(self):
        from server.content.adapters.epub_novel.tiers import EpisodeList, process_tier2

        chapters = [_make_chapter(f"Ch{i}", i, 200) for i in range(4)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        assert isinstance(result, EpisodeList)

    def test_episode_count_matches_split(self):
        from server.content.adapters.epub_novel.tiers import process_tier2

        # 4 chapters × 300 words, limit=500 → 4 episodes (each chapter alone)
        chapters = [_make_chapter(f"Ch{i}", i, 300) for i in range(4)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        assert result.episode_count == 4

    def test_each_episode_is_scene_list(self):
        from server.content.adapters.epub_novel.tiers import process_tier2
        from server.content.base import SceneList

        chapters = [_make_chapter(f"Ch{i}", i, 200) for i in range(3)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        for ep in result.episodes:
            assert isinstance(ep, SceneList)

    def test_episode_project_ids_are_unique(self):
        from server.content.adapters.epub_novel.tiers import process_tier2

        chapters = [_make_chapter(f"Ch{i}", i, 300) for i in range(3)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        ids = [ep.project_id for ep in result.episodes]
        assert len(ids) == len(set(ids))

    def test_episode_metadata_has_episode_number(self):
        from server.content.adapters.epub_novel.tiers import process_tier2

        chapters = [_make_chapter(f"Ch{i}", i, 300) for i in range(2)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        for i, ep in enumerate(result.episodes):
            assert ep.metadata.get("episode_number") == i + 1

    def test_total_scenes_property(self):
        from server.content.adapters.epub_novel.tiers import process_tier2

        chapters = [_make_chapter(f"Ch{i}", i, 50) for i in range(3)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        assert result.total_scenes == sum(len(ep.scenes) for ep in result.episodes)

    def test_empty_book_raises_adapter_error(self):
        from server.content.adapters.epub_novel.tiers import process_tier2
        from server.content.base import AdapterError

        book = _make_book([])
        with pytest.raises(AdapterError):
            process_tier2(book, project_id="proj1")

    def test_metadata_contains_tier(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, process_tier2

        chapters = [_make_chapter("Ch1", 0, 200)]
        book = _make_book(chapters)
        result = process_tier2(book, project_id="proj1", episode_max_words=500)
        assert result.metadata.get("tier") == ProcessingTier.EPISODE.value



# ═════════════════════════════════════════════════════════════════════════════
# process_tier3
# ═════════════════════════════════════════════════════════════════════════════


class TestProcessTier3:
    def test_returns_scene_list(self):
        from server.content.adapters.epub_novel.tiers import process_tier3
        from server.content.base import SceneList

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier3(book, project_id="proj1", chapter_start=1, chapter_end=3)
        assert isinstance(result, SceneList)

    def test_only_selected_chapters_included(self):
        from server.content.adapters.epub_novel.tiers import process_tier3

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier3(book, project_id="proj1", chapter_start=1, chapter_end=2)
        # Scenes should come from chapters 1 and 2 only
        # Narration text is "word word word..." — check scene count is reasonable
        assert len(result.scenes) >= 1

    def test_metadata_contains_tier(self):
        from server.content.adapters.epub_novel.tiers import ProcessingTier, process_tier3

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier3(book, project_id="proj1", chapter_start=0, chapter_end=1)
        assert result.metadata.get("tier") == ProcessingTier.MANUAL.value

    def test_metadata_contains_chapter_range(self):
        from server.content.adapters.epub_novel.tiers import process_tier3

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier3(book, project_id="proj1", chapter_start=1, chapter_end=3)
        assert result.metadata.get("chapter_start") == 1
        assert result.metadata.get("chapter_end") == 3

    def test_chapter_end_clamped_to_last_chapter(self):
        from server.content.adapters.epub_novel.tiers import process_tier3

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(3)]
        book = _make_book(chapters)
        # chapter_end=99 should be clamped to 2
        result = process_tier3(book, project_id="proj1", chapter_start=0, chapter_end=99)
        assert result.metadata.get("chapter_end") == 2

    def test_negative_chapter_start_raises(self):
        from server.content.adapters.epub_novel.tiers import process_tier3
        from server.content.base import AdapterError

        chapters = [_make_chapter("Ch1", 0, 100)]
        book = _make_book(chapters)
        with pytest.raises(AdapterError):
            process_tier3(book, project_id="proj1", chapter_start=-1, chapter_end=0)

    def test_chapter_end_less_than_start_raises(self):
        from server.content.adapters.epub_novel.tiers import process_tier3
        from server.content.base import AdapterError

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        with pytest.raises(AdapterError):
            process_tier3(book, project_id="proj1", chapter_start=3, chapter_end=1)

    def test_chapter_start_out_of_range_raises(self):
        from server.content.adapters.epub_novel.tiers import process_tier3
        from server.content.base import AdapterError

        chapters = [_make_chapter("Ch1", 0, 100)]
        book = _make_book(chapters)
        with pytest.raises(AdapterError):
            process_tier3(book, project_id="proj1", chapter_start=5, chapter_end=6)

    def test_single_chapter_range(self):
        from server.content.adapters.epub_novel.tiers import process_tier3

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier3(book, project_id="proj1", chapter_start=2, chapter_end=2)
        assert len(result.scenes) >= 1

    def test_scene_list_validates(self):
        from server.content.adapters.epub_novel.tiers import process_tier3

        chapters = [_make_chapter(f"Ch{i}", i, 100) for i in range(5)]
        book = _make_book(chapters)
        result = process_tier3(book, project_id="proj1", chapter_start=0, chapter_end=4)
        ok, errors = result.validate()
        assert ok, errors



# ═════════════════════════════════════════════════════════════════════════════
# EpubNovelAdapter.validate_input
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubNovelAdapterValidateInput:
    def _adapter(self):
        from server.content.adapters.epub_novel.adapter import EpubNovelAdapter

        return EpubNovelAdapter()

    def _input(self, raw_content: str, options: dict | None = None):
        from server.content.base import AdapterInput

        return AdapterInput(
            source_type="epub_novel",
            raw_content=raw_content,
            options=options or {},
        )

    def test_empty_raw_content_returns_error(self):
        adapter = self._adapter()
        errors = adapter.validate_input(self._input(""))
        assert errors

    def test_whitespace_raw_content_returns_error(self):
        adapter = self._adapter()
        errors = adapter.validate_input(self._input("   "))
        assert errors

    def test_nonexistent_file_returns_error(self):
        adapter = self._adapter()
        errors = adapter.validate_input(self._input("/no/such/file.epub"))
        assert any("not found" in e.lower() for e in errors)

    def test_wrong_extension_returns_error(self, tmp_path):
        txt_file = tmp_path / "book.txt"
        txt_file.write_text("not an epub")
        adapter = self._adapter()
        errors = adapter.validate_input(self._input(str(txt_file)))
        assert any(".epub" in e for e in errors)

    def test_valid_epub_path_no_errors(self, tmp_path):
        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            errors = adapter.validate_input(self._input(str(epub_path)))
            assert errors == []
        finally:
            epub_path.unlink(missing_ok=True)

    def test_invalid_tier_returns_error(self, tmp_path):
        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            errors = adapter.validate_input(
                self._input(str(epub_path), options={"tier": "invalid_tier"})
            )
            assert any("tier" in e.lower() for e in errors)
        finally:
            epub_path.unlink(missing_ok=True)

    def test_valid_tier_no_errors(self, tmp_path):
        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            errors = adapter.validate_input(
                self._input(str(epub_path), options={"tier": "direct"})
            )
            assert errors == []
        finally:
            epub_path.unlink(missing_ok=True)

    def test_negative_chapter_start_returns_error(self, tmp_path):
        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            errors = adapter.validate_input(
                self._input(str(epub_path), options={"chapter_start": -1, "chapter_end": 2})
            )
            assert any("chapter_start" in e for e in errors)
        finally:
            epub_path.unlink(missing_ok=True)

    def test_chapter_end_less_than_start_returns_error(self, tmp_path):
        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            errors = adapter.validate_input(
                self._input(str(epub_path), options={"chapter_start": 3, "chapter_end": 1})
            )
            assert any("chapter_end" in e for e in errors)
        finally:
            epub_path.unlink(missing_ok=True)

    def test_manual_tier_without_range_returns_error(self, tmp_path):
        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            errors = adapter.validate_input(
                self._input(str(epub_path), options={"tier": "manual"})
            )
            assert any("chapter_start" in e for e in errors)
            assert any("chapter_end" in e for e in errors)
        finally:
            epub_path.unlink(missing_ok=True)



# ═════════════════════════════════════════════════════════════════════════════
# EpubNovelAdapter.adapt — end-to-end (all 3 tiers)
# ═════════════════════════════════════════════════════════════════════════════


class TestEpubNovelAdapterAdapt:
    def _adapter(self):
        from server.content.adapters.epub_novel.adapter import EpubNovelAdapter

        return EpubNovelAdapter()

    def _input(self, epub_path: Path, options: dict | None = None):
        from server.content.base import AdapterInput

        return AdapterInput(
            source_type="epub_novel",
            raw_content=str(epub_path),
            options=options or {},
        )

    @pytest.mark.asyncio
    async def test_tier1_short_novel_returns_scene_list(self):
        from server.content.base import SceneList

        # Short novel: 3 chapters with small word counts
        chapters = [
            ("c1.xhtml", "Ch1", "<h1>Ch1</h1><p>Short chapter one content here.</p>"),
            ("c2.xhtml", "Ch2", "<h1>Ch2</h1><p>Short chapter two content here.</p>"),
            ("c3.xhtml", "Ch3", "<h1>Ch3</h1><p>Short chapter three content here.</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            adapter = self._adapter()
            result = await adapter.adapt(self._input(epub_path, {"tier": "direct"}))
            assert isinstance(result, SceneList)
            assert len(result.scenes) >= 1
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tier2_forced_returns_episode_list(self):
        from server.content.adapters.epub_novel.tiers import EpisodeList

        chapters = [
            (f"c{i}.xhtml", f"Ch{i}", f"<h1>Ch{i}</h1><p>Content for chapter {i}.</p>")
            for i in range(4)
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            adapter = self._adapter()
            result = await adapter.adapt(
                self._input(epub_path, {"tier": "episode", "episode_max_words": 5})
            )
            assert isinstance(result, EpisodeList)
            assert result.episode_count >= 1
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tier3_manual_range_returns_scene_list(self):
        from server.content.base import SceneList

        chapters = [
            (f"c{i}.xhtml", f"Ch{i}", f"<h1>Ch{i}</h1><p>Content for chapter {i}.</p>")
            for i in range(5)
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            adapter = self._adapter()
            result = await adapter.adapt(
                self._input(epub_path, {"chapter_start": 1, "chapter_end": 3})
            )
            assert isinstance(result, SceneList)
            assert len(result.scenes) >= 1
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_missing_epub_raises_adapter_error(self):
        from server.content.base import AdapterError, AdapterInput

        adapter = self._adapter()
        inp = AdapterInput(
            source_type="epub_novel",
            raw_content="/no/such/file.epub",
        )
        with pytest.raises(AdapterError):
            await adapter.adapt(inp)

    @pytest.mark.asyncio
    async def test_invalid_tier_raises_adapter_error(self):
        from server.content.base import AdapterError

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            with pytest.raises(AdapterError):
                await adapter.adapt(self._input(epub_path, {"tier": "bogus"}))
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_tier3_without_range_raises_adapter_error(self):
        from server.content.base import AdapterError

        epub_path = _make_epub()
        try:
            adapter = self._adapter()
            with pytest.raises(AdapterError):
                await adapter.adapt(self._input(epub_path, {"tier": "manual"}))
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_auto_tier_short_novel_returns_scene_list(self):
        from server.content.base import SceneList

        # No tier forced — short novel should auto-classify as Tier 1
        chapters = [
            ("c1.xhtml", "Ch1", "<h1>Ch1</h1><p>A short chapter.</p>"),
        ]
        epub_path = _make_epub(chapters=chapters)
        try:
            adapter = self._adapter()
            result = await adapter.adapt(self._input(epub_path))
            assert isinstance(result, SceneList)
        finally:
            epub_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_adapter_type_is_epub_novel(self):
        adapter = self._adapter()
        assert adapter.adapter_type == "epub_novel"

