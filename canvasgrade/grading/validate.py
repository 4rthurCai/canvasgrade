"""Checks that need to know about the Canvas assignment, not just the sheet.

These run after the plan is built and before anything is pushed, so a mismatch between
a 210-point rubric and a 70-point assignment is caught while it is still cheap.
"""

from __future__ import annotations

from canvasgrade.models import GradePlan, Issue

#: Only name this many students in a single aggregate warning.
SAMPLE_SIZE = 5


def validate_plan(
    plan: GradePlan,
    *,
    points_possible: float | None = None,
    roster_size: int | None = None,
) -> GradePlan:
    """Return a copy of the plan with assignment-level issues folded in."""
    issues = list(plan.issues)

    if plan.rubric and points_possible is not None:
        rubric_total = plan.rubric.total_points
        if abs(rubric_total - points_possible) > 1e-6:
            issues.append(
                Issue(
                    "warning",
                    f"The rubric adds up to {rubric_total:g} points but the assignment is out of "
                    f"{points_possible:g}. Filter columns with --include if this sheet covers "
                    "several assignments.",
                )
            )

    if points_possible is not None:
        over = [e for e in plan.entries if e.posted_grade > points_possible + 1e-6]
        if over:
            names = ", ".join(f"{e.label} ({e.posted_grade:g})" for e in over[:SAMPLE_SIZE])
            suffix = f" and {len(over) - SAMPLE_SIZE} more" if len(over) > SAMPLE_SIZE else ""
            issues.append(Issue("warning", f"{len(over)} students score above {points_possible:g}: {names}{suffix}"))

    negative = [e for e in plan.entries if e.posted_grade < 0]
    if negative:
        names = ", ".join(e.label for e in negative[:SAMPLE_SIZE])
        issues.append(Issue("error", f"{len(negative)} students have a negative total: {names}"))

    if roster_size is not None and plan.entries:
        ungraded = roster_size - len(plan.entries)
        if ungraded > 0:
            issues.append(Issue("warning", f"{ungraded} of {roster_size} enrolled students are not in this sheet"))

    if plan.skipped:
        issues.append(Issue("warning", f"{len(plan.skipped)} rows were skipped; see the skipped list for reasons"))

    return GradePlan(
        rubric=plan.rubric,
        entries=plan.entries,
        issues=tuple(issues),
        skipped=plan.skipped,
    )
