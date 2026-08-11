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
