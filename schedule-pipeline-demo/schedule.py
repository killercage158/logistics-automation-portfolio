"""Sailing schedule pipeline demo: command line and one whole crawl day in one readable function.

START READING HERE. run_day() follows one crawl day through every module:

    1. crawl.py        fetch 5 carriers in parallel, politely; record every route's result
    2. normalise.py    ports, vessel/voyage, dates, cut-offs -> clean voyages (or rejections)
    3. dedupe.py       one row per voyage key inside the crawl, keep the freshest
    4. store.py        SQLite: update in place, detect ETD changes
    5. store.py        retire voyages the carrier stopped listing (never delete, never touch bookings)
    6. health.py       per carrier and per route, against yesterday; ignores "success=true"
    7. export_xlsx.py  daily Excel for the charcoal segment
       report.py       HTML health report with the rule trace

Examples:
    python schedule.py --day 1          # fresh database, baseline crawl
    python schedule.py --day 2          # second crawl on top of day 1 (runs day 1 first if needed)
    python schedule.py --day 2 --slow   # short real sleeps so you can watch the pacing

In production, a scheduled task triggers the crawl twice a day on an office PC,
carriers run in parallel inside one service, the schedule is kept in a cloud
database, and the Excel goes to the booking team at noon. Here the same steps
run as one function call against recorded carrier responses.
"""
import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from engine import health as health_check
from engine import store
from engine.carriers import CARRIERS
from engine.crawl import crawl_all
from engine.dedupe import dedupe
from engine.export_xlsx import SEGMENTS, write_workbook
from engine.normalise import normalise_all
from engine.report import render
from engine.rules import RuleTrace
from engine.runlog import RunLog

HERE = Path(__file__).parent
DAYS = {1: date(2026, 11, 16), 2: date(2026, 11, 17)}     # fixed so every run gives the same result
SEGMENT = "charcoal"


@dataclass
class DayResult:
    """Everything the report and the tests need to know about one crawl day."""
    day: int
    crawl_date: date
    previous_date: object
    carrier_results: list
    rejected: list
    duplicates: list
    upsert: object
    retire: object
    health: object
    export: object
    trace: RuleTrace
    active_count: int
    job_success: bool


def run_day(day, conn, fixtures_dir, out_dir, log=None, real_factor=0.0, carriers=CARRIERS):
    """Run one crawl day end to end. Returns a DayResult. Writes the Excel and HTML into out_dir."""
    log = log or RunLog()
    trace = RuleTrace()
    crawl_date = DAYS[day]
    day_dir = Path(fixtures_dir) / f"day{day}"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. crawl ------------------------------------------------------------------------------
    log.add(f"[1/7] CRAWL {len(carriers)} carriers in parallel  | crawl day {day}: {crawl_date:%a %d %b %Y}")
    log.add("      (each carrier: routes one after another with a minimum gap; each carrier in its own error box)")
    results = crawl_all(carriers, day_dir, crawl_date, trace, real_factor)
    for res in results:                          # printed in a fixed order, although they ran in parallel
        log.extend(res.log)
    job_success = True                           # what a scheduler sees: nothing crashed the job itself
    crashed = sum(1 for r in results if r.crashed)
    failed_routes = sum(len(r.errors) for r in results)
    log.add(f"  job result: success=true  ({len(results)} carriers finished, {crashed} crashed, "
            f"{failed_routes} route error(s) inside the carrier results) [SC-16]")
    raw_rows = [row for r in results for row in r.raw_rows]

    # --- 2. normalise --------------------------------------------------------------------------
    log.add("[2/7] NORMALISE ports, vessel/voyage, dates and cut-offs")
    voyages, rejected = normalise_all(raw_rows, crawl_date, trace)
    log.add(f"  {len(raw_rows)} raw rows -> {len(voyages)} clean voyages, {len(rejected)} rejected")
    for raw, why in rejected:
        log.add(f"    REJECTED {raw.carrier}, {raw.source}: {why}")
    log.add(f"  port spellings mapped to UN/LOCODEs: {trace.count('SC-05')} [SC-05], e.g. "
            + "; ".join(trace.examples("SC-05", 3)))
    log.add(f"  vessel/voyage cleaned: {trace.count('SC-06')} [SC-06], e.g. " + "; ".join(trace.examples("SC-06", 2)))
    log.add(f"  rows with cut-offs kept in their own fields: {trace.count('SC-08')} [SC-08]")

    # --- 3. de-duplicate -----------------------------------------------------------------------
    log.add("[3/7] DE-DUPLICATE by voyage key (carrier + vessel + voyage + POL + POD, no dates) [SC-09]")
    voyages, duplicates = dedupe(voyages, trace)
    log.add(f"  {len(duplicates)} duplicate(s) dropped, {len(voyages)} unique voyages")
    for kept, other in duplicates:
        log.add(f"    {kept.key}: kept {kept.source} (latest in the crawl, ETD {kept.etd}), "
                f"dropped {other.source} (ETD {other.etd}) [SC-10]")

    # --- 4. store + ETD changes ----------------------------------------------------------------
    log.add("[4/7] STORE in SQLite: update in place, detect ETD changes")
    up = store.upsert(conn, voyages, crawl_date, trace)
    log.add(f"  new {len(up.new)}, updated {len(up.updated)}, unchanged {len(up.unchanged)}, "
            f"revived {len(up.revived)}, skipped as older {len(up.skipped_older)} [SC-11]")
    for key, old, new, delta, refs in up.etd_changes:
        log.add(f"    ETD CHANGE {key}: {old} -> {new} ({delta:+d} d)"
                + (f"  BOOKING {', '.join(refs)} AFFECTED: tell the customer" if refs else "") + " [SC-12]")

    # --- 5. retire -----------------------------------------------------------------------------
    log.add("[5/7] RETIRE voyages the carrier no longer lists (mark inactive, never delete)")
    ret = store.retire(conn, results, {v.key for v in voyages}, crawl_date, trace)
    for key, etd, route in ret.retired:
        log.add(f"    retired   {key} (ETD {etd}) [SC-13]")
    for key, etd, route, refs in ret.protected:
        log.add(f"    KEPT      {key} (ETD {etd}): not listed today, but booking {', '.join(refs)} points "
                f"at it -> flagged for the booking team [SC-14]")
    for carrier, route, why in ret.held:
        log.add(f"    held      {carrier} {route}: {why} -> nothing retired there [SC-13]")
    if not (ret.retired or ret.protected or ret.held):
        log.add("    nothing to retire")

    # --- 6. health check -----------------------------------------------------------------------
    log.add("[6/7] HEALTH CHECK per carrier and route, against the previous crawl (ignores success=true)")
    previous = store.previous_crawl_date(conn, crawl_date)
    configured = {c.name: [r.id for r in c.routes] for c in carriers}
    report = health_check.check(results, configured, store.route_counts(conn, previous), job_success, trace)
    store.save_crawl(conn, crawl_date, job_success, len(raw_rows), results)
    for c in report.carriers:
        log.add(f"  {c.carrier:<19} {c.status:<8} {c.routes_ok}/{c.routes_total} routes OK, "
                f"{c.rows_today:>3} rows (previous crawl: {c.rows_yesterday if previous else '-'})")
    for p in report.problems:
        log.add(f"    {p.flag:<7} {p.carrier} {p.route}: {p.detail} [{p.rule}]")
    verdict = ("healthy" if report.healthy else f"{len(report.problems)} problem(s) found")
    log.add(f"  VERDICT: job said success=true; health check: {verdict}")

    # --- 7. export + report --------------------------------------------------------------------
    log.add(f"[7/7] EXPORT {SEGMENTS[SEGMENT].name.lower()} schedule (Excel) and health report (HTML)")
    xlsx = out_dir / f"{SEGMENT}_schedule_{crawl_date.isoformat()}.xlsx"
    export = write_workbook(conn, SEGMENTS[SEGMENT], crawl_date, xlsx, report, trace)
    log.add(f"  {xlsx.name}: {export.sailings} sailings | "
            + ", ".join(f"{t}: {n}" for t, n in export.per_tab.items()))
    for why, n in sorted(export.excluded.items()):
        log.add(f"    left out {n:>2}: {why} [SC-19]")
    for carrier, last in export.stale.items():
        log.add(f"    STALE: {carrier} (latest data {last}) kept in the file and marked [SC-19]")
    active = conn.execute("SELECT COUNT(*) FROM voyages WHERE is_active = 1").fetchone()[0]
    result = DayResult(day, crawl_date, previous, results, rejected, duplicates, up, ret, report, export,
                       trace, active, job_success)
    html = out_dir / f"health_day{day}.html"
    html.write_text(render(result), encoding="utf-8")
    log.add(f"  {html.name}: health report with the rule trace")
    return result


def main():
    ap = argparse.ArgumentParser(description="Sailing schedule pipeline demo (fictional carriers).")
    ap.add_argument("--day", type=int, choices=sorted(DAYS), default=2, help="crawl day to run (default 2)")
    ap.add_argument("--slow", action="store_true", help="sleep a little per simulated second")
    ap.add_argument("--fixtures", default=str(HERE / "fixtures"))
    ap.add_argument("--out", default=str(HERE / "output"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    db_path = out / "schedule.db"
    if db_path.exists():
        db_path.unlink()                         # every run replays from an empty database: same result every time
    conn = store.connect(db_path)
    store.load_bookings(conn, HERE / "data" / "bookings.csv")
    real_factor = 0.02 if args.slow else 0.0

    for day in range(1, args.day):               # earlier days first, quietly, so "yesterday" exists
        print(f"(replaying crawl day {day} quietly first, so day {args.day} has a previous crawl to compare with)\n")
        run_day(day, conn, args.fixtures, out, RunLog(echo=False), real_factor)
    run_day(args.day, conn, args.fixtures, out, RunLog(), real_factor)
    conn.close()
    print(f"\nDatabase: {db_path}\nOpen {out / f'health_day{args.day}.html'} in a browser.")


if __name__ == "__main__":
    main()
