"""HfProtocol — window.__hf contract types and validation.

Defines the Python-side type definitions for the HfProtocol contract that
every visual layer HTML template must expose via ``window.__hf``.

HfProtocol contract (JavaScript side):
    window.__hf = {
        duration: <float>,          // total seconds (positive)
        seek(t) { ... }             // set page state to time t (0 ≤ t ≤ duration)
    }

This module provides:
    HfProtocolContract  — TypedDict describing the JS interface
    HfTemplateMetadata  — metadata a template must declare
    HfValidationResult  — result of contract validation
    validate_hf_contract(page) — async: validates window.__hf on a Playwright page
    extract_hf_metadata(page)  — async: reads window.__hf.duration from a loaded page

JavaScript snippet constants for injecting the window.__hf boilerplate into
templates are also provided as module-level string constants.

Phase 3.5.2 — Task 3.5.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    # Playwright Page — only imported for type checking to avoid hard dependency
    from playwright.async_api import Page

# ─── JavaScript snippet constants ─────────────────────────────────────────────

# Minimal window.__hf boilerplate for templates that use GSAP timelines.
# Usage: embed this snippet in a <script> block after the GSAP timeline is set up.
# Replace ``<TIMELINE_VAR>`` with the actual GSAP timeline variable name.
HF_BOILERPLATE_GSAP = """\
window.__hf = {
  duration: <TIMELINE_VAR>.duration(),
  seek(t) { <TIMELINE_VAR>.seek(t); }
};"""

# Boilerplate for templates that manage their own seek logic (no GSAP).
HF_BOILERPLATE_CUSTOM = """\
window.__hf = {
  duration: 0,   // set to total animation duration in seconds
  seek(t) {
    // Implement: set page state to time t (0 ≤ t ≤ duration)
  }
};"""

# JavaScript expression used to validate the contract from Python.
# Evaluates to a plain object so it can be serialised by Playwright's evaluate().
_HF_VALIDATE_JS = """\
(() => {
  if (!window.__hf) return { ok: false, reason: 'window.__hf is not defined' };
  const d = window.__hf.duration;
  if (typeof d !== 'number' || !isFinite(d) || d <= 0) {
    return { ok: false, reason: 'window.__hf.duration must be a positive finite number, got: ' + d };
  }
  if (typeof window.__hf.seek !== 'function') {
    return { ok: false, reason: 'window.__hf.seek must be a function' };
  }
  return { ok: true, reason: 'ok', duration: d };
})()"""

# JavaScript expression to read duration only (lighter than full validation).
_HF_READ_DURATION_JS = "window.__hf ? window.__hf.duration : null"


# ─── TypedDict — mirrors the JS interface ─────────────────────────────────────

class HfProtocolContract(TypedDict):
    """Python-side mirror of the ``window.__hf`` JavaScript interface.

    Every visual layer HTML template must expose this contract so the
    Playwright renderer can seek to arbitrary time positions during frame
    capture.

    Attributes:
        duration: Total animation duration in seconds (must be > 0).
        seek:     Not representable as a Python type — documented here for
                  completeness.  On the JS side: ``(t: number) => void``.
    """
    duration: float
    # seek is a JS function — not representable in TypedDict, documented only


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class HfTemplateMetadata:
    """Metadata that a visual layer template must declare.

    Used for template registration, linting, and variable validation before
    a render is attempted.

    Attributes:
        name:      Template identifier (e.g. ``"intro_card"``).
        duration:  Total animation duration in seconds.
        width:     Expected viewport width in pixels.
        height:    Expected viewport height in pixels.
        variables: List of required ``{{KEY}}`` template variable names
                   (without the braces, e.g. ``["TITLE", "SUBTITLE"]``).
    """
    name: str
    duration: float
    width: int
    height: int
    variables: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError(
                f"HfTemplateMetadata.duration must be positive, got {self.duration!r}"
            )
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"HfTemplateMetadata width/height must be positive, "
                f"got width={self.width!r} height={self.height!r}"
            )


@dataclass
class HfValidationResult:
    """Result of validating the ``window.__hf`` contract on a Playwright page.

    Attributes:
        passed:   ``True`` if the contract is valid, ``False`` otherwise.
        message:  Human-readable description of the result or failure reason.
        duration: The ``window.__hf.duration`` value read from the page, or
                  ``None`` if validation failed before reading it.
    """
    passed: bool
    message: str
    duration: float | None = None


# ─── Async helpers ────────────────────────────────────────────────────────────

async def validate_hf_contract(page: "Page") -> HfValidationResult:
    """Validate that a Playwright page exposes ``window.__hf`` correctly.

    Checks:
    1. ``window.__hf`` exists.
    2. ``window.__hf.duration`` is a positive finite number.
    3. ``window.__hf.seek`` is a function.

    Args:
        page: A Playwright ``Page`` object with the template already loaded.

    Returns:
        ``HfValidationResult`` with ``passed=True`` and the duration on
        success, or ``passed=False`` with a descriptive message on failure.
    """
    try:
        result = await page.evaluate(_HF_VALIDATE_JS)
    except Exception as exc:  # noqa: BLE001
        return HfValidationResult(
            passed=False,
            message=f"JavaScript evaluation error: {exc}",
        )

    if not isinstance(result, dict):
        return HfValidationResult(
            passed=False,
            message=f"Unexpected evaluate() return type: {type(result).__name__}",
        )

    if result.get("ok"):
        duration = result.get("duration")
        return HfValidationResult(
            passed=True,
            message="window.__hf contract is valid",
            duration=float(duration) if duration is not None else None,
        )

    return HfValidationResult(
        passed=False,
        message=result.get("reason", "Unknown validation failure"),
    )


async def extract_hf_metadata(page: "Page") -> float | None:
    """Read ``window.__hf.duration`` from a loaded Playwright page.

    A lightweight alternative to ``validate_hf_contract()`` when only the
    duration value is needed (e.g. to auto-detect template duration).

    Args:
        page: A Playwright ``Page`` object with the template already loaded.

    Returns:
        The duration in seconds as a ``float``, or ``None`` if
        ``window.__hf`` is not defined or ``duration`` is not a number.
    """
    try:
        value = await page.evaluate(_HF_READ_DURATION_JS)
    except Exception:  # noqa: BLE001
        return None

    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None
