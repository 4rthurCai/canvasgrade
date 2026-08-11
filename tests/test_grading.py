"""Matching students, building rubrics, and turning rows into a plan."""

from __future__ import annotations

import pytest

from canvasgrade.errors import MappingError
from canvasgrade.grading import GradeOptions, Roster, RosterEntry, build_plan, build_rubric, validate_plan
from canvasgrade.grading.rubric import CanvasCriterion, bind_to_existing
from canvasgrade.models import StudentRow
from canvasgrade.sheet.select import filter_criteria

pytestmark = pytest.mark.unit


class TestRoster:
    def test_canvas_id_is_verified_against_the_roster(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, canvas_id=101))
        assert match.user_id == 101 and match.method == "canvas id"

    def test_an_id_that_is_not_enrolled_is_refused(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, canvas_id=999))
        assert not match.ok
        assert "not enrolled" in match.detail

    def test_an_empty_roster_trusts_the_sheet(self) -> None:
        match = Roster().resolve(StudentRow(row_index=0, canvas_id=999))
        assert match.user_id == 999 and "unverified" in match.method

    def test_sis_id_resolves_when_there_is_no_canvas_id(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, sis_id="s103"))
        assert match.user_id == 103 and match.method == "sis id"

    def test_login_id_also_resolves(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, sis_id="grace"))
        assert match.user_id == 103

    def test_exact_name_match(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, name="Ada Lovelace"))
        assert match.user_id == 101 and match.method == "name"

    def test_sortable_name_order_is_handled(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, name="Lovelace, Ada"))
        assert match.user_id == 101

    def test_extra_tokens_in_the_sheet_name_still_match(self, roster) -> None:
        # A sheet may carry a second script or a nickname the Canvas record lacks.
        match = roster.resolve(StudentRow(row_index=0, name="Ada Lovelace 阿达"))
        assert match.user_id == 101 and match.method == "name (partial)"

    def test_a_typo_is_matched_fuzzily(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, name="Ada Lovelacee"))
        assert match.user_id == 101 and match.method == "name (fuzzy)"

    def test_an_unknown_name_is_refused_rather_than_guessed(self, roster) -> None:
        match = roster.resolve(StudentRow(row_index=0, name="Someone Entirely Else"))
        assert not match.ok

    def test_two_students_with_the_same_name_are_ambiguous(self) -> None:
        roster = Roster(entries=(RosterEntry(1, "Sam Lee"), RosterEntry(2, "Sam Lee")))
        match = roster.resolve(StudentRow(row_index=0, name="Sam Lee"))
        assert not match.ok and match.method == "ambiguous"

    def test_a_row_with_nothing_identifying_is_refused(self, roster) -> None:
        assert not roster.resolve(StudentRow(row_index=0)).ok


class TestBuildRubric:
    def test_headers_become_criteria_in_sheet_order(self, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        assert [c.description for c in spec.criteria] == ["M1 Design", "M1 Tests"]
        assert spec.total_points == 30

    def test_a_sheet_with_no_criteria_is_a_clear_error(self, mapping) -> None:
        stripped = filter_criteria(mapping, include=["M1 Design*"])
        bare = stripped.override("M1 Design (10)", type(stripped.columns[0].role).IGNORE)
        with pytest.raises(MappingError, match="No criterion columns"):
            build_rubric(bare, "M1")

    def test_duplicate_criterion_names_are_refused(self) -> None:
        import pandas as pd

        from canvasgrade.sheet import detect_mapping

        frame = pd.DataFrame({"ID": [1], "Design (10)": [5], "design (10)": [5]})
        with pytest.raises(MappingError, match="same name"):
            build_rubric(detect_mapping(frame), "T")


class TestBindToExisting:
    def test_descriptions_are_matched_first(self, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        canvas = [CanvasCriterion("_a", "M1 Tests", 20), CanvasCriterion("_b", "M1 Design", 10)]
        bound, warnings = bind_to_existing(spec, canvas, rubric_id=7)
        assert [c.criterion_id for c in bound.criteria] == ["_b", "_a"]
        assert not warnings

    def test_a_points_mismatch_warns_but_still_binds(self, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        canvas = [CanvasCriterion("_a", "M1 Design", 10), CanvasCriterion("_b", "M1 Tests", 25)]
        bound, warnings = bind_to_existing(spec, canvas, rubric_id=7)
        assert bound.is_bound
        assert any("out of 25 on Canvas" in w for w in warnings)

    def test_unmatched_names_fall_back_to_order_with_a_warning(self, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        canvas = [CanvasCriterion("_a", "Part one", 10), CanvasCriterion("_b", "Part two", 20)]
        bound, warnings = bind_to_existing(spec, canvas, rubric_id=7)
        assert [c.criterion_id for c in bound.criteria] == ["_a", "_b"]
        assert any("column order" in w for w in warnings)

    def test_a_different_number_of_criteria_is_an_error(self, mapping) -> None:
        spec = build_rubric(filter_criteria(mapping, include=["M1 *"]), "M1")
        with pytest.raises(MappingError, match="Cannot line up"):
            bind_to_existing(spec, [CanvasCriterion("_a", "Only one", 10)], rubric_id=7)


class TestBuildPlan:
    def test_totals_come_from_the_sheet_by_default(self, rows, roster, bound_rubric) -> None:
        plan = build_plan(rows, rubric=bound_rubric, roster=roster)
        by_label = {entry.label: entry for entry in plan.entries}
        assert by_label["Ada Lovelace"].posted_grade == 25

    def test_sum_mode_adds_the_criteria_instead(self, rows, roster, bound_rubric) -> None:
        plan = build_plan(rows, rubric=bound_rubric, roster=roster, options=GradeOptions(total="sum"))
        by_label = {entry.label: entry for entry in plan.entries}
        assert by_label["Ada Lovelace"].posted_grade == 25  # 8 + 17

    def test_scores_above_the_max_are_clamped_with_a_warning(self, rows, roster, bound_rubric) -> None:
        plan = build_plan(rows, rubric=bound_rubric, roster=roster, options=GradeOptions(total="sum"))
        alan = next(e for e in plan.entries if e.label == "Alan Turing")
        assert dict(alan.criterion_points)["_1"] == 10  # 12 clamped down to the max
        assert any("clamped" in issue.message for issue in plan.warnings)

    def test_clamping_off_turns_the_overflow_into_an_error(self, rows, roster, bound_rubric) -> None:
        options = GradeOptions(total="sum", clamp=False)
        plan = build_plan(rows, rubric=bound_rubric, roster=roster, options=options)
        assert any("exceeds the max" in issue.message for issue in plan.errors)

    def test_a_student_with_no_scores_is_skipped_with_a_reason(self, rows, roster, bound_rubric) -> None:
        plan = build_plan(rows, rubric=bound_rubric, roster=roster)
        skipped = {row.label: reason for row, reason in plan.skipped}
        assert skipped["Katherine Johnson"] == "no scores in the sheet"

    def test_comments_are_attached_to_the_right_criterion(self, rows, roster, bound_rubric) -> None:
        plan = build_plan(rows, rubric=bound_rubric, roster=roster)
        ada = next(e for e in plan.entries if e.label == "Ada Lovelace")
        assert dict(ada.criterion_comments)["_1"] == "Clean structure"

    def test_the_ratio_is_ignored_unless_asked_for(self, rows, roster, bound_rubric) -> None:
        plain = build_plan(rows, rubric=bound_rubric, roster=roster)
        scaled = build_plan(rows, rubric=bound_rubric, roster=roster, options=GradeOptions(apply_ratio=True))
        alan_plain = next(e for e in plain.entries if e.label == "Alan Turing")
        alan_scaled = next(e for e in scaled.entries if e.label == "Alan Turing")
        assert alan_scaled.posted_grade == pytest.approx(alan_plain.posted_grade * 1.1)

    def test_two_rows_for_one_student_is_an_error(self, roster, bound_rubric) -> None:
        duplicated = [
            StudentRow(row_index=0, canvas_id=101, scores=(("M1 Design (10)", 5),)),
            StudentRow(row_index=1, canvas_id=101, scores=(("M1 Design (10)", 6),)),
        ]
        plan = build_plan(duplicated, rubric=bound_rubric, roster=roster)
        assert any("same Canvas user" in issue.message for issue in plan.errors)

    def test_the_rubric_assessment_payload_shape(self, rows, roster, bound_rubric) -> None:
        plan = build_plan(rows, rubric=bound_rubric, roster=roster)
        ada = next(e for e in plan.entries if e.label == "Ada Lovelace")
        assert ada.rubric_assessment() == {
            "_1": {"points": 8.0, "comments": "Clean structure"},
            "_2": {"points": 17.0},
        }

    def test_an_unbound_rubric_is_a_programming_error(self, rows, roster) -> None:
        from canvasgrade.models import Criterion, RubricSpec

        unbound = RubricSpec(title="x", criteria=(Criterion("a", "a", 1),))
        with pytest.raises(ValueError, match="criterion ids"):
            build_plan(rows, rubric=unbound, roster=roster)


class TestValidate:
    def test_a_rubric_that_does_not_match_the_assignment_warns(self, rows, roster, bound_rubric) -> None:
        plan = validate_plan(build_plan(rows, rubric=bound_rubric, roster=roster), points_possible=70)
        assert any("out of 70" in issue.message for issue in plan.warnings)

    def test_students_scoring_above_the_maximum_are_flagged(self, rows, roster, bound_rubric) -> None:
        plan = validate_plan(build_plan(rows, rubric=bound_rubric, roster=roster), points_possible=20)
        assert any("score above 20" in issue.message for issue in plan.warnings)

    def test_ungraded_enrolled_students_are_counted(self, rows, roster, bound_rubric) -> None:
        plan = validate_plan(build_plan(rows, rubric=bound_rubric, roster=roster), roster_size=10)
        assert any("not in this sheet" in issue.message for issue in plan.warnings)

    def test_a_negative_total_is_an_error(self, roster, bound_rubric) -> None:
        negative = [StudentRow(row_index=0, canvas_id=101, total_override=-5, scores=(("M1 Design (10)", 0),))]
        plan = validate_plan(build_plan(negative, rubric=bound_rubric, roster=roster))
        assert any("negative total" in issue.message for issue in plan.errors)
