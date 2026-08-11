"""Load CSV / XLS(X) files into a normalised frame.

No index column is ever set: identifying the student is the detector's job, and it
needs to see every column to do it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from canvasgrade.errors import SheetError

CSV_SUFFIXES = frozenset({".csv", ".tsv", ".txt"})
EXCEL_SUFFIXES = frozenset({".xls", ".xlsx", ".xlsm"})
SUPPORTED_SUFFIXES = CSV_SUFFIXES | EXCEL_SUFFIXES


@dataclass(frozen=True)
class SheetData:
    """A raw sheet plus the provenance needed for good error messages."""

    frame: pd.DataFrame
    source: Path
    sheet_name: str | None = None
    has_header: bool = True

    @property
    def headers(self) -> tuple[str, ...]:
        return tuple(str(c) for c in self.frame.columns)

    @property
    def n_rows(self) -> int:
        return len(self.frame)


def list_sheets(path: str | Path) -> tuple[str, ...]:
    """Return the sheet names of an Excel workbook; empty tuple for CSV."""
    path = Path(path)
    if path.suffix.lower() not in EXCEL_SUFFIXES:
        return ()
    try:
        with pd.ExcelFile(path, engine="openpyxl") as workbook:
            return tuple(str(name) for name in workbook.sheet_names)
    except Exception as exc:
        raise SheetError(f"Could not open workbook {path}: {exc}") from exc


def read_sheet(
    path: str | Path,
    *,
    sheet: str | int = 0,
    has_header: bool = True,
) -> SheetData:
    """Read a CSV/Excel file into a :class:`SheetData`.

    ``has_header=False`` treats the file as purely positional: the first column is the
    Canvas user id and the rest are criteria, in rubric order.
    """
    path = Path(path)
    if not path.exists():
        raise SheetError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    header_arg = 0 if has_header else None
    try:
        if suffix in CSV_SUFFIXES:
            separator = "\t" if suffix == ".tsv" else ","
            frame = pd.read_csv(path, header=header_arg, sep=separator, encoding="utf-8-sig", dtype=object)
            sheet_name = None
        elif suffix in EXCEL_SUFFIXES:
            frame = pd.read_excel(path, header=header_arg, sheet_name=sheet, engine="openpyxl", dtype=object)
            sheet_name = str(sheet)
        else:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise SheetError(f"Unsupported file type '{suffix}'. Supported: {supported}")
    except SheetError:
        raise
    except Exception as exc:
        raise SheetError(f"Could not read {path}: {exc}") from exc

    if frame.empty:
        raise SheetError(f"{path} contains no data rows")

    frame.columns = [
        _clean_header(column, index) if has_header else f"column_{index}" for index, column in enumerate(frame.columns)
    ]
    return SheetData(
        frame=frame.reset_index(drop=True),
        source=path,
        sheet_name=sheet_name,
        has_header=has_header,
    )


def _clean_header(raw: object, index: int) -> str:
    """Normalise a header cell: strip BOM and whitespace, name the unnamed."""
    text = str(raw).replace("﻿", "").strip()
    if not text or text.lower().startswith("unnamed:") or text.lower() == "nan":
        return f"column_{index}"
    return " ".join(text.split())
