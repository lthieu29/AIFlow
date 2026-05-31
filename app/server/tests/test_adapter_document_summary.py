"""Task 8.7 — Integration test for ``DocumentSummaryAdapter`` per-chunk fallback.

**Validates: Requirements 4.5, 4.6**

When a Gemini client is configured but ONE of its per-chunk calls raises,
the adapter must fall back to local text only for THAT chunk, and the rest
of the chunks must still be summarised through the LLM.  The result must
be a complete ``SceneList`` (no all-or-nothing failure).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.content.adapters.document_summary.adapter import (
    DocumentSummaryAdapter,
)
from server.content.base import AdapterError, AdapterInput


def _run(coro):
    return asyncio.run(coro)


# ─── Helpers ─────────────────────────────────────────────────────────────────


_LONG_TEXT = (
    "AIFlow is a personal AI video tool. It combines Veo3 visuals with Gemini scripting. "
    "Native Windows is the target platform, no WSL required. The pipeline turns ideas into polished videos. "
    "Users supply input as text, images, or even URLs. The system handles every stage automatically. "
    "Output is rendered as a vertical 1080 by 1920 video clip ready for sharing. "
    "Every adapter is data-driven and discoverable through a registry. "
    "Skills are pure data; they describe style, not behaviour. "
    "Visual templates use HTML and GSAP for overlays."
)


# ─── R4.5 — per-chunk LLM fallback (one chunk fails, rest succeed) ───────────


def test_per_chunk_fallback_one_chunk_fails(tmp_path: Path) -> None:
    """**R4.5** — LLM call fails on ONE chunk → that chunk falls back to local
    text; the other chunks still go through the LLM.  Final SceneList contains
    all chunks (no all-or-nothing failure)."""

    # Track which chunk indices the LLM is asked about
    calls: list[str] = []

    class _PartialClient:
        """Fakes Gemini: succeeds for most prompts, raises on the 2nd call."""

        def __init__(self) -> None:
            self.invocations = 0

        def generate_text(self, prompt: str) -> str:
            calls.append(prompt[:60])
            self.invocations += 1
            if self.invocations == 2:
                raise RuntimeError("simulated LLM hiccup on chunk #2")
            return f"[LLM SUMMARY {self.invocations}]"

    client = _PartialClient()
    adapter = DocumentSummaryAdapter()
    inp = AdapterInput(
        source_type="document",
        raw_content=_LONG_TEXT,
        options={"gemini_client": client},
    )

    scene_list = _run(adapter.adapt(inp))
    ok, errors = scene_list.validate()
    assert ok, errors

    # The LLM was invoked for several chunks
    assert client.invocations >= 2

    narrations = [s.narration for s in scene_list.scenes]
    # At least one scene's narration is an LLM-prefixed summary
    assert any(
        n and n.startswith("[LLM SUMMARY") for n in narrations
    ), f"No LLM-summarised scene found; narrations: {narrations}"

    # And at least one scene's narration is the raw fallback chunk
    # (not LLM-prefixed) — that's the chunk whose call raised.
    assert any(
        n and not n.startswith("[LLM SUMMARY") for n in narrations
    ), f"Per-chunk fallback did not surface; narrations: {narrations}"


def test_no_client_uses_full_local_chunking() -> None:
    """When no client is configured, all narrations are local text — no
    ``[LLM SUMMARY ...]`` prefix appears anywhere."""
    adapter = DocumentSummaryAdapter()
    scene_list = _run(
        adapter.adapt(
            AdapterInput(source_type="document", raw_content=_LONG_TEXT)
        )
    )
    for spec in scene_list.scenes:
        assert spec.narration is not None
        assert not spec.narration.startswith("[LLM SUMMARY")


# ─── R4.6 — validate_input is local-only ────────────────────────────────────


def test_validate_input_does_not_call_llm() -> None:
    """``validate_input`` must NOT call any LLM, even when a client is configured."""
    poison = object()  # any access would AttributeError, proving no call

    adapter = DocumentSummaryAdapter()
    inp = AdapterInput(
        source_type="document",
        raw_content=_LONG_TEXT,
        options={"gemini_client": poison},
    )
    errors = adapter.validate_input(inp)
    assert errors == []


def test_validate_input_rejects_unsupported_extension(tmp_path: Path) -> None:
    """**R4.6** — local format check rejects unsupported document formats."""
    bogus = tmp_path / "doc.txt"
    bogus.write_text("plain text", encoding="utf-8")
    adapter = DocumentSummaryAdapter()
    errors = adapter.validate_input(
        AdapterInput(
            source_type="document",
            raw_content="",
            assets={"document": bogus},
        )
    )
    assert errors
    assert any(".txt" in e or "Unsupported" in e for e in errors)
