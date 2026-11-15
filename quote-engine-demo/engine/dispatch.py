"""Dispatch: how a new lead becomes work for the departments, and how the lead is chased.

The story, in order:
  1. A lead arrives with the services it needs (sea freight, trucking, customs).
  2. One work item is created for each department that is needed.
  3. Each item has a deadline 30 minutes after it was created.
  4. While an item is not answered, reminders go out (later ones also reach the leader).
  5. A department can ACCEPT or DECLINE (with a reason). A decline goes back to Sales Support.
  6. An answer is an answer: options from the system, or a price typed by hand.
  7. When every department has answered, Sales Support is told "enough options".

Rules in this file (written in skills/dispatch.md):
  DP-01  one work item for each department the lead needs
  DP-02  every item has a 30-minute deadline
  DP-03  reminders while an item is open; later ones escalate to the leader
  DP-04  a department can accept or decline; a decline goes back to Sales Support
  DP-05  a manual entry is a valid answer
  DP-06  when every department has answered, Sales Support is told
  DP-07  one item per department per lead, even if the lead is dispatched twice

WHY: before this existed, a salesperson messaged each department and had to remember
who had answered. A deadline, automatic reminders and one "all answered" message make
the status visible without anybody asking for it.

Time is simulated in minutes from the moment the lead arrives, so the demo is
repeatable. The reminder schedule is a made-up one.

In production, work items are rows in each department's table, reminders are chat
messages, and the deadline follows office hours.
"""
from dataclasses import dataclass, field

from engine.rulebook import hit, rule

DEADLINE_MIN = 30
REMINDER_MIN = [40, 60, 90]          # minutes after creation (made-up schedule)
ESCALATE_FROM = 2                    # the 2nd reminder onwards also goes to the leader


@dataclass
class WorkItem:
    lead: str
    department: str                  # "Booking", "Trucking" or "Customs"
    created_at: int
    deadline: int
    status: str = "open"             # open, accepted, declined, answered
    accepted_at: int = None
    answered_at: int = None
    answer_kind: str = ""            # "system" or "manual"
    decline_reason: str = ""
    reminders: list = field(default_factory=list)     # (minute, recipients)


@dataclass
class Event:
    minute: int
    who: str
    text: str


@rule("DP-01", "One work item for each department the lead needs")
def needed_departments(pickup, product):
    """Sea freight is always needed. Trucking needs a pickup place; customs needs a product."""
    departments = ["Booking"]
    if pickup:
        departments.append("Trucking")
    if product:
        departments.append("Customs")
    return departments


@rule("DP-02", "Every item has a 30-minute deadline")
def deadline_for(created_at):
    """The deadline is DEADLINE_MIN minutes after the item is created."""
    return created_at + DEADLINE_MIN


@rule("DP-07", "One item per department per lead, even if the lead is dispatched twice")
def create_items(store, lead, departments, now, trace=None):
    """Create the work items, unless this lead already has them (then return the existing ones)."""
    items = []
    for dept in departments:
        existing = store.get((lead, dept))
        if existing:
            hit(trace, "DP-07", dept, "item already exists: not created twice")
            items.append(existing)
            continue
        item = WorkItem(lead, dept, now, deadline_for(now))                # DP-02
        hit(trace, "DP-01", dept, f"work item created at minute {now}")
        hit(trace, "DP-02", dept, f"deadline at minute {item.deadline}")
        store[(lead, dept)] = item
        items.append(item)
    return items


@rule("DP-03", "Reminders while an item is open; later ones also go to the leader")
def due_reminders(item, now):
    """Reminders that are due at `now` and not yet sent. Each is (minute, recipients)."""
    if item.status == "answered":
        return []
    sent = {m for m, _ in item.reminders}
    due = []
    for n, offset in enumerate(REMINDER_MIN, 1):
        minute = item.created_at + offset
        if minute <= now and minute not in sent:
            who = "assignee" if n < ESCALATE_FROM else "assignee + leader"
            due.append((minute, who))
    return due


@rule("DP-04", "A department can accept or decline; a decline goes back to Sales Support")
def respond(item, action, now, reason="", trace=None):
    if item.status == "answered":
        raise ValueError(f"{item.department} has already answered")
    if action == "accept":
        item.status, item.accepted_at = "accepted", now
    elif action == "decline":
        item.status, item.decline_reason = "declined", reason
    else:
        raise ValueError(f"unknown action {action}")
    hit(trace, "DP-04", item.department, f"{action}ed at minute {now}" + (f": {reason}" if reason else ""))


@rule("DP-05", "A manual entry is a valid answer")
def record_answer(item, kind, now, trace=None):
    """kind is 'system' (options from the pipeline) or 'manual' (typed by hand). Both complete the item."""
    if kind not in ("system", "manual"):
        raise ValueError("answer kind must be 'system' or 'manual'")
    item.status, item.answered_at, item.answer_kind = "answered", now, kind
    hit(trace, "DP-05", item.department, f"{kind} answer at minute {now}")


@rule("DP-06", "When every department has answered, Sales Support is told")
def all_answered(items, trace=None):
    done = bool(items) and all(i.status == "answered" for i in items)
    if done:
        hit(trace, "DP-06", "lead", "every department has answered")
    return done


def clock(minute, start_hhmm="09:00"):
    """Minutes after the lead arrived -> wall clock text like '09:47'."""
    h, m = map(int, start_hhmm.split(":"))
    total = h * 60 + m + minute
    return f"{total // 60 % 24:02d}:{total % 60:02d}"


def simulate(lead, departments, responses, trace=None, start="09:00"):
    """Replay the lead's day on a simulated clock. Returns (items, events).

    `responses` says what each department does and when, for example:
        {"Booking":  [("accept", 2), ("answer", 11, "system")],
         "Customs":  [("accept", 6), ("answer", 47, "system")],
         "Trucking": [("decline", 4, "no trailer free this week"), ("answer", 33, "manual")]}
    A declined item is answered by Sales Support typing a manual price (DP-04, DP-05).
    """
    store, events = {}, []
    items = create_items(store, lead, departments, 0, trace)
    create_items(store, lead, departments, 0, trace)            # a second dispatch changes nothing (DP-07)
    for item in items:
        events.append(Event(0, f"{item.department} team", f"work item created, deadline {clock(item.deadline, start)}"))

    timeline = []
    for item in items:
        for step in responses.get(item.department, []):
            timeline.append((step[1], item, step))
    for minute, item, step in sorted(timeline, key=lambda x: x[0]):
        if step[0] == "answer":
            record_answer(item, step[2], minute, trace)
            who = "Sales Support" if step[2] == "manual" and item.decline_reason else f"{item.department} team"
            how = "typed a manual price" if step[2] == "manual" else "options ready"
            events.append(Event(minute, who, f"{item.department} {how}"))
        else:
            respond(item, step[0], minute, step[2] if len(step) > 2 else "", trace)
            text = "accepted the work item" if step[0] == "accept" else f"DECLINED: {step[2]} -> back to Sales Support"
            events.append(Event(minute, f"{item.department} team", text))

    last = max([i.answered_at for i in items if i.answered_at is not None], default=0)
    for item in items:
        end = item.answered_at if item.answered_at is not None else last + 100
        if item.answered_at is None or item.answered_at > item.deadline:
            events.append(Event(item.deadline, "system", f"{item.department}: 30-minute deadline passed, still open"))
        for minute, who in due_reminders(WorkItem(item.lead, item.department, item.created_at, item.deadline, "open"), end):
            if minute < end:
                item.reminders.append((minute, who))
                hit(trace, "DP-03", item.department, f"reminder at minute {minute} to {who}")
                events.append(Event(minute, "system", f"reminder to {item.department} {who}"))
    if all_answered(items, trace):
        events.append(Event(last, "system", "every department has answered: Sales Support is told 'enough options'"))
    events.sort(key=lambda e: e.minute)                       # stable: same-minute events keep their order
    return items, events
