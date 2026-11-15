"""Step 6: the health check does not trust success=true (SC-16 to SC-18)."""
from engine.health import check
from engine.models import CarrierResult, Route, RouteResult
from engine.rules import RuleTrace

R1, R2, R3 = Route("VNHPH", "KRPUS"), Route("VNHPH", "KRINC"), Route("VNHPH", "JPTYO")
CONFIG = {"Test Line": [R1.id, R2.id, R3.id]}


def result(*routes):
    return [CarrierResult("Test Line", routes=list(routes))]


def ok(route, rows):
    return RouteResult("Test Line", route, "ok", rows)


def flags(report):
    return {r.route: r.flag for r in report.routes}


def test_all_routes_fine_is_healthy():
    rep = check(result(ok(R1, 6), ok(R2, 6), ok(R3, 6)), CONFIG, {}, True)
    assert rep.healthy and rep.carriers[0].status == "OK"


def test_zero_rows_on_a_configured_route_is_a_problem():
    rep = check(result(ok(R1, 6), ok(R2, 0), ok(R3, 6)), CONFIG, {}, True)
    assert flags(rep)[R2.id] == "ZERO" and rep.carriers[0].status == "PARTIAL"


def test_route_never_reported_is_missing():
    rep = check(result(ok(R1, 6), ok(R2, 6)), CONFIG, {}, True)
    assert flags(rep)[R3.id] == "MISSING"


def test_row_count_drop_vs_yesterday_is_flagged_even_on_success():
    yesterday = {("Test Line", R1.id): ("ok", 9)}
    rep = check(result(ok(R1, 4), ok(R2, 6), ok(R3, 6)), CONFIG, yesterday, True, RuleTrace())
    route = next(r for r in rep.routes if r.route == R1.id)
    assert route.flag == "DROP" and "56%" in route.detail and route.rule == "SC-18"


def test_small_drop_is_not_flagged():
    yesterday = {("Test Line", R1.id): ("ok", 9)}
    assert flags(check(result(ok(R1, 6), ok(R2, 6), ok(R3, 6)), CONFIG, yesterday, True))[R1.id] == "OK"


def test_every_route_failed_means_carrier_failed_although_job_said_success():
    failed = [RouteResult("Test Line", r, "failed", 0, "HTTP 503") for r in (R1, R2, R3)]
    rep = check(result(*failed), CONFIG, {}, True)
    assert rep.job_success and rep.carriers[0].status == "FAILED" and len(rep.problems) == 3
