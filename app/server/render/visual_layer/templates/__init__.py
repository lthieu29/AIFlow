"""Visual layer HTML+GSAP templates package.

Templates in this directory are rendered by PlaywrightRenderer into WebM
overlays with alpha channel.  Each template must expose the HfProtocol
contract via ``window.__hf``.

Available templates:
    intro_card.html     — Opening title card (5s)
    outro_card.html     — Closing card with CTA (4s)
    lower_third.html    — Lower third name/title bar (3s)
    chapter_title.html  — Chapter/section title (3s)
    product_card.html   — Product info overlay (5s)

Phase 3.5.3 — Task 3.5.3
"""
