"""Unit tests for Task 4.3 — BlogArticleAdapter.

Covers:
- fetcher.py: extract_text_from_html, fetch_article (mocked HTTP)
  - URL detection
  - HTML extraction (stdlib fallback)
  - HTTP error handling
  - Empty / invalid input
- adapter.py: BlogArticleAdapter.validate_input, adapt (async)
  - URL input → fetch + extract + chunk → SceneList
  - Plain text input → chunk → SceneList
  - Scene count, order, duration, prompt, narration
  - Skill application (best-effort)
  - Invalid input raises AdapterError
  - Fetch error raises AdapterError
- Auto-discovery: ADAPTER instance and ADAPTER_CLASS exports
- Integration: 1 blog URL → explainer video (SceneList)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the server package is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


# ─── Sample data ─────────────────────────────────────────────────────────────

SAMPLE_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <title>How Python Works</title>
  <style>body { font-family: sans-serif; }</style>
</head>
<body>
  <h1>How Python Works</h1>
  <p>Python is an interpreted, high-level programming language. It was created by Guido van Rossum.</p>
  <p>Python uses indentation to define code blocks. This makes the code very readable.</p>
  <p>The Python interpreter reads source code and executes it line by line.</p>
  <script>console.log("skip me");</script>
  <p>Python has a large standard library and a vibrant ecosystem of third-party packages.</p>
</body>
</html>
"""

SAMPLE_ARTICLE_TEXT = """\
Python is an interpreted, high-level programming language created by Guido van Rossum.
It uses indentation to define code blocks, making the code very readable.
The Python interpreter reads source code and executes it line by line.
Python has a large standard library and a vibrant ecosystem of third-party packages.
Many developers love Python for its simplicity and versatility.
It is widely used in web development, data science, machine learning, and automation.
"""

SAMPLE_URL = "https://example.com/how-python-works"


def _make_input(
    raw_content: str = SAMPLE_ARTICLE_TEXT,
    skill_name: str | None = None,
    options: dict | None = None,
) -> "AdapterInput":
    from server.content.base import AdapterInput

    return AdapterInput(
        source_type="blog_article",
        raw_content=raw_content,
        skill_name=skill_name,
        options=options or {},
    )


# ═════════════════════════════════════════════════════════════════════════════
# fetcher.py — extract_text_from_html
# ═════════════════════════════════════════════════════════════════════════════


class TestExtractTextFromHtml:
    def test_extracts_title(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        title, _ = extract_text_from_html(SAMPLE_HTML)
        assert "Python" in title

    def test_extracts_body_text(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        _, text = extract_text_from_html(SAMPLE_HTML)
        assert "Python" in text
        assert len(text) > 50

    def test_strips_script_tags(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        _, text = extract_text_from_html(SAMPLE_HTML)
        assert "console.log" not in text
        assert "skip me" not in text

    def test_strips_style_tags(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        _, text = extract_text_from_html(SAMPLE_HTML)
        assert "font-family" not in text

    def test_empty_html_returns_empty_strings(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        title, text = extract_text_from_html("")
        assert title == ""
        assert text == ""

    def test_whitespace_only_html_returns_empty_strings(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        title, text = extract_text_from_html("   \n  ")
        assert title == ""
        assert text == ""

    def test_returns_tuple_of_two_strings(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        result = extract_text_from_html(SAMPLE_HTML)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_html_without_title_tag(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        html = "<html><body><p>Some content here.</p></body></html>"
        title, text = extract_text_from_html(html)
        assert "Some content here" in text

    def test_html_entities_decoded(self):
        from server.content.adapters.blog_article.fetcher import extract_text_from_html

        html = "<html><body><p>Hello &amp; World &lt;test&gt;</p></body></html>"
        _, text = extract_text_from_html(html)
        assert "&amp;" not in text


# ═════════════════════════════════════════════════════════════════════════════
# fetcher.py — FetchedArticle dataclass
# ═════════════════════════════════════════════════════════════════════════════


class TestFetchedArticle:
    def test_dataclass_fields(self):
        from server.content.adapters.blog_article.fetcher import FetchedArticle

        article = FetchedArticle(
            url="https://example.com",
            title="Test Title",
            text="Some text content.",
            html="<html></html>",
        )
        assert article.url == "https://example.com"
        assert article.title == "Test Title"
        assert article.text == "Some text content."
        assert article.html == "<html></html>"


# ═════════════════════════════════════════════════════════════════════════════
# fetcher.py — fetch_article (mocked HTTP)
# ═════════════════════════════════════════════════════════════════════════════


class TestFetchArticle:
    @pytest.mark.asyncio
    async def test_fetch_returns_fetched_article(self):
        from server.content.adapters.blog_article.fetcher import FetchedArticle, fetch_article

        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_article(SAMPLE_URL)

        assert isinstance(result, FetchedArticle)
        assert result.url == SAMPLE_URL
        assert "Python" in result.title or "Python" in result.text

    @pytest.mark.asyncio
    async def test_fetch_sets_url_field(self):
        from server.content.adapters.blog_article.fetcher import fetch_article

        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_article(SAMPLE_URL)

        assert result.url == SAMPLE_URL

    @pytest.mark.asyncio
    async def test_fetch_stores_raw_html(self):
        from server.content.adapters.blog_article.fetcher import fetch_article

        mock_response = MagicMock()
        mock_response.text = SAMPLE_HTML
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_article(SAMPLE_URL)

        assert result.html == SAMPLE_HTML

    @pytest.mark.asyncio
    async def test_fetch_raises_on_empty_url(self):
        from server.content.adapters.blog_article.fetcher import fetch_article

        with pytest.raises(ValueError, match="empty"):
            await fetch_article("")

    @pytest.mark.asyncio
    async def test_fetch_raises_on_non_http_url(self):
        from server.content.adapters.blog_article.fetcher import fetch_article

        with pytest.raises(ValueError, match="http"):
            await fetch_article("ftp://example.com/file")

    @pytest.mark.asyncio
    async def test_fetch_raises_on_http_error(self):
        import httpx

        from server.content.adapters.blog_article.fetcher import fetch_article

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_article(SAMPLE_URL)

    @pytest.mark.asyncio
    async def test_fetch_whitespace_url_raises(self):
        from server.content.adapters.blog_article.fetcher import fetch_article

        with pytest.raises(ValueError):
            await fetch_article("   ")


# ═════════════════════════════════════════════════════════════════════════════
# BlogArticleAdapter.validate_input
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateInput:
    def _adapter(self):
        from server.content.adapters.blog_article.adapter import BlogArticleAdapter

        return BlogArticleAdapter()

    def test_valid_text_returns_empty_errors(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input())
        assert errors == []

    def test_valid_url_returns_empty_errors(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input(SAMPLE_URL))
        assert errors == []

    def test_empty_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="blog_article", raw_content="")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_whitespace_raw_content_returns_error(self):
        from server.content.base import AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="blog_article", raw_content="   \n  ")
        errors = adapter.validate_input(ai)
        assert any("empty" in e for e in errors)

    def test_minimal_content_is_valid(self):
        adapter = self._adapter()
        errors = adapter.validate_input(_make_input("Some article text."))
        assert errors == []


# ═════════════════════════════════════════════════════════════════════════════
# BlogArticleAdapter.adapt — plain text input
# ═════════════════════════════════════════════════════════════════════════════


class TestAdaptPlainText:
    def _adapter(self):
        from server.content.adapters.blog_article.adapter import BlogArticleAdapter

        return BlogArticleAdapter()

    @pytest.mark.asyncio
    async def test_returns_scene_list(self):
        from server.content.base import SceneList

        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert isinstance(result, SceneList)

    @pytest.mark.asyncio
    async def test_scene_list_validates(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        ok, errors = result.validate()
        assert ok is True, errors

    @pytest.mark.asyncio
    async def test_scenes_have_sequential_order(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for i, scene in enumerate(result.scenes):
            assert scene.order == i

    @pytest.mark.asyncio
    async def test_each_scene_has_prompt(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.prompt and scene.prompt.strip()

    @pytest.mark.asyncio
    async def test_each_scene_has_narration(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert scene.narration and scene.narration.strip()

    @pytest.mark.asyncio
    async def test_duration_within_bounds(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        for scene in result.scenes:
            assert 3.0 <= scene.duration <= 30.0

    @pytest.mark.asyncio
    async def test_metadata_contains_adapter_type(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["adapter"] == "blog_article"

    @pytest.mark.asyncio
    async def test_metadata_contains_scene_count(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["scene_count"] == len(result.scenes)

    @pytest.mark.asyncio
    async def test_default_voice_is_vietnamese(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.voice == "vi-VN-HoaiMyNeural"

    @pytest.mark.asyncio
    async def test_custom_voice_from_options(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(options={"voice": "vi-VN-NamMinhNeural"}))
        assert result.voice == "vi-VN-NamMinhNeural"

    @pytest.mark.asyncio
    async def test_empty_content_raises_adapter_error(self):
        from server.content.base import AdapterError, AdapterInput

        adapter = self._adapter()
        ai = AdapterInput(source_type="blog_article", raw_content="")
        with pytest.raises(AdapterError) as exc_info:
            await adapter.adapt(ai)
        assert exc_info.value.code == "ADAPTER_INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_project_id_from_options(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(options={"project_id": "my_blog_project"}))
        assert result.project_id == "my_blog_project"

    @pytest.mark.asyncio
    async def test_default_project_id(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.project_id == "blog_article"

    @pytest.mark.asyncio
    async def test_source_url_is_none_for_plain_text(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        assert result.metadata["source_url"] is None

    @pytest.mark.asyncio
    async def test_nonexistent_skill_does_not_raise(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input(skill_name="nonexistent-skill-xyz"))
        assert len(result.scenes) >= 1

    @pytest.mark.asyncio
    async def test_at_least_one_scene_produced(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input("Short article text."))
        assert len(result.scenes) >= 1

    @pytest.mark.asyncio
    async def test_cost_estimate_has_veo3_clips(self):
        adapter = self._adapter()
        result = await adapter.adapt(_make_input())
        cost = result.estimate_cost()
        assert cost["veo3_clips"] == len(result.scenes)


# ═════════════════════════════════════════════════════════════════════════════
# BlogArticleAdapter.adapt — URL input (mocked HTTP)
# ═════════════════════════════════════════════════════════════════════════════


class TestAdaptUrlInput:
    def _adapter(self):
        from server.content.adapters.blog_article.adapter import BlogArticleAdapter

        return BlogArticleAdapter()

    def _mock_fetch(self, article_text: str = SAMPLE_ARTICLE_TEXT, title: str = "Test Article"):
        """Return a mock for fetch_article that returns a FetchedArticle."""
        from server.content.adapters.blog_article.fetcher import FetchedArticle

        mock_article = FetchedArticle(
            url=SAMPLE_URL,
            title=title,
            text=article_text,
            html=SAMPLE_HTML,
        )
        return AsyncMock(return_value=mock_article)

    @pytest.mark.asyncio
    async def test_url_input_returns_scene_list(self):
        from server.content.base import SceneList

        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        assert isinstance(result, SceneList)

    @pytest.mark.asyncio
    async def test_url_input_scene_list_validates(self):
        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        ok, errors = result.validate()
        assert ok is True, errors

    @pytest.mark.asyncio
    async def test_url_input_stores_source_url_in_metadata(self):
        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        assert result.metadata["source_url"] == SAMPLE_URL

    @pytest.mark.asyncio
    async def test_url_input_stores_article_title_in_metadata(self):
        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(title="How Python Works"),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        assert result.metadata["article_title"] == "How Python Works"

    @pytest.mark.asyncio
    async def test_url_input_scenes_have_sequential_order(self):
        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        for i, scene in enumerate(result.scenes):
            assert scene.order == i

    @pytest.mark.asyncio
    async def test_url_input_each_scene_has_narration(self):
        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        for scene in result.scenes:
            assert scene.narration and scene.narration.strip()

    @pytest.mark.asyncio
    async def test_fetch_error_raises_adapter_error(self):
        import httpx

        from server.content.base import AdapterError

        adapter = self._adapter()
        mock_fetch = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )
        )
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            mock_fetch,
        ):
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(_make_input(SAMPLE_URL))
        assert exc_info.value.code == "ADAPTER_FETCH_ERROR"

    @pytest.mark.asyncio
    async def test_empty_article_text_raises_adapter_error(self):
        from server.content.base import AdapterError

        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(article_text=""),
        ):
            with pytest.raises(AdapterError) as exc_info:
                await adapter.adapt(_make_input(SAMPLE_URL))
        assert exc_info.value.code == "ADAPTER_INVALID_INPUT"

    @pytest.mark.asyncio
    async def test_url_input_duration_within_bounds(self):
        adapter = self._adapter()
        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            self._mock_fetch(),
        ):
            result = await adapter.adapt(_make_input(SAMPLE_URL))
        for scene in result.scenes:
            assert 3.0 <= scene.duration <= 30.0


# ═════════════════════════════════════════════════════════════════════════════
# BlogArticleAdapter — LLM chunking with mock Gemini client
# ═════════════════════════════════════════════════════════════════════════════


class TestAdaptWithGeminiClient:
    def _adapter(self):
        from server.content.adapters.blog_article.adapter import BlogArticleAdapter

        return BlogArticleAdapter()

    def _mock_gemini(self, chunks: list[str]) -> MagicMock:
        """Return a mock GeminiClient that returns a JSON array of chunks."""
        import json

        client = MagicMock()
        client.generate_text = MagicMock(return_value=json.dumps(chunks))
        return client

    @pytest.mark.asyncio
    async def test_gemini_client_used_for_chunking(self):
        """When a gemini_client is provided, LLM chunking is attempted."""
        import json

        adapter = self._adapter()
        chunks = [
            "Python is an interpreted language created by Guido van Rossum.",
            "It uses indentation to define code blocks, making code readable.",
            "Python has a large standard library and many third-party packages.",
        ]
        mock_gemini = self._mock_gemini(chunks)

        result = await adapter.adapt(
            _make_input(
                SAMPLE_ARTICLE_TEXT,
                options={"gemini_client": mock_gemini},
            )
        )

        # Gemini was called
        assert mock_gemini.generate_text.called
        # Scenes correspond to the chunks
        assert len(result.scenes) == len(chunks)

    @pytest.mark.asyncio
    async def test_gemini_chunks_appear_as_narration(self):
        adapter = self._adapter()
        chunks = [
            "First scene narration about Python basics.",
            "Second scene narration about Python features.",
        ]
        mock_gemini = self._mock_gemini(chunks)

        result = await adapter.adapt(
            _make_input(
                SAMPLE_ARTICLE_TEXT,
                options={"gemini_client": mock_gemini},
            )
        )

        narrations = [s.narration for s in result.scenes]
        assert chunks[0] in narrations
        assert chunks[1] in narrations

    @pytest.mark.asyncio
    async def test_fallback_when_gemini_fails(self):
        """When Gemini raises, sentence-based fallback is used."""
        adapter = self._adapter()
        mock_gemini = MagicMock()
        mock_gemini.generate_text = MagicMock(side_effect=Exception("API error"))

        result = await adapter.adapt(
            _make_input(
                SAMPLE_ARTICLE_TEXT,
                options={"gemini_client": mock_gemini},
            )
        )

        # Should still produce scenes via fallback
        assert len(result.scenes) >= 1
        ok, errors = result.validate()
        assert ok is True, errors


# ═════════════════════════════════════════════════════════════════════════════
# Auto-discovery exports
# ═════════════════════════════════════════════════════════════════════════════


class TestAutoDiscovery:
    def test_adapter_instance_exported(self):
        from server.content.adapters.blog_article.adapter import ADAPTER

        assert ADAPTER is not None
        assert ADAPTER.adapter_type == "blog_article"

    def test_adapter_class_exported(self):
        from server.content.adapters.blog_article.adapter import ADAPTER_CLASS

        assert ADAPTER_CLASS is not None
        assert ADAPTER_CLASS.adapter_type == "blog_article"

    def test_adapter_satisfies_protocol(self):
        from server.content.adapters.blog_article.adapter import ADAPTER
        from server.content.base import ContentAdapter

        assert isinstance(ADAPTER, ContentAdapter)

    def test_registry_auto_discover_finds_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        assert "blog_article" in registry.list_types()

    def test_registry_get_returns_correct_adapter(self):
        from server.content.registry import AdapterRegistry

        registry = AdapterRegistry()
        registry.auto_discover("server.content.adapters")
        adapter = registry.get("blog_article")
        assert adapter.adapter_type == "blog_article"


# ═════════════════════════════════════════════════════════════════════════════
# Integration: 1 blog URL → explainer video (SceneList)
# ═════════════════════════════════════════════════════════════════════════════


class TestBlogUrlToExplainerVideo:
    """End-to-end test: 1 blog URL → SceneList ready for explainer video pipeline."""

    @pytest.mark.asyncio
    async def test_blog_url_to_scene_list(self):
        """Simulate the full flow: blog URL → fetch → chunk → SceneList."""
        from server.content.adapters.blog_article.adapter import BlogArticleAdapter
        from server.content.adapters.blog_article.fetcher import FetchedArticle
        from server.content.base import AdapterInput, SceneList

        article_text = """\
        Artificial intelligence is transforming the way we work and live.
        Machine learning algorithms can now recognize images, translate languages, and generate text.
        Deep learning, a subset of machine learning, uses neural networks with many layers.
        These networks learn patterns from vast amounts of training data.
        Today, AI is used in healthcare, finance, transportation, and entertainment.
        The future of AI promises even more breakthroughs in science and technology.
        """

        mock_article = FetchedArticle(
            url="https://example.com/ai-explained",
            title="AI Explained: How Artificial Intelligence Works",
            text=article_text,
            html=f"<html><head><title>AI Explained</title></head><body>{article_text}</body></html>",
        )

        adapter = BlogArticleAdapter()
        ai = AdapterInput(
            source_type="blog_article",
            raw_content="https://example.com/ai-explained",
            options={"project_id": "test_ai_explainer"},
        )

        with patch(
            "server.content.adapters.blog_article.adapter.fetch_article",
            AsyncMock(return_value=mock_article),
        ):
            result = await adapter.adapt(ai)

        # Verify it's a valid SceneList
        assert isinstance(result, SceneList)
        ok, errors = result.validate()
        assert ok is True, f"SceneList validation failed: {errors}"

        # Verify structure
        assert len(result.scenes) >= 1
        for i, scene in enumerate(result.scenes):
            assert scene.order == i

        # Verify all scenes have content
        for scene in result.scenes:
            assert scene.prompt.strip()
            assert scene.narration and scene.narration.strip()
            assert 3.0 <= scene.duration <= 30.0

        # Verify metadata
        assert result.metadata["adapter"] == "blog_article"
        assert result.metadata["source_url"] == "https://example.com/ai-explained"
        assert result.metadata["article_title"] == "AI Explained: How Artificial Intelligence Works"

        # Verify cost estimate
        cost = result.estimate_cost()
        assert cost["veo3_clips"] == len(result.scenes)
        assert cost["total_video_duration_sec"] > 0
