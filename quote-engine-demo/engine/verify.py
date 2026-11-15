"""Check every AI answer against the real file. Nothing is accepted on trust.

For each price the AI claims, we open the cell it cites and ask:
  1. Does that cell exist and hold something?
  2. Does the number in the cell match the number the AI claimed?
  3. Does the row (and the top of the column) of that cell name the things the
     AI says the price is for: the two ports, the pickup place, the truck type?
     (Question 2 alone is not enough: the AI could cite a cell holding the right
     number for a DIFFERENT lane.)

A claim that fails any question is REJECTED with a plain-English reason. Rejected
items are shown in the report. They are never silently dropped and never repaired:
a repaired item would just be another guess.

This file contains no AI. That is the point: plain code cannot be talked into agreeing.

Rules in this file: BK-09 (prices from booking files) and TR-02 (haulier prices).
Both use the same check_citation() function.

In production the same idea guards every AI reader: price cells, local charge tables,
trucking files and the legal text behind customs answers.
"""
import re
from pathlib import Path

from engine.price_files import context_text, open_book, parse_numbers
from engine.request import key, place_in_text, port_in_text
from engine.rulebook import hit, rule

TOLERANCE = 0.01          # numbers match if they differ by less than 0.01


def _num(x):
    """650.0 -> '650'; 3850000.0 -> '3,850,000'."""
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def check_citation(path, sheet, cell, claimed, mentions=()):
    """Return (accepted, reason). `mentions` is a list of (label, test) the context must satisfy."""
    path = Path(path)
    if not path.is_file():
        return False, f"file '{path.name}' does not exist"
    book = open_book(path)
    if sheet not in book.sheetnames:
        return False, f"sheet '{sheet}' does not exist"
    if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", cell):            # "C5", not "C" or "5"
        return False, f"'{cell}' is not a valid cell address"

    value = book[sheet][cell].value
    if value is None or str(value).strip() == "":
        return False, f"cell {cell} is empty"
    numbers = parse_numbers(value)
    if not numbers:
        return False, f"cell {cell} has no number: {value!r}"
    if not any(abs(n - claimed) <= TOLERANCE for n in numbers):
        return False, f"cell {cell} holds {value!r}, but the AI said {_num(claimed)}"

    context = context_text(path, sheet, cell)
    for label, test in mentions:
        if not test(context):
            return False, f"the cited row does not mention {label}: {context[:60]!r}"
    return True, f"cell {cell} holds {value!r}"


@rule("BK-09", "An AI-read price must cite its cell; code re-opens the cell and rejects mismatches")
def verify_row(row, data_dir, trace=None):
    """Return (accepted, reason) for one PriceRow (ocean freight read by the AI)."""
    ok, why = check_citation(Path(data_dir) / row.file, row.sheet, row.cell, row.price_usd,
                             [(row.pol, lambda t: port_in_text(row.pol, t)),
                              (row.pod, lambda t: port_in_text(row.pod, t))])
    hit(trace, "BK-09", row.carrier, ("accepted: " if ok else "rejected: ") + why)
    return ok, why


def verify_all(rows, data_dir, trace=None):
    """Return a list of (row, accepted, reason), in the same order as `rows`."""
    return [(row, *verify_row(row, data_dir, trace)) for row in rows]


@rule("TR-02", "Haulier prices: code re-opens every cited cell (price and diesel base)")
def verify_haulier_row(row, data_dir, trace=None):
    """Return (accepted, reason) for one HaulierRow. Checks the price cell and the diesel cell."""
    path = Path(data_dir) / row.file
    ok, why = check_citation(path, row.sheet, row.cell, row.price_vnd,
                             [(row.pickup, lambda t: place_in_text(row.pickup, t)),
                              (row.port, lambda t: place_in_text(row.port, t)),
                              (row.truck, lambda t: key(row.truck) in key(t))])
    if ok:
        ok, why = check_citation(path, row.diesel_sheet, row.diesel_cell, row.diesel_base_vnd)
        why = "diesel base: " + why if not ok else "price and diesel base both match their cells"
    hit(trace, "TR-02", row.haulier, ("accepted: " if ok else "rejected: ") + why)
    return ok, why
