"""A full lead: one customer request that needs sea freight, trucking and customs.

This is the whole flow in the order it happens:

  1. The lead arrives and gets a tracking code (SS-05).
  2. Work items are created for the departments that are needed (DP-01, DP-02, DP-07).
  3. Booking, Trucking and Customs each do their work. Every department proposes
     options with sources; code verifies every citation.
  4. The dispatch timeline is replayed on a simulated clock: accept or decline,
     deadline, reminders, answers (DP-03 to DP-06).
  5. Sales Support checks "enough options" (SS-03), picks one option per department
     (SS-01), sets the margin (SS-02) and the combined quote is built.

Departments run one after another in this demo. In production they work in parallel
and at their own pace; the simulated clock in step 4 shows that part.

In production, each step is a row in a department's table and each notice is a chat message.
"""
from dataclasses import dataclass
from datetime import date

from engine.customs import CustomsResult, run_customs
from engine.dispatch import clock, needed_departments, simulate
from engine.rulebook import RuleTrace
from engine.runlog import RunLog
from engine.sales_support import build_combined_quote, lead_code
from engine.trucking import run_trucking


@dataclass
class LeadResult:
    code: str
    request: object
    pickup: str
    product: str
    direction: str
    as_of: date
    booking: object
    trucking: object
    customs: object
    items: list
    events: list
    quote: object
    trace: object
    start: str = "09:00"


def default_responses(booking_first_pass, has_answer, declines, manual):
    """What each department does and when (simulated minutes after the lead arrived).

    Booking answers once its first portal run is done. Trucking is quick. Customs is slow on
    purpose, so the 30-minute deadline passes and a reminder goes out.
    A declining department is answered by Sales Support typing a manual entry, if there is one.
    """
    plan = {"Booking": [("accept", 2), ("answer", round(booking_first_pass) + 5, "system")],
            "Trucking": [("accept", 3), ("answer", 14, "system")],
            "Customs": [("accept", 6), ("answer", 47, "manual" if manual.get("Customs") else "system")]}
    for dept in list(plan):
        if dept in declines:
            plan[dept] = [("decline", 4, declines[dept])] + ([("answer", 33, "manual")] if manual.get(dept) else [])
        elif not has_answer.get(dept):
            plan[dept] = plan[dept][:1]                      # accepted, but nothing to deliver
    return plan


def run_lead(req, pickup, product, as_of, data_dir, llm, run_quote, direction="export", value_usd=20000.0,
             picks=None, margin=100.0, manual_booking=None, manual_trucking=None, manual_hs=None,
             declines=None, log=None, sleep=lambda minutes: None, start="09:00"):
    """Run the whole lead. `run_quote` is the booking pipeline function (passed in to avoid a circular import)."""
    log = log or RunLog()
    trace, picks, declines = RuleTrace(), picks or {}, declines or {}
    if "Booking" in declines:
        raise ValueError("a booking decline is not simulated: use --decline trucking or --decline customs")
    code = lead_code(req, as_of, pickup, product)
    departments = needed_departments(pickup, product)
    log.add(f"LEAD {code} | {req.label()} | pickup {pickup} | product {product}")
    log.add(f"=== DISPATCH: lead arrives at {start}; work items for {', '.join(departments)}; "
            f"deadline {clock(30, start)} ===")

    log.add("=== BOOKING (ocean freight) ===")
    booking = run_quote(req, as_of, data_dir, llm, manual_booking, log, sleep, trace)

    log.add("=== TRUCKING ===")
    if "Trucking" in declines:
        log.add("  the trucking team declined: only manual entries are used")
    trucking = run_trucking(req, pickup, as_of, data_dir, llm, log, trace, manual_trucking, "Trucking" not in declines)

    log.add("=== CUSTOMS ===")
    customs = run_customs(product, direction, value_usd, data_dir, llm, log, trace, manual_hs, "Customs" not in declines)
    log.add(f"  HS {customs.hs_code or '-'} | duty {customs.duty_pct:g}% = USD {customs.duty_usd:,.2f} | "
            f"VAT {customs.vat_pct:g}% = USD {customs.vat_usd:,.2f} | clearance fees USD {customs.fees_usd:,.0f}")
    for w in customs.warnings:
        log.add(f"  WARNING: {w}")

    manual = {"Booking": bool(manual_booking), "Trucking": bool(manual_trucking), "Customs": bool(manual_hs)}
    has_answer = {"Booking": bool(booking.ranked), "Trucking": bool(trucking.options), "Customs": customs.ok}
    responses = default_responses(booking.portal_minutes, has_answer, declines, manual)
    items, events = simulate(code, departments, {d: responses[d] for d in departments if d in responses}, trace, start)
    log.add("=== DISPATCH TIMELINE (simulated clock) ===")
    for e in events:
        log.add(f"  {clock(e.minute, start)}  {e.who:<14} {e.text}")

    log.add("=== SALES SUPPORT ===")
    answered = {i.department: i.status == "answered" for i in items}
    quote = build_combined_quote(code, req, booking.ranked if answered.get("Booking") else [],
                                 trucking.options if answered.get("Trucking") else [],
                                 customs if answered.get("Customs") else CustomsResult(product, direction, value_usd),
                                 picks, margin, trace)
    for dept, (opt, how) in quote.picks.items():
        log.add(f"  {dept}: {getattr(opt, 'carrier', None) or opt.haulier} - {how}")
    log.add(f"  margin USD {margin:g} per container, set by Sales Support")
    log.add(f"  QUOTE {quote.status}: total services USD {quote.total:,.0f}; estimated taxes USD {quote.taxes_total:,.0f}")
    for m in quote.missing:
        log.add(f"    missing: {m}")
    log.add(f"  rules applied in this lead: {', '.join(trace.all_ids())}")
    return LeadResult(code, req, pickup, product, direction, as_of, booking, trucking, customs, items, events,
                      quote, trace, start)
