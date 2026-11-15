"""Step 2: turn every RawRow, whatever the carrier, into one clean Voyage (or a rejection with a reason).

  port_code()          SC-05  any spelling or code -> one UN/LOCODE
  split_vessel_voyage  SC-06  'NORTHSTAR LYRA 2647N' -> ('NORTHSTAR LYRA', '2647N'),
                              'KSDW2645N' -> '2645N' (vessel code glued to the voyage)
  parse_when()         SC-07  ISO, YYYYMMDD, dd/mm/yyyy, 'Dec 03' (year inferred); 'TBA' -> None
  normalise_row()      SC-08  cut-offs go to their own fields, never into ETD/ETA

WHY one cleaning step for everybody: five carriers spell Hai Phong five ways.
If each parser cleaned its own way, the same voyage could get two keys and be
stored twice. One function, one alias table, one set of tests.

WHY reject instead of guess: a row without a real departure date, or with a port
we do not know, is listed in the report with the reason. It is never silently
dropped and never silently "fixed".
"""
import re
import unicodedata
from datetime import date, timedelta

from engine.models import Voyage

# UN/LOCODE -> (display name, country, known spellings). Spellings are compared
# without spaces, accents or punctuation, so "HAI PHONG", "Hải Phòng" and "HAIPHONG" all match.
PORTS = {
    "VNHPH": ("Hai Phong", "VN", ["HAIPHONG", "HPH"]),
    "VNSGN": ("Ho Chi Minh", "VN", ["HOCHIMINH", "HOCHIMINHCITY", "HCM", "SAIGON", "CATLAI"]),
    "VNDAD": ("Da Nang", "VN", ["DANANG"]),
    "KRPUS": ("Busan", "KR", ["BUSAN", "PUSAN"]),
    "KRINC": ("Incheon", "KR", ["INCHEON", "INCHON"]),
    "JPTYO": ("Tokyo", "JP", ["TOKYO"]),
    "JPOSA": ("Osaka", "JP", ["OSAKA"]),
    "SGSIN": ("Singapore", "SG", ["SINGAPORE"]),
}
COUNTRY_WORDS = {"VIETNAM", "VIETNAMESE", "KOREA", "SOUTHKOREA", "JAPAN", "VN", "KR", "JP"}
COUNTRY_NAMES = {"VN": "Vietnam", "KR": "Korea", "JP": "Japan", "SG": "Singapore"}

_ALIASES = {}
for _code, (_name, _country, _spellings) in PORTS.items():
    for _s in _spellings + [_code]:
        _ALIASES[_s] = _code

VOYAGE_RE = re.compile(r"^\d{3,4}[A-Z]{0,2}$")              # 2647N, 2648S, 651W
GLUED_CODE_RE = re.compile(r"^([A-Z]{2,5})(\d{3,4}[A-Z]{0,2})$")   # KSDW2645N -> KSDW + 2645N
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def plain(text):
    """Upper case, no accents, no punctuation, single spaces. 'Hải Phòng (HICT)' -> 'HAI PHONG'."""
    text = re.sub(r"\(.*?\)", " ", text or "")                  # terminal names in brackets
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9,]+", " ", text).upper()
    return " ".join(text.split())


def port_code(text):
    """SC-05: return the UN/LOCODE for any known spelling, or None.

    'KOREA, BUSAN' and 'BUSAN, KOREA' are split on the comma and each part is
    tried, so the country can come first or last.
    """
    cleaned = plain(text)
    candidates = [cleaned] + [p.strip() for p in cleaned.split(",")]
    for candidate in candidates:
        squashed = candidate.replace(" ", "").replace(",", "")
        if squashed in _ALIASES:
            return _ALIASES[squashed]
        words = [w for w in candidate.replace(",", " ").split() if w not in COUNTRY_WORDS]
        squashed = "".join(words)
        if squashed in _ALIASES:
            return _ALIASES[squashed]
    return None


def port_name(code):
    return PORTS[code][0] if code in PORTS else code


def port_country(code):
    return PORTS[code][1] if code in PORTS else code[:2]


def split_vessel_voyage(vessel_text, voyage_text):
    """SC-06: return (vessel, voyage, what_was_done). Raises ValueError if no voyage can be found."""
    vessel = " ".join((vessel_text or "").upper().split())
    voyage = "".join((voyage_text or "").upper().split())
    done = []
    tokens = vessel.split()
    if not voyage and len(tokens) >= 2 and VOYAGE_RE.match(tokens[-1]):
        voyage, vessel = tokens[-1], " ".join(tokens[:-1])         # 'NORTHSTAR LYRA 2647N'
        done.append("split vessel and voyage")
    glued = GLUED_CODE_RE.match(voyage)
    if glued:
        voyage = glued.group(2)                                     # 'KSDW2645N' -> '2645N'
        done.append(f"vessel code {glued.group(1)} stripped from voyage")
    if vessel.endswith(" " + voyage):                               # 'STAR ORCHID 2647N' + '2647N'
        vessel = vessel[: -len(voyage) - 1]
        done.append("voyage removed from vessel name")
    if not vessel or not voyage:
        raise ValueError(f"no vessel/voyage in '{vessel_text}' / '{voyage_text}'")
    return vessel, voyage, done


def parse_when(text, crawl_date):
    """SC-07: return (date, 'HH:MM' or None), or (None, None) if the text is not a date.

    Formats: '2026-11-20T09:00:00+07:00', '2026-11-20', '2026-11-20 17:00',
             '20261120', '20261120 1700', '20/11/2026', '20/11/2026 12:00', 'Nov 20', 'Nov 20 17:00'.
    Time zones are NOT converted: the carrier prints local port time, which is what staff need.
    A date with no year ('Dec 03') gets the crawl year, or next year if that would put it more
    than 60 days in the past (a schedule page only shows the coming weeks).
    """
    t = (text or "").strip()
    patterns = [
        (r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", "ymd"),
        (r"^(\d{4})(\d{2})(\d{2})(?:\s+(\d{2})(\d{2}))?$", "ymd"),
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2}))?$", "dmy"),
        (r"^([A-Za-z]{3})\s+(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$", "mon"),
    ]
    for pattern, kind in patterns:
        m = re.match(pattern, t)
        if not m:
            continue
        g = m.groups()
        try:
            if kind == "ymd":
                d, hh, mm = date(int(g[0]), int(g[1]), int(g[2])), g[3], g[4]
            elif kind == "dmy":
                d, hh, mm = date(int(g[2]), int(g[1]), int(g[0])), g[3], g[4]
            else:
                month = MONTHS.get(g[0].upper())
                if not month:
                    return None, None
                d, hh, mm = date(crawl_date.year, month, int(g[1])), g[2], g[3]
                if d < crawl_date - timedelta(days=60):
                    d = date(crawl_date.year + 1, month, int(g[1]))
        except ValueError:                       # 31/02/2026 and friends: not a real date
            return None, None
        return d, (f"{int(hh):02d}:{mm}" if hh else None)
    return None, None


def as_cutoff(text, crawl_date):
    """A cut-off as 'YYYY-MM-DD HH:MM' (or just the date), or None. SC-08: kept in its own field."""
    d, hhmm = parse_when(text, crawl_date)
    if d is None:
        return None
    return f"{d.isoformat()} {hhmm}" if hhmm else d.isoformat()


def normalise_row(raw, crawl_date, trace=None):
    """Return (Voyage, None) or (None, reason). Never raises: one bad row must not break the batch."""

    def fired(rule_id, detail):
        if trace is not None:
            trace.hit(rule_id, detail)

    pol, pod = port_code(raw.pol), port_code(raw.pod)
    if pol is None:
        fired("SC-05", f"unknown port '{raw.pol}' rejected")
        return None, f"unknown port of loading '{raw.pol}' [SC-05]"
    if pod is None:
        fired("SC-05", f"unknown port '{raw.pod}' rejected")
        return None, f"unknown port of discharge '{raw.pod}' [SC-05]"
    for text, code in ((raw.pol, pol), (raw.pod, pod)):
        if text != code:
            fired("SC-05", f"'{text}' -> {code}")
    if (pol, pod) != (raw.route.pol, raw.route.pod):
        return None, f"row is for {pol}-{pod}, not the route asked ({raw.route.id})"
    try:
        vessel, voyage, done = split_vessel_voyage(raw.vessel, raw.voyage)
    except ValueError as e:
        return None, f"{e} [SC-06]"
    for action in done:
        fired("SC-06", f"{raw.vessel} {raw.voyage}".strip() + f": {action}")
    etd, _ = parse_when(raw.etd, crawl_date)
    if etd is None:
        fired("SC-07", f"{vessel} {voyage}: ETD '{raw.etd}' is not a date, row rejected")
        return None, f"ETD '{raw.etd}' is not a date [SC-07]"
    eta, _ = parse_when(raw.eta, crawl_date)
    note = raw.note
    if raw.eta and eta is None:
        fired("SC-07", f"{vessel} {voyage}: ETA '{raw.eta}' is not a date, left empty")
        note = (note + " | " if note else "") + f"ETA '{raw.eta}' not a date"
    if re.match(r"^[A-Za-z]{3}\s+\d", raw.etd or ""):
        fired("SC-07", f"'{raw.etd}' has no year -> {etd.isoformat()}")
    cut_si, cut_cy = as_cutoff(raw.cutoff_si, crawl_date), as_cutoff(raw.cutoff_cy, crawl_date)
    if cut_si or cut_cy:
        fired("SC-08", f"{vessel} {voyage}: cut-off stored in its own field")
    return Voyage(raw.carrier, vessel, voyage, pol, pod, etd, eta, cut_si, cut_cy,
                  raw.service.strip().upper(), note, raw.source, raw.seen_at), None


def normalise_all(raw_rows, crawl_date, trace=None):
    """Return (voyages, rejected) where rejected is a list of (raw_row, reason)."""
    voyages, rejected = [], []
    for raw in raw_rows:
        v, why = normalise_row(raw, crawl_date, trace)
        if v:
            voyages.append(v)
        else:
            rejected.append((raw, why))
    return voyages, rejected
