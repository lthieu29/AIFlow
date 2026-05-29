"""BlogArticleAdapter — converts a blog article URL or plain text into a SceneList.

Input (``AdapterInput.raw_content``):
- A URL string (``http://`` or ``https://``) → fetched and extracted via
  :func:`~server.content.adapters.blog_article.fetcher.fetch_article`.
- Plain article text → used directly.

Processing:
1. If URL: fetch HTML, extract readable text via
   :func:`~server.content.adapters.blog_article.fetcher.extract_text_from_html`.
2. Estimate scene count from text length via
   :func:`~server.content.llm_chunking.estimate_scene_count`.
3. Use :func:`~server.content.llm_chunking.llm_chunk_to_scenes` (with the
   Gemini client from ``input.options["gemini_client"]``, or ``None`` for
   sentence-based fallback) to split text into *n_scenes* chunks.
4. Each chunk becomes a :class:`~server.content.base.SceneSpec` with a
   visual prompt and narration derived from the chunk text.

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import logging
from pathlib import Path

from server.content.base import (
    AdapterError,
    AdapterInput,
    ContentAdapter,
    SceneList,
    SceneSpec,
)
from server.content.adapters.blog_article.fetcher import FetchedArticle, fetch_article
from server.content.duration_estimator import estimate_scene_duration
from server.content.llm_chunking import estimate_scene_count, llm_chunk_to_scenes

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION = 8.0  # seconds — used when narration is empty
_DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

# Visual prompt template for explainer-style video scenes
_SCENE_PROMPT_TEMPLATE = (
    "Explainer video scene. {narration_summary} "
    "Clean, informative visual. Neutral background. "
    "Text overlay friendly composition."
)


# ─── BlogArticleAdapter ───────────────────────────────────────────────────────


class BlogArticleAdapter:
    """ContentAdapter for blog article URLs or plain article text.

    Fetches the article (if a URL is given), extracts readable text, then
    uses LLM chunking to split the content into video scenes.

    Attributes:
        adapter_type: Registry key — ``"blog_article"``.
    """

    adapter_type: str = "blog_article"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse a blog article URL or plain text and return a :class:`SceneList`.

        Args:
            input: Adapter input whose ``raw_content`` is either a URL string
                   or plain article text.  Optional keys in ``input.options``:

                   - ``"gemini_client"`` — a
                     :class:`~server.ai.gemini.GeminiClient` instance for LLM
                     chunking (falls back to sentence-based if absent).
                   - ``"project_id"`` — project identifier for the SceneList.
                   - ``"voice"`` — TTS voice preference.
                   - ``"target_duration_per_scene"`` — float, seconds per scene
                     (default 8.0).

        Returns:
            A :class:`~server.content.base.SceneList` with one scene per
            article chunk.

        Raises:
            :class:`~server.content.base.AdapterError`: On validation failure,
                fetch errors, or if no scenes could be produced.
        """
        # 1. Validate input
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid blog_article input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        raw = input.raw_content.strip()

        # 2. Determine article title + text
        article_title = ""
        article_text = ""

        if _is_url(raw):
            try:
                article: FetchedArticle = await fetch_article(raw)
                article_title = article.title
                article_text = article.text
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(
                    "ADAPTER_FETCH_ERROR",
                    f"Failed to fetch article from URL {raw!r}: {exc}",
                    details={"url": raw, "error": str(exc)},
                ) from exc
        else:
            # Plain text — use directly
            article_text = raw

        if not article_text or not article_text.strip():
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "Article text is empty — could not extract readable content.",
            )

        # 3. Estimate scene count
        target_duration = float(
            input.options.get("target_duration_per_scene", _DEFAULT_DURATION)
        )
        n_scenes = estimate_scene_count(article_text, target_duration_per_scene=target_duration)
        # Clamp to a reasonable range
        n_scenes = max(1, min(n_scenes, 20))

        # 4. LLM chunking → chunks
        gemini_client = input.options.get("gemini_client", None)
        chunk_result = await llm_chunk_to_scenes(
            article_text,
            gemini_client=gemini_client,
            n_scenes=n_scenes,
        )

        if not chunk_result.chunks:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "LLM chunking produced no scenes from the article text.",
            )

        # 5. Convert chunks → SceneSpec list
        scenes = [
            self._chunk_to_scene_spec(order=i, chunk=chunk)
            for i, chunk in enumerate(chunk_result.chunks)
        ]

        # 6. Apply skill if requested
        if input.skill_name:
            scenes = self._apply_skill(scenes, input.skill_name)

        # 7. Assemble SceneList
        project_id = input.options.get("project_id", "blog_article")
        voice = input.options.get("voice", _DEFAULT_VOICE)

        scene_list = SceneList(
            project_id=project_id,
            scenes=scenes,
            voice=voice,
            metadata={
                "adapter": self.adapter_type,
                "scene_count": len(scenes),
                "skill_name": input.skill_name,
                "article_title": article_title,
                "source_url": raw if _is_url(raw) else None,
            },
        )

        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )

        logger.debug(
            "BlogArticleAdapter: generated %d scenes from article %r",
            len(scenes),
            article_title or raw[:60],
        )
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Validate the adapter input without calling any external APIs.

        Checks:
        - ``raw_content`` is non-empty and not whitespace-only.

        Args:
            input: The adapter input to validate.

        Returns:
            A list of human-readable error strings.  Empty list = valid.
        """
        errors: list[str] = []

        if not input.raw_content or not input.raw_content.strip():
            errors.append("raw_content must not be empty")

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _chunk_to_scene_spec(self, order: int, chunk: str) -> SceneSpec:
        """Convert a text chunk into a :class:`SceneSpec`.

        The visual prompt is derived from the chunk text (first sentence or
        truncated summary).  The narration is the full chunk text.

        Args:
            order: 0-based scene index.
            chunk: Text chunk for this scene.

        Returns:
            A :class:`SceneSpec` ready for the pipeline.
        """
        narration = chunk.strip()

        # Build a concise visual prompt from the first sentence of the chunk
        first_sentence = _first_sentence(narration)
        prompt = _SCENE_PROMPT_TEMPLATE.format(
            narration_summary=first_sentence[:200] if first_sentence else narration[:200]
        )

        duration = estimate_scene_duration(narration) if narration else _DEFAULT_DURATION

        return SceneSpec(
            order=order,
            prompt=prompt,
            duration=duration,
            narration=narration if narration else None,
        )

    def _apply_skill(
        self,
        scenes: list[SceneSpec],
        skill_name: str,
    ) -> list[SceneSpec]:
        """Apply a skill's prefix to all scene prompts.

        Loads the skill from the ``skills/`` directory relative to the
        project root.  If the skill cannot be loaded, logs a warning and
        returns the scenes unchanged.

        Args:
            scenes:     List of scenes to apply the skill to.
            skill_name: Name of the skill directory (e.g. ``"ecommerce-fashion"``).

        Returns:
            List of scenes with skill prefix applied (new SceneSpec objects).
        """
        try:
            from server.content.skill_loader import SkillLoader, apply_skill_to_scene

            # Resolve skills directory relative to this file's package root
            # server/content/adapters/blog_article/adapter.py
            # → go up 4 levels to reach app/, then skills/
            adapter_dir = Path(__file__).resolve().parent
            app_dir = adapter_dir.parents[3]  # app/
            skills_dir = app_dir / "skills"

            loader = SkillLoader(skills_dir)
            skill = loader.load(skill_name)
            return [apply_skill_to_scene(scene, skill) for scene in scenes]

        except FileNotFoundError:
            logger.warning(
                "BlogArticleAdapter: skill %r not found — skipping skill application",
                skill_name,
            )
            return scenes
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "BlogArticleAdapter: failed to apply skill %r: %s — skipping",
                skill_name,
                exc,
            )
            return scenes


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _is_url(text: str) -> bool:
    """Return True if *text* looks like an HTTP/HTTPS URL."""
    return text.startswith(("http://", "https://"))


def _first_sentence(text: str) -> str:
    """Return the first sentence of *text*, or the whole text if no boundary found."""
    import re

    m = re.search(r"(?<=[.!?])\s", text)
    if m:
        return text[: m.start() + 1].strip()
    return text.strip()


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: BlogArticleAdapter = BlogArticleAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = BlogArticleAdapter
