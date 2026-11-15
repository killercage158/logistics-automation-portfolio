"""Step 3: one row per voyage key inside a single crawl (rule SC-10).

The same voyage can show up twice in one crawl:
  - a page lists a month-end sailing under "November" AND again under "December";
  - a month-based search returns it in both month files, and the carrier changed
    the date between the two calls.

We keep the row that was fetched LAST, because it is the freshest answer the
carrier gave, and we log the one we dropped, so nothing disappears unseen.

WHY the key has no dates (SC-09, see models.voyage_key): if the departure date
were part of the key, every date change by the carrier would look like a new
voyage, and the old one would stay as a duplicate.
"""


def dedupe(voyages, trace=None):
    """Return (unique voyages, dropped) where dropped is a list of (kept, dropped) pairs."""
    best, dropped = {}, []
    for v in voyages:
        current = best.get(v.key)
        if current is None:
            best[v.key] = v
            continue
        kept, other = (v, current) if v.seen_at >= current.seen_at else (current, v)
        best[v.key] = kept
        dropped.append((kept, other))
        if trace is not None:
            trace.hit("SC-10", f"{v.key}: kept {kept.source} (ETD {kept.etd}), dropped {other.source} "
                               f"(ETD {other.etd})")
    return list(best.values()), dropped
