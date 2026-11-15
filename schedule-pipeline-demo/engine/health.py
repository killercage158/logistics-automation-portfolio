"""Step 6: the health check. It does not trust the job's "success" (rule SC-16).

A crawl job says success when nothing crashed. That is true even when:
  - a carrier lost every route (its errors are inside its own result),
  - a route answered HTTP 200 with an empty table (a wrong port name looks exactly
    like "no sailings"),
  - a route returned far fewer rows than yesterday (a partial page, a login wall,
    a carrier site change).

So the check looks at every carrier and every configured route, and compares
today's row count with yesterday's:

  FAILED   the route errored                                  (SC-03, SC-16)
  ZERO     the route "succeeded" with zero rows               (SC-17)
  MISSING  a configured route was never reported at all       (SC-17)
  DROP     rows today <= half of yesterday's (yesterday >= 2) (SC-18)
  OK       none of the above

In production, this is a written checklist that a person or an AI assistant
follows every day; the same checks are coded here so they run every time.
"""
from dataclasses import dataclass, field

DROP_RATIO = 0.5             # today at or below half of yesterday = suspicious
DROP_MIN_YESTERDAY = 2       # ignore drops on routes that had almost nothing anyway


@dataclass
class RouteHealth:
    carrier: str
    route: str
    flag: str                    # OK, FAILED, ZERO, MISSING, DROP
    today: int
    yesterday: int               # -1 = no data for yesterday
    detail: str
    rule: str = ""


@dataclass
class CarrierHealth:
    carrier: str
    status: str                  # OK, PARTIAL, FAILED
    routes_ok: int
    routes_total: int
    rows_today: int
    rows_yesterday: int
    errors: list


@dataclass
class HealthReport:
    job_success: bool
    carriers: list = field(default_factory=list)
    routes: list = field(default_factory=list)

    @property
    def problems(self):
        return [r for r in self.routes if r.flag != "OK"]

    @property
    def healthy(self):
        return not self.problems


def check(carrier_results, configured, yesterday_counts, job_success, trace=None):
    """configured: {carrier name: [route ids]}. yesterday_counts: {(carrier, route): (status, rows)}."""
    report = HealthReport(job_success)
    if trace is not None and job_success:
        trace.hit("SC-16", "job reported success=true; reading each carrier's own errors instead")
    for cr in carrier_results:
        reported = {rr.route.id: rr for rr in cr.routes}
        route_rows = []
        for route_id in configured[cr.carrier]:
            y_status, y_rows = yesterday_counts.get((cr.carrier, route_id), (None, -1))
            rr = reported.get(route_id)
            if rr is None:
                h = RouteHealth(cr.carrier, route_id, "MISSING", 0, y_rows,
                                "configured but never reported: the crawl skipped or lost it", "SC-17")
            elif rr.status == "failed":
                h = RouteHealth(cr.carrier, route_id, "FAILED", 0, y_rows, rr.error, "SC-16")
            elif rr.rows == 0:
                h = RouteHealth(cr.carrier, route_id, "ZERO", 0, y_rows,
                                "answered OK with zero rows: wrong port name, empty page or site change?"
                                + (f" Yesterday: {y_rows}." if y_rows > 0 else ""), "SC-17")
            elif y_rows >= DROP_MIN_YESTERDAY and rr.rows <= y_rows * DROP_RATIO:
                fall = 100 * (y_rows - rr.rows) / y_rows
                h = RouteHealth(cr.carrier, route_id, "DROP", rr.rows, y_rows,
                                f"rows fell {fall:.0f}% vs yesterday ({y_rows} -> {rr.rows}): "
                                "possible silent data loss, check the carrier site", "SC-18")
            else:
                h = RouteHealth(cr.carrier, route_id, "OK", rr.rows, y_rows, "")
            if h.rule and trace is not None:
                trace.hit(h.rule, f"{cr.carrier} {route_id}: {h.flag}")
            route_rows.append(h)
        report.routes += route_rows
        ok = sum(1 for h in route_rows if h.flag == "OK")
        failed = sum(1 for h in route_rows if h.flag in ("FAILED", "MISSING"))
        status = "OK" if ok == len(route_rows) else ("FAILED" if failed == len(route_rows) else "PARTIAL")
        report.carriers.append(CarrierHealth(
            cr.carrier, status, ok, len(route_rows), sum(h.today for h in route_rows),
            sum(max(h.yesterday, 0) for h in route_rows), cr.errors))
    return report
