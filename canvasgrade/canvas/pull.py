"""Pull from Canvas: the roster, and a ready-to-fill grading template.

The template closes the loop. Instead of copying user ids into a spreadsheet by hand,
you download a sheet that already has every student and every criterion column in it,
fill in the numbers, and push the same file straight back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from canvasgrade.canvas.client import API_ERRORS, _explain
from canvasgrade.errors import CanvasError
from canvasgrade.grading.roster import Roster, RosterEntry
from canvasgrade.grading.rubric import CanvasCriterion

NAME_COLUMN = "Student"
ID_COLUMN = "ID"
SIS_COLUMN = "SIS Login ID"
TOTAL_COLUMN = "Total"


def fetch_roster(course: Any, *, include_test_student: bool = False) -> Roster:
    """Fetch the enrolled students, with whatever identifiers Canvas will give us."""
    try:
        users = list(
            course.get_users(
                enrollment_type=["student"],
                enrollment_state=["active", "invited"],
                include=["enrollments"],
                per_page=100,
            )
        )
    except API_ERRORS as exc:
        raise _explain(exc, f"listing students in course {course.id}") from exc

    entries: list[RosterEntry] = []
    for user in users:
        name = str(getattr(user, "name", "") or "")
        if not include_test_student and name.strip().lower() == "test student":
            continue
        entries.append(
            RosterEntry(
                user_id=int(user.id),
                name=name,
                sortable_name=str(getattr(user, "sortable_name", "") or ""),
                sis_user_id=_text(getattr(user, "sis_user_id", None)),
                login_id=_text(getattr(user, "login_id", None)),
            )
        )

    if not entries:
        raise CanvasError(f"Course {course.id} has no active students, or your role cannot see them.")
    return Roster(entries=tuple(sorted(entries, key=lambda e: e.sortable_name or e.name)))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _criterion_header(criterion: CanvasCriterion) -> str:
    """Render a criterion as a header the detector will read back correctly."""
    points = f"{criterion.points:g}"
    return f"{criterion.description} ({points})"


def fetch_existing_scores(
    assignment: Any,
    criteria: tuple[CanvasCriterion, ...],
) -> dict[int, dict[str, float]]:
    """Read back the scores already on Canvas, keyed by user id then criterion id."""
    try:
        submissions = list(assignment.get_submissions(include=["rubric_assessment"], per_page=100))
    except API_ERRORS as exc:
        raise _explain(exc, f"reading existing grades for assignment {assignment.id}") from exc

    known = {c.criterion_id for c in criteria}
    scores: dict[int, dict[str, float]] = {}
    for submission in submissions:
        assessment = getattr(submission, "rubric_assessment", None)
        if not isinstance(assessment, dict):
            continue
        per_criterion: dict[str, float] = {}
        for criterion_id, value in assessment.items():
            if criterion_id in known and isinstance(value, dict) and value.get("points") is not None:
                per_criterion[criterion_id] = float(value["points"])
        if per_criterion:
            scores[int(submission.user_id)] = per_criterion
    return scores


def build_template(
    roster: Roster,
    criteria: tuple[CanvasCriterion, ...] = (),
    *,
    existing: dict[int, dict[str, float]] | None = None,
    include_total: bool = True,
) -> pd.DataFrame:
    """Build a grading sheet: one row per student, one column per criterion."""
    existing = existing or {}
    headers = [_criterion_header(c) for c in criteria]

    records: list[dict[str, Any]] = []
    for entry in roster.entries:
        record: dict[str, Any] = {
            NAME_COLUMN: entry.name,
            ID_COLUMN: entry.user_id,
            SIS_COLUMN: entry.sis_user_id or entry.login_id or "",
        }
        scores = existing.get(entry.user_id, {})
        for criterion, header in zip(criteria, headers, strict=True):
            record[header] = scores.get(criterion.criterion_id, "")
        if include_total and criteria:
            total = sum(scores.values()) if scores else ""
            record[f"{TOTAL_COLUMN} ({sum(c.points for c in criteria):g})"] = total
        records.append(record)

    columns = [NAME_COLUMN, ID_COLUMN, SIS_COLUMN, *headers]
    if include_total and criteria:
        columns.append(f"{TOTAL_COLUMN} ({sum(c.points for c in criteria):g})")
    return pd.DataFrame.from_records(records, columns=columns)


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def merge_templates(fresh: pd.DataFrame, previous: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Carry hand-entered scores from an earlier template into a freshly pulled one.

    The roster in ``fresh`` wins, since picking up enrolment changes is the reason to
    pull again. Anything already typed in ``previous`` beats a blank, matched on Canvas
    id so that reordering rows or editing a name cannot lose a score.

    Returns the merged sheet and a plain-language account of what changed, because
    silently dropping a departed student's marks would be the worst way to find out.
    """
    if ID_COLUMN not in previous.columns:
        raise CanvasError(
            f"{ID_COLUMN!r} is missing from the existing file, so scores cannot be matched "
            "to students. Pass --force to overwrite it instead."
        )

    kept = previous.set_index(pd.to_numeric(previous[ID_COLUMN], errors="coerce"))
    # A freshly built template has empty score columns, which pandas types as str; the
    # scores being carried over are numbers, so widen to object before writing any.
    merged = fresh.astype(object)
    notes: list[str] = []

    filled = 0
    for column in merged.columns:
        if column in (NAME_COLUMN, ID_COLUMN, SIS_COLUMN) or column not in kept.columns:
            continue
        position_of_column = merged.columns.get_loc(column)
        for row, user_id in enumerate(merged[ID_COLUMN]):
            if user_id not in kept.index:
                continue
            existing = kept.at[user_id, column]
            if isinstance(existing, pd.Series):  # the old file had duplicate ids
                existing = existing.iloc[0]
            if pd.isna(existing) or str(existing).strip() == "":
                continue
            merged.iat[row, position_of_column] = existing
            filled += 1
    if filled:
        notes.append(f"kept {_plural(filled, 'score')} already entered in the file")

    fresh_ids = set(pd.to_numeric(merged[ID_COLUMN], errors="coerce").dropna())
    previous_ids = set(kept.index.dropna())
    added = fresh_ids - previous_ids
    gone = previous_ids - fresh_ids
    if added:
        notes.append(f"{_plural(len(added), 'student is', 'students are')} new since that file was written")
    if gone:
        notes.append(
            f"{_plural(len(gone), 'student', 'students')} in that file "
            f"{'is' if len(gone) == 1 else 'are'} no longer enrolled, and their scores were dropped"
        )

    dropped_columns = [
        c for c in previous.columns if c not in merged.columns and c not in (NAME_COLUMN, ID_COLUMN, SIS_COLUMN)
    ]
    if dropped_columns:
        listed = ", ".join(repr(c) for c in dropped_columns[:4])
        notes.append(
            f"{_plural(len(dropped_columns), 'column is', 'columns are')} not in the rubric any more: {listed}"
        )

    return merged, notes


def write_template(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write the template as XLSX or CSV, inferred from the file extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xlsm"):
            frame.to_excel(path, index=False, engine="openpyxl")
        elif suffix == ".csv":
            frame.to_csv(path, index=False, encoding="utf-8-sig")
        else:
            raise CanvasError(f"Cannot write '{suffix}' templates. Use .xlsx or .csv.")
    except CanvasError:
        raise
    except OSError as exc:
        raise CanvasError(f"Could not write {path}: {exc}") from exc
    return path
