"""epub_novel adapter package — 3-tier EPUB processing mode.

Tier 1 — direct:  Short novels processed in a single pass (≤ TIER1_MAX_WORDS).
Tier 2 — episode: Long novels automatically split into episodes.
Tier 3 — manual:  User selects a chapter range; only that range is processed.
"""
