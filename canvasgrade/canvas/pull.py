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
