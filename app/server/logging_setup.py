"""Logging configuration using loguru.

Usage:
    from server.logging_setup import setup_logging
    setup_logging("INFO")
"""

import sys

from loguru import logger

_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} | {message}"
)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure loguru with the standard AIFlow format.

    Removes the default loguru handler and adds a new one with the
    project-standard format.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        format=_LOG_FORMAT,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )
    logger.debug(f"Logging configured at level={log_level.upper()}")
