"""Marketing content pipeline demo: command line and one whole working day in one readable function.

START READING HERE. run_day() runs the loop every 30 simulated minutes from 06:00 to 23:30.
Each cycle does what the real loop does, in the same order:

    collect.py      06:00 and 14:00: social posts, videos, news feeds -> new ideas (+ ledger)
    decisions.py    editors' Gate 1 / Gate 2 decisions that are due (from decisions/*.csv)
    -- Gate 2 first, so publishing never waits behind AI writing --
    redo.py         drafts the editor sent back: rewrite from the saved source
    publish.py      approved posts whose time has come: Facebook, Instagram mirror, hidden article
    -- then Gate 1 --
    relevance.py    AI relevance filter on new ideas, with reasons
    writer.py       approved ideas -> drafts (thin-source rule, facts by code, voice check, cards)
    board.py        at the end: the HTML board of every idea, post and publish attempt

Examples:
    python marketing.py run              # recorded AI answers, no key needed
    python marketing.py run --live       # real AI (see .env.example); platforms are always simulated
    python marketing.py rules            # list the MK-xx rules

In production one Python process polls the team tables every minute and runs the same steps,
the editors use two dropdowns in those tables, and collectors run on their own schedules.
Here the day is simulated, so the whole flow runs in a second.
"""
import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from engine.board import render
from engine.collect import collect_all
from engine.decisions import apply_due, load_decisions
from engine.ledger import Ledger
from engine.llm import make_llm
from engine.models import State
from engine.prompts import Prompts
from engine.publish import MockPlatforms, publish_due
from engine.redo import redo_sweep
from engine.relevance import relevance_sweep
from engine.rules import RULES, RuleTrace
from engine.runlog import RunLog
from engine.writer import gate1_sweep

HERE = Path(__file__).parent
DAY = datetime(2026, 11, 16)                     # fixed so every run gives the same result
FIRST, LAST, STEP = time(6, 0), time(23, 30), timedelta(minutes=30)
COLLECT_AT = {time(6, 0): 1, time(14, 0): 2}     # collector visits: the second one sees the same posts again


@dataclass
class DayResult:
    day: datetime
    state: State
    trace: RuleTrace
    mode: str
    llm: object


def run_day(fixtures_dir, decisions_dir, llm, log=None, prompts=None, day=DAY):
    """Run one simulated working day. Returns a DayResult (nothing is written to disk here)."""
    log = log or RunLog()
    prompts = prompts or Prompts()
    trace = RuleTrace()
    state = State(ledger=Ledger())
    platforms = MockPlatforms(fixtures_dir, state)
    decisions = load_decisions(decisions_dir, day)
    log.add(f"Content pipeline, {day:%a %d %b %Y}, AI: {llm.name}. A cycle runs every 30 minutes; "
            f"only cycles that did something are shown.")
    now = day.replace(hour=FIRST.hour, minute=FIRST.minute)
    end = day.replace(hour=LAST.hour, minute=LAST.minute)
    while now <= end:
        lines = []
        if now.time() in COLLECT_AT:
            collect_all(Path(fixtures_dir) / "sources", COLLECT_AT[now.time()], state, now, trace, lines)
        apply_due(decisions, state, now, lines, trace)
        redo_sweep(state, llm, prompts, now, lines, trace)                       # Gate 2 side first
        publish_due(state, platforms, llm, prompts, now, lines, trace)
        relevance_sweep(state, llm, prompts, now, lines, trace)                  # then Gate 1 side
        gate1_sweep(state, llm, prompts, now, lines, trace)
        if lines:
            log.add(f"\n{now:%H:%M}")
            log.extend(lines)
        now += STEP

    ideas = state.ideas.values()
    posts = state.posts.values()
    log.add("\nEND OF DAY")
    log.add(f"  ideas: {len(ideas)} collected | " + ", ".join(
        f"{s.replace('_', ' ')} {sum(1 for i in ideas if i.status == s)}"
        for s in ("drafted", "filtered", "rejected", "needs_source", "pending") if any(i.status == s for i in ideas)))
    log.add(f"  posts: {len(posts)} drafts | " + ", ".join(
        f"{s} {sum(1 for p in posts if p.status == s)}" for s in ("published", "approved", "in_review", "rejected")
        if any(p.status == s for p in posts)))
    waiting = [f"{p.id} {c}" for p in posts for c, st in p.channel_state.items() if st["status"] == "waiting"]
    if waiting:
        log.add(f"  waiting: {', '.join(waiting)} (messaging quota {state.oa_used}/{state.oa_quota} this month) [MK-17]")
    return DayResult(day, state, trace, llm.name, llm)


def save_outputs(result, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "board.html").write_text(render(result), encoding="utf-8")
    result.state.ledger.save(out / "ledger.json")
    snapshot = {"ideas": [asdict(i) for i in result.state.ideas.values()],
                "posts": [{k: v for k, v in asdict(p).items() if k not in ("card_svg", "cover_svg")}
                          for p in result.state.posts.values()],
                "publish_log": result.state.publish_log}
    (out / "state.json").write_text(json.dumps(snapshot, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    cards = out / "cards"
    cards.mkdir(exist_ok=True)
    for p in result.state.posts.values():
        if p.card_svg:
            (cards / f"{p.id}.svg").write_text(p.card_svg, encoding="utf-8")
        (cards / f"{p.id}_cover.svg").write_text(p.cover_svg, encoding="utf-8")
    return out / "board.html"


def main():
    ap = argparse.ArgumentParser(description="Marketing content pipeline demo (fictional sources, simulated platforms).")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one simulated working day")
    run.add_argument("--live", action="store_true", help="use a real AI model (see .env.example)")
    run.add_argument("--fixtures", default=str(HERE / "fixtures"))
    run.add_argument("--decisions", default=str(HERE / "decisions"), help="folder with gate1.csv and gate2.csv")
    run.add_argument("--out", default=str(HERE / "output"))
    sub.add_parser("rules", help="list the MK-xx rules")
    args = ap.parse_args()

    if args.command == "rules":
        for rid, (name, desc) in RULES.items():
            print(f"{rid}  {name}\n       {desc}\n")
        return
    llm = make_llm(args.live, args.fixtures)
    result = run_day(args.fixtures, args.decisions, llm)
    board = save_outputs(result, args.out)
    print(f"\nWrote {board} (open it in a browser), plus ledger.json, state.json and cards/ in {Path(args.out)}")


if __name__ == "__main__":
    main()
