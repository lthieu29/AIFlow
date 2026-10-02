"""GSAP local bundle helper.

Manages the vendored GSAP JavaScript file used by visual layer templates.
Templates reference GSAP via the ``{{__VENDOR_GSAP__}}`` placeholder; this
module resolves that placeholder to an absolute ``file:///`` URI pointing at
the local bundle.

Vendor layout (REVIEW-01 #4 — no CDN):
    app/vendor/visual_layer/
    ├── gsap.min.js          # GSAP 3.12.5, ~70 KB
    └── README.md            # Source URL + version + license note

If the bundle is missing, ``get_gsap_bundle_path()`` raises ``RuntimeError``
with a ``curl`` command the user can run to download it.

Phase 3.5.1 — Task 3.5.1
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from loguru import logger

# ─── Constants ────────────────────────────────────────────────────────────────

# GSAP version pinned for reproducible animation behaviour.
_GSAP_VERSION = "3.12.5"
_GSAP_CDN_URL = (
    f"https://cdn.jsdelivr.net/npm/gsap@{_GSAP_VERSION}/dist/gsap.min.js"
)

# Vendor directory: app/vendor/visual_layer/
_VENDOR_DIR: Path = Path(__file__).resolve().parents[4] / "vendor" / "visual_layer"
_GSAP_PATH: Path = _VENDOR_DIR / "gsap.min.js"

# Placeholder used in HTML templates
_GSAP_PLACEHOLDER = "{{__VENDOR_GSAP__}}"


# ─── Public API ───────────────────────────────────────────────────────────────

def get_gsap_bundle_path(*, auto_download: bool = False) -> Path:
    """Return the absolute path to the local GSAP bundle.

    Args:
        auto_download: If ``True`` and the bundle is missing, attempt to
            download it from the CDN.  Defaults to ``False`` (fail-fast).

    Returns:
        Absolute path to ``vendor/visual_layer/gsap.min.js``.

    Raises:
        RuntimeError: If the bundle is missing and *auto_download* is
            ``False``, or if the download fails.
    """
    if _GSAP_PATH.is_file():
        logger.debug("[gsap_bundle] using local bundle: {}", _GSAP_PATH)
        return _GSAP_PATH

    if auto_download:
        return _download_gsap()

    raise RuntimeError(
        f"Missing GSAP vendor bundle: {_GSAP_PATH}\n"
        f"Run one of the following to download it:\n"
        f"  curl -L {_GSAP_CDN_URL} -o \"{_GSAP_PATH}\"\n"
        f"  python -c \"from server.render.visual_layer.gsap_bundle import get_gsap_bundle_path; "
        f"get_gsap_bundle_path(auto_download=True)\""
    )


def inject_gsap(html_content: str, *, auto_download: bool = False) -> str:
    """Replace the ``{{__VENDOR_GSAP__}}`` placeholder with the local bundle URI.

    The placeholder is replaced with an absolute ``file:///`` URI so that
    Playwright's headless Chromium can load the script without network access.

    Args:
        html_content:  Raw HTML string containing ``{{__VENDOR_GSAP__}}``.
        auto_download: Passed through to ``get_gsap_bundle_path()``.

    Returns:
        HTML string with the placeholder replaced by the ``file:///`` URI.

    Raises:
        RuntimeError: If the GSAP bundle is missing (see
            ``get_gsap_bundle_path()``).
    """
    gsap_path = get_gsap_bundle_path(auto_download=auto_download)
    # Use forward slashes for the file:/// URI (works on Windows too)
    uri = "file:///" + gsap_path.as_posix()
    return html_content.replace(_GSAP_PLACEHOLDER, uri)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _download_gsap() -> Path:
    """Download GSAP from CDN to the vendor directory.

    Returns:
        Path to the downloaded file.

    Raises:
        RuntimeError: If the download fails.
    """
    _VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("[gsap_bundle] downloading GSAP {} from CDN …", _GSAP_VERSION)
    logger.info("[gsap_bundle] URL: {}", _GSAP_CDN_URL)

    try:
        urllib.request.urlretrieve(_GSAP_CDN_URL, _GSAP_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to download GSAP from {_GSAP_CDN_URL}: {exc}\n"
            f"Check your internet connection or download manually:\n"
            f"  curl -L {_GSAP_CDN_URL} -o \"{_GSAP_PATH}\""
        ) from exc

    logger.info(
        "[gsap_bundle] GSAP {} downloaded → {} ({} KB)",
        _GSAP_VERSION,
        _GSAP_PATH,
        _GSAP_PATH.stat().st_size // 1024,
    )

    # Write a README alongside the bundle
    _write_vendor_readme()

    return _GSAP_PATH


def _write_vendor_readme() -> None:
    """Write a README.md in the vendor/visual_layer/ directory."""
    readme = _VENDOR_DIR / "README.md"
    if readme.exists():
        return
    readme.write_text(
        f"# vendor/visual_layer\n\n"
        f"## GSAP {_GSAP_VERSION}\n\n"
        f"- **File**: `gsap.min.js`\n"
        f"- **Source**: {_GSAP_CDN_URL}\n"
        f"- **License**: GSAP Standard License (free for personal/non-commercial use)\n"
        f"  See https://gsap.com/licensing/\n\n"
        f"Downloaded automatically by `server.render.visual_layer.gsap_bundle`.\n"
        f"Do NOT commit this file to git if the project becomes public — check GSAP licensing.\n",
        encoding="utf-8",
    )
