"""Booking rules that turn raw ocean prices into comparable options (step 5).

Rules in this file (written in skills/booking-price-files.md):
  BK-03  live portal price first, price files fill gaps (order of trust)
  BK-04  expired prices are dropped, and listed
  BK-05  doubtful data is FLAGGED, never dropped
  BK-06  cargo type: a price for the other cargo is not used; charcoal needs handling notes

(BK-01, BK-02, BK-07, BK-08, BK-09 live next to the code they govern: portals.py,
contracts.py, manual.py, verify.py.)

Each rule is a small function so you can read, test and change it on its own.

WHY these rules exist:
  - Order of trust: today's live number is the most current; files may be old.
  - Dropping expired prices stops a customer being quoted a price that no longer exists.
  - Flag, don't hide: the booking team owns its data. If something looks odd we
    show a warning next to it and let people decide.

In production, the same rules run over the booking team's own tables and the carrier
portals; manual entries flow into the same ranking. Simplified here: CSV tables.
"""
import csv
import statistics

from engine.free_time import free_time, missing_free_time_flag
from engine.local_charges import (charge_cascade, missing_required_fees, per_bl_note,
                                  remove_included_fees)
from engine.models import SOURCE_ORDER, Option
from engine.request import key
from engine.rulebook import RuleTrace, hit, rule

LOW_PRICE_RATIO = 0.6            # a price under 60% of the median of the other options looks doubtful
SHORT_VALIDITY_DAYS = 7


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def canonical_carrier(name, known):
    """Match "BLUEWAVE LINES" or "Bluewave Line" to the known spelling "Bluewave Lines"."""
    wanted = key(name)
    for k in known:
        if wanted == key(k):
            return k
    return name.strip()


@rule("BK-04", "Expired prices are dropped and listed with the reason")
def filter_validity(prices, as_of, trace=None):
    """Split prices into (kept, dropped). dropped is a list of (price, reason, rule id).

    A price with no validity date is kept (we cannot prove it is expired) and
    flagged later by BK-05.
    """
    kept, dropped = [], []
    for p in prices:
        if p.valid_until is not None and p.valid_until < as_of:
            dropped.append((p, f"expired on {p.valid_until}", "BK-04"))
            hit(trace, "BK-04", p.carrier, f"{p.source} price expired on {p.valid_until}")
        else:
            kept.append(p)
    return kept, dropped


@rule("BK-06", "Cargo type: charcoal and general prices are not mixed")
def filter_cargo(prices, cargo, trace=None):
    """Keep prices that apply to this cargo type. A price with cargo None applies to any."""
    kept, dropped = [], []
    for p in prices:
        if p.cargo in (None, cargo):
            kept.append(p)
        else:
            dropped.append((p, f"price is for {p.cargo} cargo, request is {cargo}", "BK-06"))
            hit(trace, "BK-06", p.carrier, f"{p.source} price is for {p.cargo} cargo")
    return kept, dropped


def charcoal_handling_flags(req, carrier, trace=None):
    """Handling notes for charcoal (BK-06). Charcoal can self-heat, so carriers may treat it
    as dangerous goods. We do not decide that: we remind staff to confirm it."""
    if req.cargo != "charcoal":
        return []
    hit(trace, "BK-06", carrier, "charcoal handling note added")
    return ["charcoal: confirm dangerous-goods declaration and packing with the carrier"]


@rule("BK-03", "Live portal price first; price files fill gaps (order of trust)")
def choose_per_carrier(prices, trace=None):
    """Pick one price per carrier by order of trust, then by lowest price.

    Order of trust: contract > manual > live portal > price file.
    Returns (chosen {carrier: Price}, superseded [(price, reason, rule id)]).
    """
    by_carrier = {}
    for p in prices:
        by_carrier.setdefault(p.carrier, []).append(p)
    chosen, superseded = {}, []
    for carrier, items in by_carrier.items():
        items.sort(key=lambda p: (SOURCE_ORDER.index(p.source), p.price_usd))
        chosen[carrier] = items[0]
        hit(trace, "BK-03", carrier, f"{items[0].source} price used")
        for other in items[1:]:
            superseded.append((other, f"{items[0].source} price used instead "
                                      f"(order of trust: {' > '.join(SOURCE_ORDER)})", "BK-03"))
    return chosen, superseded


@rule("BK-05", "Doubtful data is flagged, never dropped")
def flag_doubtful(options, as_of, trace=None):
    """Add warnings to options whose data looks doubtful. Nothing is removed.

    Doubts: no validity date; valid only a few more days; a price far below the median
    of the other options (a typo, a different cargo or an old file); a price that comes
    from a spreadsheet instead of a live check.
    """
    totals = [o.price.price_usd for o in options]
    median = statistics.median(totals) if len(totals) >= 3 else None
    for o in options:
        p, flags = o.price, o.flags
        before = len(flags)
        if p.valid_until is None:
            flags.append("no validity date - confirm before quoting")
        elif (p.valid_until - as_of).days <= SHORT_VALIDITY_DAYS:
            flags.append(f"valid only until {p.valid_until}")
        if median and p.price_usd < LOW_PRICE_RATIO * median:
            flags.append(f"price is far below the median ({median:,.0f}) - check it")
        if p.source == "price file":
            flags.append("price comes from a spreadsheet, not a live check - confirm before quoting")
        if len(flags) > before:
            hit(trace, "BK-05", o.carrier, "; ".join(flags[before:]))
    return options


def build_option(price, req, general_rows, carrier_rows, freetime_rows, as_of, trace=None):
    """Combine a price with local charges (LC-*) and free time (FT-*) into one Option.

    Doubtful data is flagged later by flag_doubtful (BK-05), once all options exist.
    """
    trace = trace if trace is not None else RuleTrace()
    flags, carrier = [], price.carrier
    charges = charge_cascade(carrier, req, general_rows, carrier_rows, trace)
    charges = remove_included_fees(carrier, charges, price.includes, trace)
    for fee in missing_required_fees(carrier, charges, req, trace):
        flags.append(f"required fee {fee} missing from every table - total is incomplete")
    per_bl_note(carrier, charges, trace)
    if any(c.source != "general table" and "included" not in c.source for c in charges.values()):
        flags.append("uses carrier-specific local charges")
    ft = free_time(carrier, req, freetime_rows, trace)
    note = missing_free_time_flag(carrier, ft, trace)
    if note:
        flags.append(note)
    flags += charcoal_handling_flags(req, carrier, trace)
    return Option(price, charges, ft, flags, qty=req.qty)
