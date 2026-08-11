"""Assemble the reviewable plan: which student gets which score, and why.

Nothing here talks to Canvas. A plan can be printed, diffed and argued with before a
single request goes out, which is the whole point of ``--dry-run``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from canvasgrade.grading.roster import Roster
from canvasgrade.models import GradeEntry, GradePlan, Issue, RubricSpec, StudentRow

TOTAL_MODES = ("auto", "sheet", "sum")
DEFAULT_COMMENT = "Grades updated by canvasgrade on {timestamp}."


@dataclass(frozen=True)
class GradeOptions:
    """Knobs that change how a row becomes a grade."""

    #: "sheet" trusts the sheet's total column, "sum" adds the criteria up,
    #: "auto" uses the total column when the sheet has one.
    total: str = "auto"
    #: Multiply the total by the sheet's ratio column. Off by default, because a total
    #: column usually already has the ratio baked in.
    apply_ratio: bool = False
    add_comment: bool = False
    comment_template: str = DEFAULT_COMMENT
    #: Treat a blank criterion cell as zero rather than skipping the student.
    missing_as_zero: bool = True
    #: Pull scores above a criterion's max back down to the max.
    clamp: bool = True

    def __post_init__(self) -> None:
        if self.total not in TOTAL_MODES:
            raise ValueError(f"total must be one of {TOTAL_MODES}, got {self.total!r}")


def _render_comment(template: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return template.format(timestamp=timestamp)


def _resolve_total(
    row: StudentRow,
    criterion_sum: float,
    options: GradeOptions,
    issues: list[Issue],
) -> float | None:
    if options.total == "sum":
        total = criterion_sum
    elif options.total == "sheet":
        if row.total_override is None:
            issues.append(
                Issue("error", f"{row.label}: --total sheet was requested but the total cell is empty", row.row_index)
            )
            return None
        total = row.total_override
    else:
        total = criterion_sum if row.total_override is None else row.total_override

    if options.apply_ratio:
        if row.ratio is None:
            issues.append(Issue("warning", f"{row.label}: no ratio in the sheet, applying 1.0", row.row_index))
        else:
            total *= row.ratio
    return total


def build_plan(
    rows: Sequence[StudentRow],
    *,
    rubric: RubricSpec | None,
    roster: Roster | None = None,
    options: GradeOptions | None = None,
) -> GradePlan:
    """Turn student rows into grade entries, collecting every complaint on the way."""
    options = options or GradeOptions()
    roster = roster or Roster()
    issues: list[Issue] = []
    skipped: list[tuple[StudentRow, str]] = []
    entries: list[GradeEntry] = []

    if rubric is not None and not rubric.is_bound:
        raise ValueError("Rubric must carry Canvas criterion ids before a plan can be built")

    for row in rows:
        match = roster.resolve(row)
        if not match.ok:
            skipped.append((row, match.detail or match.method))
            continue

        criterion_points: list[tuple[str, float]] = []
        criterion_comments: list[tuple[str, str]] = []
        criterion_sum = 0.0
        blank_criteria = 0

        for criterion in rubric.criteria if rubric else ():
            assert criterion.criterion_id is not None  # guaranteed by is_bound
            score = row.score_map.get(criterion.column)
            if score is None:
                blank_criteria += 1
                if not options.missing_as_zero:
                    continue
                score = 0.0
            if score < 0:
                issues.append(
                    Issue("warning", f"{row.label}: '{criterion.description}' is negative ({score:g})", row.row_index)
                )
            if score > criterion.points:
                level, action = ("warning", "clamped") if options.clamp else ("error", "exceeds the max")
                issues.append(
                    Issue(
                        level,
                        f"{row.label}: '{criterion.description}' is {score:g} but the max is "
                        f"{criterion.points:g} ({action})",
                        row.row_index,
                    )
                )
                if options.clamp:
                    score = criterion.points

            criterion_points.append((criterion.criterion_id, score))
            criterion_sum += score

            comment = row.comment_map.get(criterion.column)
            if comment:
                criterion_comments.append((criterion.criterion_id, comment))

        if rubric and blank_criteria == len(rubric.criteria) and row.total_override is None:
            skipped.append((row, "no scores in the sheet"))
            continue
        if rubric and blank_criteria and options.missing_as_zero:
            issues.append(
                Issue("warning", f"{row.label}: {blank_criteria} criteria are blank, scored as 0", row.row_index)
            )

        total = _resolve_total(row, criterion_sum, options, issues)
        if total is None:
            continue

        entries.append(
            GradeEntry(
                user_id=match.user_id,  # type: ignore[arg-type]
                posted_grade=round(total, 4),
                criterion_points=tuple(criterion_points),
                criterion_comments=tuple(criterion_comments),
                text_comment=_render_comment(options.comment_template) if options.add_comment else None,
                label=row.label,
            )
        )

    issues.extend(_duplicate_issues(entries))
    if not entries:
        issues.append(Issue("error", "No student in the sheet could be matched to this course"))

    return GradePlan(
        rubric=rubric,
        entries=tuple(entries),
        issues=tuple(issues),
        skipped=tuple(skipped),
    )


def _duplicate_issues(entries: Sequence[GradeEntry]) -> list[Issue]:
    """Two rows resolving to one student is always a mistake worth stopping for."""
    counts = Counter(entry.user_id for entry in entries)
    issues: list[Issue] = []
    for user_id, count in counts.items():
        if count > 1:
            labels = ", ".join(sorted({e.label for e in entries if e.user_id == user_id}))
            issues.append(Issue("error", f"{count} rows resolve to the same Canvas user {user_id} ({labels})"))
    return issues
