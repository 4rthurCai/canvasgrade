"""Failure messages.

A tool that writes to student records has to explain itself when it will not run. Each
of these asserts the message tells the user what to actually do next.
"""

from __future__ import annotations

import pytest
import requests
from canvasapi.exceptions import Forbidden, InvalidAccessToken, ResourceDoesNotExist, Unauthorized

from canvasgrade.canvas.client import _explain
from canvasgrade.canvas.pull import write_template
from canvasgrade.errors import CanvasError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (InvalidAccessToken("bad"), "New Access Token"),
        (Unauthorized("bad"), "New Access Token"),
        (Forbidden("nope"), "Teacher or TA role"),
        (ResourceDoesNotExist("gone"), "Check the id in the page URL"),
        (requests.exceptions.ConnectionError("down"), "Check the API URL and your network"),
        (requests.exceptions.Timeout("slow"), "--batch-size"),
        (requests.exceptions.SSLError("tls"), "Check the API URL"),
    ],
)
def test_each_failure_says_what_to_do_next(exception: Exception, expected: str) -> None:
    error = _explain(exception, "doing the thing")
    assert isinstance(error, CanvasError)
    assert expected in str(error)
    assert "doing the thing" in str(error)


def test_an_unrecognised_error_still_names_the_operation() -> None:
    assert "listing courses" in str(_explain(RuntimeError("boom"), "listing courses"))


class TestTemplateWriting:
    def test_xlsx_and_csv_both_round_trip(self, roster, tmp_path) -> None:
        from canvasgrade.canvas.pull import build_template
        from canvasgrade.sheet import read_sheet

        frame = build_template(roster)
        for name in ("template.xlsx", "template.csv"):
            path = write_template(frame, tmp_path / name)
            assert read_sheet(path).n_rows == len(roster.entries)

    def test_an_unsupported_extension_names_the_ones_that_work(self, roster, tmp_path) -> None:
        from canvasgrade.canvas.pull import build_template

        with pytest.raises(CanvasError, match=r"\.xlsx or \.csv"):
            write_template(build_template(roster), tmp_path / "template.pdf")


def test_an_empty_course_is_reported_rather_than_returning_nothing() -> None:
    from canvasgrade.canvas.pull import fetch_roster

    class EmptyCourse:
        id = 5

        def get_users(self, **kwargs: object) -> list[object]:
            return []

    with pytest.raises(CanvasError, match="no active students"):
        fetch_roster(EmptyCourse())
