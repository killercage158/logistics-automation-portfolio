"""Plain data containers shared by the whole pipeline.

The rows go through three shapes, in this order:

  RawRow   what the carrier showed, as text, exactly as fetched
  Voyage   one clean sailing: UN/LOCODE ports, real dates, separate cut-offs
  (stored) a row in the SQLite table `voyages` (see store.py)

Keeping the shapes in one file makes every other module easy to read: they
just pass these objects along.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Route:
    """A lane we crawl, as two UN/LOCODEs, e.g. VNHPH (Hai Phong) -> KRPUS (Busan)."""
    pol: str
    pod: str

    @property
    def id(self):
        return f"{self.pol}-{self.pod}"


@dataclass
class RawRow:
    """One sailing as the carrier showed it: all text, nothing cleaned yet."""
    carrier: str
    route: Route                 # the route we asked for
    vessel: str
    voyage: str                  # may be empty when the carrier glues it to the vessel name
    pol: str
    pod: str
    etd: str
    eta: str
    cutoff_si: str = ""
    cutoff_cy: str = ""
    service: str = ""
    note: str = ""
    source: str = ""             # where it came from, e.g. "northstar_shipping/VNHPH-KRPUS.html row 4"
    seen_at: float = 0.0         # simulated seconds into the crawl when this row was fetched


def voyage_key(carrier, vessel, voyage, pol, pod):
    """SC-09: the identity of a voyage. No dates in it: dates change, identity does not."""
    return "|".join([carrier, vessel, voyage, pol, pod]).upper()


@dataclass
class Voyage:
    """One clean sailing, ready to store."""
    carrier: str
    vessel: str
    voyage: str
    pol: str                     # UN/LOCODE
    pod: str                     # UN/LOCODE
    etd: date
    eta: Optional[date]
    cutoff_si: Optional[str]     # "YYYY-MM-DD HH:MM" (SC-08: never mixed into etd/eta)
    cutoff_cy: Optional[str]
    service: str = ""
    note: str = ""
    source: str = ""
    seen_at: float = 0.0

    @property
    def key(self):
        return voyage_key(self.carrier, self.vessel, self.voyage, self.pol, self.pod)

    @property
    def transit_days(self):
        return (self.eta - self.etd).days if self.eta else None


@dataclass
class RouteResult:
    """What happened on one route of one carrier in one crawl."""
    carrier: str
    route: Route
    status: str                  # "ok" or "failed"
    rows: int = 0
    error: str = ""
    window: Optional[tuple] = None   # (date_from, date_to) the crawl covered, used by SC-13
    calls: int = 0


@dataclass
class CarrierResult:
    """Everything one carrier's crawl produced."""
    carrier: str
    routes: list = field(default_factory=list)       # list[RouteResult]
    raw_rows: list = field(default_factory=list)     # list[RawRow]
    seconds: float = 0.0         # simulated time the crawl took (pacing, waits, retries)
    calls: int = 0
    crashed: str = ""            # set when the whole carrier blew up (SC-02 caught it)
    log: list = field(default_factory=list)          # this carrier's own log lines

    @property
    def errors(self):
        """SC-03: the carrier's own error list, one line per failed route (plus a crash, if any)."""
        out = [f"Route {r.route.id}: {r.error}" for r in self.routes if r.status == "failed"]
        return out + ([f"Crawl crashed: {self.crashed}"] if self.crashed else [])
