"""Steps 4 and 5: store voyages in SQLite, detect ETD changes, retire what the carrier stopped listing.

Tables (created on first use):

  voyages        one row per voyage key (SC-09). is_active = 0 means retired, never deleted.
  bookings       booking reference -> voyage key. A booked voyage is never retired (SC-14).
  crawls         one row per crawl day, with the job's own "success" flag
  route_results  one row per carrier route per day: ok/failed, row count, error, window covered
  etd_changes    every departure-date change: old date, new date, days moved (SC-12)
  events         what happened to which voyage today (new, updated, revived, retired, protected)

  upsert()  SC-11 update in place, an older crawl never overwrites a newer one
            SC-12 ETD change detection, SC-15 revive a retired voyage that came back
  retire()  SC-13 only on routes that succeeded with rows, only inside the crawled window
            SC-14 booked voyages are skipped and flagged

WHY SQLite: one file, no server, real SQL, ships with Python. In production the
schedule lives in a cloud Postgres database, and the team's table is a view of it.
"""
import csv
import sqlite3
from dataclasses import dataclass, field
from datetime import date

SCHEMA = """
CREATE TABLE IF NOT EXISTS voyages (
    key TEXT PRIMARY KEY, carrier TEXT, vessel TEXT, voyage TEXT, pol TEXT, pod TEXT, service TEXT,
    etd TEXT, eta TEXT, transit_days INTEGER, cutoff_si TEXT, cutoff_cy TEXT, note TEXT, source TEXT,
    is_active INTEGER NOT NULL DEFAULT 1, first_seen TEXT, last_seen TEXT, retired_on TEXT);
CREATE TABLE IF NOT EXISTS bookings (booking_ref TEXT PRIMARY KEY, voyage_key TEXT, customer TEXT);
CREATE TABLE IF NOT EXISTS crawls (crawl_date TEXT PRIMARY KEY, job_success INTEGER, raw_rows INTEGER);
CREATE TABLE IF NOT EXISTS route_results (
    crawl_date TEXT, carrier TEXT, route TEXT, status TEXT, rows INTEGER, error TEXT,
    window_from TEXT, window_to TEXT, PRIMARY KEY (crawl_date, carrier, route));
CREATE TABLE IF NOT EXISTS etd_changes (crawl_date TEXT, key TEXT, old_etd TEXT, new_etd TEXT, delta_days INTEGER);
CREATE TABLE IF NOT EXISTS events (crawl_date TEXT, key TEXT, kind TEXT, detail TEXT);
"""

DATA_FIELDS = ["carrier", "vessel", "voyage", "pol", "pod", "service", "etd", "eta", "transit_days",
               "cutoff_si", "cutoff_cy", "note"]


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_bookings(conn, csv_path):
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = [(r["booking_ref"], r["voyage_key"], r["customer"]) for r in csv.DictReader(f)]
    conn.executemany("INSERT OR REPLACE INTO bookings VALUES (?, ?, ?)", rows)
    conn.commit()
    return len(rows)


def bookings_for(conn, key):
    return [r["booking_ref"] for r in conn.execute(
        "SELECT booking_ref FROM bookings WHERE voyage_key = ? ORDER BY booking_ref", (key,))]


def _record(v, crawl_date):
    return {"key": v.key, "carrier": v.carrier, "vessel": v.vessel, "voyage": v.voyage, "pol": v.pol,
            "pod": v.pod, "service": v.service, "etd": v.etd.isoformat(),
            "eta": v.eta.isoformat() if v.eta else None, "transit_days": v.transit_days,
            "cutoff_si": v.cutoff_si, "cutoff_cy": v.cutoff_cy, "note": v.note, "source": v.source,
            "last_seen": crawl_date.isoformat()}


def _event(conn, crawl_date, key, kind, detail=""):
    conn.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (crawl_date.isoformat(), key, kind, detail))


@dataclass
class UpsertResult:
    new: list = field(default_factory=list)            # keys
    updated: list = field(default_factory=list)        # (key, [changed field names])
    unchanged: list = field(default_factory=list)
    revived: list = field(default_factory=list)
    etd_changes: list = field(default_factory=list)    # (key, old, new, delta_days, [booking refs])
    skipped_older: list = field(default_factory=list)  # (key, stored last_seen)


def upsert(conn, voyages, crawl_date, trace=None):
    """Insert new voyages, update known ones in place. Returns an UpsertResult."""
    res = UpsertResult()
    today = crawl_date.isoformat()
    for v in voyages:
        rec = _record(v, crawl_date)
        old = conn.execute("SELECT * FROM voyages WHERE key = ?", (v.key,)).fetchone()
        if old is None:
            conn.execute(f"INSERT INTO voyages ({', '.join(rec)}, is_active, first_seen) "
                         f"VALUES ({', '.join('?' * len(rec))}, 1, ?)", (*rec.values(), today))
            res.new.append(v.key)
            _event(conn, crawl_date, v.key, "new", f"ETD {rec['etd']}")
            continue
        if old["last_seen"] and old["last_seen"] > today:           # SC-11: never go back in time
            res.skipped_older.append((v.key, old["last_seen"]))
            if trace:
                trace.hit("SC-11", f"{v.key}: crawl {today} is older than stored {old['last_seen']}, not applied")
            continue
        changed = [f for f in DATA_FIELDS if str(old[f]) != str(rec[f])]
        if old["etd"] != rec["etd"]:                                 # SC-12
            delta = (date.fromisoformat(rec["etd"]) - date.fromisoformat(old["etd"])).days
            refs = bookings_for(conn, v.key)
            conn.execute("INSERT INTO etd_changes VALUES (?, ?, ?, ?, ?)", (today, v.key, old["etd"], rec["etd"], delta))
            res.etd_changes.append((v.key, old["etd"], rec["etd"], delta, refs))
            _event(conn, crawl_date, v.key, "etd_change", f"{old['etd']} -> {rec['etd']} ({delta:+d} d)"
                   + (f"; booking {', '.join(refs)}" if refs else ""))
            if trace:
                trace.hit("SC-09", f"{v.key}: departure moved, key unchanged -> same row, no duplicate")
                trace.hit("SC-12", f"{v.key}: ETD {old['etd']} -> {rec['etd']} ({delta:+d} d)"
                                   + (f", booking {', '.join(refs)} affected" if refs else ""))
        if not old["is_active"]:                                     # SC-15
            res.revived.append(v.key)
            _event(conn, crawl_date, v.key, "revived", f"retired on {old['retired_on']}, listed again")
            if trace:
                trace.hit("SC-15", f"{v.key}: retired on {old['retired_on']}, listed again -> active")
        sets = ", ".join(f"{k} = ?" for k in rec if k != "key")
        conn.execute(f"UPDATE voyages SET {sets}, is_active = 1, retired_on = NULL WHERE key = ?",
                     (*[rec[k] for k in rec if k != "key"], v.key))
        if changed:
            res.updated.append((v.key, changed))
            if trace:
                trace.hit("SC-11", f"{v.key}: updated in place ({', '.join(changed)})")
        else:
            res.unchanged.append(v.key)
    conn.commit()
    return res


@dataclass
class RetireResult:
    retired: list = field(default_factory=list)       # (key, etd, route id)
    protected: list = field(default_factory=list)     # (key, etd, route id, [booking refs])
    held: list = field(default_factory=list)          # (carrier, route id, why nothing was retired there)


def retire(conn, carrier_results, seen_keys, crawl_date, trace=None):
    """Mark voyages the carrier stopped listing as inactive. Never deletes anything."""
    res = RetireResult()
    today = crawl_date.isoformat()
    for cr in carrier_results:
        for rr in cr.routes:
            if rr.status != "ok" or rr.rows == 0 or rr.window is None:
                why = "route failed" if rr.status != "ok" else "route returned zero rows"
                res.held.append((cr.carrier, rr.route.id, why))
                if trace:
                    trace.hit("SC-13", f"{cr.carrier} {rr.route.id}: {why} -> proves nothing, nothing retired")
                continue
            lo, hi = (d.isoformat() for d in rr.window)
            candidates = conn.execute(
                "SELECT key, etd FROM voyages WHERE carrier = ? AND pol = ? AND pod = ? AND is_active = 1 "
                "AND etd BETWEEN ? AND ?", (cr.carrier, rr.route.pol, rr.route.pod, lo, hi)).fetchall()
            for row in candidates:
                if row["key"] in seen_keys:
                    continue
                refs = bookings_for(conn, row["key"])
                if refs:                                              # SC-14
                    res.protected.append((row["key"], row["etd"], rr.route.id, refs))
                    _event(conn, crawl_date, row["key"], "protected",
                           f"not listed today but booked ({', '.join(refs)}): kept active")
                    if trace:
                        trace.hit("SC-14", f"{row['key']}: not listed today, booking {', '.join(refs)} -> kept")
                    continue
                conn.execute("UPDATE voyages SET is_active = 0, retired_on = ? WHERE key = ?", (today, row["key"]))
                res.retired.append((row["key"], row["etd"], rr.route.id))
                _event(conn, crawl_date, row["key"], "retired", f"not listed in {lo}..{hi}")
                if trace:
                    trace.hit("SC-13", f"{row['key']}: not listed in {lo}..{hi} -> inactive")
    conn.commit()
    return res


def save_crawl(conn, crawl_date, job_success, raw_rows, carrier_results):
    day = crawl_date.isoformat()
    conn.execute("INSERT OR REPLACE INTO crawls VALUES (?, ?, ?)", (day, int(job_success), raw_rows))
    for cr in carrier_results:
        for rr in cr.routes:
            lo, hi = (rr.window or (None, None))
            conn.execute("INSERT OR REPLACE INTO route_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (day, cr.carrier, rr.route.id, rr.status, rr.rows, rr.error,
                          lo.isoformat() if lo else None, hi.isoformat() if hi else None))
    conn.commit()


def previous_crawl_date(conn, crawl_date):
    row = conn.execute("SELECT MAX(crawl_date) AS d FROM crawls WHERE crawl_date < ?",
                       (crawl_date.isoformat(),)).fetchone()
    return date.fromisoformat(row["d"]) if row and row["d"] else None


def route_counts(conn, crawl_date):
    """{(carrier, route id): (status, rows)} for one crawl day."""
    if crawl_date is None:
        return {}
    return {(r["carrier"], r["route"]): (r["status"], r["rows"]) for r in conn.execute(
        "SELECT carrier, route, status, rows FROM route_results WHERE crawl_date = ?", (crawl_date.isoformat(),))}


def has_crawl(conn, crawl_date):
    return conn.execute("SELECT 1 FROM crawls WHERE crawl_date = ?", (crawl_date.isoformat(),)).fetchone() is not None
