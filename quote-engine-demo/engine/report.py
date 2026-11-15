"""Step 7: write the HTML documents.

Booking only (python quote.py ...):
  comparison.html     for the booking team: every option with its source and the
                      RULES APPLIED to it (rule IDs), what each carrier portal did
                      (retries included), what the AI read, what verification
                      REJECTED and why, and what was left out.
  customer_quote.html for the customer: one clear offer, no internal details.

Full lead (python quote.py lead ...):
  lead_report.html    internal: timeline of the dispatch, then one section per
                      department (Booking, Trucking, Customs) with options, rejected
                      items and warnings, then Sales Support's picks, then a legend
                      of every rule applied.
  combined_quote.html for the customer: Booking + Trucking + Customs + margin.

WHY HTML: it opens in any browser, can be printed to PDF, and needs no extra
library. The real system builds PDFs the same way (HTML rendered by a browser).

In production, the comparison PDF and the quote PDF are made from HTML with a headless
browser, and the combined customer quote merges the departments' picks.
"""
from html import escape

from engine.money import FX_VND_PER_USD, vnd_to_usd
from engine.rulebook import RULES
from engine.sales_support import customer_conditions

STYLE = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px auto;max-width:1100px;color:#1d2433;padding:0 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px;border-bottom:2px solid #dde3ee;padding-bottom:4px}
.sub{color:#5b6475;font-size:13px} table{border-collapse:collapse;width:100%;font-size:13px}
th{background:#eef2f8;text-align:left} th,td{border:1px solid #dde3ee;padding:6px 8px;vertical-align:top}
.rec{background:#eaf7ee;border:1px solid #9fd3ae;border-radius:6px;padding:10px 16px;margin-top:14px}
.rec li{margin:3px 0} .bad td{background:#fdeeee} .num{text-align:right;white-space:nowrap}
.badge{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;color:#fff}
.contract{background:#6a3fb5}.manual{background:#b5701f}.portal{background:#1f6fb5}.pricefile{background:#5b6475}
.rid{background:#eef2f8;border:1px solid #c9d3e6;border-radius:4px;padding:0 4px;margin:1px;font-size:11px;display:inline-block;font-family:Consolas,monospace}
.draft{background:#fff4e5;border:1px solid #f0c58a;border-radius:6px;padding:8px 14px;margin-top:12px}
h3{font-size:14px;margin:18px 0 6px}
.flag{color:#a55a00;font-size:12px} .ok{color:#1c7a3b} .no{color:#b3261e} .foot{margin-top:28px;color:#5b6475;font-size:12px}
"""


class Raw(str):
    """Text that is already safe HTML (so cell() will not escape it again)."""


def cell(value):
    return value if isinstance(value, Raw) else escape(str(value))


def table(headers, rows, row_class="", classes=None):
    """HTML table. `row_class` styles every row; `classes` (one per row) styles rows individually."""
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    classes = classes or [row_class] * len(rows)
    body = "".join(f"<tr class='{c}'>" + "".join(f"<td>{cell(x)}</td>" for x in r) + "</tr>"
                   for r, c in zip(rows, classes))
    return f"<table><tr>{head}</tr>{body}</table>" if rows else "<p class='sub'>None.</p>"


def badge(source):
    css = source.replace(" ", "")
    return Raw(f"<span class='badge {css}'>{escape(source)}</span>")


def rule_tags(ids):
    """Rule IDs as small tags; hovering shows the rule's title."""
    return Raw("".join(f"<span class='rid' title='{escape(RULES[i].title)}'>{i}</span>" for i in ids))


def page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{escape(title)}</title>"
            f"<style>{STYLE}</style></head><body>{body}</body></html>")


def list_html(items):
    return "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in items) + "</ul>" if items else ""


def days(d):
    return "?" if d is None else f"{d}d"


def rules_legend(trace, heading="Rules applied in this run"):
    """Every rule that fired, with its department, title and how often."""
    if trace is None:
        return ""
    rows = [[rule_tags([i]), RULES[i].department, RULES[i].title, trace.count(i)] for i in trace.all_ids()]
    return f"<h2>{escape(heading)}</h2>" + table(["Rule", "Department", "What it says", "Times applied"], rows)


# --- booking ---------------------------------------------------------------------------------
def booking_section(r, level=1):
    """Everything about the ocean freight: options, carriers, AI reading, rejections, left out."""
    out = []
    if r.recommendation:
        out.append(f"<div class='rec'><b>Recommendation: {escape(r.recommendation.option.carrier)}</b>"
                   f"{list_html(r.recommendation.reasons)}</div>")
    else:
        out.append("<div class='rec'><b>No option found.</b> Try the manual price path.</div>")

    out.append(f"<h{level + 1}>Options, cheapest first</h{level + 1}>")
    rows = []
    for i, o in enumerate(r.ranked, 1):
        charges = ", ".join(f"{k} {c.usd:g} ({c.source})" for k, c in o.local_charges.items())
        ft = f"POL {days(o.freetime['pol_days'])} / POD {days(o.freetime['pod_days'])}" if o.freetime else "not found"
        flags = Raw("".join(f"<div class='flag'>{escape(f)}</div>" for f in o.flags))
        rows.append([i, o.carrier, Raw(badge(o.price.source) + "<br>" + escape(o.price.detail)),
                     Raw(f"<span class='num'>{o.price.price_usd * o.qty:,.0f}</span>"),
                     Raw(f"<span title='{escape(charges)}'>{o.local_total:,.0f}</span>"),
                     Raw(f"<b>{o.total:,.0f}</b>"), o.price.valid_until or "?", ft, flags, rule_tags(o.rules)])
    out.append(table(["#", "Carrier", "Source", "Freight USD", "Local USD", "Total USD",
                      "Valid until", "Free time", "Check", "Rules applied"], rows))

    out.append(f"<h{level + 1}>What happened on each carrier</h{level + 1}>")
    rows = []
    for o in r.portal_outcomes:
        label = {"price": "price found", "no_price": "no price (final answer)",
                 "gave_up": "gave up after retries", "contract": "contract rate, portal skipped"}[o.status]
        rows.append([o.carrier, label, o.message or "", f"{o.minutes:.1f}",
                     Raw("<br>".join(escape(a) for a in o.attempts) or "no portal check")])
    out.append(table(["Carrier", "Outcome", "Detail", "Minutes", "Runs"], rows))

    out.append(f"<h{level + 1}>Price files read by the AI</h{level + 1}>" + list_html(r.ai_files))
    rejected = [[f"{row.carrier}, {row.pol} to {row.pod}, {row.container}, USD {row.price_usd:g}",
                 row.citation, why, rule_tags(["BK-09"])] for row, ok, why in r.verified if not ok]
    rejected += [[text, "-", why, rule_tags(["BK-09"])] for text, why in r.ai_problems]
    accepted = sum(1 for _, ok, _ in r.verified if ok)
    out.append(f"<p>{accepted} prices passed verification. <b class='no'>{len(rejected)} rejected:</b></p>")
    out.append(table(["Claimed", "Cited place", "Why rejected", "Rule"], rejected, "bad"))

    out.append(f"<h{level + 1}>Left out of the ranking</h{level + 1}>")
    out.append(table(["Item", "Why", "Rule"], [[f"{p.carrier} USD {p.price_usd:,.0f} ({p.source}: {p.detail})", why,
                                               rule_tags([rid])] for p, why, rid in r.dropped]))
    out.append(list_html(r.contracts_ignored))
    return "".join(out)


def render_comparison(r):
    req = r.request
    head = (f"<h1>Rate comparison: {escape(req.pol)} to {escape(req.pod)}</h1>"
            f"<div class='sub'>{escape(req.container)} | {escape(req.cargo)} cargo | prices as of {r.as_of} | "
            f"AI mode: {escape(r.mode)} | portals: first run {r.portal_minutes} simulated minutes, "
            f"{r.portal_total_minutes} until the last retry run finished</div>")
    foot = "<div class='foot'>Price check only. Nothing was booked. All data in this demo is fictional.</div>"
    return page("Rate comparison", head + booking_section(r) + rules_legend(r.trace) + foot)


def render_customer_quote(r, margin_usd):
    """Customer-facing offer for the recommended option. margin_usd is Sales' decision."""
    if not r.recommendation:
        return page("Quote", "<h1>No quote available</h1>")
    o, req = r.recommendation.option, r.request
    freight = o.price.price_usd + margin_usd
    rows = [["Ocean freight", f"{freight * req.qty:,.0f}"]] + [
        [k, f"{c.usd * (req.qty if c.unit == 'per_container' else 1):,.0f}"] for k, c in o.local_charges.items()]
    rows.append([Raw("<b>Total (USD)</b>"), Raw(f"<b>{freight * req.qty + o.local_total:,.0f}</b>")])
    ft = (f"{days(o.freetime['pol_days'])} at origin, {days(o.freetime['pod_days'])} at destination"
          if o.freetime else "to be confirmed")
    body = (f"<h1>Quotation</h1><div class='sub'>Example Freight Co. (fictional) | quote date {r.as_of}</div>"
            f"<h2>{escape(req.pol)} to {escape(req.pod)} | {req.qty} x {escape(req.container)} | {escape(req.cargo)} cargo</h2>"
            f"<p>Carrier: <b>{escape(o.carrier)}</b></p>" + table(["Item", "USD"], rows) +
            f"<p>Valid until: <b>{o.price.valid_until or 'to be confirmed'}</b><br>Free time: {escape(ft)}</p>"
            "<h3>Conditions</h3>" + list_html(customer_conditions(req) + ["Rates exclude destination charges, taxes and customs clearance."]))
    return page("Quotation", body)


# --- full lead ---------------------------------------------------------------------------------
def trucking_section(t):
    out = [f"<div class='sub'>{escape(t.pickup)} to {escape(t.port)} | {escape(t.truck)} trailer | "
           f"diesel today: {'VND {:,.0f} per litre'.format(t.diesel_today) if t.diesel_today else 'unknown'}</div>"]
    rows = []
    for i, o in enumerate(t.options, 1):
        flags = Raw("".join(f"<div class='flag'>{escape(f)}</div>" for f in o.flags))
        rows.append([i, o.haulier, Raw(badge(o.source) + "<br>" + escape(o.detail)), f"{o.quoted_vnd:,.0f}",
                     f"x {o.factor:.3f}", Raw(f"<b>{o.total_vnd:,.0f}</b>"), f"{vnd_to_usd(o.total_vnd):,.0f}",
                     o.valid_until or "?", flags, rule_tags(o.rules)])
    out.append("<h3>Options (all verified hauliers are kept)</h3>" + table(
        ["#", "Haulier", "Source", "Quoted VND", "Fuel factor", "Total VND", "Total USD", "Valid until",
         "Check", "Rules applied"], rows))
    rejected = [[f"{r.haulier}, {r.pickup} to {r.port}, {r.truck}, VND {r.price_vnd:,.0f}", r.citation, why,
                 rule_tags(["TR-02"])] for r, ok, why in t.verified if not ok]
    rejected += [[text, "-", why, rule_tags(["TR-02"])] for text, why in t.problems]
    out.append("<h3>Rejected by verification</h3>" + table(["Claimed", "Cited place", "Why", "Rule"], rejected, "bad"))
    out.append("<h3>Left out</h3>" + table(["Item", "Why", "Rule"], [[a, b, rule_tags([c])] for a, b, c in t.dropped]))
    return "".join(out)


def customs_section(c):
    out = [f"<div class='sub'>{escape(c.product)} | {escape(c.direction)} | customs value USD {c.value_usd:,.0f} | "
           f"{escape(c.source)}</div>"]
    if c.ok:
        rows = [["HS code", c.hs_code, rule_tags(["CU-01"])], ["Goods", c.description, ""],
                [f"Duty ({c.duty_pct:g}%)", f"USD {c.duty_usd:,.2f}", rule_tags(["CU-03", "CU-04"])],
                [f"VAT ({c.vat_pct:g}% on value + duty)", f"USD {c.vat_usd:,.2f}", rule_tags(["CU-03", "CU-04"])]]
        rows += [[name, f"VND {vnd:,.0f} (USD {vnd_to_usd(vnd):,.0f})", rule_tags(["CU-05"])] for name, vnd in c.fees]
        rows.append(["Legal basis", c.basis or "not verified", rule_tags(["CU-02"])])
        out.append(table(["Item", "Value", "Rules"], rows))
        out.append(list_html(["Procedure: " + p for p in c.procedures]))
    out.append("<h3>HS code candidates proposed by the AI</h3>" + table(
        ["HS code", "Goods", "Verdict", "Rule"],
        [[cand.get("hs_code"), cand.get("description"), ("accepted: " if ok else "REJECTED: ") + why, rule_tags([rid])]
         for cand, ok, why, rid in c.candidates], classes=["" if ok else "bad" for _, ok, _, _ in c.candidates]))
    if c.warnings:
        out.append("<div class='draft'><b>Warnings</b> " + rule_tags(["CU-06"]) + list_html(c.warnings) + "</div>")
    return "".join(out)


def dispatch_section(items, events, start):
    from engine.dispatch import clock
    out = [table(["Department", "Created", "Deadline", "Status", "Answered", "Answer", "Reminders"],
                 [[i.department, clock(i.created_at, start), clock(i.deadline, start), i.status,
                   clock(i.answered_at, start) if i.answered_at is not None else "-", i.answer_kind or "-",
                   ", ".join(f"{clock(m, start)} ({w})" for m, w in i.reminders) or "-"] for i in items])]
    out.append("<h3>Timeline</h3>" + table(["Clock", "Min", "Who", "What"],
                                           [[clock(e.minute, start), e.minute, e.who, e.text] for e in events]))
    return "".join(out)


def sales_section(q):
    out = [f"<div class='{'rec' if q.status == 'READY' else 'draft'}'><b>Quote status: {q.status}</b> "
           f"{rule_tags(['SS-03'])}{list_html(q.missing)}</div>"]
    rows = [[dept, getattr(opt, "carrier", None) or opt.haulier, how, rule_tags(["SS-01"])]
            for dept, (opt, how) in q.picks.items()]
    out.append("<h3>Sales Support decisions</h3>" + table(["Department", "Picked option", "How", "Rule"], rows))
    out.append(f"<p>Margin set by Sales Support: <b>USD {q.margin:g} per container</b> {rule_tags(['SS-02'])}</p>")
    out.append(f"<h3>Internal notes: never shown to the customer {rule_tags(['SS-06'])}</h3>" + list_html(q.internal_notes))
    out.append("<h3>Conditions printed on the customer quotation</h3>" + list_html(q.customer_notes))
    return "".join(out)


def render_lead_report(lead):
    req = lead.request
    head = (f"<h1>{escape(lead.code)}: lead report</h1>{rule_tags(['SS-05'])}"
            f"<div class='sub'>{escape(req.label())} | pickup {escape(lead.pickup)} | product {escape(lead.product)} | "
            f"prices as of {lead.as_of} | AI mode: {escape(lead.booking.mode)}</div>")
    body = (head + "<h2>1. Dispatch timeline</h2>" + dispatch_section(lead.items, lead.events, lead.start)
            + "<h2>2. Booking: ocean freight</h2>" + booking_section(lead.booking, 2)
            + "<h2>3. Trucking: pickup to port</h2>" + trucking_section(lead.trucking)
            + "<h2>4. Customs</h2>" + customs_section(lead.customs)
            + "<h2>5. Sales Support</h2>" + sales_section(lead.quote)
            + rules_legend(lead.trace)
            + "<div class='foot'>Price check only. Nothing was booked. All data in this demo is fictional.</div>")
    return page(f"{lead.code} lead report", body)


def render_combined_quote(lead):
    q, req = lead.quote, lead.request
    out = [f"<h1>Quotation {escape(q.lead_code)}</h1><div class='sub'>Example Freight Co. (fictional) | "
           f"quote date {lead.as_of}</div>"]
    if q.status == "DRAFT":      # the customer sees only that it is not final, never what is missing (SS-06)
        out.append("<div class='draft'><b>DRAFT.</b> Some items are still being confirmed. This quotation is not final.</div>")
    out.append(f"<h2>{escape(req.pol)} to {escape(req.pod)} | {req.qty} x {escape(req.container)} | "
               f"{escape(req.cargo)} cargo | from {escape(lead.pickup)}</h2>")
    rows = [[s, label, f"{usd:,.0f}"] for s, label, usd in q.lines]
    rows.append(["", Raw("<b>Total services (USD)</b>"), Raw(f"<b>{q.total:,.0f}</b>")])
    out.append(table(["Service", "Item", "USD"], rows))
    if q.taxes:
        out.append("<h3>Government duty and VAT (estimate, paid at cost)</h3>" + table(
            ["Item", "USD"], [[a, f"{b:,.2f}"] for a, b in q.taxes]
            + [[Raw("<b>Estimated taxes</b>"), Raw(f"<b>{q.taxes_total:,.2f}</b>")]]))
    out.append(f"<p>Valid until: <b>{q.valid_until or 'to be confirmed'}</b></p>")
    out.append("<h3>Conditions</h3>" + list_html(q.customer_notes))
    out.append("<div class='foot'>Amounts in USD. Trucking and customs fees are converted from VND at "
               f"{FX_VND_PER_USD:,} VND per USD.</div>")
    return page(f"Quotation {q.lead_code}", "".join(out))
