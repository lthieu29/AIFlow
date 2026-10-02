"""EpubNovelAdapter — converts an EPUB novel into scenes via 3-tier mode.

Input (``AdapterInput``):
    - ``raw_content``:  Path to the ``.epub`` file (as a string).
    - ``options``:      Dict with optional keys:

      ``tier`` (str)
          Force a specific tier: ``"direct"``, ``"episode"``, or ``"manual"``.
          When omitted the tier is auto-classified from the book's word count.

      ``chapter_start`` (int)
          0-based index of the first chapter to include (Tier 3 only).

      ``chapter_end`` (int)
          0-based index of the last chapter to include, inclusive (Tier 3).

      ``project_id`` (str)
          Identifier for the owning project.  Defaults to the book title.

      ``voice`` (str)
          TTS voice preference.  Defaults to ``"vi-VN-HoaiMyNeural"``.

      ``episode_max_words`` (int)
          Override the per-episode word-count limit for Tier 2.

Output:
    - Tier 1 / Tier 3 → :class:`~server.content.base.SceneList`
    - Tier 2           → :class:`~server.content.adapters.epub_novel.tiers.EpisodeList`

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from server.content.adapters.epub_novel.quality_gates import (
    EpubGateResult,
    check_epub_skill,
    run_character_gate,
    run_plot_gate,
    run_style_gate,
)
from server.content.adapters.epub_novel.tiers import (
    EPISODE_MAX_WORDS,
    TIER1_MAX_WORDS,
    EpisodeList,
    ProcessingTier,
    classify_tier,
    process_tier1,
    process_tier2,
    process_tier3,
)
from server.content.base import AdapterError, AdapterInput, SceneList
from server.content.epub.parser import EpubParseError, parse_epub
from server.pipeline.gates.epub_checkpoints import EpubSkillRestrictionError

logger = logging.getLogger(__name__)

# ─── EpubNovelAdapter ─────────────────────────────────────────────────────────


class EpubNovelAdapter:
    """ContentAdapter for EPUB novels with 3-tier processing mode.

    Tier 1 — direct
        Short novels (≤ :data:`~server.content.adapters.epub_novel.tiers.TIER1_MAX_WORDS`
        words) are processed in a single pass.  Returns a
        :class:`~server.content.base.SceneList`.

    Tier 2 — episode
        Long novels are automatically split into episodes.  Returns an
        :class:`~server.content.adapters.epub_novel.tiers.EpisodeList`.

    Tier 3 — manual range
        The user selects a chapter range via ``chapter_start`` / ``chapter_end``
        in ``AdapterInput.options``.  Returns a
        :class:`~server.content.base.SceneList`.

    Attributes:
        adapter_type: Registry key — ``"epub_novel"``.
    """

    adapter_type: str = "epub_novel"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(
        self,
        input: AdapterInput,  # noqa: A002
    ) -> Union[SceneList, EpisodeList]:
        """Parse an EPUB file and return scenes via the appropriate tier.

        Args:
            input: Adapter input whose ``raw_content`` is the path to an
                   ``.epub`` file.

        Returns:
            A :class:`~server.content.base.SceneList` (Tier 1 / Tier 3) or
            an :class:`~server.content.adapters.epub_novel.tiers.EpisodeList`
            (Tier 2).

        Raises:
            :class:`~server.content.base.AdapterError`: On validation failure,
                missing file, or parse error.
        """
        # 1. Validate input
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid epub_novel input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        # 1b. Enforce skill restriction — EPUB novel only works with kdrama-romance.
        try:
            check_epub_skill(input.skill_name)
        except EpubSkillRestrictionError as exc:
            raise AdapterError(
                "ADAPTER_SKILL_RESTRICTED",
                str(exc),
                details={
                    "requested_skill": exc.requested_skill,
                    "allowed_skill": exc.allowed_skill,
                },
            ) from exc

        # 2. Parse EPUB
        epub_path = Path(input.raw_content.strip())
        try:
            book = parse_epub(epub_path)
        except EpubParseError as exc:
            raise AdapterError(
                "ADAPTER_PARSE_ERROR",
                f"Failed to parse EPUB: {exc.message}",
                details={"path": str(epub_path)},
            ) from exc

        # 3. Extract options
        opts = input.options or {}
        project_id: str = opts.get("project_id") or book.title or "epub_novel"
        voice: str = opts.get("voice", "vi-VN-HoaiMyNeural")
        episode_max_words: int = int(opts.get("episode_max_words", EPISODE_MAX_WORDS))

        # chapter_start / chapter_end for Tier 3
        chapter_start: int | None = (
            int(opts["chapter_start"]) if "chapter_start" in opts else None
        )
        chapter_end: int | None = (
            int(opts["chapter_end"]) if "chapter_end" in opts else None
        )

        # force_tier override
        force_tier: ProcessingTier | None = None
        if "tier" in opts:
            try:
                force_tier = ProcessingTier(opts["tier"])
            except ValueError:
                valid = [t.value for t in ProcessingTier]
                raise AdapterError(
                    "ADAPTER_INVALID_INPUT",
                    f"Unknown tier {opts['tier']!r}. Valid values: {valid}",
                )

        # 4. Classify tier
        tier = classify_tier(
            book,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            force_tier=force_tier,
        )

        logger.info(
            "EpubNovelAdapter: book=%r, words=%d, tier=%s",
            book.title,
            book.total_words,
            tier.value,
        )

        # 5. EG1 — Character Gate: extract characters and pause for user review.
        from server.content.epub.parser import extract_characters

        characters = extract_characters(book)
        eg1_result: EpubGateResult = await run_character_gate(
            characters,
            project_id=None,  # No DB session in adapter layer; gate is informational.
        )
        logger.info(
            "EpubNovelAdapter: EG1 gate status=%s, characters=%d",
            eg1_result.status,
            len(characters),
        )

        # 6. Dispatch to tier processor
        if tier == ProcessingTier.DIRECT:
            scene_list = process_tier1(book, project_id=project_id, voice=voice)

        elif tier == ProcessingTier.EPISODE:
            return process_tier2(
                book,
                project_id=project_id,
                voice=voice,
                episode_max_words=episode_max_words,
            )

        else:
            # Tier 3 — manual range
            if chapter_start is None or chapter_end is None:
                raise AdapterError(
                    "ADAPTER_INVALID_INPUT",
                    "Tier 3 (manual) requires both 'chapter_start' and 'chapter_end' "
                    "in options.",
                )
            scene_list = process_tier3(
                book,
                project_id=project_id,
                chapter_start=chapter_start,
                chapter_end=chapter_end,
                voice=voice,
            )

        # 7. EG2 — Plot Gate: review scene/chapter breakdown before Veo3 calls.
        eg2_result: EpubGateResult = await run_plot_gate(
            scene_list,
            project_id=None,
        )
        logger.info(
            "EpubNovelAdapter: EG2 gate status=%s, scenes=%d",
            eg2_result.status,
            len(scene_list.scenes),
        )

        # 8. EG3 — Style Gate: review skill style configuration.
        style_info = {
            "skill_name": input.skill_name or "kdrama-romance",
            "book_title": book.title,
            "tier": tier.value,
        }
        eg3_result: EpubGateResult = await run_style_gate(
            style_info,
            project_id=None,
        )
        logger.info(
            "EpubNovelAdapter: EG3 gate status=%s, skill=%r",
            eg3_result.status,
            style_info["skill_name"],
        )

        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Validate the adapter input without calling any external APIs.

        Checks:
        - ``raw_content`` is non-empty and points to an existing ``.epub`` file.
        - If ``tier`` is provided in options, it must be a valid
          :class:`~server.content.adapters.epub_novel.tiers.ProcessingTier` value.
        - If ``chapter_start`` / ``chapter_end`` are provided, they must be
          non-negative integers with ``chapter_end >= chapter_start``.

        Args:
            input: The adapter input to validate.

        Returns:
            A list of human-readable error strings.  Empty list = valid.
        """
        errors: list[str] = []

        if not input.raw_content or not input.raw_content.strip():
            errors.append("raw_content must be a path to an .epub file")
            return errors  # no point checking further

        epub_path = Path(input.raw_content.strip())
        if not epub_path.exists():
            errors.append(f"EPUB file not found: {epub_path}")
        elif epub_path.suffix.lower() != ".epub":
            errors.append(
                f"raw_content must point to a .epub file, got: {epub_path.suffix!r}"
            )

        opts = input.options or {}

        # Validate tier option
        if "tier" in opts:
            valid_tiers = {t.value for t in ProcessingTier}
            if opts["tier"] not in valid_tiers:
                errors.append(
                    f"options.tier must be one of {sorted(valid_tiers)}, "
                    f"got {opts['tier']!r}"
                )

        # Validate chapter range
        chapter_start = opts.get("chapter_start")
        chapter_end = opts.get("chapter_end")

        if chapter_start is not None:
            try:
                cs = int(chapter_start)
                if cs < 0:
                    errors.append("options.chapter_start must be >= 0")
            except (TypeError, ValueError):
                errors.append("options.chapter_start must be an integer")
                cs = None
        else:
            cs = None

        if chapter_end is not None:
            try:
                ce = int(chapter_end)
                if ce < 0:
                    errors.append("options.chapter_end must be >= 0")
                elif cs is not None and ce < cs:
                    errors.append(
                        f"options.chapter_end ({ce}) must be >= "
                        f"options.chapter_start ({cs})"
                    )
            except (TypeError, ValueError):
                errors.append("options.chapter_end must be an integer")

        # Tier 3 requires both chapter_start and chapter_end
        tier_val = opts.get("tier")
        if tier_val == ProcessingTier.MANUAL.value:
            if chapter_start is None:
                errors.append(
                    "options.chapter_start is required when tier='manual'"
                )
            if chapter_end is None:
                errors.append(
                    "options.chapter_end is required when tier='manual'"
                )

        return errors


# ─── Module-level auto-discovery exports ─────────────────────────────────────

#: Shared instance used by :class:`~server.content.registry.AdapterRegistry`
#: auto-discovery (``ADAPTER`` convention).
ADAPTER: EpubNovelAdapter = EpubNovelAdapter()

#: Class reference for registry ``ADAPTER_CLASS`` convention.
ADAPTER_CLASS = EpubNovelAdapter
