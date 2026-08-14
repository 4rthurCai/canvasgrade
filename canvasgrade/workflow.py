"""Orchestration shared by every front end.

The CLI and the web GUI both need the same sequence - read the sheet, work out the
rubric, resolve students, build a plan - so it lives here rather than in either one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from canvasgrade.canvas.client import AssignmentInfo, CanvasSession, _assignment_info
from canvasgrade.canvas.pull import fetch_roster
from canvasgrade.canvas.rubrics import create_rubric, find_attached_rubric, load_rubric
from canvasgrade.errors import CanvasGradeError, MappingError
from canvasgrade.grading.plan import GradeOptions, build_plan
from canvasgrade.grading.roster import Roster
from canvasgrade.grading.rubric import bind_to_existing, build_rubric
from canvasgrade.grading.validate import validate_plan
from canvasgrade.models import (
    ColumnRole,
    ColumnSpec,
    GradePlan,
    Issue,
    RubricSpec,
    SheetMapping,
    StudentRow,
)
from canvasgrade.sheet.detect import detect_mapping, promote_all_to_criteria
from canvasgrade.sheet.reader import SheetData, read_sheet
from canvasgrade.sheet.rows import extract_rows
from canvasgrade.sheet.select import filter_criteria

#: Rubric sources, in the order a user is likely to want them.
RUBRIC_MODES = ("attached", "create", "existing", "none")
#: Placeholder criterion ids used to preview a rubric that has not been created yet.
PREVIEW_ID_PREFIX = "_preview_"


@dataclass(frozen=True)
class ColumnOverride:
    """A role the user assigned by hand, overruling what the detector guessed."""

    name: str
    role: ColumnRole
    points: float | None = None
    target: str | None = None
    description: str | None = None
    long_description: str | None = None


@dataclass(frozen=True)
class SheetRequest:
    """Where the grades come from and which columns count."""

    path: Path
    sheet: str | int = 0
    has_header: bool = True
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    #: Make every column that can hold a score a criterion, instead of only those whose
    #: header declares a max. Applied before ``overrides``, so a hand-set role wins.
    all_criteria: bool = False
    #: Applied after detection and before filtering, so the GUI can correct a guess.
    overrides: tuple[ColumnOverride, ...] = ()
    #: Name of the column holding the assignment total, when the detector's choice is
    #: wrong - a sheet covering three milestones has a subtotal per milestone and the
    #: detector keeps the last one, which is the whole-project figure.
    total_column: str | None = None
    #: Name of the column holding the Canvas user id, when the detector picks the wrong
    #: one. A sheet often carries both a Canvas id and an institution student number.
    id_column: str | None = None


@dataclass(frozen=True)
class RubricRequest:
    """Which rubric to score against."""

    mode: str = "attached"
    rubric_id: int | None = None
    title: str | None = None
    use_for_grading: bool = False

    def __post_init__(self) -> None:
        if self.mode not in RUBRIC_MODES:
            raise ValueError(f"rubric mode must be one of {RUBRIC_MODES}, got {self.mode!r}")


@dataclass(frozen=True)
class PreparedSheet:
    """A sheet that has been read, understood and reduced to student rows."""

    data: SheetData
    mapping: SheetMapping
    rows: tuple[StudentRow, ...]


@dataclass(frozen=True)
class PreparedPush:
    """Everything a caller needs to preview, confirm and then execute a push."""

    sheet: PreparedSheet
    assignment: AssignmentInfo
    rubric: RubricSpec | None
    plan: GradePlan
    rubric_created: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_preview_only(self) -> bool:
        """True when the rubric is a stand-in that does not exist on Canvas yet."""
        rubric = self.rubric
        return bool(rubric and any((c.criterion_id or "").startswith(PREVIEW_ID_PREFIX) for c in rubric.criteria))


def load_sheet(request: SheetRequest) -> PreparedSheet:
    """Read a spreadsheet and infer everything we can without touching the network."""
    data = read_sheet(request.path, sheet=request.sheet, has_header=request.has_header)
    mapping = detect_mapping(data.frame, has_header=request.has_header)
    if request.all_criteria:
        mapping = promote_all_to_criteria(data.frame, mapping)
    for override in request.overrides:
        mapping = mapping.override(
            override.name,
            override.role,
            points=override.points,
            target=override.target,
            description=override.description,
            long_description=override.long_description,
        )
    mapping = _resolve_single_roles(mapping)
    if request.id_column:
        mapping = _force_role(mapping, request.id_column, ColumnRole.CANVAS_ID, "--id-column")
    if request.total_column:
        mapping = _force_role(mapping, request.total_column, ColumnRole.TOTAL, "--total-column")
    mapping = filter_criteria(mapping, include=request.include, exclude=request.exclude)
    rows = extract_rows(data.frame, mapping)
    if not rows:
        raise MappingError(
            f"No student rows found in {request.path.name}. Run 'canvasgrade inspect' to see how the columns were read."
        )
    return PreparedSheet(data=data, mapping=mapping, rows=rows)


#: Roles only one column can hold at a time.
SINGLE_ROLES = (
    ColumnRole.CANVAS_ID,
    ColumnRole.SIS_ID,
    ColumnRole.NAME,
    ColumnRole.TEAM,
    ColumnRole.TOTAL,
    ColumnRole.RATIO,
)


def _resolve_single_roles(mapping: SheetMapping) -> SheetMapping:
    """Let a hand-assigned role displace the one the detector chose.

    Detection already keeps a single column per role, but an override is applied on top
    and can reintroduce a duplicate. Lookups then pick by column order, which silently
    ignores the choice the user just made.
    """
    for role in SINGLE_ROLES:
        holders = mapping.by_role(role)
        if len(holders) < 2:
            continue
        explicit = [c for c in holders if not c.inferred]
        if not explicit:
            continue
        winner = explicit[-1]
        for column in holders:
            if column.name != winner.name:
                mapping = mapping.override(
                    column.name,
                    ColumnRole.IGNORE,
                    reason=f"'{winner.name}' was set as the {role.value.replace('_', ' ')}",
                )
    return mapping


def _find_column(mapping: SheetMapping, name: str) -> ColumnSpec | None:
    """Locate a column by header, case-insensitively and with the max marker optional."""
    from canvasgrade.sheet.detect import normalise, strip_points

    wanted = normalise(name)
    return next(
        (c for c in mapping.columns if wanted in (normalise(c.name), normalise(strip_points(c.name)))),
        None,
    )


def _force_role(mapping: SheetMapping, name: str, role: ColumnRole, flag: str) -> SheetMapping:
    """Give ``name`` a role by hand, demoting whichever column the detector chose.

    The chosen column may have been demoted during detection, which drops its max, so
    the max is read back off the header rather than trusting what survived.
    """
    from canvasgrade.sheet.detect import parse_points

    chosen = _find_column(mapping, name)
    if chosen is None:
        current = ", ".join(repr(c.name) for c in mapping.by_role(role)) or "none detected"
        raise MappingError(
            f"No column named {name!r}. Columns currently read as the {role.value.replace('_', ' ')}: "
            f"{current}. Run 'canvasgrade inspect' to list every column."
        )

    for column in mapping.by_role(role):
        if column.name != chosen.name:
            mapping = mapping.override(column.name, ColumnRole.IGNORE, reason=f"{flag} chose '{chosen.name}' instead")
    return mapping.override(
        chosen.name,
        role,
        points=chosen.points if chosen.points is not None else parse_points(chosen.name),
        reason=f"named by {flag}",
    )


def diagnose_identity(prepared: PreparedSheet, roster: Roster, plan: GradePlan) -> str | None:
    """When rows fail to match, name the column whose values are actually enrolled.

    Canvas user ids cannot be told from an institution's student number by looking at
    them - both are just integers, and how many digits a Canvas id has depends on how
    old the instance is. What can be checked is whether the numbers are enrolled.
    """
    import pandas as pd

    if roster.is_empty or not plan.skipped:
        return None

    enrolled = {entry.user_id for entry in roster.entries}
    current = prepared.mapping.first(ColumnRole.CANVAS_ID)
    current_hits = len(plan.entries)

    best_name, best_hits = None, current_hits
    for column in prepared.mapping.columns:
        if current is not None and column.name == current.name:
            continue
        values = pd.to_numeric(prepared.data.frame.iloc[:, column.index], errors="coerce").dropna()
        if values.empty:
            continue
        hits = sum(1 for value in values if float(value).is_integer() and int(value) in enrolled)
        if hits > best_hits:
            best_name, best_hits = column.name, hits

    if best_name is None:
        return None
    using = f"'{current.name}' matched {current_hits} students" if current else "no id column was found"
    return (
        f"{using}, but {best_hits} of the values in '{best_name}' are enrolled in this "
        f"course. If that is the Canvas user id, use '{best_name}' as the id column "
        f"instead (--id-column on the command line, or the Role dropdown in the GUI)."
    )


def _preview_rubric(spec: RubricSpec) -> RubricSpec:
    """Bind placeholder ids so a not-yet-created rubric can still be previewed."""
    criteria = tuple(
        criterion.with_id(f"{PREVIEW_ID_PREFIX}{index}") for index, criterion in enumerate(spec.criteria, start=1)
    )
    return RubricSpec(title=spec.title, criteria=criteria)


def resolve_rubric(
    course: Any,
    assignment: Any,
    prepared: PreparedSheet,
    request: RubricRequest,
    *,
    dry_run: bool,
) -> tuple[RubricSpec | None, bool, list[str]]:
    """Work out which rubric to score against, creating one if that is what was asked.

    Returns the bound rubric, whether it was created just now, and any notes to show.
    """
    notes: list[str] = []
    if request.mode == "none":
        return None, False, ["Pushing totals only - no rubric assessment will be written."]

    title = request.title or f"{getattr(assignment, 'name', 'Assignment')} rubric"

    if request.mode == "create":
        spec = build_rubric(prepared.mapping, title)
        existing_id, _ = find_attached_rubric(assignment)
        if existing_id:
            notes.append(
                f"This assignment already has rubric {existing_id} attached; a second one will be "
                "created and used instead. Pass --rubric-id to reuse the existing one."
            )
        if dry_run:
            notes.append(f"Would create rubric {title!r} with {len(spec.criteria)} criteria.")
            return _preview_rubric(spec), False, notes
        created = create_rubric(course, assignment, spec, use_for_grading=request.use_for_grading)
        notes.append(f"Created rubric {created.rubric_id} ({len(created.criteria)} criteria).")
        return created, True, notes

    if request.mode == "existing":
        if request.rubric_id is None:
            raise MappingError("--rubric-id is required when reusing an existing rubric.")
        criteria = load_rubric(course, request.rubric_id)
        spec = build_rubric(prepared.mapping, title)
        bound, warnings = bind_to_existing(spec, criteria, rubric_id=request.rubric_id)
        notes.extend(warnings)
        return bound, False, notes

    rubric_id, criteria = find_attached_rubric(assignment)
    if rubric_id is None or not criteria:
        raise CanvasGradeError(
            "No rubric is attached to this assignment. Add --create-rubric to build one from "
            "your column headers, or --no-rubric to push totals only."
        )
    spec = build_rubric(prepared.mapping, title)
    bound, warnings = bind_to_existing(spec, criteria, rubric_id=rubric_id)
    notes.append(f"Using the rubric already attached to this assignment (id {rubric_id}).")
    notes.extend(warnings)
    return bound, False, notes


def prepare_push(
    session: CanvasSession,
    *,
    course_id: int,
    assignment_id: int,
    sheet_request: SheetRequest,
    rubric_request: RubricRequest | None = None,
    options: GradeOptions | None = None,
    dry_run: bool = False,
    use_roster: bool = True,
) -> PreparedPush:
    """Do everything up to, but not including, writing grades to Canvas."""
    rubric_request = rubric_request or RubricRequest()
    options = options or GradeOptions()

    prepared = load_sheet(sheet_request)
    course = session.course(course_id)
    assignment = session.assignment(course, assignment_id)
    info = _assignment_info(assignment)

    rubric, created, notes = resolve_rubric(course, assignment, prepared, rubric_request, dry_run=dry_run)

    roster = fetch_roster(course) if use_roster else Roster()
    plan = build_plan(prepared.rows, rubric=rubric, roster=roster, options=options)
    plan = validate_plan(plan, points_possible=info.points_possible, roster_size=len(roster.entries) or None)

    suggestion = diagnose_identity(prepared, roster, plan)
    if suggestion:
        plan = GradePlan(
            rubric=plan.rubric,
            entries=plan.entries,
            issues=(*plan.issues, Issue("warning", suggestion)),
            skipped=plan.skipped,
        )

    return PreparedPush(
        sheet=prepared,
        assignment=info,
        rubric=rubric,
        plan=plan,
        rubric_created=created,
        notes=tuple(notes),
    )
