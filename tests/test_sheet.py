"""Reading spreadsheets and working out what their columns mean."""

from __future__ import annotations

import pytest

from canvasgrade.errors import MappingError, SheetError
from canvasgrade.models import ColumnRole
from canvasgrade.sheet import detect_mapping, parse_points, read_sheet, strip_points
from canvasgrade.sheet.rows import to_float, to_int
from canvasgrade.sheet.select import filter_criteria

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Code Quality (35)", 35.0),
        ("Docs (7.5)", 7.5),
        ("设计 （10分）", 10.0),
        ("Thing (12 pts)", 12.0),
        # Square brackets, ASCII and full-width.
        ("Design [10]", 10.0),
        ("Thing [7.5 pts]", 7.5),
        ("设计 【10】", 10.0),
        # A prime marks a variant of a question; it is not part of the number.
        ("题目一 [10']", 10.0),
        ("Q3 [8’]", 8.0),  # Excel turns a typed ' into a curly quote
        ("Q4 [8′]", 8.0),  # and some sheets use a real prime
        ("[10]", 10.0),
        ("[10']", 10.0),
        # A header wrapped end to end, score inside, unit required.
        ("【设计 10分】", 10.0),
        ("(Design 10 pts)", 10.0),
        ("No max here", None),
        ("Ratio", None),
        ("Weird (10) trailing", None),
        ("Weird (10] mixed", None),  # brackets must pair
        ("Milestone 2", None),  # a bare trailing number is not a score
        ("【项目 2】", None),  # nor is one inside brackets without a unit
        ("【备注】", None),
    ],
)
def test_parse_points(header: str, expected: float | None) -> None:
    assert parse_points(header) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("M1 Design (10)", "M1 Design"),
        ("Design [10]", "Design"),
        ("题目一 [10']", "题目一"),
        ("【设计 10分】", "设计"),
        ("Plain name", "Plain name"),
        # With nothing but the marker there is no name to keep, so keep the marker -
        # and "[10]" and "[10']" stay distinct, which is what lets both be criteria.
        ("[10]", "[10]"),
        ("[10']", "[10']"),
    ],
)
def test_strip_points(header: str, expected: str) -> None:
    assert strip_points(header) == expected


class TestDetection:
    def test_identifies_the_three_identity_columns(self, mapping) -> None:
        assert mapping.first(ColumnRole.NAME).name == "Student"
        assert mapping.first(ColumnRole.CANVAS_ID).name == "ID"
        assert mapping.first(ColumnRole.SIS_ID).name == "SIS Login ID"

    def test_sis_beats_canvas_id_for_sis_login_id(self, mapping) -> None:
        # "SIS Login ID" contains "id"; it must not be read as the Canvas user id.
        assert mapping.get("SIS Login ID").role is ColumnRole.SIS_ID

    def test_criteria_need_an_explicit_max(self, mapping) -> None:
        criteria = {c.name for c in mapping.criteria_columns}
        assert criteria == {
            "M1 Design (10)",
            "M1 Tests (20)",
            "M2 Design (10)",
            "M2 Tests (20)",
        }

    def test_grader_initials_column_is_ignored(self, mapping) -> None:
        assert mapping.get("Grader").role is ColumnRole.IGNORE

    def test_last_total_wins_and_earlier_ones_are_dropped(self, mapping) -> None:
        assert mapping.first(ColumnRole.TOTAL).name == "Total (30)"
        assert mapping.get("M1 Total (30)").role is ColumnRole.IGNORE
        assert mapping.get("M2 Total (30)").role is ColumnRole.IGNORE

    def test_last_ratio_wins(self, mapping) -> None:
        assert mapping.first(ColumnRole.RATIO).name == "Ratio"
        assert mapping.get("M1 Ratio").role is ColumnRole.IGNORE

    def test_comment_column_points_at_its_criterion(self, mapping) -> None:
        column = mapping.get("M1 Design comment")
        assert column.role is ColumnRole.COMMENT
        assert column.target == "M1 Design (10)"

    def test_every_column_explains_itself(self, mapping) -> None:
        assert all(column.reason for column in mapping.columns)

    def test_canvas_id_is_recognised_without_a_separator(self) -> None:
        import pandas as pd

        for header in ("CanvasID", "Canvas_ID", "canvas id", "CanvasUserID"):
            frame = pd.DataFrame({"Name": ["a"], header: [550531], "Design (10)": [8]})
            mapping = detect_mapping(frame)
            assert mapping.first(ColumnRole.CANVAS_ID).name == header, header

    def test_an_explicit_canvas_id_beats_a_bare_id(self) -> None:
        # A sheet with both means the student number by "ID". Grading against that
        # addresses users who do not exist.
        import pandas as pd

        frame = pd.DataFrame(
            {
                "Name": ["a"],
                "CanvasID": [550531],
                "ID": [525370990084],
                "Design (10)": [8],
            }
        )
        mapping = detect_mapping(frame)
        assert mapping.first(ColumnRole.CANVAS_ID).name == "CanvasID"
        assert mapping.get("ID").role is ColumnRole.IGNORE
        assert "CanvasID" in mapping.get("ID").reason

    def test_a_bare_id_is_still_used_when_it_is_all_there_is(self) -> None:
        import pandas as pd

        frame = pd.DataFrame({"Name": ["a"], "ID": [550531], "Design (10)": [8]})
        assert detect_mapping(frame).first(ColumnRole.CANVAS_ID).name == "ID"

    def test_a_student_id_is_not_mistaken_for_the_canvas_id(self) -> None:
        import pandas as pd

        frame = pd.DataFrame({"Name": ["a"], "Student_ID": [525370990084], "Design (10)": [8]})
        assert detect_mapping(frame).first(ColumnRole.CANVAS_ID) is None

    def test_a_declared_max_beats_an_identity_keyword(self) -> None:
        # "Bug reports (team) [5]" is a criterion that happens to say "team". Reading
        # it as the team column silently dropped 5 points from the rubric.
        import pandas as pd

        frame = pd.DataFrame(
            {
                "Name": ["a"],
                "Team": ["t1"],
                "Bug reports (team) [5]": [4],
                "Group work [10]": [8],
            }
        )
        mapping = detect_mapping(frame)
        assert mapping.get("Bug reports (team) [5]").role is ColumnRole.CRITERION
        assert mapping.get("Group work [10]").role is ColumnRole.CRITERION
        # The genuine team column, which declares no max, is still found.
        assert mapping.first(ColumnRole.TEAM).name == "Team"

    def test_a_declared_max_does_not_override_a_total(self) -> None:
        import pandas as pd

        frame = pd.DataFrame({"ID": [1], "Design (10)": [8], "Total (10)": [8]})
        mapping = detect_mapping(frame)
        assert mapping.first(ColumnRole.TOTAL).name == "Total (10)"

    def test_bracketed_question_numbers_become_criteria(self) -> None:
        import pandas as pd

        # Question 10 and its variant, each out of 10, named only by the marker.
        frame = pd.DataFrame({"ID": [1, 2], "[10]": [8, 9], "[10']": [7, 10]})
        mapping = detect_mapping(frame)
        criteria = {c.name: c.points for c in mapping.criteria_columns}
        assert criteria == {"[10]": 10.0, "[10']": 10.0}

    def test_a_comment_column_may_repeat_the_max_marker(self) -> None:
        import pandas as pd

        frame = pd.DataFrame({"ID": [1], "Design (10)": [8], "Design (10) comment": ["ok"]})
        mapping = detect_mapping(frame)
        assert mapping.get("Design (10) comment").target == "Design (10)"

    def test_a_comment_column_may_also_omit_it(self) -> None:
        import pandas as pd

        frame = pd.DataFrame({"ID": [1], "Design (10)": [8], "Design comment": ["ok"]})
        mapping = detect_mapping(frame)
        assert mapping.get("Design comment").target == "Design (10)"

    def test_positional_layout_without_a_header(self, positional_path) -> None:
        data = read_sheet(positional_path, has_header=False)
        mapping = detect_mapping(data.frame, has_header=False)
        assert mapping.columns[0].role is ColumnRole.CANVAS_ID
        assert all(c.role is ColumnRole.CRITERION for c in mapping.columns[1:])

    def test_bare_numeric_columns_become_criteria_when_nothing_declares_a_max(self) -> None:
        import pandas as pd

        frame = pd.DataFrame({"ID": [1, 2], "Quiz": [8, 9], "Essay": [15, 12]})
        mapping = detect_mapping(frame)
        assert {c.name for c in mapping.criteria_columns} == {"Quiz", "Essay"}
        assert mapping.get("Quiz").points == 9


class TestRows:
    def test_team_header_rows_become_a_team_not_a_student(self, rows) -> None:
        assert [row.name for row in rows] == [
            "Ada Lovelace",
            "Alan Turing",
            "Grace Hopper",
            "Katherine Johnson",
        ]
        assert rows[0].team == "teamalpha"
        assert rows[2].team == "teambeta"

    def test_blank_trailing_rows_are_dropped(self, rows) -> None:
        assert len(rows) == 4

    def test_ids_survive_pandas_float_coercion(self, rows) -> None:
        assert rows[0].canvas_id == 101
        assert rows[0].sis_id == "s101"

    def test_scores_comments_total_and_ratio_are_picked_up(self, rows) -> None:
        ada = rows[0]
        assert ada.score_map["M1 Design (10)"] == 8
        assert ada.comment_map["M1 Design (10)"] == "Clean structure"
        assert ada.total_override == 25
        assert ada.ratio == 1.0

    def test_a_student_with_no_scores_still_produces_a_row(self, rows) -> None:
        # They have an id, so they are a real student; the plan decides what to do.
        assert rows[3].name == "Katherine Johnson"
        assert rows[3].scores == ()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("8", 8.0), (" 9.5 ", 9.5), ("85%", 85.0), ("1,000", 1000.0), ("", None), ("n/a", None), ("abc", None)],
)
def test_to_float(value: str, expected: float | None) -> None:
    assert to_float(value) == expected


def test_to_int_rejects_non_integers() -> None:
    assert to_int("101.0") == 101
    assert to_int("101.5") is None


class TestFiltering:
    def test_include_keeps_only_matching_criteria(self, mapping) -> None:
        filtered = filter_criteria(mapping, include=["M1 *"])
        assert {c.name for c in filtered.criteria_columns} == {"M1 Design (10)", "M1 Tests (20)"}

    def test_comments_follow_their_criterion_out(self, mapping) -> None:
        filtered = filter_criteria(mapping, include=["M2 *"])
        assert filtered.get("M1 Design comment").role is ColumnRole.IGNORE

    def test_exclude_drops_matching_criteria(self, mapping) -> None:
        filtered = filter_criteria(mapping, exclude=["* Tests *"])
        assert {c.name for c in filtered.criteria_columns} == {"M1 Design (10)", "M2 Design (10)"}

    def test_a_filter_matching_nothing_is_an_error(self, mapping) -> None:
        with pytest.raises(MappingError, match="No criterion columns matched"):
            filter_criteria(mapping, include=["M9 *"])


def test_missing_file_is_reported_clearly(tmp_path) -> None:
    with pytest.raises(SheetError, match="not found"):
        read_sheet(tmp_path / "nope.csv")


def test_unsupported_extension_is_reported_clearly(tmp_path) -> None:
    path = tmp_path / "grades.docx"
    path.write_text("x")
    with pytest.raises(SheetError, match="Unsupported file type"):
        read_sheet(path)
