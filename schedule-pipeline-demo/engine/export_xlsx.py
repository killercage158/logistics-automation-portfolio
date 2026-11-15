"""Step 7a: the daily Excel schedule for one cargo segment (rule SC-19).

The booking team wants a file, not a database. One workbook per day:

  - one tab per loading port and destination country ("HAI PHONG - KOREA");
  - inside a tab, one section per discharge port, sailings sorted by departure;
  - a "Notes" tab that prints the rules used, counts per carrier and every warning.

Segment rules are DATA (the SEGMENTS table below), printed in the Notes tab, so
staff can read them and challenge them:

  carriers           only the carriers that carry this cargo
  countries          only export lanes from Vietnam to these countries
  excluded services  a carrier's loop that does not accept this cargo
  latest crawl only  a sailing must be in the carrier's most recent crawl that returned data
                     (protects the file from rows the crawl no longer confirms)
  STALE              a carrier whose latest data is older than today is kept but marked,
                     so staff know those dates were not re-checked today

In production, the export runs at noon after the morning crawl and the file is
sent to the booking team by a chat bot. Here it is written to output/.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from engine.normalise import COUNTRY_NAMES, port_country, port_name


@dataclass
class Segment:
    name: str
    carriers: list
    countries: list
    excluded_services: dict      # service code -> reason


SEGMENTS = {
    "charcoal": Segment(
        name="Charcoal",
        carriers=["Bluewave Lines", "Northstar Shipping", "Kestrel Line", "Pacific Arrow"],
        countries=["KR", "JP"],
        excluded_services={"NSX2": "Northstar's NSX2 loop does not accept charcoal"},
    ),
}

COLUMNS = ["Carrier", "Vessel", "Voyage", "Service", "ETD", "ETA", "Transit (days)",
           "SI cut-off", "CY cut-off", "ETD change", "Note"]
WIDTHS = [20, 22, 9, 9, 12, 12, 9, 17, 17, 22, 34]

THIN = Side(style="thin", color="C9D1DE")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
SECTION_FILL = PatternFill("solid", fgColor="DDE7F3")
CHANGE_FILL = PatternFill("solid", fgColor="FCE4D6")
STALE_FILL = PatternFill("solid", fgColor="FFF2CC")


@dataclass
class ExportResult:
    path: str
    sailings: int = 0
    per_tab: dict = field(default_factory=dict)
    per_carrier: dict = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)      # reason -> count
    stale: dict = field(default_factory=dict)         # carrier -> last listed date


def select_rows(conn, segment, export_date, trace=None):
    """Return (rows to export, ExportResult with counts filled in except path)."""
    res = ExportResult(path="")
    seen_since = {r["carrier"]: r["d"] for r in conn.execute(
        "SELECT carrier, MAX(last_seen) AS d FROM voyages GROUP BY carrier")}
    rows = []
    for row in conn.execute("SELECT * FROM voyages WHERE is_active = 1 AND etd >= ? ORDER BY etd, carrier",
                            (export_date.isoformat(),)):
        reason = None
        if row["carrier"] not in segment.carriers:
            reason = f"{row['carrier']}: carrier not in the {segment.name.lower()} segment"
        elif port_country(row["pol"]) != "VN" or port_country(row["pod"]) not in segment.countries:
            reason = f"lane {row['pol']}-{row['pod']} not in the segment"
        elif row["service"] in segment.excluded_services:
            reason = segment.excluded_services[row["service"]]
        elif row["last_seen"] < seen_since[row["carrier"]]:
            reason = f"{row['carrier']}: not listed in its latest crawl ({seen_since[row['carrier']]})"
        if reason:
            res.excluded[reason] = res.excluded.get(reason, 0) + 1
            continue
        rows.append(row)
    for carrier in segment.carriers:
        last = seen_since.get(carrier)
        if last and last < export_date.isoformat():
            res.stale[carrier] = last
            if trace:
                trace.hit("SC-19", f"{carrier}: latest data from {last}, marked STALE in the file")
    if trace:
        for reason, n in res.excluded.items():
            trace.hit("SC-19", f"excluded {n}: {reason}")
    return rows, res


def last_etd_change(conn, key, export_date, days=7):
    row = conn.execute("SELECT old_etd, delta_days FROM etd_changes WHERE key = ? AND crawl_date >= ? "
                       "ORDER BY crawl_date DESC LIMIT 1",
                       (key, (export_date - timedelta(days=days)).isoformat())).fetchone()
    if not row:
        return ""
    return f"moved {row['delta_days']:+d} d (was {date.fromisoformat(row['old_etd']):%d-%b})"


def _cell(ws, r, c, value, bold=False, fill=None, fmt=None, color=None, size=10):
    cell = ws.cell(row=r, column=c, value=value)
    cell.font = Font(name="Calibri", size=size, bold=bold, color=color)
    cell.border = BORDER
    cell.alignment = Alignment(vertical="center", wrap_text=c == len(COLUMNS))
    if fill:
        cell.fill = fill
    if fmt:
        cell.number_format = fmt
    return cell


def write_workbook(conn, segment, export_date, path, health=None, trace=None):
    rows, res = select_rows(conn, segment, export_date, trace)
    res.path = str(path)
    wb = Workbook()
    wb.remove(wb.active)

    tabs = {}
    for row in rows:
        tab = f"{port_name(row['pol']).upper()} - {COUNTRY_NAMES[port_country(row['pod'])].upper()}"
        tabs.setdefault(tab, []).append(row)

    for tab in sorted(tabs):
        ws = wb.create_sheet(tab[:31])
        ws.sheet_view.showGridLines = False
        for i, w in enumerate(WIDTHS, 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        title = ws.cell(row=1, column=1, value=f"{segment.name} sailing schedule  |  {tab.title()}  |  "
                                                f"exported {export_date:%d %b %Y}")
        title.font = Font(size=13, bold=True, color="1F4E79")
        r = 3
        by_pod = {}
        for row in tabs[tab]:
            by_pod.setdefault(row["pod"], []).append(row)
        for pod in sorted(by_pod, key=port_name):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(COLUMNS))
            _cell(ws, r, 1, f"{port_name(pod).upper()}  ({pod})", bold=True, fill=SECTION_FILL, size=11)
            r += 1
            for c, head in enumerate(COLUMNS, 1):
                _cell(ws, r, c, head, bold=True, fill=HEAD_FILL, color="FFFFFF")
            r += 1
            for row in sorted(by_pod[pod], key=lambda x: (x["etd"], x["carrier"])):
                change = last_etd_change(conn, row["key"], export_date)
                stale = row["carrier"] in res.stale
                note = "; ".join(x for x in [
                    f"STALE: last listed {row['last_seen']}" if stale else "", row["note"] or ""] if x)
                values = [row["carrier"], row["vessel"], row["voyage"], row["service"],
                          date.fromisoformat(row["etd"]),
                          date.fromisoformat(row["eta"]) if row["eta"] else None,
                          row["transit_days"], row["cutoff_si"] or "", row["cutoff_cy"] or "", change, note]
                fill = STALE_FILL if stale else None
                for c, value in enumerate(values, 1):
                    _cell(ws, r, c, value, fmt="dd-mmm-yy" if c in (5, 6) else None,
                          fill=CHANGE_FILL if (c == 10 and change) else fill)
                res.per_carrier[row["carrier"]] = res.per_carrier.get(row["carrier"], 0) + 1
                r += 1
            r += 1
        ws.freeze_panes = "A3"
        res.per_tab[tab] = len(tabs[tab])
    res.sailings = len(rows)
    _notes_sheet(wb, segment, export_date, res, health)
    wb.save(path)
    return res


def _notes_sheet(wb, segment, export_date, res, health):
    ws = wb.create_sheet("Notes")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 90
    lines = [
        ("Exported", f"{export_date:%d %b %Y}"),
        ("Segment", segment.name),
        ("Carriers", ", ".join(segment.carriers)),
        ("Lanes", "export from Vietnam to " + ", ".join(COUNTRY_NAMES[c] for c in segment.countries)),
    ]
    lines += [("Excluded service " + code, why) for code, why in segment.excluded_services.items()]
    lines += [("Latest crawl only", "a sailing must be listed in the carrier's most recent crawl that "
                                    "returned data (rule SC-19)"),
              ("", ""), ("Sailings in this file", str(res.sailings))]
    lines += [(f"  {c}", str(n)) for c, n in sorted(res.per_carrier.items())]
    lines += [("", ""), ("Left out", "")]
    lines += [(f"  {n} sailing(s)", why) for why, n in sorted(res.excluded.items())]
    lines += [("", ""), ("Warnings", "" if (res.stale or (health and health.problems)) else "none")]
    lines += [(f"  STALE {c}", f"latest data from {d}: its crawl failed today; dates not re-checked")
              for c, d in res.stale.items()]
    if health:
        lines += [(f"  {h.flag} {h.carrier}", f"{h.route}: {h.detail}") for h in health.problems]
    for i, (a, b) in enumerate(lines, 1):
        ws.cell(row=i, column=1, value=a).font = Font(bold=bool(a) and not a.startswith("  "))
        ws.cell(row=i, column=2, value=b)
