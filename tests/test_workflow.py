"""End-to-end orchestration: sheet in, reviewable plan out."""

from __future__ import annotations

import pytest

from canvasgrade.canvas.pull import fetch_roster
from canvasgrade.errors import CanvasGradeError, MappingError
from canvasgrade.grading.plan import GradeOptions
from canvasgrade.models import ColumnRole
from canvasgrade.workflow import (
    ColumnOverride,
    RubricRequest,
    SheetRequest,
    load_sheet,
    prepare_push,
)

pytestmark = pytest.mark.integration


def sheet_request(path, **kwargs) -> SheetRequest:
    return SheetRequest(path=path, **kwargs)


class TestLoadSheet:
    def test_overrides_beat_the_detector(self, gradebook_path) -> None:
        prepared = load_sheet(
            sheet_request(
                gradebook_path,
                overrides=(ColumnOverride(name="Grader", role=ColumnRole.CRITERION, points=5),),
            )
        )
        column = prepared.mapping.get("Grader")
        assert column.role is ColumnRole.CRITERION
        assert column.inferred is False

    def test_overrides_apply_before_filtering(self, gradebook_path) -> None:
        prepared = load_sheet(
            sheet_request(
                gradebook_path,
                include=["M1 *"],
                overrides=(ColumnOverride(name="M1 Total (30)", role=ColumnRole.CRITERION, points=30),),
            )
        )
        assert "M1 Total (30)" in {c.name for c in prepared.mapping.criteria_columns}

    def test_total_column_beats_the_detected_one(self, gradebook_path) -> None:
        # The detector keeps the last total ("Total (30)"); a milestone push wants an
        # earlier one instead.
        prepared = load_sheet(sheet_request(gradebook_path, total_column="M1 Total (30)"))
        assert prepared.mapping.first(ColumnRole.TOTAL).name == "M1 Total (30)"
        assert prepared.mapping.get("Total (30)").role is ColumnRole.IGNORE

    def test_total_column_accepts_the_name_without_its_max(self, gradebook_path) -> None:
        prepared = load_sheet(sheet_request(gradebook_path, total_column="m1 total"))
        assert prepared.mapping.first(ColumnRole.TOTAL).name == "M1 Total (30)"

    def test_the_forced_total_keeps_its_max(self, gradebook_path) -> None:
        # It was demoted during detection, which dropped the max; it must come back.
        prepared = load_sheet(sheet_request(gradebook_path, total_column="M1 Total (30)"))
        assert prepared.mapping.first(ColumnRole.TOTAL).points == 30

    def test_the_forced_total_actually_changes_the_grades(self, gradebook_path) -> None:
        default = load_sheet(sheet_request(gradebook_path))
        forced = load_sheet(sheet_request(gradebook_path, total_column="M2 Total (30)"))
        ada_default = next(r for r in default.rows if r.name == "Ada Lovelace")
        ada_forced = next(r for r in forced.rows if r.name == "Ada Lovelace")
        assert ada_default.total_override == 25  # from "Total (30)"
        assert ada_forced.total_override == 27  # from "M2 Total (30)"

    def test_an_unknown_total_column_lists_the_candidates(self, gradebook_path) -> None:
        with pytest.raises(MappingError, match="Columns currently read as the total"):
            load_sheet(sheet_request(gradebook_path, total_column="Nope"))

    def test_a_criterion_can_be_renamed(self, gradebook_path) -> None:
        # The header is written for the marker; the criterion name is what students see.
        from canvasgrade.grading.rubric import build_rubric

        prepared = load_sheet(
            sheet_request(
                gradebook_path,
                include=["M1 *"],
                overrides=(
                    ColumnOverride(
                        name="M1 Design (10)",
                        role=ColumnRole.CRITERION,
                        points=10,
                        description="Architecture & design decisions",
                    ),
                ),
            )
        )
        spec = build_rubric(prepared.mapping, "M1")
        assert [c.description for c in spec.criteria] == [
            "Architecture & design decisions",
            "M1 Tests",
        ]
        assert spec.total_points == 30

    def test_renaming_does_not_disturb_the_score_lookup(self, gradebook_path, roster) -> None:
        # Scores join on the column name, not the display name.
        from canvasgrade.grading.plan import build_plan
        from canvasgrade.grading.rubric import build_rubric

        prepared = load_sheet(
            sheet_request(
                gradebook_path,
                include=["M1 *"],
                overrides=(
                    ColumnOverride(name="M1 Design (10)", role=ColumnRole.CRITERION, points=10, description="Renamed"),
                ),
            )
        )
        spec = build_rubric(prepared.mapping, "M1")
        bound = spec.with_ids({c.description: f"_{i}" for i, c in enumerate(spec.criteria, 1)}, rubric_id=1)
        plan = build_plan(prepared.rows, rubric=bound, roster=roster)
        ada = next(e for e in plan.entries if e.label == "Ada Lovelace")
        assert dict(ada.criterion_points)["_1"] == 8.0

    def test_a_hand_set_role_displaces_the_detected_one(self, gradebook_path) -> None:
        # Setting a second column to canvas_id used to leave two, and lookups then
        # picked by column order - silently ignoring the choice just made.
        prepared = load_sheet(
            sheet_request(
                gradebook_path,
                overrides=(ColumnOverride(name="SIS Login ID", role=ColumnRole.CANVAS_ID),),
            )
        )
        holders = [c.name for c in prepared.mapping.by_role(ColumnRole.CANVAS_ID)]
        assert holders == ["SIS Login ID"]
        assert prepared.mapping.get("ID").role is ColumnRole.IGNORE

    def test_detection_alone_still_settles_duplicates(self, gradebook_path) -> None:
        prepared = load_sheet(sheet_request(gradebook_path))
        for role in (ColumnRole.CANVAS_ID, ColumnRole.TOTAL, ColumnRole.RATIO):
            assert len(prepared.mapping.by_role(role)) <= 1

    def test_a_sheet_with_no_students_is_rejected(self, tmp_path) -> None:
        path = tmp_path / "headers-only.csv"
        path.write_text("Student,ID,Design (10)\n,,\n")
        with pytest.raises(MappingError, match="No student rows"):
            load_sheet(sheet_request(path))


class TestPreparePush:
    def _prepare(self, session, path, **kwargs):
        return prepare_push(
            session,
            course_id=786,
            assignment_id=7081,
            sheet_request=sheet_request(path, include=["M1 *"]),
            **kwargs,
        )

    def test_creating_a_rubric_binds_real_ids(self, fake_session, fake_course, gradebook_path) -> None:
        prepared = self._prepare(fake_session, gradebook_path, rubric_request=RubricRequest(mode="create", title="M1"))
        assert prepared.rubric_created
        assert prepared.rubric.is_bound
        assert not prepared.is_preview_only
        assert fake_course.created

    def test_a_dry_run_never_creates_anything(self, fake_session, fake_course, gradebook_path) -> None:
        prepared = self._prepare(
            fake_session, gradebook_path, rubric_request=RubricRequest(mode="create"), dry_run=True
        )
        assert not fake_course.created
        assert prepared.is_preview_only
        # The plan is still complete enough to review.
        assert len(prepared.plan.entries) == 3

    def test_no_rubric_mode_pushes_totals_only(self, fake_session, gradebook_path) -> None:
        prepared = self._prepare(fake_session, gradebook_path, rubric_request=RubricRequest(mode="none"))
        assert prepared.rubric is None
        assert all(entry.criterion_points == () for entry in prepared.plan.entries)

    def test_a_missing_rubric_says_what_to_do_about_it(self, fake_session, gradebook_path) -> None:
        with pytest.raises(CanvasGradeError, match="--create-rubric"):
            self._prepare(fake_session, gradebook_path, rubric_request=RubricRequest(mode="attached"))

    def test_the_test_student_is_kept_out_of_the_roster(self, fake_course) -> None:
        roster = fetch_roster(fake_course)
        assert 999 not in {entry.user_id for entry in roster.entries}
        assert len(roster.entries) == 4

    def test_students_missing_from_the_sheet_are_reported(self, fake_session, gradebook_path) -> None:
        prepared = self._prepare(fake_session, gradebook_path, rubric_request=RubricRequest(mode="create"))
        # Four enrolled, three graded: Katherine has no scores.
        assert len(prepared.plan.entries) == 3
        assert any("not in this sheet" in issue.message for issue in prepared.plan.warnings)

    def test_the_rubric_total_is_checked_against_the_assignment(self, fake_session, gradebook_path) -> None:
        prepared = self._prepare(fake_session, gradebook_path, rubric_request=RubricRequest(mode="create"))
        # The fixture rubric is 30 points and the fake assignment is out of 30.
        assert not any("adds up to" in issue.message for issue in prepared.plan.warnings)

    def test_an_unfiltered_sheet_warns_that_it_covers_too_much(self, fake_session, gradebook_path) -> None:
        prepared = prepare_push(
            fake_session,
            course_id=786,
            assignment_id=7081,
            sheet_request=sheet_request(gradebook_path),
            rubric_request=RubricRequest(mode="create"),
            dry_run=True,
        )
        assert any("--include" in issue.message for issue in prepared.plan.warnings)

    def test_options_flow_through_to_the_plan(self, fake_session, gradebook_path) -> None:
        prepared = self._prepare(
            fake_session,
            gradebook_path,
            rubric_request=RubricRequest(mode="create"),
            options=GradeOptions(total="sum", add_comment=True),
        )
        assert all(entry.text_comment for entry in prepared.plan.entries)


class TestIdentityDiagnosis:
    """Canvas ids and student numbers are both just integers; only the roster knows."""

    def _sheet(self, tmp_path, canvas_ids, other_ids):
        path = tmp_path / "grades.csv"
        rows = "\n".join(
            f"Student {i},{c},{o},8,17" for i, (c, o) in enumerate(zip(canvas_ids, other_ids, strict=True), 1)
        )
        path.write_text(f"Name,CanvasID,ID,Design (10),Tests (20)\n{rows}\n")
        return path

    def test_it_names_the_column_whose_values_are_enrolled(self, tmp_path, fake_course) -> None:
        from canvasgrade.canvas.pull import fetch_roster
        from canvasgrade.grading.plan import build_plan
        from canvasgrade.grading.rubric import build_rubric
        from canvasgrade.workflow import diagnose_identity

        roster = fetch_roster(fake_course)
        enrolled = [e.user_id for e in roster.entries][:3]
        path = self._sheet(tmp_path, enrolled, [525370990084, 525370990085, 525370990086])

        # Point it at the student number on purpose.
        prepared = load_sheet(sheet_request(path, id_column="ID"))
        spec = build_rubric(prepared.mapping, "t")
        bound = spec.with_ids({c.description: f"_{i}" for i, c in enumerate(spec.criteria, 1)}, rubric_id=1)
        plan = build_plan(prepared.rows, rubric=bound, roster=roster)

        assert len(plan.entries) == 0
        message = diagnose_identity(prepared, roster, plan)
        assert "CanvasID" in message
        # The GUI shows this too, so it must not name a command-line flag alone.
        assert "--id-column" in message and "GUI" in message

    def test_it_stays_quiet_when_everything_matched(self, tmp_path, fake_course) -> None:
        from canvasgrade.canvas.pull import fetch_roster
        from canvasgrade.grading.plan import build_plan
        from canvasgrade.grading.rubric import build_rubric
        from canvasgrade.workflow import diagnose_identity

        roster = fetch_roster(fake_course)
        enrolled = [e.user_id for e in roster.entries][:3]
        path = self._sheet(tmp_path, enrolled, [1, 2, 3])

        prepared = load_sheet(sheet_request(path))
        spec = build_rubric(prepared.mapping, "t")
        bound = spec.with_ids({c.description: f"_{i}" for i, c in enumerate(spec.criteria, 1)}, rubric_id=1)
        plan = build_plan(prepared.rows, rubric=bound, roster=roster)

        assert len(plan.entries) == 3
        assert diagnose_identity(prepared, roster, plan) is None

    def test_id_column_can_be_forced_either_way(self, tmp_path, fake_course) -> None:
        from canvasgrade.models import ColumnRole

        path = self._sheet(tmp_path, [1, 2, 3], [4, 5, 6])
        for wanted in ("CanvasID", "ID"):
            prepared = load_sheet(sheet_request(path, id_column=wanted))
            assert prepared.mapping.first(ColumnRole.CANVAS_ID).name == wanted

    def test_an_unknown_id_column_is_reported(self, tmp_path, fake_course) -> None:
        path = self._sheet(tmp_path, [1], [2])
        with pytest.raises(MappingError, match="No column named"):
            load_sheet(sheet_request(path, id_column="Nope"))
