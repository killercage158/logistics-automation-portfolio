"""Create the recorded carrier responses in fixtures/ and the bookings in data/bookings.csv.

Everything is invented: carriers, vessels, voyages, dates and bookings.
The files are committed, so you do not need to run this. It is here so you can
see exactly how the test data was made, and change it.

Five carriers, five shapes (see engine/carriers.py):
  bluewave_lines/<route>.json           JSON API answer per route (UN/LOCODEs, ISO date-times)
  northstar_shipping/<route>.html       HTML table per route, grouped by month, dd/mm/yyyy
  kestrel_line/<route>_<yyyymm>.csv     CSV export per route and month, YYYYMMDD, glued vessel code
  jade_ocean/<route>.json               the carrier's full list; the fake API filters it and caps it at 8
  pacific_arrow/<route>.html            HTML table per route, dates like "Nov 19" (no year)
  incidents.json                        planted HTTP trouble (timeouts, 429, 503)

PLANTED (what each rule should catch):
  Bluewave   VNHPH-KRPUS  day 2: one sailing departs 2 days later         SC-12, booking B-1001 affected
             VNHPH-JPTYO  a "TBN" vessel gets its real name on day 2       new key; old one retired (SC-13)
             VNSGN-KRPUS  day 2: a booked sailing is no longer listed      kept and flagged (SC-14, B-1002)
  Northstar  VNHPH-KRPUS  month-end sailing printed twice (both days)     SC-10
             VNHPH-KRINC  day 2: page answers OK with an empty table      ZERO (SC-17), nothing retired
             VNDAD-JPOSA  one sailing with ETD "TBA" (both days)          rejected (SC-07)
                          day 2: first call times out                     retried (SC-01)
  Kestrel    VNSGN-KRPUS  a sailing moved into December; both month files list it   SC-10 keeps the later fetch
             VNHPH-KRINC  day 2: the December file comes back empty       DROP (SC-18); 4 retired, booked one kept (B-1003)
             VNHPH-JPOSA  day 2: one sailing departs a day later          SC-12
  Jade       VNHPH-SGSIN  12 sailings in the window, API returns max 8   SC-04 splits the window (both days)
             VNSGN-JPTYO  day 2: first call answers 429                   wait and retry (SC-01); one sailing a day earlier (SC-12)
  Pacific    both routes  day 2: HTTP 503 on every attempt                FAILED (SC-03, SC-16), nothing retired,
                                                                          Excel keeps its day-1 rows marked STALE (SC-19)

Run:  python data/make_fixtures.py
"""
import csv
import io
import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
FIXTURES = HERE.parent / "fixtures"
DAY = {1: date(2026, 11, 16), 2: date(2026, 11, 17)}
HORIZON = 41
BASE_FROM, BASE_TO = date(2026, 11, 1), date(2027, 1, 15)


@dataclass(frozen=True)
class Sailing:
    route: str
    vessel: str
    voyage: str
    etd: date
    eta: date
    service: str
    code: str = ""               # vessel code (Kestrel glues it to the voyage number)


def weekly(route, weekdays, vessels, transit, service, suffix="N", codes=None):
    """Sailings on the given weekdays (0 = Monday), vessels in rotation, voyage = yy + ISO week + suffix."""
    out, i, d = [], 0, BASE_FROM
    while d <= BASE_TO:
        if d.weekday() in weekdays:
            year, week, _ = d.isocalendar()
            vessel = vessels[i % len(vessels)]
            out.append(Sailing(route, vessel, f"{year % 100:02d}{week:02d}{suffix}", d,
                               d + timedelta(days=transit), service, (codes or {}).get(vessel, "")))
            i += 1
        d += timedelta(days=1)
    return out


ROUTES = {
    "bluewave_lines": {
        "VNHPH-KRPUS": weekly("VNHPH-KRPUS", {4}, ["BLUEWAVE ARIES", "BLUEWAVE TAURUS", "BLUEWAVE ORION"], 5, "VKX"),
        "VNHPH-JPTYO": weekly("VNHPH-JPTYO", {1}, ["BLUEWAVE LEO", "BLUEWAVE VIRGO"], 7, "VJX"),
        "VNSGN-KRPUS": weekly("VNSGN-KRPUS", {2}, ["BLUEWAVE GEMINI", "BLUEWAVE CANCER", "BLUEWAVE LIBRA"], 8, "SKX"),
    },
    "northstar_shipping": {
        "VNHPH-KRPUS": weekly("VNHPH-KRPUS", {0}, ["NORTHSTAR LYRA", "NORTHSTAR VEGA"], 4, "NSX1"),
        "VNHPH-KRINC": weekly("VNHPH-KRINC", {3}, ["NORTHSTAR DENEB", "NORTHSTAR ALTAIR"], 5, "NSX2"),
        "VNDAD-JPOSA": weekly("VNDAD-JPOSA", {5}, ["NORTHSTAR RIGEL"], 6, "NSJ"),
    },
    "kestrel_line": {
        "VNHPH-KRINC": weekly("VNHPH-KRINC", {1}, ["KESTREL DAWN", "KESTREL DUSK"], 5, "KHX",
                              codes={"KESTREL DAWN": "KSDW", "KESTREL DUSK": "KSDK"}),
        "VNSGN-KRPUS": weekly("VNSGN-KRPUS", {4}, ["KESTREL MIST"], 7, "KSX", codes={"KESTREL MIST": "KSMT"}),
        "VNHPH-JPOSA": weekly("VNHPH-JPOSA", {2}, ["KESTREL GALE"], 6, "KJX", codes={"KESTREL GALE": "KSGL"}),
    },
    "jade_ocean": {
        "VNHPH-SGSIN": weekly("VNHPH-SGSIN", {0, 3}, ["JADE HARMONY", "JADE PROSPER", "JADE FORTUNE"], 4, "JSE", "S"),
        "VNSGN-JPTYO": weekly("VNSGN-JPTYO", {6}, ["JADE SERENE"], 9, "JNE"),
    },
    "pacific_arrow": {
        "VNHPH-JPTYO": weekly("VNHPH-JPTYO", {3}, ["ARROW SWIFT", "ARROW BRAVE"], 7, "PA1"),
        "VNSGN-KRINC": weekly("VNSGN-KRINC", {5}, ["ARROW NOBLE"], 8, "PA2"),
    },
}

TBN_DATE = date(2026, 12, 8)                  # Bluewave VNHPH-JPTYO: "TBN" on day 1, named on day 2
TBA_DATE = date(2026, 12, 5)                  # Northstar VNDAD-JPOSA: departure printed as "TBA"
MOVED = (date(2026, 11, 27), date(2026, 12, 1))   # Kestrel VNSGN-KRPUS: moved into December


def shift(sailings, when, days):
    return [replace(s, etd=s.etd + timedelta(days=days), eta=s.eta + timedelta(days=days)) if s.etd == when else s
            for s in sailings]


def sailings_for(carrier, route, day):
    """The carrier's list for one route on one crawl day, with the day-2 changes applied."""
    s = list(ROUTES[carrier][route])
    if (carrier, route) == ("bluewave_lines", "VNHPH-JPTYO"):
        name = "BLUEWAVE TBN" if day == 1 else "BLUEWAVE PISCES"
        s = [replace(x, vessel=name) if x.etd == TBN_DATE else x for x in s]
    if day == 2:
        if (carrier, route) == ("bluewave_lines", "VNHPH-KRPUS"):
            s = shift(s, date(2026, 11, 27), +2)
        elif (carrier, route) == ("bluewave_lines", "VNSGN-KRPUS"):
            s = [x for x in s if x.etd != date(2026, 12, 2)]
        elif (carrier, route) == ("kestrel_line", "VNHPH-JPOSA"):
            s = shift(s, date(2026, 12, 9), +1)
        elif (carrier, route) == ("jade_ocean", "VNSGN-JPTYO"):
            s = shift(s, date(2026, 12, 6), -1)
    return s


def on_page(sailings, day):
    lo = DAY[day]
    return [s for s in sailings if lo <= s.etd <= lo + timedelta(days=HORIZON)]


def months(day):
    lo, hi = DAY[day], DAY[day] + timedelta(days=HORIZON)
    out, d = [], date(lo.year, lo.month, 1)
    while d <= hi:
        out.append(f"{d.year}{d.month:02d}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


# --- writers, one per carrier shape -------------------------------------------------------------

def bluewave(route, day):
    pol, pod = route.split("-")
    tz = {"VN": "+07:00", "KR": "+09:00", "JP": "+09:00"}
    data = []
    for s in on_page(sailings_for("bluewave_lines", route, day), day):
        data.append({
            "service": s.service, "vessel": {"name": s.vessel}, "voyageNo": s.voyage,
            "origin": {"unloc": pol, "name": pol}, "destination": {"unloc": pod, "name": pod},
            "departure": f"{s.etd}T09:00:00{tz[pol[:2]]}", "arrival": f"{s.eta}T08:00:00{tz[pod[:2]]}",
            "cutoffs": [{"type": "SI", "at": f"{s.etd - timedelta(days=2)}T17:00:00{tz[pol[:2]]}"},
                        {"type": "CY", "at": f"{s.etd - timedelta(days=1)}T12:00:00{tz[pol[:2]]}"}]})
    lo = DAY[day]
    meta = {"carrier": "BLUEWAVE LINES", "from": str(lo), "to": str(lo + timedelta(days=HORIZON))}
    return json.dumps({"meta": meta, "data": data}, indent=1)


NORTHSTAR_NAMES = {"VNHPH": "HAI PHONG", "VNDAD": "DA NANG", "KRPUS": "BUSAN, KOREA",
                   "KRINC": "INCHEON, KOREA", "JPOSA": "OSAKA, JAPAN"}


def northstar(route, day):
    pol, pod = route.split("-")
    rows = on_page(sailings_for("northstar_shipping", route, day), day)
    if (route, day) == ("VNHPH-KRINC", 2):
        rows = []                                    # planted: OK answer, empty table
    head = ["Service", "Vessel / Voyage", "Port of Loading", "Port of Discharge", "ETD", "ETA", "CY Closing", "Remark"]
    html = [f"<html><head><title>Northstar Shipping - Schedule</title></head><body>",
            f"<h2>Point to point: {NORTHSTAR_NAMES[pol]} to {NORTHSTAR_NAMES[pod]}</h2>",
            "<table class='sched'>", "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + "</tr>"]
    if not rows:
        html.append("<tr><td colspan='8'>No sailings found for the selected period.</td></tr>")
    by_month = {}
    for s in rows:
        by_month.setdefault(s.etd.strftime("%B %Y"), []).append(s)
    months_list = list(by_month)
    for m_i, month in enumerate(months_list):
        html.append(f"<tr class='month'><td colspan='8'>{month}</td></tr>")
        listed = list(by_month[month])
        if route == "VNHPH-KRPUS" and m_i > 0:       # planted: last sailing of the previous month printed again
            listed = [(by_month[months_list[m_i - 1]][-1], "carried over")] + [(x, "") for x in listed]
        else:
            listed = [(x, "") for x in listed]
        for s, remark in listed:
            tba = route == "VNDAD-JPOSA" and s.etd == TBA_DATE
            etd = "TBA" if tba else s.etd.strftime("%d/%m/%Y")
            eta = "TBA" if tba else s.eta.strftime("%d/%m/%Y")
            cy = "" if tba else (s.etd - timedelta(days=1)).strftime("%d/%m/%Y") + " 12:00"
            cells = [s.service, f"{s.vessel} {s.voyage}", NORTHSTAR_NAMES[pol], NORTHSTAR_NAMES[pod], etd, eta, cy, remark]
            html.append("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in cells) + "</tr>")
    html += ["</table>", "</body></html>"]
    return "\n".join(html)


KESTREL_NAMES = {"VNHPH": "VIETNAM, HAIPHONG", "VNSGN": "VIETNAM, HOCHIMINH", "KRINC": "KOREA, INCHON",
                 "KRPUS": "KOREA, PUSAN", "JPOSA": "JAPAN, OSAKA"}


def kestrel(route, month, day):
    pol, pod = route.split("-")
    rows = [s for s in sailings_for("kestrel_line", route, day) if s.etd.strftime("%Y%m") == month]
    if route == "VNSGN-KRPUS" and month == "202612":     # planted: the moved sailing also appears in December
        orig = next(s for s in ROUTES["kestrel_line"][route] if s.etd == MOVED[0])
        moved = replace(orig, etd=MOVED[1], eta=MOVED[1] + (orig.eta - orig.etd))
        rows = sorted(rows + [moved], key=lambda s: s.etd)
    if (route, month, day) == ("VNHPH-KRINC", "202612", 2):
        rows = []                                    # planted: December export comes back empty
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["VSL_NAME", "VSLVOY", "LANE", "POL", "POD", "ETD", "ETA", "DOC_CLOSING", "CARGO_CLOSING"])
    for s in rows:
        w.writerow([s.vessel, f"{s.code}{s.voyage}", s.service, KESTREL_NAMES[pol], KESTREL_NAMES[pod],
                    s.etd.strftime("%Y%m%d"), s.eta.strftime("%Y%m%d"),
                    (s.etd - timedelta(days=2)).strftime("%Y%m%d") + " 1700",
                    (s.etd - timedelta(days=1)).strftime("%Y%m%d") + " 1200"])
    return buf.getvalue()


def jade(route, day):
    pol, pod = route.split("-")
    out = []
    for i, s in enumerate(sailings_for("jade_ocean", route, day), 1):
        out.append({"routingId": f"JO-{route}-{i:03d}",
                    "legs": [{"vessel": s.vessel, "voyage": s.voyage, "from": pol, "to": pod,
                              "etd": str(s.etd), "eta": str(s.eta), "service": s.service}],
                    "cutoffs": {"doc": f"{s.etd - timedelta(days=2)} 17:00", "cargo": f"{s.etd - timedelta(days=1)} 12:00"}})
    return json.dumps({"carrier": "JADE OCEAN", "sailings": out}, indent=1)


PACIFIC_NAMES = {"VNHPH": "HAIPHONG", "VNSGN": "HO CHI MINH (CAT LAI)", "JPTYO": "TOKYO", "KRINC": "INCHEON"}


def pacific(route, day):
    pol, pod = route.split("-")
    head = ["Loop", "Vessel", "Voy.", "From", "To", "Departure", "Arrival", "SI Cut-off"]
    html = ["<html><body><h3>Pacific Arrow sailing schedule</h3><table border='1'>",
            "<tr>" + "".join(f"<th>{escape(h)}</th>" for h in head) + "</tr>"]
    for s in on_page(sailings_for("pacific_arrow", route, day), day):
        cells = [s.service, s.vessel, s.voyage, PACIFIC_NAMES[pol], PACIFIC_NAMES[pod], s.etd.strftime("%b %d"),
                 s.eta.strftime("%b %d"), (s.etd - timedelta(days=2)).strftime("%b %d") + " 17:00"]
        html.append("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in cells) + "</tr>")
    html.append("</table></body></html>")
    return "\n".join(html)


INCIDENTS = {
    1: {},
    2: {"northstar_shipping": {"VNDAD-JPOSA": ["timeout"]},
        "jade_ocean": {"VNSGN-JPTYO": ["429"]},
        "pacific_arrow": {"*": ["503", "503", "503"]}},
}

BOOKINGS = [
    ("B-1001", "bluewave_lines", "VNHPH-KRPUS", date(2026, 11, 27), "Example Trading Co."),
    ("B-1002", "bluewave_lines", "VNSGN-KRPUS", date(2026, 12, 2), "Sample Exports Ltd."),
    ("B-1003", "kestrel_line", "VNHPH-KRINC", date(2026, 12, 1), "Demo Charcoal JSC"),
    ("B-1004", "northstar_shipping", "VNHPH-KRPUS", date(2026, 11, 23), "Example Trading Co."),
]
CARRIER_NAMES = {"bluewave_lines": "Bluewave Lines", "northstar_shipping": "Northstar Shipping",
                 "kestrel_line": "Kestrel Line", "jade_ocean": "Jade Ocean", "pacific_arrow": "Pacific Arrow"}


def write_all(fixtures=FIXTURES, data=HERE):
    for day in (1, 2):
        base = Path(fixtures) / f"day{day}"
        files = {}
        for route in ROUTES["bluewave_lines"]:
            files[f"bluewave_lines/{route}.json"] = bluewave(route, day)
        for route in ROUTES["northstar_shipping"]:
            files[f"northstar_shipping/{route}.html"] = northstar(route, day)
        for route in ROUTES["kestrel_line"]:
            for month in months(day):
                files[f"kestrel_line/{route}_{month}.csv"] = kestrel(route, month, day)
        for route in ROUTES["jade_ocean"]:
            files[f"jade_ocean/{route}.json"] = jade(route, day)
        for route in ROUTES["pacific_arrow"]:
            files[f"pacific_arrow/{route}.html"] = pacific(route, day)
        files["incidents.json"] = json.dumps(INCIDENTS[day], indent=1)
        for name, text in files.items():
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8", newline="\n")

    rows = []
    for ref, carrier, route, etd, customer in BOOKINGS:
        s = next(x for x in ROUTES[carrier][route] if x.etd == etd)
        pol, pod = route.split("-")
        rows.append([ref, "|".join([CARRIER_NAMES[carrier], s.vessel, s.voyage, pol, pod]).upper(), customer])
    with open(Path(data) / "bookings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["booking_ref", "voyage_key", "customer"])
        w.writerows(rows)


if __name__ == "__main__":
    write_all()
    print(f"Wrote {FIXTURES} and {HERE / 'bookings.csv'}")
