"""Generate AIFlow icons (extension + client favicon) from a vector design.

Draws the same design as ``extension/icons/icon.svg`` directly with Pillow
(no cairosvg needed): a rounded-square blue badge with a white play/generate
triangle and three "flow" motion lines.

Outputs:
    extension/icons/icon16.png
    extension/icons/icon48.png
    extension/icons/icon128.png
    ui/public/favicon-32.png
    ui/public/favicon-16.png
    ui/public/favicon.ico   (multi-size)
    ui/public/apple-touch-icon.png (180px)

Usage:
    python scripts/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_ROOT = Path(__file__).resolve().parent.parent
_EXT_ICONS = _ROOT / "extension" / "icons"
_UI_PUBLIC = _ROOT / "ui" / "public"

# Brand colours (match icon.svg)
_BG_TOP = (59, 130, 246)     # #3B82F6
_BG_BOTTOM = (30, 58, 138)   # #1E3A8A
_PLAY = (255, 255, 255)      # white
_FLOW = (147, 197, 253)      # #93C5FD

# Supersampling factor for crisp anti-aliased edges at small sizes.
_SS = 8


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _rounded_mask(size: int, radius: int) -> Image.Image:
    """Return an L-mode rounded-rectangle mask of *size*×*size*."""
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def render_icon(px: int) -> Image.Image:
    """Render the AIFlow badge icon at *px*×*px* (RGBA)."""
    s = px * _SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Vertical gradient background (drawn row by row) ──────────────────────
    grad = Image.new("RGBA", (1, s))
    gpix = grad.load()
    for y in range(s):
        gpix[0, y] = (*_lerp(_BG_TOP, _BG_BOTTOM, y / max(1, s - 1)), 255)
    grad = grad.resize((s, s))

    # Rounded-square mask (radius ~22% like the SVG rx=28/128)
    radius = round(s * 28 / 128)
    mask = _rounded_mask(s, radius)
    img.paste(grad, (0, 0), mask)

    # ── Flow motion lines (left side) ────────────────────────────────────────
    lw = round(s * 6 / 128)
    line_specs = [  # (x0, x1, y) in 128-space
        (28, 40, 52),
        (24, 40, 64),
        (28, 40, 76),
    ]
    for x0, x1, y in line_specs:
        draw.line(
            [(x0 * s / 128, y * s / 128), (x1 * s / 128, y * s / 128)],
            fill=(*_FLOW, 230),
            width=lw,
        )
        # round caps
        r = lw / 2
        for cx in (x0, x1):
            draw.ellipse(
                [cx * s / 128 - r, y * s / 128 - r, cx * s / 128 + r, y * s / 128 + r],
                fill=(*_FLOW, 230),
            )

    # ── Play / generate triangle ─────────────────────────────────────────────
    tri = [
        (52 * s / 128, 40 * s / 128),
        (52 * s / 128, 88 * s / 128),
        (92 * s / 128, 64 * s / 128),
    ]
    draw.polygon(tri, fill=(*_PLAY, 255))

    # Downsample for anti-aliasing
    return img.resize((px, px), Image.LANCZOS)


def main() -> None:
    _EXT_ICONS.mkdir(parents=True, exist_ok=True)
    _UI_PUBLIC.mkdir(parents=True, exist_ok=True)

    # Extension icons
    for size in (16, 48, 128):
        icon = render_icon(size)
        out = _EXT_ICONS / f"icon{size}.png"
        icon.save(out)
        print(f"  wrote {out}")

    # Client favicons
    fav32 = render_icon(32)
    fav16 = render_icon(16)
    fav32.save(_UI_PUBLIC / "favicon-32.png")
    fav16.save(_UI_PUBLIC / "favicon-16.png")
    print(f"  wrote {_UI_PUBLIC / 'favicon-32.png'}")
    print(f"  wrote {_UI_PUBLIC / 'favicon-16.png'}")

    # Multi-size .ico (16/32/48)
    ico_src = render_icon(48)
    ico_src.save(
        _UI_PUBLIC / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print(f"  wrote {_UI_PUBLIC / 'favicon.ico'}")

    # Apple touch icon
    render_icon(180).save(_UI_PUBLIC / "apple-touch-icon.png")
    print(f"  wrote {_UI_PUBLIC / 'apple-touch-icon.png'}")

    print("Done.")


if __name__ == "__main__":
    main()
