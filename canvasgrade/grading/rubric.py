"""Build a rubric from sheet headers, or bind sheet columns to an existing rubric."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from canvasgrade.errors import MappingError
from canvasgrade.models import Criterion, RubricSpec, SheetMapping
from canvasgrade.sheet.detect import normalise, strip_points


@dataclass(frozen=True)
class CanvasCriterion:
    """A criterion that already exists on Canvas."""

    criterion_id: str
    description: str
    points: float


def build_rubric(mapping: SheetMapping, title: str) -> RubricSpec:
    """Derive a :class:`RubricSpec` from the sheet's criterion columns, in sheet order."""
    columns = mapping.criteria_columns
    if not columns:
        raise MappingError(
            "No criterion columns found. Headers need a max score, e.g. 'Code Quality (35)'. "
            "Run 'canvasgrade inspect <file>' to see how each column was read."
        )

    missing = [c.name for c in columns if c.points is None]
    if missing:
        listed = ", ".join(repr(name) for name in missing[:5])
        raise MappingError(f"These criterion columns have no max score: {listed}")

    descriptions = [c.description or strip_points(c.name) or c.name for c in columns]
    duplicates = [text for text, count in Counter(map(normalise, descriptions)).items() if count > 1]
    if duplicates:
        raise MappingError(
            f"Two criterion columns reduce to the same name ({duplicates[0]!r}). "
            "Canvas cannot tell them apart - rename one of them."
        )

    criteria = tuple(
        Criterion(column=column.name, description=description, points=float(column.points))  # type: ignore[arg-type]
        for column, description in zip(columns, descriptions, strict=True)
    )
    return RubricSpec(title=title, criteria=criteria)


def bind_to_existing(
    spec: RubricSpec,
    canvas_criteria: Sequence[CanvasCriterion],
    *,
    rubric_id: int,
) -> tuple[RubricSpec, tuple[str, ...]]:
    """Attach Canvas criterion ids to a spec built from the sheet.

    Returns the bound spec plus any warnings. Descriptions are matched first; if they
    do not line up but the counts do, we fall back to position and say so.
    """
    if not canvas_criteria:
        raise MappingError(f"Rubric {rubric_id} on Canvas has no criteria to match against.")

    by_description = {normalise(c.description): c for c in canvas_criteria}
    matched = [by_description.get(normalise(c.description)) for c in spec.criteria]
    warnings: list[str] = []

    if all(m is not None for m in matched):
        criteria = tuple(
            criterion.with_id(match.criterion_id)  # type: ignore[union-attr]
            for criterion, match in zip(spec.criteria, matched, strict=True)
        )
        for criterion, match in zip(spec.criteria, matched, strict=True):
            if match and abs(match.points - criterion.points) > 1e-6:
                warnings.append(
                    f"'{criterion.description}' is out of {criterion.points:g} in the sheet "
                    f"but out of {match.points:g} on Canvas"
                )
        return RubricSpec(title=spec.title, criteria=criteria, rubric_id=rubric_id), tuple(warnings)

    if len(canvas_criteria) != len(spec.criteria):
        unmatched = [c.description for c, m in zip(spec.criteria, matched, strict=True) if m is None]
        available = ", ".join(repr(c.description) for c in canvas_criteria)
        raise MappingError(
            f"Cannot line up the sheet with rubric {rubric_id}: {len(spec.criteria)} columns vs "
            f"{len(canvas_criteria)} criteria, and these have no counterpart: "
            f"{', '.join(repr(u) for u in unmatched[:5])}. Canvas has: {available}"
        )

    warnings.append(
        "Criterion names do not match the rubric on Canvas; falling back to column order. Check the preview carefully."
    )
    criteria = tuple(
        criterion.with_id(canvas.criterion_id) for criterion, canvas in zip(spec.criteria, canvas_criteria, strict=True)
    )
    return RubricSpec(title=spec.title, criteria=criteria, rubric_id=rubric_id), tuple(warnings)
