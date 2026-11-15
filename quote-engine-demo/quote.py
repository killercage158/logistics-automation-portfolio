"""Freight quote engine demo: command line and the whole pipeline in one readable function.

START READING HERE. run_quote() follows ONE request through every module:

    1. request.py      clean up what staff typed (ports, container, cargo)
    2. contracts.py    contract rates first; carriers with a contract skip the portal
    3. portals.py      carrier portals one after another, time budgets, retries
    4. ai_reader.py    (at the same time) AI reads the price spreadsheets
       verify.py       code re-opens every cited cell: accept or reject, with reason
    5. rules.py        expired prices, cargo, one price per carrier, local charges, free time
       manual.py       staff-typed prices join here
    6. rank.py         cheapest all-in total + reasons
    7. report.py       comparison.html (internal) and customer_quote.html

Full lead (sea freight + trucking + customs + dispatch timeline + combined quote):
    python quote.py lead --pol "Hai Phong" --pod Busan --container 40HC --cargo charcoal \\
                         --pickup "Bac Ninh" --product "wood charcoal"

Examples:
    python quote.py --pol "Hai Phong" --pod Singapore --container 40HC --cargo general
    python quote.py --pol "Ho Chi Minh" --pod Busan --container 40HC --cargo charcoal
    python quote.py --pol "Hai Phong" --pod Singapore --container 40HC --cargo general --manual data/sample/manual_prices_example.csv
    python quote.py ... --live          # real AI (see .env.example); portals are always fake

In production, a small service on an office PC is the "foreman". It receives the
tick from the staff table, queues the job, runs the carrier checks and the AI
reader, and writes the options back. Here the same job runs as one function call.
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from engine.ai_reader import read_price_file
from engine.contracts import carriers_for_portal, find_contracts, load_contracts
from engine.llm import make_llm
from engine.manual import load_manual
from engine.models import Price, RunResult
from engine.portals import PORTAL_ORDER, PortalOutcome, make_portals, run_portals
from engine.rank import rank_options, recommend
from engine.lead import run_lead
from engine.report import (render_combined_quote, render_comparison, render_customer_quote,
                           render_lead_report)
from engine.request import build_request
from engine.rulebook import RuleTrace
from engine.rules import (build_option, canonical_carrier, choose_per_carrier, filter_cargo,
                          filter_validity, flag_doubtful, load_csv)
from engine.runlog import RunLog
from engine.verify import verify_all

HERE = Path(__file__).parent
DEMO_DATE = "2026-11-16"      # fixed on purpose so the demo gives the same answer every day


def read_and_verify(llm, price_dir, log, trace=None):
    """Step 4: AI reads every price file, then code verifies every answer.

    Runs in its own thread so it overlaps with the portal step, as in the real system.
    Returns (file_lines, rows, verified, problems).
    """
    file_lines, rows, problems = [], [], []
    for path in sorted(Path(price_dir).glob("*.xlsx")):
        got, bad = read_price_file(llm, path, log)
        rows += got
        problems += bad
        file_lines.append(f"{path.name}: {len(got)} readable items, {len(bad)} unreadable")
    verified = verify_all(rows, price_dir, trace)
    accepted = sum(1 for _, ok, _ in verified if ok)
    log.add(f"  verification: {accepted} accepted, {len(verified) - accepted + len(problems)} rejected")
    for row, ok, why in verified:
        if not ok:
            log.add(f"    REJECTED {row.carrier} {row.pol}->{row.pod} {row.container} USD {row.price_usd:g} "
                    f"[{row.citation}]\n             why: {why}")
    for text, why in problems:
        log.add(f"    REJECTED {text}\n             why: {why}")
    return file_lines, verified, problems


def run_quote(req, as_of, data_dir, llm, manual_path=None, log=None, sleep=lambda minutes: None, trace=None):
    """Run the whole pipeline for one request. Returns a RunResult (nothing is printed except the log)."""
    log = log or RunLog()
    trace = trace if trace is not None else RuleTrace()
    data_dir = Path(data_dir)

    log.add(f"[1/6] REQUEST  {req.label()}  | prices as of {as_of}")

    # --- step 2: contracts first --------------------------------------------------------
    log.add("[2/6] CONTRACT CHECK")
    contracts, ignored = find_contracts(load_contracts(data_dir / "contracts.csv"), req, as_of, trace)
    for c, p in contracts.items():
        log.add(f"  {c}: contract USD {p.price_usd:,.0f} ({p.detail}) -> portal check skipped")
    for line in ignored:
        log.add("  " + line)
    if not contracts and not ignored:
        log.add("  no contract rates for this lane")
    to_check = carriers_for_portal(PORTAL_ORDER, contracts)

    # --- steps 3 and 4 at the same time ---------------------------------------------------
    ai_log = RunLog(echo=False)                   # collected quietly, printed after the portal log
    with ThreadPoolExecutor(max_workers=1) as pool:
        ai_job = pool.submit(read_and_verify, llm, data_dir / "price_files", ai_log, trace)
        log.add(f"[3/6] PORTALS, one after another inside a shared run budget "
                f"(budget = 2 + 8.5 x carriers in the run, max 30 min)")
        portal_results, first_pass, total = run_portals(req, to_check, make_portals(), log, as_of, sleep, trace)
        log.add(f"  first run took {first_pass} simulated minutes; "
                f"last retry run finished at {total} minutes")
        file_lines, verified, problems = ai_job.result()
    log.add(f"[4/6] AI READS PRICE FILES (ran at the same time as the portals; {llm.name})")
    ai_log.dump()

    # --- step 5: rules --------------------------------------------------------------------
    log.add("[5/6] RULES")
    outcomes = {o.carrier: o for o in portal_results}
    for c, p in contracts.items():
        outcomes[c] = PortalOutcome(c, "contract", p, p.detail)
    outcomes = [outcomes[c] for c in PORTAL_ORDER]

    prices = list(contracts.values())
    if manual_path:
        manual = load_manual(manual_path, req, trace)
        prices += manual
        log.add(f"  manual entries used: {len(manual)}")
    prices += [o.price for o in portal_results if o.status == "price"]
    on_lane = 0
    for row, ok, _ in verified:
        if ok and (row.pol, row.pod, row.container) == (req.pol, req.pod, req.container):
            on_lane += 1
            prices.append(Price(canonical_carrier(row.carrier, PORTAL_ORDER), row.price_usd,
                                row.valid_until, "price file", row.citation, row.cargo))
    log.add(f"  verified price-file items on this lane: {on_lane}")

    prices, dropped = filter_validity(prices, as_of, trace)
    prices, wrong_cargo = filter_cargo(prices, req.cargo, trace)
    chosen, superseded = choose_per_carrier(prices, trace)
    dropped += wrong_cargo + superseded
    for p, why, rid in dropped:
        log.add(f"  left out [{rid}]: {p.carrier} USD {p.price_usd:,.0f} ({p.source}) - {why}")

    general = load_csv(data_dir / "local_charges_general.csv")
    specific = load_csv(data_dir / "local_charges_carrier.csv")
    free = load_csv(data_dir / "freetime.csv")
    options = [build_option(p, req, general, specific, free, as_of, trace) for p in chosen.values()]
    flag_doubtful(options, as_of, trace)
    for o in options:
        o.rules = trace.ids_for(o.carrier)

    # --- step 6: rank -----------------------------------------------------------------------
    log.add("[6/6] RANKING (all-in total = freight + local charges)")
    ranked = rank_options(options)
    for i, o in enumerate(ranked, 1):
        log.add(f"  {i}. {o.carrier:<19} {o.price.source:<10} freight {o.price.price_usd:>6,.0f} "
                f"+ local {o.local_total:>4,.0f} = {o.total:>6,.0f}   rules: {', '.join(o.rules)}")
    rec = recommend(ranked)
    if rec:
        log.add(f"  RECOMMENDED: {rec.option.carrier}")
        for reason in rec.reasons:
            log.add(f"    - {reason}")
    else:
        log.add("  No options. Use --manual to enter a price by hand.")

    return RunResult(req, as_of, ranked, rec, outcomes, contracts, ignored, file_lines,
                     verified, problems, dropped, first_pass, total, llm.name, trace)


def main():
    ap = argparse.ArgumentParser(description="Freight quote engine demo (fake data).")
    ap.add_argument("--pol", required=True)
    ap.add_argument("--pod", required=True)
    ap.add_argument("--container", required=True, help="20GP, 40GP or 40HC (aliases like 40hq work)")
    ap.add_argument("--cargo", required=True, help="general or charcoal")
    ap.add_argument("--live", action="store_true", help="use a real AI model (see .env.example)")
    ap.add_argument("--manual", help="CSV of prices typed by staff")
    ap.add_argument("--today", default=DEMO_DATE, help="pricing date, YYYY-MM-DD (default: fixed demo date)")
    ap.add_argument("--margin", type=float, default=100, help="Sales margin on the customer quote, USD")
    ap.add_argument("--slow", action="store_true", help="sleep a little per simulated minute")
    ap.add_argument("--data", default=str(HERE / "data" / "sample"))
    ap.add_argument("--out", default=str(HERE / "output"))
    args = ap.parse_args()

    try:
        req = build_request(args.pol, args.pod, args.container, args.cargo)
    except ValueError as e:
        raise SystemExit(f"Cannot read the request: {e}")
    if not (Path(args.data) / "contracts.csv").exists():
        raise SystemExit("No sample data found. Run: python data/make_sample_data.py")

    llm = make_llm(args.live, HERE / "fixtures")
    sleep = (lambda m: time.sleep(m * 0.05)) if args.slow else (lambda m: None)
    result = run_quote(req, date.fromisoformat(args.today), args.data, llm, args.manual, sleep=sleep)

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "comparison.html").write_text(render_comparison(result), encoding="utf-8")
    (out / "customer_quote.html").write_text(render_customer_quote(result, args.margin), encoding="utf-8")
    print(f"\nWrote {out / 'comparison.html'}\nWrote {out / 'customer_quote.html'}")


def main_lead():
    """`python quote.py lead ...`: the full lead with all three departments."""
    ap = argparse.ArgumentParser(prog="quote.py lead", description="Full lead: Booking + Trucking + Customs + quote.")
    ap.add_argument("--pol", required=True)
    ap.add_argument("--pod", required=True)
    ap.add_argument("--container", required=True)
    ap.add_argument("--cargo", required=True)
    ap.add_argument("--qty", type=int, default=1, help="number of containers")
    ap.add_argument("--pickup", required=True, help="place where the cargo is picked up (trucking)")
    ap.add_argument("--product", required=True, help="what is shipped, e.g. 'wood charcoal' (customs)")
    ap.add_argument("--direction", default="export", choices=["export", "import"])
    ap.add_argument("--value", type=float, default=20000, help="customs value, USD")
    ap.add_argument("--pick", action="append", default=[], metavar="DEPT=N",
                    help="Sales Support pick, e.g. --pick booking=2 --pick trucking=1")
    ap.add_argument("--margin", type=float, default=100, help="margin per container set by Sales Support, USD")
    ap.add_argument("--manual", help="CSV of booking prices typed by staff")
    ap.add_argument("--manual-trucking", help="CSV of trucking prices typed by staff")
    ap.add_argument("--hs", help="HS code typed by staff (skips the AI proposal)")
    ap.add_argument("--decline", action="append", default=[], metavar="DEPT",
                    help="simulate a department declining its work item (trucking or customs)")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--today", default=DEMO_DATE)
    ap.add_argument("--data", default=str(HERE / "data" / "sample"))
    ap.add_argument("--out", default=str(HERE / "output"))
    args = ap.parse_args(sys.argv[2:])
    try:
        req = build_request(args.pol, args.pod, args.container, args.cargo, args.qty)
        picks = {k.lower(): int(v) for k, v in (p.split("=") for p in args.pick)}
    except ValueError as e:
        raise SystemExit(f"Cannot read the request: {e}")
    if not (Path(args.data) / "contracts.csv").exists():
        raise SystemExit("No sample data found. Run: python data/make_sample_data.py")
    declines = {d.capitalize(): "cannot take this on today" for d in args.decline}

    llm = make_llm(args.live, HERE / "fixtures")
    lead = run_lead(req, args.pickup, args.product, date.fromisoformat(args.today), args.data, llm, run_quote,
                    args.direction, args.value, picks, args.margin, args.manual, args.manual_trucking, args.hs, declines)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "comparison.html").write_text(render_comparison(lead.booking), encoding="utf-8")
    (out / "lead_report.html").write_text(render_lead_report(lead), encoding="utf-8")
    (out / "combined_quote.html").write_text(render_combined_quote(lead), encoding="utf-8")
    print(f"\nWrote {out / 'lead_report.html'}\nWrote {out / 'combined_quote.html'}")


if __name__ == "__main__":
    main_lead() if sys.argv[1:2] == ["lead"] else main()
