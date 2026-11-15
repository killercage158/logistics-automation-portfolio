"""Free time: how many days a container may stay at the origin port (POL) and the
destination port (POD) before demurrage / detention fees start.

Rules in this file (written in skills/free-time.md):
  FT-01  free time comes ONLY from the carrier's published guide
  FT-02  a port- or cargo-specific row in the guide beats the carrier's default row
  FT-03  a carrier missing from the guide is flagged, never guessed, never dropped

WHY only the guide: staff check free time against the carrier's guide. A number
from another source (even a live carrier quote) would look "wrong" to them, even
if it were correct. For prices, live data comes first; for free time, the guide does.

In production, each carrier has its own guide and the guide is read by an AI that
cites the page and the exact sentence. Simplified here: one CSV table.
"""
from engine.rulebook import hit, rule


@rule("FT-02", "Exceptions beat defaults: the most specific guide row wins")
def pick_guide_row(rows, carrier, place, port, cargo):
    """Best matching guide row for one place (POL or POD): most specific wins."""
    best, best_score = None, -1
    for r in rows:
        if r["carrier"] != carrier or r["place"] != place:
            continue
        if r["port"] not in ("", port) or r["cargo"] not in ("", cargo):
            continue                                         # an exception for another port / cargo
        score = (2 if r["port"] else 0) + (1 if r["cargo"] else 0)
        if score > best_score:
            best, best_score = r, score
    return best


@rule("FT-01", "Free time comes only from the carrier's guide")
def free_time(carrier, req, rows, trace=None):
    """Return {"pol_days", "pod_days", "guide", "notes"} or None when the guide has nothing.

    A day count is None when the guide covers only the other end.
    """
    pol = pick_guide_row(rows, carrier, "POL", req.pol, req.cargo)
    pod = pick_guide_row(rows, carrier, "POD", req.pod, req.cargo)
    if pol is None and pod is None:
        return None
    notes = []
    for label, row in (("POL", pol), ("POD", pod)):
        if row is not None and (row["port"] or row["cargo"]):           # FT-02: an exception row won
            what = " ".join(x for x in (row["port"], row["cargo"]) if x)
            notes.append(f"{label}: exception for {what}")
            hit(trace, "FT-02", carrier, f"{label} uses the guide's exception row for {what}")
    hit(trace, "FT-01", carrier, "taken from " + (pol or pod)["guide"])
    return {"pol_days": int(pol["free_days"]) if pol else None,
            "pod_days": int(pod["free_days"]) if pod else None,
            "guide": (pol or pod)["guide"], "notes": notes}


@rule("FT-03", "A carrier missing from the guide is flagged: ask the carrier")
def missing_free_time_flag(carrier, ft, trace=None):
    """Return a flag text when free time is unknown (fully or for one end), else None."""
    if ft is None:
        hit(trace, "FT-03", carrier, "not in the guide")
        return "free time not found in the guides - ask the carrier"
    gaps = [n for n, d in (("POL", ft["pol_days"]), ("POD", ft["pod_days"])) if d is None]
    if gaps:
        hit(trace, "FT-03", carrier, "guide has no " + "/".join(gaps))
        return f"free time at {'/'.join(gaps)} not in the guide - ask the carrier"
    return None
