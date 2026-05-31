"""Shared exceptions for the signing package.

These let callers (downloaders) distinguish *"signing is unavailable in this
environment"* (e.g. an optional dependency such as ``gmssl`` is missing) from
*"signing ran but produced an error"*.  Either way the native-API download
path can fall back to yt-dlp without crashing the pipeline.
"""

from __future__ import annotations


class SigningError(Exception):
    """Base class for all signing failures."""


class SigningUnavailableError(SigningError):
    """Raised when a signing backend cannot run in the current environment.

    Typically because an optional dependency is not installed (``gmssl`` for
    A-Bogus, ``httpx`` for WBI key fetching).  Downloaders should catch this
    and fall back to the yt-dlp download path.
    """


__all__ = ["SigningError", "SigningUnavailableError"]
