"""DocumentSummaryAdapter — turns a PDF/Word document into a summarised SceneList.

Input:
- ``AdapterInput.assets["document"]`` — path to a ``.pdf`` or ``.docx`` file
  (preferred), OR
- ``AdapterInput.raw_content`` — plain text to summarise directly.

Processing:
1. ``validate_input()`` — local-only checks (file exists, supported format,
   structural integrity via :func:`validate_document_local`).  No network/LLM.
2. Extract text locally via :func:`extract_text`.
3. Summarise the text into scenes:
   - With a ``gemini_client`` in ``options``: summarise PER CHUNK via the LLM.
     A failure on ONE chunk falls back to local sentence-chunking for THAT
     chunk only (per-chunk fallback, not all-or-nothing) — R4.5.
   - Without a client: local sentence-chunking for the whole document.
4. Each chunk becomes a :class:`~server.content.base.SceneSpec`.

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
    SceneList,
    SceneSpec,
)
from server.content.adapters.document_summary.extractor import (
    extract_text,
    is_supported_format,
    validate_document_local,
)
from server.content.duration_estimator import estimate_scene_duration
from server.content.llm_chunking import (
    chunk_by_sentences,
    estimate_scene_count,
)
from server.content.pipeline_limits import enforce_pipeline_limits

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_DEFAULT_DURATION = 8.0
_DEFAULT_VOICE = "vi-VN-HoaiMyNeural"
_DOCUMENT_ASSET_KEY = "document"

_SCENE_PROMPT_TEMPLATE = (
    "Explainer video scene summarising a document. {summary} "
    "Clean informative composition, neutral background, friendly for text overlay."
)

_SUMMARISE_PROMPT_TEMPLATE = (
    "Summarise the following text into a single concise narration sentence "
    "(max 2 sentences) suitable for a short explainer video. "
    "Return ONLY the summary text, no preamble.\n\n{text}"
)


class DocumentSummaryAdapter:
    """ContentAdapter that summarises a PDF/Word document into video scenes.

    Attributes:
        adapter_type: Registry key — ``"document_summary"``.
    """

    adapter_type: str = "document_summary"

    # ── ContentAdapter Protocol ───────────────────────────────────────────────

    async def adapt(self, input: AdapterInput) -> SceneList:  # noqa: A002
        """Extract, summarise, and return a :class:`SceneList`."""
        errors = self.validate_input(input)
        if errors:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                f"Invalid document_summary input: {'; '.join(errors)}",
                details={"errors": errors},
            )

        # 1. Obtain document text (file asset preferred, else raw_content)
        doc_path = input.assets.get(_DOCUMENT_ASSET_KEY)
        if doc_path is not None:
            text = extract_text(Path(doc_path))
        else:
            text = input.raw_content or ""

        text = text.strip()
        if not text:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "Document produced no extractable text.",
            )

        # 2. Decide scene count + split into base chunks (local, deterministic)
        n_scenes = estimate_scene_count(text)
        max_chars = max(50, len(text) // max(1, n_scenes))
        base_chunks = chunk_by_sentences(text, max_chars_per_chunk=max_chars)
        if not base_chunks:
            raise AdapterError(
                "ADAPTER_INVALID_INPUT",
                "Document could not be split into scenes.",
            )

        # 3. Summarise each chunk (per-chunk LLM fallback — R4.5)
        gemini_client = input.options.get("gemini_client")
        narrations = [
            self._summarise_chunk(chunk, gemini_client) for chunk in base_chunks
        ]

        # 4. Build scenes
        scenes = [
            self._to_scene_spec(order, narration)
            for order, narration in enumerate(narrations)
        ]

        if input.skill_name:
            scenes = _apply_skill(scenes, input.skill_name, self.adapter_type)

        scene_list = SceneList(
            project_id=input.options.get("project_id", "document_summary"),
            scenes=scenes,
            voice=input.options.get("voice", _DEFAULT_VOICE),
            metadata={
                "adapter": self.adapter_type,
                "scene_count": len(scenes),
                "skill_name": input.skill_name,
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

        logger.debug(
            "DocumentSummaryAdapter: generated %d scenes", len(scenes)
        )
        return scene_list

    def validate_input(self, input: AdapterInput) -> list[str]:  # noqa: A002
        """Cheap local validation — no network/LLM calls (R4.6)."""
        errors: list[str] = []

        doc_path = input.assets.get(_DOCUMENT_ASSET_KEY)
        if doc_path is not None:
            path = Path(doc_path)
            if not is_supported_format(path):
                errors.append(
                    f"Unsupported document format {path.suffix!r}. Supported: .pdf, .docx"
                )
            errors.extend(validate_document_local(path))
            return errors

        if not input.raw_content or not input.raw_content.strip():
            errors.append(
                "Provide a document via assets['document'] or non-empty raw_content"
            )

        return errors

    # ── Private helpers ───────────────────────────────────────────────────────

    def _summarise_chunk(self, chunk: str, gemini_client: object | None) -> str:
        """Summarise a single chunk, falling back to local text on failure.

        Per-chunk fallback (R4.5): if the LLM call for this chunk fails, the
        chunk's own (trimmed) text is used instead of aborting the whole job.
        """
        chunk = chunk.strip()
        if gemini_client is None:
            return chunk

        try:
            prompt = _SUMMARISE_PROMPT_TEMPLATE.format(text=chunk)
            summary = gemini_client.generate_text(prompt)
            summary = (summary or "").strip()
            return summary if summary else chunk
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "document_summary: LLM summarisation failed for a chunk (%s) — "
                "falling back to local text for this chunk only.",
                exc,
            )
            return chunk

    def _to_scene_spec(self, order: int, narration: str) -> SceneSpec:
        narration = narration.strip()
        first = narration.split(".")[0].strip() if narration else ""
        prompt = _SCENE_PROMPT_TEMPLATE.format(
            summary=(first[:200] or narration[:200])
        )
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
        app_dir = adapter_dir.parents[3]  # app/
        skills_dir = app_dir / "skills"

        loader = SkillLoader(skills_dir)
        skill = loader.load(skill_name)
        return [apply_skill_to_scene(scene, skill) for scene in scenes]
    except FileNotFoundError:
        logger.warning(
            "%s: skill %r not found — skipping skill application",
            adapter_type,
            skill_name,
        )
        return scenes
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "%s: failed to apply skill %r: %s — skipping",
            adapter_type,
            skill_name,
            exc,
        )
        return scenes


# ─── Module-level auto-discovery exports ─────────────────────────────────────

ADAPTER: DocumentSummaryAdapter = DocumentSummaryAdapter()
ADAPTER_CLASS = DocumentSummaryAdapter
