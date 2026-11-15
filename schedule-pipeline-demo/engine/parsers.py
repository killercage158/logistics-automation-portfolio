"""Turn each carrier's raw answer (JSON, HTML or CSV text) into RawRow objects.

A parser only READS. It copies what the carrier wrote into a RawRow, as text,
without cleaning anything. Cleaning (ports, dates, vessel names) happens once,
in normalise.py, for every carrier the same way.

WHY separate reading from cleaning: when a carrier changes its page layout, only
its parser changes. The rules that decide what a clean sailing looks like stay
in one place and keep their tests.
"""
import csv
import io
import json
from html.parser import HTMLParser

from engine.models import RawRow


class ParseError(Exception):
    """The answer could not be read at all (broken JSON, no table, wrong columns)."""


# --- JSON -------------------------------------------------------------------------------------

def parse_bluewave(body, carrier, route, source, seen_at):
    """Bluewave's JSON API: ISO date-times with time zone, cut-offs as a typed list."""
    try:
        data = json.loads(body)["data"]
    except (ValueError, KeyError) as e:
        raise ParseError(f"unreadable JSON ({e})")
    rows = []
    for i, item in enumerate(data, 1):
        cut = {c.get("type"): c.get("at", "") for c in item.get("cutoffs", [])}
        rows.append(RawRow(
            carrier=carrier, route=route,
            vessel=item["vessel"]["name"], voyage=item.get("voyageNo", ""),
            pol=item["origin"].get("unloc") or item["origin"].get("name", ""),
            pod=item["destination"].get("unloc") or item["destination"].get("name", ""),
            etd=item.get("departure") or "", eta=item.get("arrival") or "",
            cutoff_si=cut.get("SI", ""), cutoff_cy=cut.get("CY", ""),
            service=item.get("service", ""), source=f"{source} item {i}", seen_at=seen_at))
    return rows


def parse_jade(body, carrier, route, source, seen_at):
    """Jade Ocean's JSON API: one routing per result, the first leg is the sailing we sell."""
    try:
        results = json.loads(body)["results"]
    except (ValueError, KeyError) as e:
        raise ParseError(f"unreadable JSON ({e})")
    rows = []
    for item in results:
        leg = item["legs"][0]
        cut = item.get("cutoffs", {})
        rows.append(RawRow(
            carrier=carrier, route=route, vessel=leg["vessel"], voyage=leg["voyage"],
            pol=leg["from"], pod=leg["to"], etd=leg["etd"], eta=leg.get("eta", ""),
            cutoff_si=cut.get("doc", ""), cutoff_cy=cut.get("cargo", ""),
            service=leg.get("service", ""), source=f"{source} {item.get('routingId', '')}".strip(),
            seen_at=seen_at))
    return rows


# --- HTML -------------------------------------------------------------------------------------

class _TableReader(HTMLParser):
    """Collects every table row as a list of cell texts. Header cells are marked."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell, self._in_cell = [], None, [], False
        self._is_header = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._in_cell, self._cell = True, []
            self._is_header = tag == "th"

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None:
            self._row.append((" ".join("".join(self._cell).split()), self._is_header))
            self._in_cell = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def read_html_table(body):
    """Return (headers, data_rows). Section rows (a single cell spanning the table) are skipped."""
    reader = _TableReader()
    reader.feed(body)
    headers, rows = None, []
    for row in reader.rows:
        if row and all(is_header for _, is_header in row):
            headers = [text for text, _ in row]
        elif headers and len(row) == len(headers):
            rows.append([text for text, _ in row])
        # rows with another cell count are month titles such as "December 2026": not sailings
    if headers is None:
        raise ParseError("no schedule table on the page")
    return headers, rows


def _need(headers, names, carrier):
    missing = [n for n in names if n not in headers]
    if missing:
        raise ParseError(f"{carrier} page has no column {missing} (layout changed?)")


def parse_northstar(body, carrier, route, source, seen_at):
    """Northstar's HTML: 'Vessel / Voyage' is ONE cell such as 'NORTHSTAR LYRA 2647N'."""
    headers, rows = read_html_table(body)
    cols = ["Service", "Vessel / Voyage", "Port of Loading", "Port of Discharge", "ETD", "ETA", "CY Closing"]
    _need(headers, cols, carrier)
    out = []
    for i, cells in enumerate(rows, 1):
        c = dict(zip(headers, cells))
        out.append(RawRow(
            carrier=carrier, route=route, vessel=c["Vessel / Voyage"], voyage="",
            pol=c["Port of Loading"], pod=c["Port of Discharge"], etd=c["ETD"], eta=c["ETA"],
            cutoff_cy=c["CY Closing"], service=c["Service"], note=c.get("Remark", ""),
            source=f"{source} row {i}", seen_at=seen_at))
    return out


def parse_pacific(body, carrier, route, source, seen_at):
    """Pacific Arrow's HTML: dates like 'Dec 03' with NO year (normalise.py infers it)."""
    headers, rows = read_html_table(body)
    cols = ["Loop", "Vessel", "Voy.", "From", "To", "Departure", "Arrival", "SI Cut-off"]
    _need(headers, cols, carrier)
    out = []
    for i, cells in enumerate(rows, 1):
        c = dict(zip(headers, cells))
        out.append(RawRow(
            carrier=carrier, route=route, vessel=c["Vessel"], voyage=c["Voy."],
            pol=c["From"], pod=c["To"], etd=c["Departure"], eta=c["Arrival"],
            cutoff_si=c["SI Cut-off"], service=c["Loop"], source=f"{source} row {i}", seen_at=seen_at))
    return out


# --- CSV --------------------------------------------------------------------------------------

def parse_kestrel(body, carrier, route, source, seen_at):
    """Kestrel's CSV export: VSLVOY glues a vessel code to the voyage ('KSDW2645N')."""
    reader = csv.DictReader(io.StringIO(body))
    cols = ["VSL_NAME", "VSLVOY", "LANE", "POL", "POD", "ETD", "ETA", "DOC_CLOSING", "CARGO_CLOSING"]
    if reader.fieldnames is None or any(c not in reader.fieldnames for c in cols):
        raise ParseError(f"CSV columns changed: {reader.fieldnames}")
    out = []
    for i, c in enumerate(reader, 2):        # row 1 is the header line
        out.append(RawRow(
            carrier=carrier, route=route, vessel=c["VSL_NAME"], voyage=c["VSLVOY"],
            pol=c["POL"], pod=c["POD"], etd=c["ETD"], eta=c["ETA"],
            cutoff_si=c["DOC_CLOSING"], cutoff_cy=c["CARGO_CLOSING"], service=c["LANE"],
            source=f"{source} line {i}", seen_at=seen_at))
    return out


PARSERS = {
    "json_api": parse_bluewave,
    "json_capped": parse_jade,
    "html_table": parse_northstar,
    "html_noyear": parse_pacific,
    "csv_month": parse_kestrel,
}

EXTENSIONS = {"json_api": "json", "json_capped": "json", "html_table": "html",
              "html_noyear": "html", "csv_month": "csv"}
