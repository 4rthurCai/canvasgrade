"""Exception hierarchy.

Every error the user can plausibly hit derives from :class:`CanvasGradeError` so the
CLI and the web layer can render one clean message instead of a traceback.
"""

from __future__ import annotations


class CanvasGradeError(Exception):
    """Base class for all expected, user-facing failures."""


class ConfigError(CanvasGradeError):
    """Credentials or profile settings are missing or malformed."""


class SheetError(CanvasGradeError):
    """The input spreadsheet cannot be read or understood."""


class MappingError(CanvasGradeError):
    """The column mapping is incomplete or contradictory."""


class CanvasError(CanvasGradeError):
    """Canvas rejected a request or returned something unusable."""
