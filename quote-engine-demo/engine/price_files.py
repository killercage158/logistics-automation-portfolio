"""Helpers for the team's hand-made price spreadsheets.

Two jobs:
  1. grid_text(): turn a workbook into plain text, one cell per line, so an AI
     model can read it. The AI sees the SAME cell addresses that verify.py will
     use later to check its answer. That is what makes the check possible.
  2. parse_numbers(): read messy price text such as "USD 3,450" or "1.250,00".

In production, the booking team's whole price folder is turned into text and
handed to the AI, using a separate spreadsheet reader. Simplified here: only .xlsx, one file at a time.
"""
import re
from functools import lru_cache
from pathlib import Path

from openpyxl import load_workbook


@lru_cache(maxsize=None)
def open_book(path):
    """Open a workbook once and reuse it (verification opens many cells).

    data_only=True: read the values Excel saved, not the formulas.
    """
    return load_workbook(Path(path), data_only=True)


def grid_text(path):
    """Describe every non-empty cell as 'A1 | value', grouped by sheet.

    Merged cells hold their value in the top-left cell only, so that is the
    only one listed. This is exactly what a human sees, too.
    """
    lines = []
    for ws in open_book(path).worksheets:
        lines.append(f"## Sheet: {ws.title}")
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is not None and str(cell.value).strip():
                    lines.append(f"{cell.coordinate} | {cell.value}")
    return "\n".join(lines)


def row_text(path, sheet, cell_ref):
    """All text in the same row as a cell (used to check the cited row names the right ports)."""
    ws = open_book(path)[sheet]
    row_no = ws[cell_ref].row
    return " ".join(str(c.value) for c in ws[row_no] if c.value is not None)


# A number "chunk" starts and ends with a digit and may contain , or . inside.
NUMBER_TOKEN = re.compile(r"\d(?:[\d.,]*\d)?")


def parse_one_number(digits):
    """Convert one digits such as '3,450' or '1.250,00' to a float.

    Rules, kept simple on purpose:
      - both ',' and '.' present: the LAST one is the decimal mark
      - a lone ',' followed by exactly 3 digits is a thousands mark (3,450)
      - a lone ',' followed by 1-2 digits is a decimal mark (12,5)
      - several dots are thousands marks (1.250.000)
      - a single '.' is a decimal point, so "1.250" reads as 1.25. That is a
        deliberate choice: when unsure we prefer a mismatch (row rejected)
        over silently accepting a wrong price.
    """
    has_comma, has_dot = "," in digits, "." in digits
    if has_comma and has_dot:
        decimal = "," if digits.rfind(",") > digits.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        digits = digits.replace(thousands, "").replace(decimal, ".")
    elif has_comma:
        head, _, tail = digits.rpartition(",")
        digits = digits.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    elif has_dot and digits.count(".") > 1:
        digits = digits.replace(".", "")
    return float(digits)


def parse_numbers(value):
    """Every number found in a cell value, as floats.

    A numeric cell gives one number. "USD 3,450" gives [3450.0]. A sentence
    gives all its numbers, so the caller can ask "is the claimed price one of them?".
    """
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [parse_one_number(t) for t in NUMBER_TOKEN.findall(str(value))]


def context_text(path, sheet, cell_ref):
    """The words around a cell: its whole row plus the top of its column (the header area).

    Why both: some files name the lane in the row (POL | POD | price), others name the
    destination in the column header (a matrix). The checker accepts either.
    """
    ws = open_book(path)[sheet]
    cell = ws[cell_ref]
    top = [ws.cell(row=r, column=cell.column).value for r in range(1, 6)]
    return row_text(path, sheet, cell_ref) + " " + " ".join(str(v) for v in top if v is not None)
