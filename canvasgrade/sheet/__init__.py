"""Spreadsheet ingestion: read a file, work out what its columns mean, extract rows."""

from canvasgrade.sheet.detect import detect_mapping, parse_header, parse_points, strip_points
from canvasgrade.sheet.reader import SheetData, list_sheets, read_sheet
from canvasgrade.sheet.rows import extract_rows, to_float

__all__ = [
    "SheetData",
    "detect_mapping",
    "extract_rows",
    "list_sheets",
    "parse_header",
    "parse_points",
    "read_sheet",
    "strip_points",
    "to_float",
]
