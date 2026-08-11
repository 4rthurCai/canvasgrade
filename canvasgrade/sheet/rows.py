"""Turn a raw frame plus a mapping into :class:`StudentRow` records.

Real gradebooks are messy: blank spacer rows, team headers like ``team1`` sitting in
the name column with nothing else filled in, integer ids that pandas read as floats. This
module normalises all of that away.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from canvasgrade.models import ColumnRole, SheetMapping, StudentRow

BLANK_TOKENS = frozenset({"", "-", "--", "n/a", "na", "nan", "none", "null", "/", "无"})


def is_blank(value: Any) -> bool:
    """True for empty cells, NaN, and the usual placeholder strings."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if value is pd.NaT:
        return True
    return str(value).strip().lower() in BLANK_TOKENS


def to_float(value: Any) -> float | None:
    """Parse a cell as a number, tolerating percent signs and stray whitespace."""
    if is_blank(value):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return None if math.isnan(float(value)) else float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        parsed = float(text)
    except ValueError:
        return None
    return None if math.isnan(parsed) else parsed


def to_int(value: Any) -> int | None:
    """Parse a cell as an integer id, tolerating the ``12345.0`` floats pandas hands back."""
    parsed = to_float(value)
    if parsed is None:
        return None
    rounded = round(parsed)
    return rounded if abs(parsed - rounded) < 1e-9 else None


def to_text(value: Any) -> str | None:
    if is_blank(value):
        return None
    return " ".join(str(value).split())


def _cell(row: pd.Series, mapping: SheetMapping, role: ColumnRole) -> Any:
    column = mapping.first(role)
    return None if column is None else row.iloc[column.index]


def extract_rows(frame: pd.DataFrame, mapping: SheetMapping) -> tuple[StudentRow, ...]:
    """Extract student rows, folding team-header rows into the ``team`` field.

    A row with a name but no id and no scores is read as a team header: it names the
    group that the following rows belong to, and produces no student of its own.
    """
    criteria = mapping.criteria_columns
    comment_columns = mapping.by_role(ColumnRole.COMMENT)
    team_column = mapping.first(ColumnRole.TEAM)

    rows: list[StudentRow] = []
    current_team: str | None = None

    for position in range(len(frame)):
        raw = frame.iloc[position]

        canvas_id = to_int(_cell(raw, mapping, ColumnRole.CANVAS_ID))
        sis_id = to_text(_cell(raw, mapping, ColumnRole.SIS_ID))
        name = to_text(_cell(raw, mapping, ColumnRole.NAME))

        scores = tuple(
            (column.name, value) for column in criteria if (value := to_float(raw.iloc[column.index])) is not None
        )

        if canvas_id is None and not sis_id and not scores:
            # Nothing identifying and nothing to grade: either a spacer or a team header.
            if name:
                current_team = name
            continue

        comments = tuple(
            (column.target, text)
            for column in comment_columns
            if column.target and (text := to_text(raw.iloc[column.index]))
        )

        explicit_team = to_text(raw.iloc[team_column.index]) if team_column else None
        total_column = mapping.first(ColumnRole.TOTAL)
        ratio_column = mapping.first(ColumnRole.RATIO)

        rows.append(
            StudentRow(
                row_index=position,
                name=name,
                canvas_id=canvas_id,
                sis_id=sis_id,
                team=explicit_team or current_team,
                scores=scores,
                comments=comments,
                total_override=to_float(raw.iloc[total_column.index]) if total_column else None,
                ratio=to_float(raw.iloc[ratio_column.index]) if ratio_column else None,
            )
        )

    return tuple(rows)
