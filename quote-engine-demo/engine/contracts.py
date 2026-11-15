"""Step 2: contract rates are checked FIRST, and they switch the portal check off.

Business rule (from the booking team's guide): if we already have a negotiated
contract rate for a carrier on this lane, that rate is the price. Asking the
carrier's website for a spot price too would waste minutes and could show a
different, confusing number. So a carrier with a valid contract is NOT sent to
the portal step.

An expired contract is ignored (and we say so in the log), so the carrier goes
back to the normal portal check.

In production, contract rates are read from the team's contract workbook, contract
carriers get top priority in the ranking, and their portals are skipped.
Simplified here: one CSV file instead of a team workbook with its own layout.
"""
import csv
from datetime import date

from engine.models import Price
from engine.rulebook import hit, rule
from engine.request import normalise_cargo, normalise_container, normalise_port


def load_contracts(path):
    """Read contracts.csv into a list of dicts with clean ports, container and cargo."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "carrier": r["carrier"].strip(),
                "pol": normalise_port(r["pol"]),
                "pod": normalise_port(r["pod"]),
                "container": normalise_container(r["container"]),
                "cargo": normalise_cargo(r["cargo"]),
                "price_usd": float(r["price_usd"]),
                "valid_until": date.fromisoformat(r["valid_until"]),
                "ref": r["contract_ref"].strip(),
            })
    return rows


def find_contracts(rows, req, as_of, trace=None):
    """Return (valid, ignored).

    valid:   {carrier: Price} for contracts that match the lane and are in date.
    ignored: log lines for matching contracts that have expired.
    """
    valid, ignored = {}, []
    for r in rows:
        same_lane = (r["pol"], r["pod"], r["container"], r["cargo"]) == \
                    (req.pol, req.pod, req.container, req.cargo)
        if not same_lane:
            continue
        if r["valid_until"] < as_of:
            ignored.append(f"{r['carrier']}: contract {r['ref']} expired on {r['valid_until']} "
                           f"-> ignored, carrier will be checked on its portal")
            hit(trace, "BK-02", r["carrier"], f"contract {r['ref']} expired, portal check stays on")
            continue
        valid[r["carrier"]] = Price(r["carrier"], r["price_usd"], r["valid_until"], "contract",
                                    f"contract {r['ref']}", req.cargo)
        hit(trace, "BK-02", r["carrier"], f"valid contract {r['ref']}: portal check skipped")
    return valid, ignored


@rule("BK-02", "Contract first: a carrier with a valid contract is not checked on its portal")
def carriers_for_portal(all_carriers, contracts):
    """The contract-first rule in one line: carriers WITH a contract are not checked on the web."""
    return [c for c in all_carriers if c not in contracts]
