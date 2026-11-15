"""The two human gates, as decision files an editor would fill in (MK-05, MK-12, MK-13, MK-14).

decisions/gate1.csv   time, idea, action, format, text
    approve      the idea may be written, in this format (news card, text card, photo album)
    reject       not this time: the idea leaves the board (its key stays in the ledger)
    edit_source  the editor replaces the source text (answers a "needs source" flag)

decisions/gate2.csv   time, post, action, channels, schedule, feedback
    approve      publish to these channels (facebook, oa, joined with +), schedule now / HH:MM / golden
    redo         rewrite with this feedback, then back to review
    reject       never publish

Each row is applied once, at the first cycle at or after its time, exactly like an editor
changing a dropdown in a table between two cycles of the loop. A decision that no longer
fits (the idea was filtered out, the post is not in review) is logged and ignored, never
forced through.

In production the editors use two dropdowns in the team tables (one on the idea row, one on
the draft row) and the loop reads them every minute.
"""
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from engine.slots import resolve_slot

FORMATS = {"news card", "text card", "photo album"}
CHANNELS = {"facebook", "oa"}


@dataclass
class Decision:
    when: datetime
    gate: int
    target: str
    action: str
    option: str = ""              # gate 1: format; gate 2: channels
    schedule: str = ""            # gate 2 only
    text: str = ""                # gate 1: new source text; gate 2: redo feedback
    applied: bool = False


def load_decisions(folder, day):
    out = []
    for gate, name in ((1, "gate1.csv"), (2, "gate2.csv")):
        with open(Path(folder) / name, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                hh, mm = (int(x) for x in row["time"].split(":"))
                when = day.replace(hour=hh, minute=mm)
                if gate == 1:
                    out.append(Decision(when, 1, row["idea"], row["action"], row.get("format", ""), "", row.get("text", "")))
                else:
                    out.append(Decision(when, 2, row["post"], row["action"], row.get("channels", ""),
                                        row.get("schedule", ""), row.get("feedback", "")))
    return sorted(out, key=lambda d: (d.when, d.gate))


def _gate1(d, state, now, log, trace):
    idea = state.ideas.get(d.target)
    if idea is None:
        return log.append(f"    {d.target}: no such idea -> decision ignored")
    if d.action == "edit_source":
        idea.text = d.text
        idea.note(now, f"editor replaced the source text ({len(d.text)} characters)")
        return log.append(f"    {idea.id} editor replaced the source text ({len(' '.join(d.text.split()))} characters)")
    if idea.status != "pending":
        why = {"filtered": "it was removed by the relevance filter", "new": "it has not been filtered yet"}.get(
            idea.status, f"its status is {idea.status}")
        return log.append(f"    {idea.id} {d.action}: ignored, {why}")
    if d.action == "approve":
        if d.option not in FORMATS:
            return log.append(f"    {idea.id} approve: unknown format '{d.option}' -> ignored")
        idea.status, idea.fmt, idea.reason = "approved", d.option, f"approved at Gate 1 as {d.option}"
        idea.note(now, f"approved at Gate 1 ({d.option})")
        trace.hit("MK-05", f"{idea.id}: approved as {d.option}")
        log.append(f"    {idea.id} approved as {d.option}")
    elif d.action == "reject":
        idea.status, idea.reason = "rejected", "rejected by the editor at Gate 1; its key stays in the ledger"
        idea.note(now, "rejected at Gate 1")
        trace.hit("MK-05", f"{idea.id}: rejected by the editor, key kept in the ledger")
        log.append(f"    {idea.id} rejected by the editor -> off the board, key stays in the ledger [MK-05]")


def _gate2(d, state, now, log, trace):
    post = state.posts.get(d.target)
    if post is None:
        return log.append(f"    {d.target}: no such draft -> decision ignored")
    if post.status != "in_review":
        return log.append(f"    {post.id} {d.action}: ignored, the draft is '{post.status}', not in review")
    if d.action == "reject":
        post.status = "rejected"
        post.note(now, "rejected at Gate 2")
        state.ideas[post.idea_id].reason = f"draft {post.id} rejected at Gate 2: never published"
        trace.hit("MK-12", f"{post.id}: rejected at Gate 2, never published")
        return log.append(f"    {post.id} rejected by the editor -> never published [MK-12]")
    if d.action == "redo":
        post.status, post.feedback = "redo", d.text
        post.note(now, f"redo requested: {d.text}")
        trace.hit("MK-13", f"{post.id}: redo requested")
        return log.append(f"    {post.id} redo requested: \"{d.text}\"")
    channels = [c for c in d.option.split("+") if c in CHANNELS]
    if not channels:
        return log.append(f"    {post.id} approve: no known channel in '{d.option}' -> ignored")
    post.slot, how = resolve_slot(d.schedule or "now", now, state.taken_slots)
    if d.schedule == "golden":
        state.taken_slots.add(post.slot)
        trace.hit("MK-14", f"{post.id}: golden hour -> {post.slot:%H:%M}")
    post.status, post.channels, post.schedule = "approved", channels, d.schedule or "now"
    post.channel_state = {c: {"status": "pending", "link": "", "detail": ""} for c in channels}
    post.note(now, f"approved at Gate 2: {' + '.join(channels)}, {how}")
    state.ideas[post.idea_id].reason = f"draft {post.id} approved: {' + '.join(channels)}, {how}"
    trace.hit("MK-12", f"{post.id}: approved by the editor")
    log.append(f"    {post.id} approved: {' + '.join(channels)}, {how}"
               + (" [MK-14]" if d.schedule == "golden" else ""))


def apply_due(decisions, state, now, log, trace):
    due = [d for d in decisions if not d.applied and d.when <= now]
    for gate in (1, 2):
        rows = [d for d in due if d.gate == gate]
        if rows:
            log.append(f"  GATE {gate} decisions by the editor ({len(rows)})")
        for d in rows:
            d.applied = True
            (_gate1 if gate == 1 else _gate2)(d, state, now, log, trace)
    return len(due)
