"""Rule MK-14: when an approved post goes out.

Three choices for the editor:
  now      at the next cycle
  HH:MM    a fixed time today (if it has already passed, at the next cycle)
  golden   the nearest free "golden hour" slot: 07:00, 12:00, 18:00 or 21:00, when the audience
           is most active. One post per slot. If every slot left today is taken or past,
           the post goes to 07:00 tomorrow.

The chosen time is written back on the post so the editor sees it on the board.

In production the slot is written into the post's time field in the team table, so the
team sees which hour was picked.
"""
from datetime import timedelta

GOLDEN_HOURS = [7, 12, 18, 21]


def next_golden_slot(now, taken):
    """Nearest golden-hour slot after now that is not in taken (a set of datetimes)."""
    for hour in GOLDEN_HOURS:
        slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if slot > now and slot not in taken:
            return slot
    tomorrow = (now + timedelta(days=1)).replace(hour=GOLDEN_HOURS[0], minute=0, second=0, microsecond=0)
    while tomorrow in taken:                       # extremely busy day: try the next slots tomorrow
        later = [h for h in GOLDEN_HOURS if h > tomorrow.hour]
        tomorrow = tomorrow.replace(hour=later[0]) if later else (tomorrow + timedelta(days=1)).replace(hour=GOLDEN_HOURS[0])
    return tomorrow


def resolve_slot(schedule, now, taken):
    """Return (slot datetime, description) for a schedule choice."""
    if schedule == "now":
        return now, "now"
    if schedule == "golden":
        slot = next_golden_slot(now, taken)
        return slot, f"golden hour {slot:%H:%M}" + ("" if slot.date() == now.date() else " tomorrow")
    hh, mm = (int(x) for x in schedule.split(":"))
    slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return max(slot, now), f"fixed time {slot:%H:%M}"


def is_due(slot, now):
    return slot is not None and slot <= now

