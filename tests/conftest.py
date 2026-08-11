"""Shared fixtures.

Every fixture here is synthetic. Real gradebooks must never be committed: they contain
student names and identifiers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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
