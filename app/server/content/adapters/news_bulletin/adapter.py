"""NewsBulletinAdapter — turns an RSS/Atom feed into a news-bulletin SceneList.

Input (``AdapterInput.raw_content``):
- Raw RSS/Atom XML, OR
- A feed URL (``http://`` / ``https://``) fetched in :meth:`adapt`.

Processing:
1. ``validate_input()`` — local-only well-formedness checks (R4.6).
   For raw XML it parses locally to confirm a feed structure; for a URL it
   only checks the URL is well-formed.  It CANNOT detect "URL is valid HTML
   but not a feed" — that surfaces in :meth:`adapt` as ``ADAPTER_FETCH_ERROR``.
2. Parse the feed (``feedparser``); each item → one bulletin scene
   (headline + summary).

Auto-discovery convention:
    ``ADAPTER``       — module-level instance (used by AdapterRegistry)
    ``ADAPTER_CLASS`` — module-level class reference
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from server.content.base import (
    AdapterError,
    AdapterInput,
    SceneList,
    SceneSpec,
)
from server.content.duration_estimator import estimate_scene_duration
from server.content.pipeline_limits import enforce_pipeline_limits

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION = 8.0
_DEFAULT_VOICE = "vi-VN-HoaiMyNeural"

_SCENE_PROMPT_TEMPLATE = (
    "News bulletin scene. Headline: {headline}. "
    "Clean broadcast-style composition, lower-third friendly, neutral studio background."
)


def _import_feedparser():
    """Lazy import of the optional ``feedparser`` dependency."""
    try:
        import feedparser  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "feedparser is required to process RSS/Atom feeds. "
            "Install it with: pip install feedparser",
            details={"missing_package": "feedparser"},
        ) from exc
    return feedparser


def _looks_like_url(text: str) -> bool:
    return text.strip().startswith(("http://", "https://"))


class NewsBulletinAdapter:
    """ContentAdapter for RSS/Atom news feeds.

    Attributes:
        adapter_type: Registry key — ``"news_bulletin"``.
    """

    adapter_type: str = "news_bulletin"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Parse a feed (XML or URL) and return a :class:`SceneList`."""
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid news_bulletin input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        feedparser = _import_feedparser()
        raw = input.raw_content.strip()

        if _looks_like_url(raw):
            try:
                parsed = feedparser.parse(raw)
            except Exception as exc:  # noqa: BLE001
                raise AdapterError(
                    "ADAPTER_FETCH_ERROR",
                    f"Failed to fetch feed from URL {raw!r}: {exc}",
                    details={"url": raw, "error": str(exc)},
                ) from exc
        else:
            parsed = feedparser.parse(raw)

        entries = getattr(parsed, "entries", []) or []
        if not entries:
            raise AdapterError(
                "ADAPTER_FETCH_ERROR",
                "Feed contained no items — the source may not be a valid RSS/Atom feed.",
                details={"source": raw[:200]},
            )

        max_items = int(input.options.get("max_items", 0) or 0)
        if max_items > 0:
            entries = entries[:max_items]

        scenes = [
            self._entry_to_scene(order, entry)
            for order, entry in enumerate(entries)
        ]

        if input.skill_name:
            scenes = _apply_skill(scenes, input.skill_name, self.adapter_type)

        feed_title = getattr(getattr(parsed, "feed", None), "get", lambda *_: "")("title", "")

        scene_list = SceneList(
            project_id=input.options.get("project_id", "news_bulletin"),
            scenes=scenes,
            voice=input.options.get("voice", _DEFAULT_VOICE),
            metadata={
                "adapter": self.adapter_type,
                "scene_count": len(scenes),
                "skill_name": input.skill_name,
                "feed_title": feed_title,
            },
        )

        ok, validation_errors = scene_list.validate()
        if not ok:
            raise AdapterError(
                "ADAPTER_INVALID_OUTPUT",
                f"Generated SceneList failed validation: {'; '.join(validation_errors)}",
                details={"errors": validation_errors},
            )
        enforce_pipeline_limits(scene_list)

        logger.debug("NewsBulletinAdapter: generated %d scenes", len(scenes))
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Cheap local validation — no network calls (R4.6).

        For a URL: only checks the URL is well-formed (http/https + netloc).
        For raw XML: parses locally and checks at least a feed-like structure.
        Cannot detect "valid URL that is HTML, not a feed" without network.
        """
        errors: list[str] = []
        raw = (input.raw_content or "").strip()

        if not raw:
            errors.append("raw_content must not be empty — expected RSS/Atom XML or a feed URL")
            return errors

        if _looks_like_url(raw):
            parsed = urlparse(raw)
            if parsed.scheme not in ("http", "https"):
                errors.append(f"URL scheme must be http/https, got {parsed.scheme!r}")
            if not parsed.netloc:
                errors.append("URL must have a non-empty host (netloc)")
            return errors

        # Raw content path — must look like XML (start with '<') so we never
        # hand a stray URL-like string to feedparser, which would attempt a
        # network fetch.  Verify it parses to a feed-like structure locally.
        if not raw.lstrip().startswith("<"):
            errors.append(
                "raw_content must be either an http/https feed URL or RSS/Atom XML "
                "(starting with '<')"
            )
            return errors

        feedparser = _import_feedparser()
        parsed_feed = feedparser.parse(raw)
        version = getattr(parsed_feed, "version", "") or ""
        entries = getattr(parsed_feed, "entries", []) or []
        if not version and not entries:
            errors.append(
                "raw_content does not appear to be a valid RSS/Atom feed"
            )
        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _entry_to_scene(self, order: int, entry: object) -> SceneSpec:
        get = getattr(entry, "get", None)
        if callable(get):
            headline = (get("title", "") or "").strip()
            summary = (get("summary", "") or get("description", "") or "").strip()
        else:  # pragma: no cover - defensive
            headline = str(getattr(entry, "title", "")).strip()
            summary = str(getattr(entry, "summary", "")).strip()

        narration = headline
        if summary:
            narration = f"{headline}. {summary}" if headline else summary

        prompt = _SCENE_PROMPT_TEMPLATE.format(headline=headline[:200] or "news item")
        duration = estimate_scene_duration(narration) if narration else _DEFAULT_DURATION

        return SceneSpec(
            order=order,
            prompt=prompt,
            duration=duration,
            narration=narration if narration else None,
        )


def _apply_skill(
    scenes: list[SceneSpec],
    skill_name: str,
    adapter_type: str,
) -> list[SceneSpec]:
    """Apply a skill's prefix to all scene prompts (best-effort)."""
    try:
        from server.content.skill_loader import SkillLoader, apply_skill_to_scene

        adapter_dir = Path(__file__).resolve().parent
        app_dir = adapter_dir.parents[3]
        skills_dir = app_dir / "skills"

        loader = SkillLoader(skills_dir)
        skill = loader.load(skill_name)
        return [apply_skill_to_scene(scene, skill) for scene in scenes]
    except FileNotFoundError:
        logger.warning(
            "%s: skill %r not found — skipping skill application",
            adapter_type, skill_name,
        )
        return scenes
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s: failed to apply skill %r: %s — skipping",
            adapter_type, skill_name, exc,
        )
        return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

ADAPTER: NewsBulletinAdapter = NewsBulletinAdapter()
ADAPTER_CLASS = NewsBulletinAdapter
