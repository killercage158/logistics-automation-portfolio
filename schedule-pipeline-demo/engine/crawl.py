"""Step 1: crawl every carrier, politely, without letting one failure hide another.

  SimClock       simulated time, so pacing and waits show up in the log without real waiting
  PoliteCaller   SC-01: minimum gap between calls, retries for temporary errors only
  fetch plans    per route (most carriers), per route AND month (Kestrel),
                 per window with splitting at the silent result cap (Jade Ocean, SC-04)
  crawl_carrier  one carrier, route by route; a failed route is RECORDED (SC-03)
  crawl_all      all carriers in parallel threads, each in its own error box (SC-02)

WHY sequential routes but parallel carriers: one carrier's site must not be hit
by many calls at once (it would block us), but different carriers do not share
limits, so they can run side by side.

WHY "success" is not trusted later: crawl_all only fails if Python itself
breaks. A carrier that lost every route still "succeeds" here. That is exactly
what a scheduler sees, and why the health check (health.py) exists.

In production, a scheduled task starts the crawl twice a day, carriers run in
parallel inside one service, and some carriers are fetched through a real
browser. Here the calls go to recorded files and the clock is simulated.
"""
import random
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from engine.models import CarrierResult, RouteResult
from engine.parsers import EXTENSIONS, PARSERS, ParseError
from engine.sites import CappedApi, RecordedSite

HORIZON_DAYS = 41            # page-based carriers show about six weeks ahead
MAX_ATTEMPTS = 3             # tries per call for temporary errors (5xx, timeout)
MAX_QUOTA_WAITS = 3          # "429 too many requests" waits do not use up an attempt
BACKOFF_S = 5.0              # wait before retry n = BACKOFF_S x n
PERMANENT = {400, 401, 403, 404}


class FetchError(Exception):
    """A route could not be fetched. The message says why, in plain words."""


class SimClock:
    """Simulated time in seconds. sleep() only moves the number forward.

    real_factor > 0 also sleeps for real (seconds x real_factor), used by --slow.
    """

    def __init__(self, real_factor=0.0):
        self.now = 0.0
        self.real_factor = real_factor

    def sleep(self, seconds):
        if seconds > 0:
            self.now += seconds
            if self.real_factor:
                time.sleep(seconds * self.real_factor)


class PoliteCaller:
    """Wraps one carrier site. SC-01: pacing, retries for temporary errors, none for permanent ones."""

    def __init__(self, carrier, site, clock, log, trace, seed=7):
        self.carrier, self.site, self.clock, self.log, self.trace = carrier, site, clock, log, trace
        self.rng = random.Random(f"{carrier.slug}-{seed}")   # same jitter every run (reproducible)
        self.last_call = None
        self.calls = 0

    def _pace(self):
        if self.last_call is None:
            return
        gap = self.carrier.min_gap_s + (self.rng.uniform(0, self.carrier.jitter_s) if self.carrier.jitter_s else 0)
        wait = gap - (self.clock.now - self.last_call)
        self.clock.sleep(wait)

    def get(self, path, params=None):
        attempt, quota_waits = 1, 0
        while True:
            self._pace()
            response = self.site.get(path, params)
            self.clock.sleep(response.seconds)
            self.last_call = self.clock.now
            self.calls += 1
            if response.status == 200:
                return response.body
            what = "timeout (no answer)" if response.is_timeout else f"HTTP {response.status}"
            if response.status in PERMANENT:
                raise FetchError(f"{what} - permanent, not retried")
            if response.status == 429 and quota_waits < MAX_QUOTA_WAITS:
                quota_waits += 1
                self.log.append(f"      {path}: {what} rate limit -> wait {self.carrier.quota_wait_s:.0f} s, "
                                f"then ask again (quota waits do not use up an attempt) [SC-01]")
                self.trace.hit("SC-01", f"{self.carrier.name} {path}: 429, waited {self.carrier.quota_wait_s:.0f} s")
                self.clock.sleep(self.carrier.quota_wait_s)
                continue
            if attempt >= MAX_ATTEMPTS:
                raise FetchError(f"{what} on all {MAX_ATTEMPTS} attempts")
            wait = BACKOFF_S * attempt
            self.log.append(f"      {path}: {what} (temporary) -> wait {wait:.0f} s, attempt {attempt + 1} "
                            f"of {MAX_ATTEMPTS} [SC-01]")
            self.trace.hit("SC-01", f"{self.carrier.name} {path}: {what}, retried")
            self.clock.sleep(wait)
            attempt += 1


# --- windows ----------------------------------------------------------------------------------

def page_window(crawl_date):
    """The six weeks a page-based carrier shows, starting on the crawl day."""
    return crawl_date, crawl_date + timedelta(days=HORIZON_DAYS)


def months_of(window):
    """['202611', '202612'] for a window from mid-November to late December."""
    first, last = window
    months, d = [], date(first.year, first.month, 1)
    while d <= last:
        months.append(f"{d.year}{d.month:02d}")
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return months


def month_window(months):
    """Month-based carriers cover whole months: 1st of the first month to the last day of the last."""
    first, last = months[0], months[-1]
    y, m = int(last[:4]), int(last[4:])
    end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    return date(int(first[:4]), int(first[4:]), 1), end


def split_window(lo, hi):
    """Split [lo, hi] into two halves that do not overlap."""
    mid = lo + timedelta(days=(hi - lo).days // 2)
    return (lo, mid), (mid + timedelta(days=1), hi)


# --- fetch plans --------------------------------------------------------------------------------

def fetch_per_route(carrier, caller, route, crawl_date, log, trace):
    """One call per route. Returns (raw rows, window covered)."""
    body = caller.get(route.id)
    source = f"{carrier.slug}/{route.id}.{EXTENSIONS[carrier.shape]}"
    rows = PARSERS[carrier.shape](body, carrier.name, route, source, caller.clock.now)
    return rows, page_window(crawl_date)


def fetch_per_month(carrier, caller, route, crawl_date, log, trace):
    """Month-based search: one call per route per month. Any failed month fails the route."""
    months = months_of(page_window(crawl_date))
    rows = []
    for month in months:
        path = f"{route.id}_{month}"
        body = caller.get(path)
        got = PARSERS[carrier.shape](body, carrier.name, route, f"{carrier.slug}/{path}.csv", caller.clock.now)
        log.append(f"      {path}: {len(got)} rows")
        rows += got
    return rows, month_window(months)


def fetch_capped(carrier, caller, route, crawl_date, log, trace):
    """SC-04: ask for a window; if the answer is exactly at the cap, split the window and ask again."""
    window = page_window(crawl_date)

    def ask(lo, hi, depth):
        body = caller.get(route.id, {"from": lo.isoformat(), "to": hi.isoformat()})
        got = PARSERS[carrier.shape](body, carrier.name, route, f"{carrier.slug}/{route.id}.json",
                                     caller.clock.now)
        indent = "      " + "  " * depth
        if len(got) < carrier.result_cap or lo == hi:
            log.append(f"{indent}{lo:%d %b}..{hi:%d %b}: {len(got)} results")
            return got
        log.append(f"{indent}{lo:%d %b}..{hi:%d %b}: {len(got)} results = the cap of {carrier.result_cap} "
                   f"-> later sailings may be missing, split the window [SC-04]")
        trace.hit("SC-04", f"{carrier.name} {route.id} {lo}..{hi}: hit cap {carrier.result_cap}, split")
        first, second = split_window(lo, hi)
        return ask(*first, depth + 1) + ask(*second, depth + 1)

    return ask(*window, 0), window


FETCH_PLANS = {"json_api": fetch_per_route, "html_table": fetch_per_route, "html_noyear": fetch_per_route,
               "csv_month": fetch_per_month, "json_capped": fetch_capped}


def make_site(carrier, day_dir):
    if carrier.shape == "json_capped":
        return CappedApi(day_dir, carrier.slug, carrier.result_cap, carrier.latency_s)
    return RecordedSite(day_dir, carrier.slug, EXTENSIONS[carrier.shape], carrier.latency_s)


# --- one carrier, then all carriers -------------------------------------------------------------

def crawl_carrier(carrier, day_dir, crawl_date, trace, real_factor=0.0):
    """Crawl every route of one carrier, one after another. Never raises for a bad route."""
    result = CarrierResult(carrier.name)
    log = result.log
    clock = SimClock(real_factor)
    caller = PoliteCaller(carrier, make_site(carrier, day_dir), clock, log, trace)
    log.append(f"  {carrier.name} ({carrier.shape}, {len(carrier.routes)} routes, "
               f"min gap {carrier.min_gap_s:g} s{f' + up to {carrier.jitter_s:g} s jitter' if carrier.jitter_s else ''})")
    for route in carrier.routes:
        calls_before = caller.calls
        try:
            rows, window = FETCH_PLANS[carrier.shape](carrier, caller, route, crawl_date, log, trace)
            result.raw_rows += rows
            result.routes.append(RouteResult(carrier.name, route, "ok", len(rows), "", window,
                                             caller.calls - calls_before))
            log.append(f"    {route.id:<12} OK      {len(rows):>3} rows   "
                       f"({caller.calls - calls_before} call{'s' if caller.calls - calls_before > 1 else ''}, "
                       f"clock {clock.now:5.1f} s)")
        except (FetchError, ParseError) as e:
            # SC-03: the failure goes into the result, not only into the log
            result.routes.append(RouteResult(carrier.name, route, "failed", 0, str(e), None,
                                             caller.calls - calls_before))
            trace.hit("SC-03", f"{carrier.name} {route.id}: {e}")
            log.append(f"    {route.id:<12} FAILED  {e}  [SC-03]")
    result.seconds, result.calls = clock.now, caller.calls
    return result


def crawl_all(carriers, day_dir, crawl_date, trace, real_factor=0.0):
    """SC-02: all carriers in parallel, each in its own error box. Returns results in config order."""

    def boxed(carrier):
        try:
            return crawl_carrier(carrier, day_dir, crawl_date, trace, real_factor)
        except Exception as e:                       # a bug or a surprise: record it, never stop the others
            res = CarrierResult(carrier.name, crashed=f"{type(e).__name__}: {e}")
            res.log += [f"  {carrier.name}: CRASHED {e}  [SC-02]",
                        *("    " + line for line in traceback.format_exc().splitlines()[-3:])]
            trace.hit("SC-02", f"{carrier.name} crashed: {e}")
            return res

    with ThreadPoolExecutor(max_workers=len(carriers), thread_name_prefix="crawl") as pool:
        results = list(pool.map(boxed, carriers))
    for res in results:
        if res.errors and not res.crashed:
            trace.hit("SC-02", f"{res.carrier}: {len(res.errors)} failed route(s) recorded; other carriers unaffected")
    return results

