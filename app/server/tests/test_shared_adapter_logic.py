"""Unit tests for Task 4.0.2 — Shared adapter logic.

Covers:
- character_dedup: normalize_name, dedup_characters, extract_character_names
- duration_estimator: estimate_scene_duration, estimate_total_duration, distribute_duration
- llm_chunking: chunk_by_sentences, chunk_by_paragraphs, estimate_scene_count, llm_chunk_to_scenes
- srt_utils: seconds_to_srt_time, srt_time_to_seconds, parse_srt, format_srt,
             merge_short_segments, shift_segments
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ═════════════════════════════════════════════════════════════════════════════
# character_dedup
# ═════════════════════════════════════════════════════════════════════════════


class TestNormalizeName:
    def test_lowercase(self):
        from server.content.character_dedup import normalize_name
        assert normalize_name("Alice") == "alice"

    def test_strips_whitespace(self):
        from server.content.character_dedup import normalize_name
        assert normalize_name("  Bob  ") == "bob"

    def test_unicode(self):
        from server.content.character_dedup import normalize_name
        assert normalize_name("Hùng An") == "hùng an"

    def test_empty_string(self):
        from server.content.character_dedup import normalize_name
        assert normalize_name("") == ""


class TestDedupCharacters:
    def _make(self, name, aliases=None, description=""):
        from server.content.character_dedup import CharacterRef
        return CharacterRef(name=name, aliases=aliases or [], description=description)

    def test_no_duplicates_unchanged(self):
        from server.content.character_dedup import dedup_characters
        chars = [self._make("Alice"), self._make("Bob")]
        result = dedup_characters(chars)
        assert len(result) == 2

    def test_same_name_merged(self):
        from server.content.character_dedup import dedup_characters
        chars = [self._make("Alice"), self._make("Alice")]
        result = dedup_characters(chars)
        assert len(result) == 1
        assert result[0].name == "Alice"

    def test_case_insensitive_name_merge(self):
        from server.content.character_dedup import dedup_characters
        chars = [self._make("alice"), self._make("Alice")]
        result = dedup_characters(chars)
        assert len(result) == 1

    def test_overlapping_aliases_merged(self):
        from server.content.character_dedup import dedup_characters
        chars = [
            self._make("Hùng An", aliases=["Hùng"]),
            self._make("Anh Hùng", aliases=["Hùng"]),
        ]
        result = dedup_characters(chars)
        assert len(result) == 1
        assert result[0].name == "Hùng An"

    def test_descriptions_combined(self):
        from server.content.character_dedup import dedup_characters
        chars = [
            self._make("Alice", description="tall"),
            self._make("Alice", description="blonde"),
        ]
        result = dedup_characters(chars)
        assert "tall" in result[0].description
        assert "blonde" in result[0].description

    def test_ref_image_from_first_available(self, tmp_path):
        from server.content.character_dedup import CharacterRef, dedup_characters
        img = tmp_path / "alice.png"
        img.write_bytes(b"PNG")
        chars = [
            CharacterRef(name="Alice", ref_image=None),
            CharacterRef(name="Alice", ref_image=img),
        ]
        result = dedup_characters(chars)
        assert result[0].ref_image == img

    def test_empty_list(self):
        from server.content.character_dedup import dedup_characters
        assert dedup_characters([]) == []

    def test_three_way_merge_via_alias_chain(self):
        from server.content.character_dedup import dedup_characters
        chars = [
            self._make("A", aliases=["x"]),
            self._make("B", aliases=["x"]),
            self._make("C", aliases=["x"]),
        ]
        result = dedup_characters(chars)
        assert len(result) == 1


class TestExtractCharacterNames:
    def test_capitalized_two_word_name(self):
        from server.content.character_dedup import extract_character_names
        names = extract_character_names("John Smith walked into the room.")
        assert "John Smith" in names

    def test_quoted_name(self):
        from server.content.character_dedup import extract_character_names
        names = extract_character_names('She called out "Alice" from across the hall.')
        assert "Alice" in names

    def test_no_names_in_plain_text(self):
        from server.content.character_dedup import extract_character_names
        names = extract_character_names("the quick brown fox jumps over the lazy dog")
        assert names == []

    def test_deduplication(self):
        from server.content.character_dedup import extract_character_names
        names = extract_character_names("John Smith met John Smith again.")
        assert names.count("John Smith") == 1

    def test_empty_string(self):
        from server.content.character_dedup import extract_character_names
        assert extract_character_names("") == []


# ═════════════════════════════════════════════════════════════════════════════
# duration_estimator
# ═════════════════════════════════════════════════════════════════════════════


class TestEstimateSceneDuration:
    def test_empty_narration_returns_min(self):
        from server.content.duration_estimator import estimate_scene_duration
        assert estimate_scene_duration("") == 3.0

    def test_whitespace_only_returns_min(self):
        from server.content.duration_estimator import estimate_scene_duration
        assert estimate_scene_duration("   ") == 3.0

    def test_short_text_clamped_to_min(self):
        from server.content.duration_estimator import estimate_scene_duration
        # 2 words at 150 wpm = 0.8 s → clamped to 3.0
        assert estimate_scene_duration("Hello world") == pytest.approx(3.0)

    def test_long_text_clamped_to_max(self):
        from server.content.duration_estimator import estimate_scene_duration
        # 1000 words at 150 wpm = 400 s → clamped to 30.0
        text = " ".join(["word"] * 1000)
        assert estimate_scene_duration(text) == pytest.approx(30.0)

    def test_typical_narration(self):
        from server.content.duration_estimator import estimate_scene_duration
        # 20 words at 150 wpm = 8.0 s
        text = " ".join(["word"] * 20)
        assert estimate_scene_duration(text) == pytest.approx(8.0)

    def test_custom_wpm(self):
        from server.content.duration_estimator import estimate_scene_duration
        # 30 words at 300 wpm = 6.0 s
        text = " ".join(["word"] * 30)
        assert estimate_scene_duration(text, words_per_minute=300) == pytest.approx(6.0)


class TestEstimateTotalDuration:
    def test_empty_list(self):
        from server.content.duration_estimator import estimate_total_duration
        assert estimate_total_duration([]) == pytest.approx(0.0)

    def test_uses_scene_duration_when_no_narration(self):
        from server.content.base import SceneSpec
        from server.content.duration_estimator import estimate_total_duration
        scenes = [SceneSpec(order=0, prompt="p", duration=10.0)]
        assert estimate_total_duration(scenes) == pytest.approx(10.0)

    def test_uses_narration_when_present(self):
        from server.content.base import SceneSpec
        from server.content.duration_estimator import estimate_total_duration
        # 20 words → 8.0 s
        narration = " ".join(["word"] * 20)
        scenes = [SceneSpec(order=0, prompt="p", duration=5.0, narration=narration)]
        assert estimate_total_duration(scenes) == pytest.approx(8.0)

    def test_mixed_scenes(self):
        from server.content.base import SceneSpec
        from server.content.duration_estimator import estimate_total_duration
        narration = " ".join(["word"] * 20)  # 8.0 s
        scenes = [
            SceneSpec(order=0, prompt="p", duration=10.0),           # no narration → 10.0
            SceneSpec(order=1, prompt="p", duration=5.0, narration=narration),  # → 8.0
        ]
        assert estimate_total_duration(scenes) == pytest.approx(18.0)


class TestDistributeDuration:
    def test_even_distribution(self):
        from server.content.duration_estimator import distribute_duration
        result = distribute_duration(40.0, 5)
        assert result == [pytest.approx(8.0)] * 5

    def test_clamped_to_min(self):
        from server.content.duration_estimator import distribute_duration
        # 1 s per scene → clamped to 3.0
        result = distribute_duration(5.0, 5)
        assert all(d == pytest.approx(3.0) for d in result)

    def test_clamped_to_max(self):
        from server.content.duration_estimator import distribute_duration
        # 100 s per scene → clamped to 30.0
        result = distribute_duration(500.0, 5)
        assert all(d == pytest.approx(30.0) for d in result)

    def test_single_scene(self):
        from server.content.duration_estimator import distribute_duration
        result = distribute_duration(15.0, 1)
        assert result == [pytest.approx(15.0)]

    def test_raises_for_zero_scenes(self):
        from server.content.duration_estimator import distribute_duration
        with pytest.raises(ValueError):
            distribute_duration(40.0, 0)

    def test_custom_bounds(self):
        from server.content.duration_estimator import distribute_duration
        result = distribute_duration(100.0, 4, min_duration=5.0, max_duration=20.0)
        assert all(d == pytest.approx(20.0) for d in result)


# ═════════════════════════════════════════════════════════════════════════════
# llm_chunking
# ═════════════════════════════════════════════════════════════════════════════


class TestChunkBySentences:
    def test_empty_string(self):
        from server.content.llm_chunking import chunk_by_sentences
        assert chunk_by_sentences("") == []

    def test_single_sentence(self):
        from server.content.llm_chunking import chunk_by_sentences
        result = chunk_by_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_splits_at_sentence_boundary(self):
        from server.content.llm_chunking import chunk_by_sentences
        text = "First sentence. Second sentence. Third sentence."
        result = chunk_by_sentences(text, max_chars_per_chunk=20)
        assert len(result) >= 2

    def test_long_single_sentence_in_own_chunk(self):
        from server.content.llm_chunking import chunk_by_sentences
        long_sentence = "word " * 200
        result = chunk_by_sentences(long_sentence.strip(), max_chars_per_chunk=50)
        assert len(result) == 1

    def test_respects_max_chars(self):
        from server.content.llm_chunking import chunk_by_sentences
        text = "A. B. C. D. E."
        result = chunk_by_sentences(text, max_chars_per_chunk=5)
        # Each sentence is 2 chars; should be split into individual chunks
        assert len(result) >= 3


class TestChunkByParagraphs:
    def test_empty_string(self):
        from server.content.llm_chunking import chunk_by_paragraphs
        assert chunk_by_paragraphs("") == []

    def test_single_paragraph(self):
        from server.content.llm_chunking import chunk_by_paragraphs
        result = chunk_by_paragraphs("Hello world.")
        assert result == ["Hello world."]

    def test_groups_paragraphs(self):
        from server.content.llm_chunking import chunk_by_paragraphs
        text = "Para 1.\n\nPara 2.\n\nPara 3.\n\nPara 4."
        result = chunk_by_paragraphs(text, max_paragraphs_per_chunk=2)
        assert len(result) == 2
        assert "Para 1" in result[0]
        assert "Para 3" in result[1]

    def test_single_paragraph_per_chunk(self):
        from server.content.llm_chunking import chunk_by_paragraphs
        text = "A.\n\nB.\n\nC."
        result = chunk_by_paragraphs(text, max_paragraphs_per_chunk=1)
        assert len(result) == 3


class TestEstimateSceneCount:
    def test_empty_text(self):
        from server.content.llm_chunking import estimate_scene_count
        assert estimate_scene_count("") == 1

    def test_short_text(self):
        from server.content.llm_chunking import estimate_scene_count
        # Very short text → 1 scene
        assert estimate_scene_count("Hello.") == 1

    def test_longer_text_more_scenes(self):
        from server.content.llm_chunking import estimate_scene_count
        # 200 words at 2.5 wps = 80 s / 8 s per scene = 10 scenes
        text = " ".join(["word"] * 200)
        count = estimate_scene_count(text, target_duration_per_scene=8.0)
        assert count >= 5


class TestLlmChunkToScenes:
    """Tests for llm_chunk_to_scenes — uses a mock Gemini client."""

    def _make_mock_client(self, response: str):
        """Return a minimal mock with generate_text()."""
        class _MockClient:
            def generate_text(self, prompt: str) -> str:
                return response
        return _MockClient()

    @pytest.mark.asyncio
    async def test_empty_text_returns_empty(self):
        from server.content.llm_chunking import llm_chunk_to_scenes
        result = await llm_chunk_to_scenes("", gemini_client=None, n_scenes=3)
        assert result.scene_count == 0
        assert result.chunks == []

    @pytest.mark.asyncio
    async def test_fallback_when_client_is_none(self):
        from server.content.llm_chunking import llm_chunk_to_scenes
        text = "First sentence. Second sentence. Third sentence."
        result = await llm_chunk_to_scenes(text, gemini_client=None, n_scenes=2)
        assert result.scene_count >= 1
        assert result.total_chars > 0

    @pytest.mark.asyncio
    async def test_uses_llm_response_when_valid_json(self):
        from server.content.llm_chunking import llm_chunk_to_scenes
        import json
        chunks = ["Scene one text.", "Scene two text.", "Scene three text."]
        client = self._make_mock_client(json.dumps(chunks))
        result = await llm_chunk_to_scenes("some text", gemini_client=client, n_scenes=3)
        assert result.chunks == chunks
        assert result.scene_count == 3

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_llm_response(self):
        from server.content.llm_chunking import llm_chunk_to_scenes
        client = self._make_mock_client("not valid json at all")
        text = "First sentence. Second sentence."
        result = await llm_chunk_to_scenes(text, gemini_client=client, n_scenes=2)
        # Should fall back to sentence chunking — still returns something
        assert result.scene_count >= 1

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self):
        from server.content.llm_chunking import llm_chunk_to_scenes
        class _FailingClient:
            def generate_text(self, prompt: str) -> str:
                raise RuntimeError("API down")
        text = "First sentence. Second sentence."
        result = await llm_chunk_to_scenes(text, gemini_client=_FailingClient(), n_scenes=2)
        assert result.scene_count >= 1

    @pytest.mark.asyncio
    async def test_total_chars_matches_chunks(self):
        from server.content.llm_chunking import llm_chunk_to_scenes
        import json
        chunks = ["Hello world.", "Goodbye world."]
        client = self._make_mock_client(json.dumps(chunks))
        result = await llm_chunk_to_scenes("text", gemini_client=client, n_scenes=2)
        assert result.total_chars == sum(len(c) for c in result.chunks)


# ═════════════════════════════════════════════════════════════════════════════
# srt_utils
# ═════════════════════════════════════════════════════════════════════════════


class TestSecondsToSrtTime:
    def test_zero(self):
        from server.content.srt_utils import seconds_to_srt_time
        assert seconds_to_srt_time(0.0) == "00:00:00,000"

    def test_one_second(self):
        from server.content.srt_utils import seconds_to_srt_time
        assert seconds_to_srt_time(1.0) == "00:00:01,000"

    def test_one_hour(self):
        from server.content.srt_utils import seconds_to_srt_time
        assert seconds_to_srt_time(3600.0) == "01:00:00,000"

    def test_milliseconds(self):
        from server.content.srt_utils import seconds_to_srt_time
        assert seconds_to_srt_time(1.5) == "00:00:01,500"

    def test_complex_time(self):
        from server.content.srt_utils import seconds_to_srt_time
        assert seconds_to_srt_time(3661.5) == "01:01:01,500"

    def test_negative_clamped_to_zero(self):
        from server.content.srt_utils import seconds_to_srt_time
        assert seconds_to_srt_time(-5.0) == "00:00:00,000"


class TestSrtTimeToSeconds:
    def test_zero(self):
        from server.content.srt_utils import srt_time_to_seconds
        assert srt_time_to_seconds("00:00:00,000") == pytest.approx(0.0)

    def test_one_second(self):
        from server.content.srt_utils import srt_time_to_seconds
        assert srt_time_to_seconds("00:00:01,000") == pytest.approx(1.0)

    def test_one_hour(self):
        from server.content.srt_utils import srt_time_to_seconds
        assert srt_time_to_seconds("01:00:00,000") == pytest.approx(3600.0)

    def test_milliseconds(self):
        from server.content.srt_utils import srt_time_to_seconds
        assert srt_time_to_seconds("00:00:01,500") == pytest.approx(1.5)

    def test_complex_time(self):
        from server.content.srt_utils import srt_time_to_seconds
        assert srt_time_to_seconds("01:01:01,500") == pytest.approx(3661.5)

    def test_invalid_format_raises(self):
        from server.content.srt_utils import srt_time_to_seconds
        with pytest.raises(ValueError):
            srt_time_to_seconds("not a time")

    def test_roundtrip(self):
        from server.content.srt_utils import seconds_to_srt_time, srt_time_to_seconds
        for secs in [0.0, 1.0, 3661.5, 7199.999]:
            assert srt_time_to_seconds(seconds_to_srt_time(secs)) == pytest.approx(secs, abs=0.001)


class TestParseSrt:
    _SAMPLE_SRT = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "Hello world.\n"
        "\n"
        "2\n"
        "00:00:05,000 --> 00:00:08,500\n"
        "Second subtitle.\n"
    )

    def test_parses_two_segments(self):
        from server.content.srt_utils import parse_srt
        segs = parse_srt(self._SAMPLE_SRT)
        assert len(segs) == 2

    def test_first_segment_fields(self):
        from server.content.srt_utils import parse_srt
        segs = parse_srt(self._SAMPLE_SRT)
        assert segs[0].index == 1
        assert segs[0].start_sec == pytest.approx(1.0)
        assert segs[0].end_sec == pytest.approx(4.0)
        assert segs[0].text == "Hello world."

    def test_second_segment_fields(self):
        from server.content.srt_utils import parse_srt
        segs = parse_srt(self._SAMPLE_SRT)
        assert segs[1].index == 2
        assert segs[1].start_sec == pytest.approx(5.0)
        assert segs[1].end_sec == pytest.approx(8.5)

    def test_empty_string(self):
        from server.content.srt_utils import parse_srt
        assert parse_srt("") == []

    def test_windows_line_endings(self):
        from server.content.srt_utils import parse_srt
        srt = "1\r\n00:00:01,000 --> 00:00:04,000\r\nHello.\r\n"
        segs = parse_srt(srt)
        assert len(segs) == 1
        assert segs[0].text == "Hello."

    def test_multiline_text(self):
        from server.content.srt_utils import parse_srt
        srt = "1\n00:00:01,000 --> 00:00:04,000\nLine one.\nLine two.\n"
        segs = parse_srt(srt)
        assert "Line one." in segs[0].text
        assert "Line two." in segs[0].text


class TestFormatSrt:
    def test_empty_list(self):
        from server.content.srt_utils import format_srt
        assert format_srt([]) == ""

    def test_single_segment(self):
        from server.content.srt_utils import SrtSegment, format_srt
        seg = SrtSegment(index=1, start_sec=1.0, end_sec=4.0, text="Hello.")
        result = format_srt([seg])
        assert "1\n" in result
        assert "00:00:01,000 --> 00:00:04,000" in result
        assert "Hello." in result

    def test_roundtrip(self):
        from server.content.srt_utils import SrtSegment, format_srt, parse_srt
        segs = [
            SrtSegment(index=1, start_sec=1.0, end_sec=4.0, text="Hello."),
            SrtSegment(index=2, start_sec=5.0, end_sec=8.0, text="World."),
        ]
        srt_str = format_srt(segs)
        parsed = parse_srt(srt_str)
        assert len(parsed) == 2
        assert parsed[0].text == "Hello."
        assert parsed[1].text == "World."


class TestMergeShortSegments:
    def _seg(self, idx, start, end, text="text"):
        from server.content.srt_utils import SrtSegment
        return SrtSegment(index=idx, start_sec=start, end_sec=end, text=text)

    def test_empty_list(self):
        from server.content.srt_utils import merge_short_segments
        assert merge_short_segments([]) == []

    def test_no_short_segments_unchanged(self):
        from server.content.srt_utils import merge_short_segments
        segs = [self._seg(1, 0.0, 2.0), self._seg(2, 2.0, 5.0)]
        result = merge_short_segments(segs, min_duration=1.0)
        assert len(result) == 2

    def test_short_segment_merged_with_next(self):
        from server.content.srt_utils import merge_short_segments
        segs = [
            self._seg(1, 0.0, 0.5, "short"),   # 0.5 s < 1.0 s
            self._seg(2, 0.5, 3.0, "long"),
        ]
        result = merge_short_segments(segs, min_duration=1.0)
        assert len(result) == 1
        assert result[0].start_sec == pytest.approx(0.0)
        assert result[0].end_sec == pytest.approx(3.0)

    def test_last_short_segment_merged_with_previous(self):
        from server.content.srt_utils import merge_short_segments
        segs = [
            self._seg(1, 0.0, 3.0, "long"),
            self._seg(2, 3.0, 3.4, "short"),   # 0.4 s < 1.0 s
        ]
        result = merge_short_segments(segs, min_duration=1.0)
        assert len(result) == 1
        assert result[0].end_sec == pytest.approx(3.4)

    def test_indices_renumbered(self):
        from server.content.srt_utils import merge_short_segments
        segs = [
            self._seg(1, 0.0, 0.5),
            self._seg(2, 0.5, 3.0),
            self._seg(3, 3.0, 6.0),
        ]
        result = merge_short_segments(segs, min_duration=1.0)
        for i, seg in enumerate(result, start=1):
            assert seg.index == i

    def test_single_short_segment_left_alone(self):
        from server.content.srt_utils import merge_short_segments
        segs = [self._seg(1, 0.0, 0.5)]
        result = merge_short_segments(segs, min_duration=1.0)
        assert len(result) == 1


class TestShiftSegments:
    def _seg(self, idx, start, end):
        from server.content.srt_utils import SrtSegment
        return SrtSegment(index=idx, start_sec=start, end_sec=end, text="t")

    def test_positive_shift(self):
        from server.content.srt_utils import shift_segments
        segs = [self._seg(1, 1.0, 4.0)]
        result = shift_segments(segs, 2.0)
        assert result[0].start_sec == pytest.approx(3.0)
        assert result[0].end_sec == pytest.approx(6.0)

    def test_negative_shift(self):
        from server.content.srt_utils import shift_segments
        segs = [self._seg(1, 5.0, 8.0)]
        result = shift_segments(segs, -3.0)
        assert result[0].start_sec == pytest.approx(2.0)
        assert result[0].end_sec == pytest.approx(5.0)

    def test_clamped_to_zero(self):
        from server.content.srt_utils import shift_segments
        segs = [self._seg(1, 1.0, 4.0)]
        result = shift_segments(segs, -10.0)
        assert result[0].start_sec == pytest.approx(0.0)
        assert result[0].end_sec == pytest.approx(0.0)

    def test_original_not_modified(self):
        from server.content.srt_utils import shift_segments
        segs = [self._seg(1, 1.0, 4.0)]
        shift_segments(segs, 5.0)
        assert segs[0].start_sec == pytest.approx(1.0)

    def test_empty_list(self):
        from server.content.srt_utils import shift_segments
        assert shift_segments([], 5.0) == []

    def test_zero_shift_unchanged(self):
        from server.content.srt_utils import shift_segments
        segs = [self._seg(1, 2.0, 5.0)]
        result = shift_segments(segs, 0.0)
        assert result[0].start_sec == pytest.approx(2.0)
        assert result[0].end_sec == pytest.approx(5.0)
