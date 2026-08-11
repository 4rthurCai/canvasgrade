"""Request and response shapes for the GUI's JSON API.

The access token never appears in any of these: it stays on the server side, so the
browser can drive Canvas without ever holding the credential.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from canvasgrade.models import ColumnRole, GradePlan, SheetMapping
from canvasgrade.sheet.detect import strip_points


class SessionInfo(BaseModel):
    user: str
    api_url: str
    profile: str
    course_id: int | None = None
    assignment_id: int | None = None


class CourseOut(BaseModel):
    id: int
    name: str
    code: str = ""


class AssignmentOut(BaseModel):
    id: int
    name: str
    points_possible: float | None = None
    published: bool = True
    rubric_id: int | None = None


class RubricOut(BaseModel):
    id: int
    title: str
    criteria: int = 0
    points: float | None = None


class ColumnOut(BaseModel):
    name: str
    index: int
    role: str
    points: float | None = None
    target: str | None = None
    #: The criterion name students will see, whether derived or overridden.
    description: str | None = None
    inferred: bool = True
    reason: str = ""


class UploadOut(BaseModel):
    token: str
    filename: str
    sheets: list[str] = Field(default_factory=list)
    sheet: str | int = 0
    n_rows: int
    columns: list[ColumnOut]
    preview: list[list[str]]
    students: int
    teams: list[str] = Field(default_factory=list)


class ColumnOverrideIn(BaseModel):
    name: str
    role: ColumnRole
    points: float | None = None
    target: str | None = None
    description: str | None = None


class OptionsIn(BaseModel):
    total: str = "auto"
    apply_ratio: bool = False
    add_comment: bool = False
    missing_as_zero: bool = True
    clamp: bool = True


class RubricIn(BaseModel):
    mode: str = "attached"
    rubric_id: int | None = None
    title: str | None = None
    use_for_grading: bool = False


class PlanIn(BaseModel):
    token: str
    course_id: int
    assignment_id: int
    sheet: str | int = 0
    has_header: bool = True
    overrides: list[ColumnOverrideIn] = Field(default_factory=list)
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    rubric: RubricIn = Field(default_factory=RubricIn)
    options: OptionsIn = Field(default_factory=OptionsIn)


class PushIn(PlanIn):
    batch_size: int = 200


class CriterionOut(BaseModel):
    description: str
    points: float
    criterion_id: str | None = None


class EntryOut(BaseModel):
    label: str
    user_id: int
    posted_grade: float
    scores: list[float] = Field(default_factory=list)
    comments: int = 0


class IssueOut(BaseModel):
    level: str
    message: str
    row_index: int | None = None


class SkippedOut(BaseModel):
    label: str
    row_index: int
    reason: str


class PlanOut(BaseModel):
    assignment: AssignmentOut
    rubric_title: str | None = None
    rubric_total: float | None = None
    criteria: list[CriterionOut] = Field(default_factory=list)
    entries: list[EntryOut] = Field(default_factory=list)
    issues: list[IssueOut] = Field(default_factory=list)
    skipped: list[SkippedOut] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    columns: list[ColumnOut] = Field(default_factory=list)
    pushable: bool = False


class PushOut(BaseModel):
    ok: bool
    submitted: int
    batches: int
    failures: list[str] = Field(default_factory=list)
    speedgrader_url: str = ""
    rubric_id: int | None = None


def columns_out(mapping: SheetMapping) -> list[ColumnOut]:
    return [
        ColumnOut(
            name=column.name,
            index=column.index,
            role=column.role.value,
            points=column.points,
            target=column.target,
            description=column.description or (strip_points(column.name) or column.name),
            inferred=column.inferred,
            reason=column.reason,
        )
        for column in mapping.columns
    ]


def plan_out(plan: GradePlan, *, assignment: AssignmentOut, notes: list[str], mapping: SheetMapping) -> PlanOut:
    rubric = plan.rubric
    return PlanOut(
        assignment=assignment,
        rubric_title=rubric.title if rubric else None,
        rubric_total=rubric.total_points if rubric else None,
        criteria=[
            CriterionOut(description=c.description, points=c.points, criterion_id=c.criterion_id)
            for c in (rubric.criteria if rubric else ())
        ],
        entries=[
            EntryOut(
                label=entry.label,
                user_id=entry.user_id,
                posted_grade=entry.posted_grade,
                scores=[points for _, points in entry.criterion_points],
                comments=len(entry.criterion_comments),
            )
            for entry in plan.entries
        ],
        issues=[IssueOut(level=i.level, message=i.message, row_index=i.row_index) for i in plan.issues],
        skipped=[
            SkippedOut(label=row.label, row_index=row.row_index + 1, reason=reason) for row, reason in plan.skipped
        ],
        notes=notes,
        columns=columns_out(mapping),
        pushable=plan.is_pushable,
    )
