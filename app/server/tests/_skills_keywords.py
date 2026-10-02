"""Shared keyword sets and helpers for skill content tests.

Used by ``test_skills_all.py`` and ``test_skills_pairing.py`` to assert that
every skill prefix (after merge with ``_base``) carries the Veo 8-element
formula keywords, at least one camera-lexicon keyword, and the three core
constraint terms.

Names of the constants are stable; tests import them by name.
"""

from __future__ import annotations

import re
from pathlib import Path

# ─── Repository roots ────────────────────────────────────────────────────────

#: Resolves to ``app/`` regardless of where the test is launched from.
APP_ROOT: Path = Path(__file__).resolve().parents[2]

#: Path to the ``skills/`` directory.
SKILLS_DIR: Path = APP_ROOT / "skills"

# ─── Skill set membership ────────────────────────────────────────────────────

#: The 6 skills that existed before video-variety-expansion. Refactored in R2.
LEGACY_6_SKILLS: frozenset[str] = frozenset({
    "ecommerce-fashion",
    "kdrama-romance",
    "explainer-tech",
    "cinematic-action",
    "ecommerce-tech",
    "ecommerce-food",
})

#: The 30 new skills introduced by R3.
NEW_30_SKILLS: frozenset[str] = frozenset({
    # commercial (5)
    "ecommerce-beauty",
    "ecommerce-jewelry",
    "ecommerce-home",
    "product-tech-launch",
    "product-minimal-rotate",
    # cinematic (5)
    "cinematic-noir",
    "cinematic-drama",
    "cinematic-thriller",
    "cinematic-romance",
    "cinematic-period",
    # social-viral (4)
    "social-viral-hook",
    "social-viral-transform",
    "social-viral-pet-comedy",
    "social-viral-meme",
    # nature (3)
    "nature-landscape",
    "nature-wildlife",
    "nature-timelapse",
    # action (3)
    "action-sports-pov",
    "action-extreme",
    "action-wuxia",
    # dialogue-driven (3)
    "dialogue-interview",
    "dialogue-vlog",
    "dialogue-podcast-clip",
    # educational (2)
    "explainer-finance",
    "explainer-history",
    # lifestyle (2)
    "travel-vlog",
    "lifestyle-wellness",
    # experimental (2)
    "experimental-abstract",
    "experimental-asmr",
    # chinese-native (1)
    "chinese-ink-wash",
})

#: Every non-base skill the spec covers (R5 parametrize target).
ALL_NON_BASE_SKILLS: frozenset[str] = LEGACY_6_SKILLS | NEW_30_SKILLS

#: Including ``_base``.
ALL_KNOWN_SKILLS: frozenset[str] = ALL_NON_BASE_SKILLS | frozenset({"_base"})


# ─── Keyword sets used by content tests ──────────────────────────────────────

#: At least one of these keywords (case-insensitive) must appear in a skill's
#: merged prefix. Indicates the prefix follows the Veo 8-element formula.
VEO_KEYWORDS: frozenset[str] = frozenset({
    "shot",
    "framing",
    "medium",
    "close-up",
    "wide",
    "lighting",
    "lit",
    "light",
    "audio",
    "sound",
    "music",
    "dialogue",
    "speaks",
    "says",
    "action",
    "motion",
    "style",
    "cinematic",
    "photorealistic",
})

#: At least one of these keywords (case-insensitive) must appear in a skill's
#: merged prefix. Indicates the prefix uses the standard camera lexicon.
CAMERA_KEYWORDS: frozenset[str] = frozenset({
    "dolly",
    "pan",
    "tilt",
    "tracking",
    "orbit",
    "handheld",
    "gimbal",
    "steadicam",
    "rack focus",
    "slow push-in",
    "drone",
    "pov",
    "static",
    "locked-off",
    "tripod",
    "golden hour",
    "blue hour",
    "overcast",
    "neon",
    "soft window light",
    "hard key light",
    "backlight",
    "rim light",
    "volumetric",
    "candlelight",
    "tungsten",
    "fluorescent",
})

#: All three of these constraint phrases must appear in a skill's merged
#: prefix (provided by ``_base``). Order is irrelevant; matching is
#: case-insensitive substring.
REQUIRED_CONSTRAINT_PHRASES: tuple[str, ...] = (
    "watermark",
    "logo",
    # any of these counts as "no subtitle / text overlay"
    "subtitle",  # ``test_skill_loaded_prefix_has_constraint_keywords`` accepts
                 # either ``subtitle`` or ``text overlay`` — see helper below
)

#: Pair of acceptable wordings for the no-subtitles constraint.
SUBTITLE_CONSTRAINT_VARIANTS: tuple[str, ...] = ("subtitle", "text overlay")


# ─── Helpers ─────────────────────────────────────────────────────────────────


_WORD_RE = re.compile(r"\S+")


def word_count(text: str) -> int:
    """Return the number of whitespace-separated tokens in *text*.

    Mirrors the helper used by ``test_skills_new.py`` of content-expansion.
    """
    return len(_WORD_RE.findall(text or ""))


def contains_any(text: str, keywords) -> str | None:
    """Return the first keyword from *keywords* found in *text* (case-insensitive),
    or ``None`` if none match. Substring match.
    """
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return kw
    return None


def contains_all_constraints(text: str) -> tuple[bool, list[str]]:
    """Return ``(ok, missing)`` for the 3 core constraint phrases.

    ``missing`` lists the constraint labels that are absent. The
    no-subtitle constraint accepts either of
    :data:`SUBTITLE_CONSTRAINT_VARIANTS`.
    """
    lower = text.lower()
    missing: list[str] = []
    if "watermark" not in lower:
        missing.append("watermark")
    if "logo" not in lower:
        missing.append("logo")
    if not any(v in lower for v in SUBTITLE_CONSTRAINT_VARIANTS):
        missing.append("subtitle/text overlay")
    return not missing, missing
