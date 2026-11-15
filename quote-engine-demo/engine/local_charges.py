"""Local charges: the fees paid at the origin port on top of the ocean freight.

Rules in this file (written in skills/local-charges.md):
  LC-01  charge sources form a cascade, most specific first
  LC-02  a required set of export fees must be present
  LC-03  each charge is counted per container or once per bill of lading
  LC-04  a fee the carrier says is "included" is not added a second time

WHY the cascade: the carrier's own table knows its own fees better than a general
table does, and a table for one cargo type knows more than a table for all cargo.
Each later source only FILLS what the earlier ones lack. No source is thrown
away; it just ranks lower.

WHY the required set: a total that silently forgets one fee looks cheaper than it
is. A missing fee is flagged on the option, never quietly counted as zero.

In production the tables are the booking team's workbooks, read by an AI reader
that cites every cell; the same cascade applies. Simplified here: CSV tables.
"""
from engine.models import Charge
from engine.rulebook import hit, rule

REQUIRED_FEES = ("THC", "DOC", "SEAL", "TLX")        # AMS is added for US / EU destinations
PER_BL_FEES = ("DOC", "TLX", "AMS")                  # charged once per bill of lading


@rule("LC-03", "Each charge is per container or once per bill of lading")
def charge_unit(name, written_unit=""):
    """Unit of a charge: the table's own unit if it states one, else the usual practice.

    Why: documents (DOC), telex release (TLX) and manifest filing (AMS) happen once per
    bill of lading however many containers there are. THC and seals are per container.
    """
    if written_unit:
        return written_unit
    return "per_bl" if name in PER_BL_FEES else "per_container"


def _usable(row, req, container_key="container"):
    """Does this table row apply to this container size and destination region?"""
    if row[container_key] not in (req.container, "any"):
        return False
    return row.get("applies_to", "all") in ("all", "") or row["applies_to"] == req.region


@rule("LC-01", "Charge sources form a cascade: carrier+cargo table, carrier table, general table")
def charge_cascade(carrier, req, general_rows, carrier_rows, trace=None):
    """Return {charge name: Charge}, taking each charge from the most specific table that has it."""
    mine = [r for r in carrier_rows if r["carrier"] == carrier]
    sources = [
        (f"{carrier} {req.cargo} table", [r for r in mine if r.get("cargo") == req.cargo]),
        (f"{carrier} table", [r for r in mine if not r.get("cargo")]),
        ("general table", general_rows),
    ]
    charges = {}
    for label, rows in sources:
        for r in rows:
            if r["charge"] in charges or not _usable(r, req):
                continue                                     # an earlier, more specific table won
            charges[r["charge"]] = Charge(float(r["amount_usd"]), charge_unit(r["charge"], r.get("unit", "")), label)
            if label != "general table":
                hit(trace, "LC-01", carrier, f"{r['charge']} taken from the {label}")
    return charges


@rule("LC-04", "A fee the carrier says is included is not added again")
def remove_included_fees(carrier, charges, includes, trace=None):
    """Set fees that the carrier's own quote says are included to zero (kept visible, not deleted)."""
    for name in includes:
        if name in charges:
            charges[name] = Charge(0.0, charges[name].unit, "included in the carrier's quote")
            hit(trace, "LC-04", carrier, f"{name} is included in the carrier's quote")
    return charges


@rule("LC-02", "Required export fees must be present; a missing one is flagged")
def missing_required_fees(carrier, charges, req, trace=None):
    """Return the required fees that no table supplied. The caller flags them on the option."""
    required = REQUIRED_FEES + (("AMS",) if req.region == "us_eu" else ())
    missing = [f for f in required if f not in charges]
    hit(trace, "LC-02", carrier, "missing: " + ", ".join(missing) if missing else "all required fees present")
    return missing


def per_bl_note(carrier, charges, trace=None):
    """Record LC-03 when the option has per-bill-of-lading charges."""
    if any(c.unit == "per_bl" for c in charges.values()):
        hit(trace, "LC-03", carrier, "per-B/L charges are counted once, not per container")
