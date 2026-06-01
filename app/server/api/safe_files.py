"""Safe file-serving helpers — prevent path traversal / reading unauthorised files.

The AIFlow server serves a few files to the local UI (rendered videos, voice
demo audio, exported SRT). To avoid ever exposing sensitive files (the SQLite
DB, ``storage/cookies/``, ``.env``, etc.), every served path MUST be resolved
through :func:`safe_resolve`, which guarantees the final path stays *inside* an
explicitly allowed base directory.

Security model
--------------
- Only whitelisted base directories may be served (callers pass the base).
- ``safe_resolve`` rejects absolute escapes, ``..`` traversal, and symlinks
  that point outside the base.
- On any violation it raises ``HTTPException(403)`` so the request is blocked
  immediately — the client never learns whether the target exists.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException


def safe_resolve(base: Path, *parts: str) -> Path:
    """Resolve ``base / parts...`` and guarantee the result stays under *base*.

    Args:
        base:  The allowed root directory (e.g. ``storage/output``). Resolved
               to an absolute, symlink-free path before comparison.
        parts: Untrusted path segments supplied by the caller/client.

    Returns:
        The resolved absolute :class:`~pathlib.Path` inside *base*.

    Raises:
        HTTPException: 403 if the resolved path escapes *base* (path traversal,
            absolute path, or symlink pointing outside).
    """
    base_resolved = Path(base).resolve()

    # Reject obviously hostile segments early (absolute paths, traversal,
    # drive letters, NUL bytes). This is belt-and-braces — the containment
    # check below is the real guard.
    for part in parts:
        if part is None:
            raise HTTPException(status_code=403, detail="Forbidden path")
        s = str(part)
        if "\x00" in s:
            raise HTTPException(status_code=403, detail="Forbidden path")

    candidate = base_resolved.joinpath(*[str(p) for p in parts]).resolve()

    # Containment check (works on Python 3.9+ via is_relative_to).
    try:
        is_inside = candidate.is_relative_to(base_resolved)
    except AttributeError:  # pragma: no cover — Python < 3.9 fallback
        is_inside = str(candidate).startswith(str(base_resolved))

    if not is_inside:
        # Do not reveal whether the target exists — just block.
        raise HTTPException(status_code=403, detail="Forbidden path")

    return candidate


def safe_file_or_404(base: Path, *parts: str) -> Path:
    """Like :func:`safe_resolve` but also require the path to be an existing file.

    Args:
        base:  Allowed root directory.
        parts: Untrusted path segments.

    Returns:
        The resolved file path (guaranteed inside *base* and an existing file).

    Raises:
        HTTPException: 403 on traversal, 404 if the file does not exist.
    """
    path = safe_resolve(base, *parts)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return path
