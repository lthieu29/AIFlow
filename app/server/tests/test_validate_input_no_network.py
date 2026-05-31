"""Task 11.1 — ``validate_input`` must NOT make network/LLM calls.

**Property 8 (Validates: Requirements 1.12, 4.6)**

Uses ``pytest-socket`` to disable all socket I/O for the duration of these
tests.  For ``script_direct`` and the 5 new content-expansion adapters, we
assert that ``validate_input()``:

- Returns a non-empty list of human-readable errors for invalid input, AND
- Does NOT raise ``SocketBlockedError`` (i.e. it makes no network call).

Note: ``validate_input`` is also called inside ``adapt()`` as a defensive
pre-flight; this test only invokes the public ``validate_input()`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Disable socket I/O for every test in this module — any network call will
# raise ``SocketBlockedError`` and fail the test.
pytestmark = pytest.mark.disable_socket

from server.content.base import AdapterInput
from server.content.registry import AdapterRegistry


# ─── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def registry() -> AdapterRegistry:
    reg = AdapterRegistry()
    reg.auto_discover("server.content.adapters")
    return reg


# ─── Per-adapter invalid-input cases ─────────────────────────────────────────

# Each case is a tuple: (adapter_type, AdapterInput-with-bad-payload)
INVALID_CASES: list[tuple[str, AdapterInput]] = [
    # script_direct — empty raw_content
    (
        "script_direct",
        AdapterInput(source_type="script", raw_content=""),
    ),
    # script_direct — JSON without 'scenes'
    (
        "script_direct",
        AdapterInput(source_type="script", raw_content='{"foo": 1}'),
    ),
    # script_direct — malformed JSON
    (
        "script_direct",
        AdapterInput(source_type="script", raw_content="not json"),
    ),
    # document_summary — neither asset nor raw_content
    (
        "document_summary",
        AdapterInput(source_type="document", raw_content=""),
    ),
    # lyric_video — empty
    (
        "lyric_video",
        AdapterInput(source_type="lyric", raw_content=""),
    ),
    # news_bulletin — bad URL scheme
    (
        "news_bulletin",
        AdapterInput(source_type="news", raw_content="ftp://example.com/feed"),
    ),
    # news_bulletin — empty
    (
        "news_bulletin",
        AdapterInput(source_type="news", raw_content=""),
    ),
    # podcast_caption — no audio asset
    (
        "podcast_caption",
        AdapterInput(source_type="audio", raw_content=""),
    ),
    # photo_slideshow — no images at all
    (
        "photo_slideshow",
        AdapterInput(source_type="album", raw_content=""),
    ),
]


# ─── The property itself ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "adapter_type,bad_input",
    INVALID_CASES,
    ids=[f"{a}-{i}" for i, (a, _) in enumerate(INVALID_CASES)],
)
def test_validate_input_returns_errors_without_network(
    registry: AdapterRegistry,
    adapter_type: str,
    bad_input: AdapterInput,
) -> None:
    """**Property 8 — Validates: R1.12, R4.6**

    With sockets disabled (``pytest-socket``), ``validate_input`` must:

    - Return a non-empty list of error strings for an invalid input.
    - NOT raise ``SocketBlockedError`` (no network call).
    - NOT raise any other exception (it must be a pure validator).
    """
    adapter = registry.get(adapter_type)

    # If validate_input attempts ANY socket I/O, pytest-socket will raise
    # SocketBlockedError and this test will fail.
    errors = adapter.validate_input(bad_input)

    assert isinstance(errors, list), (
        f"{adapter_type}.validate_input must return a list, got {type(errors).__name__}"
    )
    assert errors, (
        f"{adapter_type}.validate_input was expected to flag invalid input "
        f"but returned []"
    )
    for err in errors:
        assert isinstance(err, str) and err.strip(), (
            f"{adapter_type}.validate_input returned an empty/non-string error: {err!r}"
        )


# ─── Sanity check: validate_input on a *valid* input also makes no network call


def test_script_direct_validate_input_valid_no_network(
    registry: AdapterRegistry,
) -> None:
    """A well-formed script_direct payload returns ``[]`` and makes no socket call."""
    import json

    adapter = registry.get("script_direct")
    payload = json.dumps(
        {
            "scenes": [
                {
                    "narration": "A short narration.",
                    "visual_prompt": "A simple visual prompt.",
                    "duration_sec": 8.0,
                },
            ],
        }
    )
    errors = adapter.validate_input(
        AdapterInput(source_type="script", raw_content=payload)
    )
    assert errors == []


def test_news_bulletin_validate_input_valid_url_no_network(
    registry: AdapterRegistry,
) -> None:
    """A well-formed feed URL passes validate_input without any network call.

    The URL is NOT fetched here — that only happens in ``adapt``.  Even if the
    URL host does not exist, validate_input must not try to resolve it.
    """
    adapter = registry.get("news_bulletin")
    errors = adapter.validate_input(
        AdapterInput(
            source_type="news",
            raw_content="https://example.invalid/feed.xml",
        )
    )
    assert errors == []
