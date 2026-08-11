"""Narrow a detected mapping down to the criteria you actually want to push.

One spreadsheet often covers several assignments - three milestones side by side, say -
so the criteria for a single Canvas assignment are a subset of the sheet's columns.
Filters are glob patterns matched against column headers, e.g. ``--include 'P1M1 *'``.
"""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch

from canvasgrade.errors import MappingError
from canvasgrade.models import ColumnRole, ColumnSpec, SheetMapping


def _matches_any(name: str, patterns: Sequence[str]) -> bool:
    lowered = name.lower()
    return any(fnmatch(lowered, pattern.lower()) for pattern in patterns)


def filter_criteria(
    mapping: SheetMapping,
    *,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> SheetMapping:
    """Return a mapping where non-matching criteria are demoted to IGNORE.

    Comment columns follow their criterion: drop the criterion and its comment column
    is dropped too, so a filtered push never carries orphaned feedback.
    """
    if not include and not exclude:
        return mapping

    kept: set[str] = set()
    columns: list[ColumnSpec] = []
    for column in mapping.columns:
        if column.role is not ColumnRole.CRITERION:
            columns.append(column)
            continue
        if include and not _matches_any(column.name, include):
            columns.append(_demote(column, f"excluded by --include {include[0]!r}"))
            continue
        if exclude and _matches_any(column.name, exclude):
            columns.append(_demote(column, "dropped by --exclude"))
            continue
        kept.add(column.name)
        columns.append(column)

    if not kept:
        patterns = ", ".join(include or exclude)
        raise MappingError(f"No criterion columns matched {patterns}. Run 'canvasgrade inspect' to list them.")

    columns = [
        _demote(c, f"its criterion '{c.target}' was filtered out")
        if c.role is ColumnRole.COMMENT and c.target not in kept
        else c
        for c in columns
    ]
    return SheetMapping(columns=tuple(columns))


def _demote(column: ColumnSpec, reason: str) -> ColumnSpec:
    return ColumnSpec(name=column.name, index=column.index, role=ColumnRole.IGNORE, reason=reason)
