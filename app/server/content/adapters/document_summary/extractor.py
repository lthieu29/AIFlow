"""Text extraction utilities for the ``document_summary`` adapter.

Supports PDF (``.pdf``) and Word (``.docx``) documents.  Both libraries
(``pypdf`` and ``python-docx``) are imported lazily so that the adapter
can be loaded even when the optional ``[content]`` extras are not installed;
a clear :class:`~server.content.base.AdapterError` is raised at runtime if
the required library is missing.

Public API
----------
- :func:`extract_text` — dispatch to the right extractor by file extension.
- :func:`extract_text_from_pdf` — extract text from a PDF file.
- :func:`extract_text_from_docx` — extract text from a Word ``.docx`` file.
- :func:`is_supported_format` — return True for ``.pdf`` / ``.docx``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from server.content.base import AdapterError

logger = logging.getLogger(__name__)

# ─── Supported extensions ─────────────────────────────────────────────────────

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx"})


def is_supported_format(path: Path) -> bool:
    """Return ``True`` if *path* has a supported document extension.

    Args:
        path: Path to the document file.

    Returns:
        ``True`` for ``.pdf`` and ``.docx`` files (case-insensitive).
    """
    return path.suffix.lower() in _SUPPORTED_EXTENSIONS


# ─── Dispatch ─────────────────────────────────────────────────────────────────


def extract_text(path: Path) -> str:
    """Extract plain text from a PDF or Word document.

    Dispatches to :func:`extract_text_from_pdf` or
    :func:`extract_text_from_docx` based on the file extension.

    Args:
        path: Path to the document file.

    Returns:
        Extracted plain text (may be empty if the document has no text layer).

    Raises:
        :class:`~server.content.base.AdapterError`: If the file format is not
            supported, the file does not exist, or the required library is
            missing.
    """
    if not path.exists():
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"Document file not found: {path}",
            details={"path": str(path)},
        )

    ext = path.suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(path)
    elif ext == ".docx":
        return extract_text_from_docx(path)
    else:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"Unsupported document format {ext!r}. Supported: .pdf, .docx",
            details={"path": str(path), "extension": ext},
        )


# ─── PDF extraction ───────────────────────────────────────────────────────────


def extract_text_from_pdf(path: Path) -> str:
    """Extract plain text from a PDF file using ``pypdf``.

    Imports ``pypdf`` lazily so the adapter can be loaded without the
    optional dependency installed.

    Args:
        path: Path to the ``.pdf`` file.

    Returns:
        Concatenated text from all pages, separated by newlines.

    Raises:
        :class:`~server.content.base.AdapterError`: If ``pypdf`` is not
            installed or the file cannot be parsed.
    """
    try:
        import pypdf  # lazy import — optional dependency
    except ImportError as exc:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "pypdf is required to process PDF files. "
            "Install it with: pip install pypdf",
            details={"missing_package": "pypdf"},
        ) from exc

    try:
        reader = pypdf.PdfReader(str(path))
        pages: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text)
        return "\n\n".join(pages)
    except Exception as exc:  # noqa: BLE001
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"Failed to extract text from PDF {path.name!r}: {exc}",
            details={"path": str(path), "error": str(exc)},
        ) from exc


# ─── DOCX extraction ──────────────────────────────────────────────────────────


def extract_text_from_docx(path: Path) -> str:
    """Extract plain text from a Word ``.docx`` file using ``python-docx``.

    Imports ``docx`` lazily so the adapter can be loaded without the
    optional dependency installed.

    Args:
        path: Path to the ``.docx`` file.

    Returns:
        Concatenated paragraph text, separated by newlines.

    Raises:
        :class:`~server.content.base.AdapterError`: If ``python-docx`` is not
            installed or the file cannot be parsed.
    """
    try:
        import docx  # lazy import — optional dependency (python-docx)
    except ImportError as exc:
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            "python-docx is required to process Word files. "
            "Install it with: pip install python-docx",
            details={"missing_package": "python-docx"},
        ) from exc

    try:
        document = docx.Document(str(path))
        paragraphs: list[str] = [
            para.text for para in document.paragraphs if para.text.strip()
        ]
        return "\n\n".join(paragraphs)
    except Exception as exc:  # noqa: BLE001
        raise AdapterError(
            "ADAPTER_INVALID_INPUT",
            f"Failed to extract text from Word document {path.name!r}: {exc}",
            details={"path": str(path), "error": str(exc)},
        ) from exc


# ─── Validate document (local, no network) ────────────────────────────────────


def validate_document_local(path: Path) -> list[str]:
    """Perform cheap local validation of a document file.

    Checks:
    - File exists on disk.
    - Extension is ``.pdf`` or ``.docx``.
    - For PDF: attempts to open with ``pypdf`` to verify it is a valid PDF
      (reads only the header/metadata, not all pages).
    - For DOCX: attempts to open with ``python-docx`` to verify the ZIP
      structure is intact.

    This function does NOT call any external APIs or network services.

    Args:
        path: Path to the document file.

    Returns:
        A list of human-readable error strings.  Empty list = valid.
    """
    errors: list[str] = []

    if not path.exists():
        errors.append(f"Document file not found: {path}")
        return errors  # no point checking further

    ext = path.suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        errors.append(
            f"Unsupported document format {ext!r}. Supported: .pdf, .docx"
        )
        return errors

    if ext == ".pdf":
        try:
            import pypdf  # lazy import
            pypdf.PdfReader(str(path))  # validates PDF structure
        except ImportError:
            # pypdf not installed — skip structural check, report as warning
            logger.debug(
                "pypdf not installed; skipping PDF structural validation for %s",
                path,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"PDF file appears to be corrupt or unreadable: {exc}")

    elif ext == ".docx":
        try:
            import docx  # lazy import
            docx.Document(str(path))  # validates ZIP/OOXML structure
        except ImportError:
            # python-docx not installed — skip structural check
            logger.debug(
                "python-docx not installed; skipping DOCX structural validation for %s",
                path,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(
                f"Word document appears to be corrupt or unreadable: {exc}"
            )

    return errors
