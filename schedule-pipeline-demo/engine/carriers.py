"""The five (invented) carriers: which routes we crawl, how their site works, how fast we may call it.

Each carrier publishes its schedule in its own shape:

  Bluewave Lines      json_api      JSON API, one call per route
  Northstar Shipping  html_table    HTML page per route, dd/mm/yyyy, vessel and voyage in one cell
  Kestrel Line        csv_month     CSV export per route AND per month, YYYYMMDD dates
  Jade Ocean          json_capped   JSON API that silently returns at most 8 results per call
  Pacific Arrow       html_noyear   HTML page per route, dates like "Dec 03" with no year

WHY a "priority routes" list per carrier: the daily run crawls the lanes the
booking team actually sells, not every port pair the carrier serves. That keeps
the run short and the number of calls to each carrier low.

In production, each carrier has its own folder with a routes list, the API
client, a parser and the crawl loop, and some carriers need a real browser.
Here every carrier is a few lines of configuration and the "site" is a folder
of recorded responses.
"""
from dataclasses import dataclass, field

from engine.models import Route


@dataclass
class Carrier:
    name: str
    slug: str                    # folder name under fixtures/dayN/
    shape: str                   # which parser and fetch plan to use (see crawl.py)
    routes: list = field(default_factory=list)
    min_gap_s: float = 1.0       # SC-01: minimum wait between two calls to this carrier
    jitter_s: float = 0.0        # extra random wait (0..jitter_s), so calls do not look robotic
    latency_s: float = 0.8       # how long one answer takes (simulated)
    result_cap: int = 0          # json_capped only: the silent maximum results per call
    quota_wait_s: float = 60.0   # how long to wait after "429 too many requests"


def r(pol, pod):
    return Route(pol, pod)


CARRIERS = [
    Carrier("Bluewave Lines", "bluewave_lines", "json_api",
            [r("VNHPH", "KRPUS"), r("VNHPH", "JPTYO"), r("VNSGN", "KRPUS")],
            min_gap_s=1.0),
    Carrier("Northstar Shipping", "northstar_shipping", "html_table",
            [r("VNHPH", "KRPUS"), r("VNHPH", "KRINC"), r("VNDAD", "JPOSA")],
            min_gap_s=3.0, jitter_s=2.0, latency_s=1.5),
    Carrier("Kestrel Line", "kestrel_line", "csv_month",
            [r("VNHPH", "KRINC"), r("VNSGN", "KRPUS"), r("VNHPH", "JPOSA")],
            min_gap_s=2.0, latency_s=1.2),
    Carrier("Jade Ocean", "jade_ocean", "json_capped",
            [r("VNHPH", "SGSIN"), r("VNSGN", "JPTYO")],
            min_gap_s=1.2, result_cap=8, quota_wait_s=60.0),
    Carrier("Pacific Arrow", "pacific_arrow", "html_noyear",
            [r("VNHPH", "JPTYO"), r("VNSGN", "KRINC")],
            min_gap_s=2.5, latency_s=1.0),
]


def carrier_by_name(name):
    for c in CARRIERS:
        if c.name == name:
            return c
    raise KeyError(name)
