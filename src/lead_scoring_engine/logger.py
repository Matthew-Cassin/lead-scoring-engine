"""Centralized logging setup for lead-scoring-engine.

Following standard library-logging practice, this module does not
configure handlers, formatters, or levels on import -- that decision
belongs to the consuming application (or the CLI's ``--verbose`` flag),
not the library. A :class:`logging.NullHandler` is attached to the
package logger so that, absent any configuration, the library stays
silent instead of triggering Python's "No handlers could be found"
warning.

Library modules should call :func:`get_logger` rather than using
``print`` or the root logger directly.
"""

from __future__ import annotations

import logging

__all__ = ["configure_logging", "get_logger"]

_PACKAGE_LOGGER_NAME = "lead_scoring_engine"

_package_logger = logging.getLogger(_PACKAGE_LOGGER_NAME)
_package_logger.addHandler(logging.NullHandler())


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the package logger, or a named child of it.

    Args:
        name: Optional dotted suffix identifying the calling submodule,
            e.g. ``"claude_extractor"``. When given, returns a child
            logger named ``"lead_scoring_engine.<name>"``. When omitted,
            returns the package's top-level logger.

    Returns:
        A standard :class:`logging.Logger`.

    Example:
        >>> logger = get_logger("claude_extractor")
        >>> logger.name
        'lead_scoring_engine.claude_extractor'
    """
    if name:
        return _package_logger.getChild(name)
    return _package_logger


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a console handler to the package logger.

    Used by the CLI's ``--verbose`` flag, and available for scripts,
    demos, and interactive use. Library code itself never calls this.
    Applications that already manage their own logging configuration
    should rely on that instead, since this adds a second handler on top
    of anything already configured.

    Args:
        level: The logging level to enable on the package logger, e.g.
            ``logging.INFO`` or ``logging.DEBUG``. Defaults to
            ``logging.INFO``.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    _package_logger.addHandler(handler)
    _package_logger.setLevel(level)
