"""The Canvas layer, exercised against fakes rather than a live instance."""

from __future__ import annotations

import pytest

from canvasgrade.canvas.pull import build_template
from canvasgrade.canvas.push import push_grades
from canvasgrade.canvas.rubrics import create_rubric, find_attached_rubric, load_rubric
from canvasgrade.errors import CanvasError
from canvasgrade.grading.rubric import build_rubric
from canvasgrade.models import GradeEntry
from canvasgrade.sheet.select import filter_criteria
from tests.conftest import FakeAssignment, FakeRubric

pytestmark = pytest.mark.integration


class TestCreateRubric:
    def test_the_payload_canvas_expects(self, fake_course, fake_assignment, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1 rubric")
        create_rubric(fake_course, fake_assignment, spec)

        sent = fake_course.created[0]
        assert sent["rubric"]["title"] == "M1 rubric"
        # Free-form comments must be on, or per-criterion feedback is rejected.
        assert sent["rubric"]["free_form_criterion_comments"] is True
        assert sent["rubric"]["criteria"][0]["description"] == "M1 Design"
        assert sent["rubric"]["criteria"][0]["points"] == 10
        # Every criterion needs ratings or Canvas will not render it.
        assert sent["rubric"]["criteria"][0]["ratings"][0]["points"] == 10
        assert sent["rubric_association"]["association_id"] == fake_assignment.id
        assert sent["rubric_association"]["association_type"] == "Assignment"

    def test_use_for_grading_is_off_by_default(self, fake_course, fake_assignment, mapping) -> None:
        # On, Canvas recomputes the grade from the rubric and clobbers the sheet total.
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        create_rubric(fake_course, fake_assignment, spec)
        assert fake_course.created[0]["rubric_association"]["use_for_grading"] is False

    def test_criterion_ids_come_back_bound(self, fake_course, fake_assignment, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        created = create_rubric(fake_course, fake_assignment, spec)
        assert created.rubric_id == 99
        assert created.is_bound
        assert [c.criterion_id for c in created.criteria] == ["_1", "_2"]

    def test_an_empty_rubric_is_refused(self, fake_course, fake_assignment) -> None:
        from canvasgrade.models import RubricSpec

        with pytest.raises(CanvasError, match="no criteria"):
            create_rubric(fake_course, fake_assignment, RubricSpec(title="empty", criteria=()))

    def test_a_truncated_response_is_caught(self, fake_assignment, mapping) -> None:
        class ShortCourse:
            id = 1

            def create_rubric(self, **kwargs: object) -> dict[str, object]:
                return {"rubric": FakeRubric(5, [{"id": "_1", "description": "only one", "points": 10}])}

        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        with pytest.raises(CanvasError, match="came back with 1 criteria"):
            create_rubric(ShortCourse(), fake_assignment, spec)


class TestFindAttached:
    def test_an_assignment_carries_its_rubric_inline(self) -> None:
        assignment = FakeAssignment(rubric=[{"id": "_9", "description": "Design", "points": 10.0}], rubric_id=182)
        rubric_id, criteria = find_attached_rubric(assignment)
        assert rubric_id == 182
        assert criteria[0].criterion_id == "_9"

    def test_no_rubric_reports_nothing_rather_than_failing(self, fake_assignment) -> None:
        assert find_attached_rubric(fake_assignment) == (None, ())


class TestLoadRubric:
    def test_reads_the_criteria_array(self) -> None:
        class Course:
            def get_rubric(self, rubric_id: int, **kwargs: object) -> FakeRubric:
                return FakeRubric(rubric_id, [{"id": "_1", "description": "A", "points": 5.0}])

        assert load_rubric(Course(), 7)[0].description == "A"

    def test_a_rubric_with_no_data_points_at_the_easier_route(self) -> None:
        class EmptyCourse:
            def get_rubric(self, rubric_id: int, **kwargs: object) -> FakeRubric:
                return FakeRubric(rubric_id, [])

        with pytest.raises(CanvasError, match="--create-rubric"):
            load_rubric(EmptyCourse(), 7)


class TestPush:
    def _entries(self, count: int) -> list[GradeEntry]:
        return [
            GradeEntry(
                user_id=100 + i,
                posted_grade=float(i),
                criterion_points=(("_1", float(i)),),
                label=f"student {i}",
            )
            for i in range(count)
        ]

    def test_one_request_carries_every_student(self, fake_assignment) -> None:
        result = push_grades(fake_assignment, self._entries(50))
        assert result.ok and result.submitted == 50
        assert len(fake_assignment.pushed) == 1

    def test_large_classes_are_split_into_batches(self, fake_assignment) -> None:
        result = push_grades(fake_assignment, self._entries(45), batch_size=20)
        assert [b.size for b in result.batches] == [20, 20, 5]
        assert len(fake_assignment.pushed) == 3

    def test_the_grade_data_payload_shape(self, fake_assignment) -> None:
        entry = GradeEntry(
            user_id=101,
            posted_grade=25.0,
            criterion_points=(("_1", 8.0),),
            criterion_comments=(("_1", "nice"),),
            text_comment="see rubric",
        )
        push_grades(fake_assignment, [entry])
        assert fake_assignment.pushed[0] == {
            101: {
                "posted_grade": 25.0,
                "rubric_assessment": {"_1": {"points": 8.0, "comments": "nice"}},
                "text_comment": "see rubric",
            }
        }

    def test_pushing_nothing_is_refused(self, fake_assignment) -> None:
        with pytest.raises(CanvasError, match="nothing to push"):
            push_grades(fake_assignment, [])

    def test_a_failed_job_is_reported_not_swallowed(self) -> None:
        from tests.conftest import FakeProgress

        class FailingAssignment(FakeAssignment):
            def submissions_bulk_update(self, **kwargs: object) -> FakeProgress:
                return FakeProgress("failed")

        result = push_grades(FailingAssignment(), self._entries(2))
        assert not result.ok and result.submitted == 0


class TestTemplate:
    def test_headers_round_trip_through_the_detector(self, roster) -> None:
        from canvasgrade.grading.rubric import CanvasCriterion
        from canvasgrade.sheet import detect_mapping

        criteria = (CanvasCriterion("_1", "Design", 10.0), CanvasCriterion("_2", "Tests", 20.0))
        frame = build_template(roster, criteria)

        assert list(frame.columns) == ["Student", "ID", "SIS Login ID", "Design (10)", "Tests (20)", "Total (30)"]
        assert len(frame) == len(roster.entries)

        # The point of the template: what we write, we can read straight back.
        mapping = detect_mapping(frame)
        assert {c.name for c in mapping.criteria_columns} == {"Design (10)", "Tests (20)"}

    def test_existing_scores_are_pre_filled(self, roster) -> None:
        from canvasgrade.grading.rubric import CanvasCriterion

        criteria = (CanvasCriterion("_1", "Design", 10.0),)
        frame = build_template(roster, criteria, existing={101: {"_1": 7.5}})
        assert frame.loc[frame["ID"] == 101, "Design (10)"].iloc[0] == 7.5
