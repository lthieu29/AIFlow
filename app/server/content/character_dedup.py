"""Character deduplication utilities for content adapters.

Provides helpers to normalise, merge, and extract character references
across scenes so that the same character is not represented multiple times
under different names or aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Data class ──────────────────────────────────────────────────────────────


@dataclass
class CharacterRef:
    """A reference to a character that may appear across multiple scenes.

    Attributes:
        name:        Canonical display name (e.g. "Hùng An").
        aliases:     Alternative names / pronouns used in the text
                     (e.g. ["Hùng", "anh", "he"]).
        ref_image:   Optional path to a reference image for Veo3 continuity.
        description: Free-text description used in LLM prompts.
    """

    name: str
    aliases: list[str] = field(default_factory=list)
    ref_image: Optional[Path] = None
    description: str = ""


# ─── Normalisation ───────────────────────────────────────────────────────────


def normalize_name(name: str) -> str:
    """Return a lowercase, stripped version of *name* for comparison.

    Args:
        name: Raw character name or alias.

    Returns:
        Lowercase, whitespace-stripped string.

    Example::

        >>> normalize_name("  Hùng An  ")
        'hùng an'
    """
    return name.strip().lower()


# ─── Deduplication ───────────────────────────────────────────────────────────


def dedup_characters(characters: list[CharacterRef]) -> list[CharacterRef]:
    """Merge characters that share the same name or overlapping aliases.

    Two characters are considered the same when:
    - Their normalised canonical names are equal, **or**
    - Any normalised alias of one matches the normalised name or any alias
      of the other.

    When merging, the first character's name is kept as canonical.  Aliases
    and descriptions are combined (duplicates removed).  ``ref_image`` is
    taken from the first character that has one.

    Args:
        characters: Input list of :class:`CharacterRef` objects (may contain
                    duplicates).

    Returns:
        Deduplicated list preserving original insertion order of the first
        occurrence of each merged group.
    """
    # Each group is a list of CharacterRef indices that belong together.
    groups: list[list[int]] = []
    # Map from normalised token → group index for fast lookup.
    token_to_group: dict[str, int] = {}

    def _tokens(char: CharacterRef) -> set[str]:
        """All normalised tokens for a character (name + aliases)."""
        tokens = {normalize_name(char.name)}
        for alias in char.aliases:
            stripped = normalize_name(alias)
            if stripped:
                tokens.add(stripped)
        return tokens

    for idx, char in enumerate(characters):
        tokens = _tokens(char)
        # Find which existing groups this character overlaps with.
        matching_groups: list[int] = []
        for token in tokens:
            if token in token_to_group:
                g = token_to_group[token]
                if g not in matching_groups:
                    matching_groups.append(g)

        if not matching_groups:
            # New group
            g = len(groups)
            groups.append([idx])
            for token in tokens:
                token_to_group[token] = g
        else:
            # Merge all matching groups into the first one.
            primary = matching_groups[0]
            for other in matching_groups[1:]:
                # Move all members of `other` into `primary`.
                for member_idx in groups[other]:
                    groups[primary].append(member_idx)
                    # Re-point their tokens to primary.
                    for token in _tokens(characters[member_idx]):
                        token_to_group[token] = primary
                groups[other] = []  # empty the merged group

            groups[primary].append(idx)
            for token in tokens:
                token_to_group[token] = primary

    # Build merged CharacterRef for each non-empty group.
    result: list[CharacterRef] = []
    for group in groups:
        if not group:
            continue
        # Use the first character in the group as the canonical base.
        first = characters[group[0]]
        merged_aliases: list[str] = list(first.aliases)
        merged_description = first.description
        merged_ref_image = first.ref_image

        seen_aliases = {normalize_name(a) for a in merged_aliases}
        seen_aliases.add(normalize_name(first.name))

        for member_idx in group[1:]:
            other = characters[member_idx]
            # Add the other's canonical name as an alias if it differs.
            other_norm = normalize_name(other.name)
            if other_norm not in seen_aliases:
                merged_aliases.append(other.name)
                seen_aliases.add(other_norm)
            # Merge aliases.
            for alias in other.aliases:
                alias_norm = normalize_name(alias)
                if alias_norm and alias_norm not in seen_aliases:
                    merged_aliases.append(alias)
                    seen_aliases.add(alias_norm)
            # Merge description (append if non-empty and different).
            if other.description and other.description not in merged_description:
                merged_description = (
                    f"{merged_description} {other.description}".strip()
                    if merged_description
                    else other.description
                )
            # Take the first available ref_image.
            if merged_ref_image is None and other.ref_image is not None:
                merged_ref_image = other.ref_image

        result.append(
            CharacterRef(
                name=first.name,
                aliases=merged_aliases,
                ref_image=merged_ref_image,
                description=merged_description,
            )
        )

    return result


# ─── Name extraction ─────────────────────────────────────────────────────────

# Patterns for extracting character names from plain text.
# 1. Quoted names: "Alice", 'Bob', "Hùng An"
_QUOTED_NAME_RE = re.compile(r'["\u201c\u201d\u2018\u2019]([A-ZÀ-Ỹa-zà-ỹ][^\"\u201c\u201d\u2018\u2019]{1,40})["\u201c\u201d\u2018\u2019]')
# 2. Capitalised multi-word names (2–4 words, each starting with uppercase).
_CAPITALIZED_NAME_RE = re.compile(
    r'\b([A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ]'
    r'[a-zàáâãèéêìíòóôõùúăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]+'
    r'(?:\s[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ]'
    r'[a-zàáâãèéêìíòóôõùúăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]+){1,3})\b'
)

# Common English words that look capitalised but are not names.
_STOPWORDS = frozenset(
    [
        "The", "A", "An", "In", "On", "At", "To", "For", "Of", "And", "Or",
        "But", "With", "From", "By", "As", "Is", "Was", "Are", "Were", "Be",
        "Been", "Being", "Have", "Has", "Had", "Do", "Does", "Did", "Will",
        "Would", "Could", "Should", "May", "Might", "Must", "Shall", "Can",
        "This", "That", "These", "Those", "It", "He", "She", "They", "We",
        "You", "I", "My", "Your", "His", "Her", "Its", "Our", "Their",
        "Chapter", "Scene", "Part", "Section", "Episode",
    ]
)


def extract_character_names(text: str) -> list[str]:
    """Extract likely character names from *text* using simple heuristics.

    Heuristics applied (in order):
    1. Names inside quotation marks that start with a capital letter.
    2. Capitalised multi-word sequences (2–4 words) that are not common
       stop-words.

    Duplicates (case-insensitive) are removed; the first occurrence is kept.

    Args:
        text: Plain text (narration, script, novel excerpt, etc.).

    Returns:
        Deduplicated list of candidate character name strings.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        stripped = name.strip()
        key = normalize_name(stripped)
        if key and key not in seen:
            seen.add(key)
            candidates.append(stripped)

    # 1. Quoted names
    for match in _QUOTED_NAME_RE.finditer(text):
        _add(match.group(1))

    # 2. Capitalised multi-word names
    for match in _CAPITALIZED_NAME_RE.finditer(text):
        name = match.group(1)
        # Skip if the first word is a stopword
        first_word = name.split()[0]
        if first_word not in _STOPWORDS:
            _add(name)

    return candidates
