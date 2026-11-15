"""Step 7b: the HTML health report for one crawl day.

What a booking lead or the owner of the pipeline needs to see in one page:

  1. the verdict: what the job said ("success") next to what the health check found
  2. every carrier and every route: rows today vs yesterday, flags with rule IDs
  3. what changed: ETD changes (and the bookings they affect), retired voyages,
     booked voyages that were protected, routes where retirement was held back
  4. rows rejected while cleaning, and duplicates dropped, each with the reason
  5. the Excel export: what went in, what was left out and why, STALE carriers
  6. the rule trace: every rule ID, how often it fired today, examples

WHY HTML: it opens in any browser, can be printed, and needs no extra library.
In production, the same checks are read from the crawl status, the logs and the
database, and summarised as a table plus a short list of red flags.
"""
from html import escape

from engine.rules import RULES

STYLE = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px auto;max-width:1160px;color:#1d2433;padding:0 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px;border-bottom:2px solid #dde3ee;padding-bottom:4px}
.sub{color:#5b6475;font-size:13px} table{border-collapse:collapse;width:100%;font-size:13px}
th{background:#eef2f8;text-align:left} th,td{border:1px solid #dde3ee;padding:5px 8px;vertical-align:top}
.verdict{display:flex;gap:14px;margin-top:14px;flex-wrap:wrap}
.box{flex:1;min-width:260px;border-radius:6px;padding:10px 16px;border:1px solid}
.said{background:#eef6ff;border-color:#a9c8ec}.bad{background:#fdeeee;border-color:#e6a5a0}.good{background:#eaf7ee;border-color:#9fd3ae}
.box b{font-size:15px} .tiles{display:flex;gap:10px;margin-top:12px;flex-wrap:wrap}
.tile{flex:1;min-width:110px;background:#f6f8fb;border:1px solid #dde3ee;border-radius:6px;padding:8px 12px}
.tile .n{font-size:20px;font-weight:600} .tile .l{font-size:12px;color:#5b6475}
.flag{display:inline-block;border-radius:10px;padding:1px 8px;font-size:11px;color:#fff;font-weight:600}
.OK{background:#1c7a3b}.FAILED{background:#b3261e}.ZERO{background:#c25e00}.DROP{background:#c25e00}
.MISSING{background:#b3261e}.PARTIAL{background:#c25e00}.STALE{background:#8a6d00}
tr.prob td{background:#fff6ec} .rule{font-family:Consolas,monospace;font-size:12px;color:#3d4b66;white-space:nowrap}
.booked{color:#b3261e;font-weight:600} .num{text-align:right} .foot{margin-top:28px;color:#5b6475;font-size:12px}
details summary{cursor:pointer;color:#1f5fa8;font-size:13px}
"""


class Raw(str):
    """Text that is already safe HTML."""


def cell(v):
    return v if isinstance(v, Raw) else escape(str(v))


def table(headers, rows, classes=None):
    if not rows:
        return "<p class='sub'>None.</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = ""
    for i, r in enumerate(rows):
        cls = f" class='{classes[i]}'" if classes and classes[i] else ""
        body += f"<tr{cls}>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>"
    return f"<table><tr>{head}</tr>{body}</table>"


def flag(text):
    return Raw(f"<span class='flag {escape(text)}'>{escape(text)}</span>")


def tile(n, label):
    return f"<div class='tile'><div class='n'>{n}</div><div class='l'>{escape(label)}</div></div>"


def render(day):
    """day is a DayResult (see schedule.py)."""
    h, up, ret = day.health, day.upsert, day.retire
    problems = h.problems
    out = [f"<h1>Sailing schedule health: crawl of {day.crawl_date:%d %b %Y} (day {day.day})</h1>",
           f"<div class='sub'>{len(day.carrier_results)} carriers, {len(h.routes)} configured routes, "
           f"compared with {day.previous_date or 'no previous crawl'}. All carriers and data are fictional.</div>"]
    said = "success=true" if h.job_success else "success=false"
    verdict = (f"<div class='box bad'><b>Health check: {len(problems)} problem"
               f"{'s' if len(problems) != 1 else ''} found</b><br>"
               + "<br>".join(escape(f"{p.flag}: {p.carrier} {p.route}") for p in problems) + "</div>"
               if problems else "<div class='box good'><b>Health check: healthy</b><br>every route returned "
                                "data and no count dropped</div>")
    out.append(f"<div class='verdict'><div class='box said'><b>Job result: {said}</b><br>what the scheduler "
               f"sees. It is true whenever nothing crashed (rule SC-16).</div>{verdict}</div>")
    out.append("<div class='tiles'>" + tile(day.active_count, "active voyages stored") + tile(len(up.new), "new today")
               + tile(len(up.updated), "updated in place") + tile(len(up.etd_changes), "ETD changes")
               + tile(len(ret.retired), "retired (inactive)") + tile(len(ret.protected), "kept: booked")
               + tile(day.export.sailings if day.export else 0, "sailings in the Excel") + "</div>")

    out.append("<h2>1. Carriers</h2>")
    out.append(table(["Carrier", "Status", "Routes OK", "Rows today", "Rows yesterday", "Calls",
                      "Crawl time (simulated)", "Errors in the carrier's own result"],
                     [[c.carrier, flag(c.status), f"{c.routes_ok} / {c.routes_total}", c.rows_today, c.rows_yesterday,
                       cr.calls, f"{cr.seconds:.0f} s", Raw("<br>".join(escape(e) for e in c.errors) or "none")]
                      for c, cr in zip(h.carriers, day.carrier_results)],
                     ["prob" if c.status != "OK" else "" for c in h.carriers]))

    out.append("<h2>2. Routes, today vs yesterday</h2>")
    out.append(table(["Carrier", "Route", "Flag", "Rows today", "Yesterday", "Detail", "Rule"],
                     [[r.carrier, r.route, flag(r.flag), r.today, r.yesterday if r.yesterday >= 0 else "-",
                       r.detail, Raw(f"<span class='rule'>{r.rule}</span>")] for r in h.routes],
                     ["prob" if r.flag != "OK" else "" for r in h.routes]))

    out.append("<h2>3. What changed today</h2>")
    out.append("<p><b>ETD changes</b> <span class='rule'>SC-12</span></p>")
    out.append(table(["Voyage key", "Old ETD", "New ETD", "Moved", "Bookings affected"],
                     [[k, o, n, f"{d:+d} days", Raw(f"<span class='booked'>{escape(', '.join(refs))}: tell the "
                                                    f"customer</span>") if refs else "-"]
                      for k, o, n, d, refs in up.etd_changes]))
    out.append("<p><b>Retired</b> (carrier stopped listing them; marked inactive, nothing deleted) "
               "<span class='rule'>SC-13</span></p>")
    out.append(table(["Voyage key", "ETD", "Route"], [list(x) for x in ret.retired]))
    out.append("<p><b>Kept because a booking points at them</b> <span class='rule'>SC-14</span></p>")
    out.append(table(["Voyage key", "ETD", "Route", "Booking", "Action"],
                     [[k, e, r, Raw(f"<span class='booked'>{escape(', '.join(refs))}</span>"),
                       "carrier no longer lists it: booking team to check with the carrier"]
                      for k, e, r, refs in ret.protected]))
    out.append("<p><b>Retirement held back</b> (a failed or empty route proves nothing) "
               "<span class='rule'>SC-13</span></p>")
    out.append(table(["Carrier", "Route", "Why"], [list(x) for x in ret.held]))
    if up.revived:
        out.append("<p><b>Revived</b> <span class='rule'>SC-15</span></p>"
                   + table(["Voyage key"], [[k] for k in up.revived]))
    out.append(f"<details><summary>{len(up.new)} new voyage(s), {len(up.updated)} updated</summary>"
               + table(["New voyage key"], [[k] for k in up.new])
               + table(["Updated voyage key", "Fields changed"], [[k, ", ".join(f)] for k, f in up.updated])
               + "</details>")

    out.append("<h2>4. Cleaning: rejected rows and duplicates</h2>")
    out.append(table(["Carrier", "Source", "What the carrier wrote", "Why rejected"],
                     [[raw.carrier, raw.source, f"{raw.vessel} {raw.voyage} | ETD '{raw.etd}'".strip(), why]
                      for raw, why in day.rejected]))
    out.append(table(["Duplicate voyage key", "Kept (latest in the crawl)", "Dropped"],
                     [[kept.key, f"{kept.source} (ETD {kept.etd})", f"{other.source} (ETD {other.etd})"]
                      for kept, other in day.duplicates]))

    out.append("<h2>5. Daily Excel export</h2>")
    if day.export:
        e = day.export
        out.append(f"<p>{escape(e.path.replace(chr(92), '/').split('/')[-1])}: <b>{e.sailings}</b> sailings. "
                   + ", ".join(f"{escape(t)}: {n}" for t, n in e.per_tab.items()) + "</p>")
        out.append(table(["Left out", "Sailings"], [[why, n] for why, n in sorted(e.excluded.items())]))
        if e.stale:
            out.append(table(["STALE carrier", "Latest data"], [[flag("STALE"), f"{c}: {d}"] for c, d in e.stale.items()]))

    out.append("<h2>6. Rule trace</h2>")
    out.append(table(["Rule", "Name", "Fired today", "Examples"],
                     [[Raw(f"<span class='rule'>{rid}</span>"), Raw(f"<b>{escape(name)}</b><br>"
                                                                    f"<span class='sub'>{escape(desc)}</span>"),
                       day.trace.count(rid), Raw("<br>".join(escape(x) for x in day.trace.examples(rid)) or "-")]
                      for rid, (name, desc) in RULES.items()]))
    out.append("<div class='foot'>Generated by schedule-pipeline-demo. Carriers, vessels, bookings and dates are "
               "invented.</div>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>Schedule health</title>"
            f"<style>{STYLE}</style></head><body>{''.join(out)}</body></html>")
