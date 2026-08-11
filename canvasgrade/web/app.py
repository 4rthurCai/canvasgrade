"""FastAPI application backing the local GUI.

Routes are thin: they translate JSON into the same workflow calls the CLI makes, so
the two front ends cannot drift apart in behaviour.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from canvasgrade import __version__
from canvasgrade.canvas.client import CanvasSession
from canvasgrade.canvas.push import push_grades
from canvasgrade.config import Profile
from canvasgrade.errors import CanvasGradeError
from canvasgrade.grading.plan import GradeOptions
from canvasgrade.sheet.reader import list_sheets
from canvasgrade.web import schemas as api
from canvasgrade.web.state import UploadError, UploadStore
from canvasgrade.workflow import (
    ColumnOverride,
    RubricRequest,
    SheetRequest,
    load_sheet,
    prepare_push,
)

STATIC_DIR = Path(__file__).parent / "static"
#: Rows of the raw sheet shown in the upload preview.
PREVIEW_ROWS = 8


def _sheet_request(payload: api.PlanIn, path: Path) -> SheetRequest:
    return SheetRequest(
        path=path,
        sheet=payload.sheet,
        has_header=payload.has_header,
        include=tuple(payload.include),
        exclude=tuple(payload.exclude),
        overrides=tuple(
            ColumnOverride(name=o.name, role=o.role, points=o.points, target=o.target, description=o.description)
            for o in payload.overrides
        ),
    )


def _grade_options(payload: api.OptionsIn) -> GradeOptions:
    return GradeOptions(
        total=payload.total,
        apply_ratio=payload.apply_ratio,
        add_comment=payload.add_comment,
        missing_as_zero=payload.missing_as_zero,
        clamp=payload.clamp,
    )


def create_app(profile: Profile) -> FastAPI:
    """Build the application around one already-resolved Canvas profile."""
    store = UploadStore()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        store.close()

    app = FastAPI(title="canvasgrade", version=__version__, lifespan=lifespan)
    session = CanvasSession(profile)

    @app.exception_handler(CanvasGradeError)
    async def _canvas_error(_: Any, exc: CanvasGradeError) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/api/session", response_model=api.SessionInfo)
    def read_session() -> api.SessionInfo:
        return api.SessionInfo(
            user=session.whoami(),
            api_url=profile.api_url,
            profile=profile.name,
            course_id=profile.course_id,
            assignment_id=profile.assignment_id,
        )

    @app.get("/api/courses", response_model=list[api.CourseOut])
    def read_courses() -> list[api.CourseOut]:
        return [api.CourseOut(id=c.id, name=c.name, code=c.code) for c in session.courses()]

    @app.get("/api/courses/{course_id}/assignments", response_model=list[api.AssignmentOut])
    def read_assignments(course_id: int) -> list[api.AssignmentOut]:
        course = session.course(course_id)
        return [
            api.AssignmentOut(
                id=a.id,
                name=a.name,
                points_possible=a.points_possible,
                published=a.published,
                rubric_id=a.rubric_id,
            )
            for a in session.assignments(course)
        ]

    @app.get("/api/courses/{course_id}/rubrics", response_model=list[api.RubricOut])
    def read_rubrics(course_id: int) -> list[api.RubricOut]:
        course = session.course(course_id)
        return [
            api.RubricOut(id=r.id, title=r.title, criteria=r.criteria, points=r.points) for r in session.rubrics(course)
        ]

    @app.post("/api/uploads", response_model=api.UploadOut)
    async def create_upload(file: UploadFile, sheet: str = "0", has_header: bool = True) -> api.UploadOut:
        try:
            upload = store.add(file.filename or "sheet.csv", await file.read())
        except UploadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        sheets = list(list_sheets(upload.path))
        chosen: str | int = _coerce_sheet(sheet, sheets)
        prepared = load_sheet(SheetRequest(path=upload.path, sheet=chosen, has_header=has_header))
        frame = prepared.data.frame.head(PREVIEW_ROWS)
        return api.UploadOut(
            token=upload.token,
            filename=upload.filename,
            sheets=sheets,
            sheet=chosen,
            n_rows=prepared.data.n_rows,
            columns=api.columns_out(prepared.mapping),
            preview=[["" if value is None else str(value) for value in row] for row in frame.to_numpy()],
            students=len(prepared.rows),
            teams=sorted({row.team for row in prepared.rows if row.team}),
        )

    @app.post("/api/plan", response_model=api.PlanOut)
    def create_plan(payload: api.PlanIn) -> api.PlanOut:
        upload = store.get(payload.token)
        prepared = prepare_push(
            session,
            course_id=payload.course_id,
            assignment_id=payload.assignment_id,
            sheet_request=_sheet_request(payload, upload.path),
            rubric_request=RubricRequest(**payload.rubric.model_dump()),
            options=_grade_options(payload.options),
            dry_run=True,
        )
        return api.plan_out(
            prepared.plan,
            assignment=api.AssignmentOut(**prepared.assignment.__dict__),
            notes=list(prepared.notes),
            mapping=prepared.sheet.mapping,
        )

    @app.post("/api/push", response_model=api.PushOut)
    def create_push(payload: api.PushIn) -> api.PushOut:
        upload = store.get(payload.token)

        def prepare(*, dry_run: bool):
            return prepare_push(
                session,
                course_id=payload.course_id,
                assignment_id=payload.assignment_id,
                sheet_request=_sheet_request(payload, upload.path),
                rubric_request=RubricRequest(**payload.rubric.model_dump()),
                options=_grade_options(payload.options),
                dry_run=dry_run,
            )

        # Validate against a stand-in rubric first, so a refused push never leaves a
        # freshly created rubric behind on Canvas.
        prepared = prepare(dry_run=True)
        if not prepared.plan.is_pushable:
            messages = "; ".join(issue.message for issue in prepared.plan.errors[:3])
            raise HTTPException(status_code=400, detail=f"Refusing to push: {messages}")
        if prepared.is_preview_only:
            prepared = prepare(dry_run=False)

        course = session.course(payload.course_id)
        assignment = session.assignment(course, payload.assignment_id)
        result = push_grades(assignment, prepared.plan.entries, batch_size=payload.batch_size)

        return api.PushOut(
            ok=result.ok,
            submitted=result.submitted,
            batches=len(result.batches),
            failures=[f"{b.state}: {b.message}" for b in result.failed],
            speedgrader_url=session.speedgrader_url(payload.course_id, payload.assignment_id),
            rubric_id=prepared.rubric.rubric_id if prepared.rubric else None,
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _coerce_sheet(sheet: str, sheets: list[str]) -> str | int:
    """Accept either a worksheet name or an index from the browser."""
    if sheet in sheets:
        return sheet
    try:
        return int(sheet)
    except (TypeError, ValueError):
        return 0
