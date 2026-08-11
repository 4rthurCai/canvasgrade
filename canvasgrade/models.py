"""Immutable data models shared across the pipeline.

Flow::

    spreadsheet -> SheetMapping + StudentRow -> RubricSpec -> GradePlan -> Canvas

Every model is frozen; transformations return new objects rather than mutating.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class ColumnRole(str, Enum):
    """What a spreadsheet column means to us."""

    CANVAS_ID = "canvas_id"
    SIS_ID = "sis_id"
    NAME = "name"
    TEAM = "team"
    CRITERION = "criterion"
    COMMENT = "comment"
    TOTAL = "total"
    RATIO = "ratio"
    IGNORE = "ignore"

    @property
    def is_identity(self) -> bool:
        return self in (ColumnRole.CANVAS_ID, ColumnRole.SIS_ID, ColumnRole.NAME)


@dataclass(frozen=True)
class ColumnSpec:
    """One column of the input sheet and the role it plays."""

    name: str
    index: int
    role: ColumnRole
    points: float | None = None
    #: For COMMENT columns: the ``name`` of the criterion column it annotates.
    target: str | None = None
    #: True when the role was guessed, False when the user set it explicitly.
    inferred: bool = True
    #: Why the detector chose this role - shown in the CLI table and the GUI.
    reason: str = ""

    def with_role(
        self,
        role: ColumnRole,
        *,
        points: float | None = None,
        target: str | None = None,
        reason: str = "set by user",
    ) -> ColumnSpec:
        """Return a copy carrying a user-supplied role."""
        return replace(self, role=role, points=points, target=target, inferred=False, reason=reason)


@dataclass(frozen=True)
class SheetMapping:
    """The full column -> role assignment for one sheet."""

    columns: tuple[ColumnSpec, ...]

    def by_role(self, role: ColumnRole) -> tuple[ColumnSpec, ...]:
        return tuple(c for c in self.columns if c.role is role)

    def first(self, role: ColumnRole) -> ColumnSpec | None:
        found = self.by_role(role)
        return found[0] if found else None

    def get(self, name: str) -> ColumnSpec | None:
        for column in self.columns:
            if column.name == name:
                return column
        return None

    @property
    def criteria_columns(self) -> tuple[ColumnSpec, ...]:
        return self.by_role(ColumnRole.CRITERION)

    @property
    def has_identity(self) -> bool:
        return any(c.role.is_identity for c in self.columns)

    def override(
        self,
        name: str,
        role: ColumnRole,
        *,
        points: float | None = None,
        target: str | None = None,
        reason: str = "set by user",
    ) -> SheetMapping:
        """Return a new mapping with one column's role replaced."""
        if self.get(name) is None:
            raise KeyError(f"No column named {name!r} in this sheet")
        columns = tuple(
            c.with_role(role, points=points, target=target, reason=reason) if c.name == name else c
            for c in self.columns
        )
        return SheetMapping(columns=columns)


@dataclass(frozen=True)
class Criterion:
    """One rubric criterion, derived from a spreadsheet column header."""

    #: Originating column name - the join key against StudentRow.scores.
    column: str
    description: str
    points: float
    long_description: str = ""
    #: Canvas criterion id (e.g. "_1234"), known only once the rubric exists.
    criterion_id: str | None = None

    def with_id(self, criterion_id: str) -> Criterion:
        return replace(self, criterion_id=criterion_id)


@dataclass(frozen=True)
class RubricSpec:
    """A rubric we intend to create on, or match against, Canvas."""

    title: str
    criteria: tuple[Criterion, ...]
    rubric_id: int | None = None

    @property
    def total_points(self) -> float:
        return sum(c.points for c in self.criteria)

    @property
    def is_bound(self) -> bool:
        """True once every criterion carries a Canvas criterion id."""
        return bool(self.criteria) and all(c.criterion_id for c in self.criteria)

    def criterion_for(self, column: str) -> Criterion | None:
        for criterion in self.criteria:
            if criterion.column == column:
                return criterion
        return None

    def with_ids(self, ids_by_description: dict[str, str], rubric_id: int) -> RubricSpec:
        """Attach Canvas criterion ids, matched on criterion description."""
        criteria = tuple(
            c.with_id(ids_by_description[c.description]) if c.description in ids_by_description else c
            for c in self.criteria
        )
        return replace(self, criteria=criteria, rubric_id=rubric_id)


@dataclass(frozen=True)
class StudentRow:
    """One student's row, normalised out of the raw sheet."""

    row_index: int
    name: str | None = None
    canvas_id: int | None = None
    sis_id: str | None = None
    team: str | None = None
    #: criterion column name -> raw score
    scores: tuple[tuple[str, float], ...] = ()
    #: criterion column name -> comment text
    comments: tuple[tuple[str, str], ...] = ()
    #: Explicit total from a TOTAL column, when the sheet provides one.
    total_override: float | None = None
    #: Multiplier from a RATIO column, when present.
    ratio: float | None = None

    @property
    def score_map(self) -> dict[str, float]:
        return dict(self.scores)

    @property
    def comment_map(self) -> dict[str, str]:
        return dict(self.comments)

    @property
    def has_identity(self) -> bool:
        return self.canvas_id is not None or bool(self.sis_id) or bool(self.name)

    @property
    def label(self) -> str:
        """Human-readable identifier for logs and error messages."""
        if self.name:
            return self.name
        if self.canvas_id is not None:
            return str(self.canvas_id)
        if self.sis_id:
            return self.sis_id
        return f"row {self.row_index + 1}"


@dataclass(frozen=True)
class GradeEntry:
    """A fully-resolved grade ready to be pushed for one Canvas user."""

    user_id: int
    posted_grade: float
    #: Canvas criterion id -> points
    criterion_points: tuple[tuple[str, float], ...] = ()
    #: Canvas criterion id -> comment
    criterion_comments: tuple[tuple[str, str], ...] = ()
    text_comment: str | None = None
    #: Carried for display only.
    label: str = ""

    def rubric_assessment(self) -> dict[str, dict[str, object]]:
        """Render the ``rubric_assessment`` payload Canvas expects."""
        comments = dict(self.criterion_comments)
        assessment: dict[str, dict[str, object]] = {}
        for criterion_id, points in self.criterion_points:
            entry: dict[str, object] = {"points": points}
            comment = comments.get(criterion_id)
            if comment:
                entry["comments"] = comment
            assessment[criterion_id] = entry
        return assessment


@dataclass(frozen=True)
class Issue:
    """A validation finding surfaced before anything is pushed."""

    level: str  # "error" | "warning"
    message: str
    row_index: int | None = None

    @property
    def is_error(self) -> bool:
        return self.level == "error"


@dataclass(frozen=True)
class GradePlan:
    """Everything needed to preview or execute a push."""

    rubric: RubricSpec | None
    entries: tuple[GradeEntry, ...]
    issues: tuple[Issue, ...] = ()
    #: Rows that produced no entry, paired with the reason.
    skipped: tuple[tuple[StudentRow, str], ...] = ()

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if i.is_error)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(i for i in self.issues if not i.is_error)

    @property
    def is_pushable(self) -> bool:
        return bool(self.entries) and not self.errors

    def with_warnings_as_errors(self) -> GradePlan:
        """Return a copy where every warning blocks the push.

        Warnings are advisory by default because several of them fire on perfectly
        normal runs - grading half a class, or leaving criteria blank. ``--strict``
        turns that judgement off for people who would rather stop and look.
        """
        return replace(
            self,
            issues=tuple(issue if issue.is_error else replace(issue, level="error") for issue in self.issues),
        )
