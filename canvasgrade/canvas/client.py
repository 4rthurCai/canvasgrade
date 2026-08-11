"""A thin, well-mannered wrapper around :mod:`canvasapi`.

Its whole job is to turn Canvas's HTTP failures into sentences a TA can act on. A 401
should say "your token is wrong", not raise ``Unauthorized``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from canvasapi import Canvas
from canvasapi.exceptions import (
    CanvasException,
    Forbidden,
    InvalidAccessToken,
    ResourceDoesNotExist,
    Unauthorized,
)

from canvasgrade.config import Profile
from canvasgrade.errors import CanvasError

#: Everything the Canvas layer is allowed to fail with. Network errors surface as
#: requests exceptions, which canvasapi passes straight through.
API_ERRORS = (CanvasException, requests.exceptions.RequestException)


@dataclass(frozen=True)
class CourseInfo:
    """A course, flattened to the fields we display."""

    id: int
    name: str
    code: str = ""


@dataclass(frozen=True)
class AssignmentInfo:
    """An assignment, flattened to the fields we display."""

    id: int
    name: str
    points_possible: float | None = None
    published: bool = True
    rubric_id: int | None = None


def _explain(exc: Exception, what: str) -> CanvasError:
    """Translate a Canvas or network exception into something actionable."""
    if isinstance(exc, requests.exceptions.SSLError):
        return CanvasError(f"TLS handshake with Canvas failed while {what}. Check the API URL: {exc}")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return CanvasError(f"Could not reach Canvas while {what}. Check the API URL and your network connection.")
    if isinstance(exc, requests.exceptions.Timeout):
        return CanvasError(f"Canvas timed out while {what}. Try again, or use a smaller --batch-size.")
    if isinstance(exc, InvalidAccessToken | Unauthorized):
        return CanvasError(
            f"Canvas rejected your access token while {what}. Generate a new one under "
            "Account -> Settings -> New Access Token."
        )
    if isinstance(exc, Forbidden):
        return CanvasError(
            f"Your account is not allowed to {what}. You usually need a Teacher or TA role "
            "with grading permission on this course."
        )
    if isinstance(exc, ResourceDoesNotExist):
        return CanvasError(f"Canvas has no such resource while {what}. Check the id in the page URL.")
    return CanvasError(f"Canvas returned an error while {what}: {exc}")


class CanvasSession:
    """An authenticated connection, plus lookups for the objects we grade against."""

    def __init__(self, profile: Profile) -> None:
        self._profile = profile
        self._canvas = Canvas(profile.api_url, profile.require_key())

    @property
    def profile(self) -> Profile:
        return self._profile

    @property
    def raw(self) -> Canvas:
        """The underlying :class:`canvasapi.Canvas`, for anything not wrapped here."""
        return self._canvas

    def whoami(self) -> str:
        try:
            user = self._canvas.get_current_user()
        except API_ERRORS as exc:
            raise _explain(exc, "checking who you are") from exc
        return str(getattr(user, "name", "unknown"))

    def courses(self, *, only_active: bool = True) -> tuple[CourseInfo, ...]:
        try:
            kwargs: dict[str, Any] = {"per_page": 100}
            if only_active:
                kwargs["enrollment_state"] = "active"
            courses = list(self._canvas.get_courses(**kwargs))
        except API_ERRORS as exc:
            raise _explain(exc, "listing your courses") from exc
        return tuple(
            CourseInfo(
                id=int(course.id),
                name=str(getattr(course, "name", f"course {course.id}")),
                code=str(getattr(course, "course_code", "")),
            )
            for course in courses
            if getattr(course, "id", None) is not None
        )

    def course(self, course_id: int) -> Any:
        try:
            return self._canvas.get_course(course_id)
        except API_ERRORS as exc:
            raise _explain(exc, f"opening course {course_id}") from exc

    def assignments(self, course: Any) -> tuple[AssignmentInfo, ...]:
        try:
            assignments = list(course.get_assignments(per_page=100))
        except API_ERRORS as exc:
            raise _explain(exc, f"listing assignments in course {course.id}") from exc
        return tuple(_assignment_info(a) for a in assignments)

    def assignment(self, course: Any, assignment_id: int) -> Any:
        try:
            return course.get_assignment(assignment_id)
        except API_ERRORS as exc:
            raise _explain(exc, f"opening assignment {assignment_id}") from exc

    def speedgrader_url(self, course_id: int, assignment_id: int) -> str:
        base = self._profile.api_url.rstrip("/")
        return f"{base}/courses/{course_id}/gradebook/speed_grader?assignment_id={assignment_id}"


def _assignment_info(assignment: Any) -> AssignmentInfo:
    settings = getattr(assignment, "rubric_settings", None) or {}
    points = getattr(assignment, "points_possible", None)
    return AssignmentInfo(
        id=int(assignment.id),
        name=str(getattr(assignment, "name", f"assignment {assignment.id}")),
        points_possible=float(points) if points is not None else None,
        published=bool(getattr(assignment, "published", True)),
        rubric_id=int(settings["id"]) if isinstance(settings, dict) and settings.get("id") else None,
    )
