"""Shared fixtures.

Every fixture here is synthetic. Real gradebooks must never be committed: they contain
student names and identifiers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from canvasgrade.grading.roster import Roster, RosterEntry
from canvasgrade.models import Criterion, RubricSpec
from canvasgrade.sheet import detect_mapping, extract_rows, read_sheet

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def gradebook_path() -> Path:
    return FIXTURES / "gradebook.csv"


@pytest.fixture
def positional_path() -> Path:
    return FIXTURES / "positional.csv"


@pytest.fixture
def sheet(gradebook_path: Path):
    return read_sheet(gradebook_path)


@pytest.fixture
def mapping(sheet):
    return detect_mapping(sheet.frame)


@pytest.fixture
def rows(sheet, mapping):
    return extract_rows(sheet.frame, mapping)


@pytest.fixture
def roster() -> Roster:
    return Roster(
        entries=(
            RosterEntry(101, "Ada Lovelace", "Lovelace, Ada", "s101", "ada"),
            RosterEntry(102, "Alan Turing", "Turing, Alan", "s102", "alan"),
            RosterEntry(103, "Grace Hopper", "Hopper, Grace", "s103", "grace"),
            RosterEntry(104, "Katherine Johnson", "Johnson, Katherine", "s104", "katherine"),
        )
    )


@pytest.fixture
def bound_rubric() -> RubricSpec:
    """A two-criterion rubric that already carries Canvas ids."""
    return RubricSpec(
        title="M1",
        rubric_id=7,
        criteria=(
            Criterion(column="M1 Design (10)", description="M1 Design", points=10, criterion_id="_1"),
            Criterion(column="M1 Tests (20)", description="M1 Tests", points=20, criterion_id="_2"),
        ),
    )


class FakeProgress:
    """Stands in for a Canvas async job that completes immediately."""

    def __init__(self, state: str = "completed") -> None:
        self.id = 42
        self.workflow_state = state
        self.completion = 100
        self.message = ""

    def query(self) -> FakeProgress:
        return self


class FakeAssignment:
    def __init__(self, *, rubric: list[dict[str, Any]] | None = None, rubric_id: int | None = None) -> None:
        self.id = 7081
        self.name = "Project 1"
        self.points_possible = 30.0
        self.published = True
        self.rubric = rubric
        self.rubric_settings = {"id": rubric_id} if rubric_id else None
        self.pushed: list[dict[str, Any]] = []

    def submissions_bulk_update(self, **kwargs: Any) -> FakeProgress:
        self.pushed.append(kwargs["grade_data"])
        return FakeProgress()


class FakeRubric:
    def __init__(self, rubric_id: int, data: list[dict[str, Any]]) -> None:
        self.id = rubric_id
        self.data = data


class FakeUser:
    """A Canvas user as ``course.get_users`` returns them."""

    def __init__(self, user_id: int, name: str, sis: str) -> None:
        self.id = user_id
        self.name = name
        self.sortable_name = f"{name.split()[-1]}, {name.split()[0]}"
        self.sis_user_id = sis
        self.login_id = sis


ROSTER_USERS = [
    FakeUser(101, "Ada Lovelace", "s101"),
    FakeUser(102, "Alan Turing", "s102"),
    FakeUser(103, "Grace Hopper", "s103"),
    FakeUser(104, "Katherine Johnson", "s104"),
    FakeUser(999, "Test Student", ""),
]


class FakeCourse:
    def __init__(self, assignment: FakeAssignment | None = None) -> None:
        self.id = 786
        self.name = "Intro to Everything"
        self.course_code = "VV186"
        self.created: list[dict[str, Any]] = []
        self._assignment = assignment or FakeAssignment()

    def create_rubric(self, **kwargs: Any) -> dict[str, Any]:
        self.created.append(kwargs)
        criteria = kwargs["rubric"]["criteria"]
        data = [
            {"id": f"_{index + 1}", "description": item["description"], "points": item["points"]}
            for index, item in sorted(criteria.items())
        ]
        return {"rubric": FakeRubric(99, data)}

    def get_users(self, **kwargs: Any) -> list[FakeUser]:
        return list(ROSTER_USERS)

    def get_assignment(self, assignment_id: int) -> FakeAssignment:
        return self._assignment

    def get_assignments(self, **kwargs: Any) -> list[FakeAssignment]:
        return [self._assignment]


class FakeSession:
    """Stands in for :class:`CanvasSession` without touching the network."""

    def __init__(self, profile: Any, course: FakeCourse | None = None) -> None:
        self.profile = profile
        self._course = course or FakeCourse()

    def whoami(self) -> str:
        return "Test Grader"

    def course(self, course_id: int) -> FakeCourse:
        return self._course

    def assignment(self, course: FakeCourse, assignment_id: int) -> FakeAssignment:
        return course.get_assignment(assignment_id)

    def speedgrader_url(self, course_id: int, assignment_id: int) -> str:
        return (
            f"https://canvas.example.invalid/courses/{course_id}/gradebook/speed_grader?assignment_id={assignment_id}"
        )


@pytest.fixture
def fake_assignment() -> FakeAssignment:
    return FakeAssignment()


@pytest.fixture
def fake_course(fake_assignment: FakeAssignment) -> FakeCourse:
    return FakeCourse(fake_assignment)


@pytest.fixture
def fake_session(fake_course: FakeCourse) -> FakeSession:
    from canvasgrade.config import Profile

    return FakeSession(Profile(api_key="token", course_id=786, assignment_id=7081), fake_course)
