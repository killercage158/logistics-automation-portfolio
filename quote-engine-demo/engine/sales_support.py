"""Sales Support: the people who turn the departments' options into one customer quote.

The departments (Booking, Trucking, Customs) only PROPOSE. They produce ranked
options and stop there. Sales Support looks at the options, picks one per
department, sets the profit and sends the quote.

Rules in this file (written in skills/sales-support.md):
  SS-01  teams propose, Sales Support decides (one pick per department)
  SS-02  the profit margin is set only by Sales Support
  SS-03  "enough options": a quote is READY only when every department has enough
  SS-04  manual entries count equally with system options
  SS-05  one tracking code per lead, shown first on every document
  SS-06  internal doubts and action items never appear on the customer quotation

WHY SS-06: the departments' flags ("possible copied file, check it", "confirm the right HS
code") are working notes for staff. A customer who read them would lose trust in the
whole quotation. So every note has an audience. Internal notes stay in the internal lead
report; the customer sees only conditions written for customers.

WHY this split: when many leads are open at the same time, a department that also
decides price and profit creates confusion. A clear hand-off (departments propose,
one role decides) keeps every lead understandable.

In production, Sales Support picks the option number in the team's table or on a chat
card, and the combined quote is built from those picks.
"""
import zlib
from dataclasses import dataclass, field

from engine.money import vnd_to_usd
from engine.rulebook import hit, rule

MIN_OPTIONS = {"Booking": 2, "Trucking": 2, "Customs": 1}     # fictional "enough" levels


@rule("SS-05", "One tracking code per lead, shown first on every document")
def lead_code(req, as_of, pickup="", product=""):
    """A readable, repeatable code: LD-<date>-<3 digits from the request>."""
    digits = zlib.crc32(f"{req.label()}|{pickup}|{product}".encode()) % 1000
    return f"LD-{as_of:%Y%m%d}-{digits:03d}"


@rule("SS-04", "Manual entries count equally with system options")
def count_options(options, trace=None):
    """Number of options a department delivered. Manual ones count like any other."""
    for o in options:
        price = getattr(o, "price", None)
        source = getattr(price, "source", None) or getattr(o, "source", "")
        if source == "manual":
            hit(trace, "SS-04", getattr(o, "carrier", None) or o.haulier, "manual option counted equally")
    return len(options)


@rule("SS-03", "Enough options: Booking and Trucking need 2, Customs needs 1 verified answer")
def enough_options(n_booking, n_trucking, customs_ok, trace=None):
    """Return a list of what is missing. Empty list = READY."""
    missing = []
    if n_booking < MIN_OPTIONS["Booking"]:
        missing.append(f"Booking has {n_booking} option(s), needs {MIN_OPTIONS['Booking']}")
    if n_trucking < MIN_OPTIONS["Trucking"]:
        missing.append(f"Trucking has {n_trucking} option(s), needs {MIN_OPTIONS['Trucking']}")
    if not customs_ok:
        missing.append("Customs has no verified answer (or manual entry)")
    hit(trace, "SS-03", "lead", "DRAFT: " + "; ".join(missing) if missing else "READY: every department has enough")
    return missing


@rule("SS-01", "Teams propose, Sales Support decides: one pick per department")
def pick_options(booking, trucking, picks, trace=None):
    """Return {"Booking": (option, how), "Trucking": (option, how)}.

    `picks` is Sales Support's choice by option number ({"booking": 2}). With no pick the
    recommended (first) option is used and the quote says so: the default is a
    suggestion, not a decision.
    """
    chosen = {}
    for dept, options in (("Booking", booking), ("Trucking", trucking)):
        if not options:
            continue
        number = picks.get(dept.lower())
        if number is not None and not 1 <= number <= len(options):
            raise ValueError(f"{dept} has no option number {number}")
        option = options[(number or 1) - 1]
        how = f"picked by Sales Support (option {number})" if number else "default: recommended option"
        chosen[dept] = (option, how)
        hit(trace, "SS-01", dept, how)
    return chosen


@rule("SS-02", "The profit margin is set only by Sales Support")
def apply_margin(freight_usd, margin_per_container, qty, trace=None):
    """Return the selling freight per container: cost + the margin Sales Support typed."""
    hit(trace, "SS-02", "quote", f"margin USD {margin_per_container:g} per container, set by Sales Support")
    return freight_usd + margin_per_container


SPACE_CONDITION = "Subject to space and equipment availability."


@rule("SS-06", "Internal doubts and action items never appear on the customer quotation")
def customer_conditions(req, customs=None):
    """Conditions for the customer, written as conditions (never as doubts or to-do items).

    They are built from facts (cargo type, licence, inspection), not copied from the
    departments' internal flags.
    """
    notes = []
    if req.cargo == "charcoal":
        notes.append("Charcoal ships as dangerous goods: a DG declaration and suitable packing are required.")
    if customs is not None and customs.ok:
        if customs.licence:
            notes.append(f"An {customs.direction} licence is required before customs clearance.")
        if customs.inspection == "physical":
            notes.append("Goods are subject to physical inspection at the port.")
        elif customs.inspection == "documents":
            notes.append("Documents are subject to inspection by customs.")
    return notes + [SPACE_CONDITION]


@dataclass
class CombinedQuote:
    lead_code: str
    status: str                                  # "READY" or "DRAFT"
    missing: list
    picks: dict                                  # dept -> (option, how)
    lines: list = field(default_factory=list)    # (section, label, usd)
    taxes: list = field(default_factory=list)    # (label, usd): government taxes, paid at cost
    valid_until: object = None
    internal_notes: list = field(default_factory=list)   # doubts and action items: staff only
    customer_notes: list = field(default_factory=list)   # conditions written for the customer
    margin: float = 0.0

    @property
    def total(self):
        return sum(usd for _, _, usd in self.lines)

    @property
    def taxes_total(self):
        return sum(usd for _, usd in self.taxes)


def build_combined_quote(code, req, booking_opts, trucking_opts, customs, picks, margin, trace=None):
    """Assemble the combined quote from the PICKED options (never from unpicked ones)."""
    nb, nt = count_options(booking_opts, trace), count_options(trucking_opts, trace)
    missing = enough_options(nb, nt, customs.ok, trace)
    chosen = pick_options(booking_opts, trucking_opts, picks, trace)
    quote = CombinedQuote(code, "DRAFT" if missing else "READY", missing, chosen, margin=margin)
    dates = []

    if "Booking" in chosen:
        o, _ = chosen["Booking"]
        sell = apply_margin(o.price.price_usd, margin, req.qty, trace)
        quote.lines.append(("Ocean freight", f"{o.carrier} ({req.container} x {req.qty})", sell * req.qty))
        for name, c in o.local_charges.items():
            qty = req.qty if c.unit == "per_container" else 1
            quote.lines.append(("Local charges", f"{name} ({'x ' + str(qty) if qty > 1 else 'per B/L' if c.unit == 'per_bl' else 'per container'})",
                                c.usd * qty))
        dates.append(o.price.valid_until)
        quote.internal_notes += o.flags
    if "Trucking" in chosen:
        t, _ = chosen["Trucking"]
        quote.lines.append(("Trucking", f"{t.haulier}: pickup to port, {req.qty} trip{'s' if req.qty != 1 else ''}", vnd_to_usd(t.total_vnd)))
        dates.append(t.valid_until)
        quote.internal_notes += t.flags
    if customs.ok:
        for name, vnd in customs.fees:
            quote.lines.append(("Customs service", name, vnd_to_usd(vnd)))
        quote.taxes = [(f"Customs duty {customs.duty_pct:g}% on USD {customs.value_usd:,.0f}", customs.duty_usd),
                       (f"VAT {customs.vat_pct:g}% on value plus duty", customs.vat_usd)]
        quote.internal_notes += customs.procedures + customs.warnings
    quote.valid_until = min((d for d in dates if d), default=None)
    quote.customer_notes = customer_conditions(req, customs if customs.ok else None)
    hit(trace, "SS-06", "quote", f"{len(quote.internal_notes)} internal note(s) kept off the customer quotation")
    return quote
