"""Terminal rendering.

Kept apart from the command definitions so the CLI stays a thin layer of argument
parsing, and so the same summaries can be reused by other front ends.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from canvasgrade.models import ColumnRole, GradePlan, RubricSpec, SheetMapping, StudentRow

#: How many rows of the grade preview to print before summarising.
PREVIEW_ROWS = 10
#: How many issues of each severity to print in full.
ISSUE_LIMIT = 12

ROLE_STYLES = {
    ColumnRole.CRITERION: "bold cyan",
    ColumnRole.TOTAL: "bold magenta",
    ColumnRole.CANVAS_ID: "green",
    ColumnRole.SIS_ID: "green",
    ColumnRole.NAME: "green",
    ColumnRole.TEAM: "yellow",
    ColumnRole.COMMENT: "blue",
    ColumnRole.RATIO: "yellow",
    ColumnRole.IGNORE: "dim",
}


def console(*, quiet: bool = False) -> Console:
    return Console(quiet=quiet, highlight=False)


def mapping_table(mapping: SheetMapping) -> Table:
    """Show how every column was read, and why."""
    table = Table(title="Detected columns", title_justify="left", header_style="bold")
    table.add_column("Column", overflow="fold", max_width=38)
    table.add_column("Role")
    table.add_column("Max", justify="right")
    table.add_column("Why", style="dim", overflow="fold")

    for column in mapping.columns:
        points = f"{column.points:g}" if column.points is not None else ""
        table.add_row(
            column.name,
            Text(column.role.value, style=ROLE_STYLES.get(column.role, "")),
            points,
            column.reason,
        )
    return table


def rubric_table(spec: RubricSpec) -> Table:
    table = Table(title=f"Rubric: {spec.title}", title_justify="left", header_style="bold")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Criterion", overflow="fold")
    table.add_column("Max", justify="right")
    table.add_column("Canvas id", style="dim")
    for index, criterion in enumerate(spec.criteria, start=1):
        table.add_row(str(index), criterion.description, f"{criterion.points:g}", criterion.criterion_id or "-")
    table.add_row("", Text("total", style="bold"), Text(f"{spec.total_points:g}", style="bold"), "")
    return table


def rows_summary(rows: Sequence[StudentRow]) -> str:
    teams = sorted({row.team for row in rows if row.team})
    parts = [f"{len(rows)} students"]
    if teams:
        parts.append(f"{len(teams)} teams")
    with_totals = sum(1 for row in rows if row.total_override is not None)
    if with_totals:
        parts.append(f"{with_totals} with a total in the sheet")
    return ", ".join(parts)


def plan_table(plan: GradePlan, *, limit: int = PREVIEW_ROWS) -> Table:
    """Preview what each student will receive."""
    rubric = plan.rubric
    table = Table(title="Grades to push", title_justify="left", header_style="bold")
    table.add_column("Student", overflow="fold", max_width=26)
    table.add_column("Canvas id", justify="right", style="dim")
    table.add_column("Total", justify="right", style="bold")
    if rubric:
        table.add_column("Criteria", overflow="fold")
        table.add_column("Comments", justify="right", style="dim")

    for entry in plan.entries[:limit]:
        row = [entry.label, str(entry.user_id), f"{entry.posted_grade:g}"]
        if rubric:
            scores = " ".join(f"{points:g}" for _, points in entry.criterion_points)
            row.append(scores)
            row.append(str(len(entry.criterion_comments)) if entry.criterion_comments else "")
        table.add_row(*row)

    remaining = len(plan.entries) - limit
    if remaining > 0:
        filler = ["", "", ""] + (["", ""] if rubric else [])
        filler[0] = f"... and {remaining} more"
        table.add_row(*[Text(cell, style="dim") for cell in filler])
    return table


def print_issues(out: Console, plan: GradePlan) -> None:
    """Print errors, then warnings, then skipped rows - each capped."""
    for issue in plan.errors[:ISSUE_LIMIT]:
        out.print(f"  [bold red]error[/]   {issue.message}")
    if len(plan.errors) > ISSUE_LIMIT:
        out.print(f"  [dim]... and {len(plan.errors) - ISSUE_LIMIT} more errors[/]")

    for issue in plan.warnings[:ISSUE_LIMIT]:
        out.print(f"  [yellow]warning[/] {issue.message}")
    if len(plan.warnings) > ISSUE_LIMIT:
        out.print(f"  [dim]... and {len(plan.warnings) - ISSUE_LIMIT} more warnings[/]")

    if plan.skipped:
        out.print(f"\n  [yellow]{len(plan.skipped)} rows skipped:[/]")
        for row, reason in plan.skipped[:ISSUE_LIMIT]:
            out.print(f"    [dim]row {row.row_index + 1}[/] {row.label}: {reason}")
        if len(plan.skipped) > ISSUE_LIMIT:
            out.print(f"    [dim]... and {len(plan.skipped) - ISSUE_LIMIT} more[/]")


def plan_summary(plan: GradePlan) -> Text:
    """One line a TA can read at a glance before confirming."""
    text = Text()
    text.append(f"{len(plan.entries)} students ready", style="bold green" if plan.entries else "bold red")
    if plan.skipped:
        text.append(f", {len(plan.skipped)} skipped", style="yellow")
    if plan.errors:
        text.append(f", {len(plan.errors)} errors", style="bold red")
    if plan.warnings:
        text.append(f", {len(plan.warnings)} warnings", style="yellow")
    if plan.entries:
        totals = [entry.posted_grade for entry in plan.entries]
        text.append(
            f"  |  totals {min(totals):g}-{max(totals):g}, mean {sum(totals) / len(totals):.1f}",
            style="dim",
        )
    return text
