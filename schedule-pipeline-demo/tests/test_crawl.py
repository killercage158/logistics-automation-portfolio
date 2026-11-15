"""Step 1: polite fetching, retries, window split, error isolation (SC-01 to SC-04)."""
import json
from datetime import date

import pytest

from conftest import DAY1, DAY2, FIXTURES
from engine.carriers import CARRIERS, Carrier, carrier_by_name
from engine.crawl import (FetchError, PoliteCaller, SimClock, crawl_all, crawl_carrier, month_window, months_of,
                          split_window)
from engine.models import Route
from engine.rules import RuleTrace
from engine.sites import RecordedSite


def write_site(tmp_path, incidents, files=None, slug="test_line"):
    day = tmp_path / "day"
    (day / slug).mkdir(parents=True)
    (day / "incidents.json").write_text(json.dumps({slug: incidents}), encoding="utf-8")
    for name, text in (files or {"A-B.json": "{}"}).items():
        (day / slug / name).write_text(text, encoding="utf-8")
    return day


def caller_for(day, carrier=None):
    carrier = carrier or Carrier("Test Line", "test_line", "json_api", min_gap_s=2.0)
    clock, log = SimClock(), []
    return PoliteCaller(carrier, RecordedSite(day, "test_line", "json"), clock, log, RuleTrace()), clock, log


def test_minimum_gap_between_calls(tmp_path):
    caller, clock, _ = caller_for(write_site(tmp_path, {}))
    caller.get("A-B")
    first_done = clock.now
    caller.get("A-B")
    assert clock.now - first_done >= 2.0 + 0.8           # waited the gap, then the answer took 0.8 s


def test_temporary_error_is_retried_then_succeeds(tmp_path):
    caller, _, log = caller_for(write_site(tmp_path, {"A-B": ["503", "503"]}))
    assert caller.get("A-B") == "{}"
    assert caller.calls == 3 and sum("SC-01" in line for line in log) == 2


def test_permanent_error_is_not_retried(tmp_path):
    caller, _, _ = caller_for(write_site(tmp_path, {}))
    with pytest.raises(FetchError, match="404 - permanent"):
        caller.get("NO-ROUTE")
    assert caller.calls == 1


def test_rate_limit_waits_do_not_use_up_attempts(tmp_path):
    caller, clock, _ = caller_for(write_site(tmp_path, {"A-B": ["429", "429", "503", "503"]}))
    assert caller.get("A-B") == "{}"
    assert caller.calls == 5 and clock.now >= 2 * 60


def test_timeout_costs_time_and_is_retried(tmp_path):
    caller, clock, _ = caller_for(write_site(tmp_path, {"A-B": ["timeout"]}))
    assert caller.get("A-B") == "{}" and clock.now >= 30


def test_gives_up_after_three_attempts(tmp_path):
    caller, _, _ = caller_for(write_site(tmp_path, {"A-B": ["500", "500", "500"]}))
    with pytest.raises(FetchError, match="all 3 attempts"):
        caller.get("A-B")


def test_capped_api_window_is_split_until_every_sailing_is_found():
    jade = carrier_by_name("Jade Ocean")
    trace = RuleTrace()
    res = crawl_carrier(jade, FIXTURES / "day1", DAY1, trace)
    route = next(r for r in res.routes if r.route.id == "VNHPH-SGSIN")
    assert route.rows == 12 > jade.result_cap and route.calls == 3 and trace.count("SC-04") == 1


def test_failed_route_is_written_into_the_carrier_result():
    res = crawl_carrier(carrier_by_name("Pacific Arrow"), FIXTURES / "day2", DAY2, RuleTrace())
    assert res.errors == ["Route VNHPH-JPTYO: HTTP 503 on all 3 attempts",
                          "Route VNSGN-KRINC: HTTP 503 on all 3 attempts"]


def test_one_carrier_crashing_does_not_stop_the_others(monkeypatch):
    import engine.crawl as crawl
    real = crawl.FETCH_PLANS["html_table"]

    def boom(carrier, *a, **kw):
        if carrier.name == "Northstar Shipping":
            raise RuntimeError("parser bug")
        return real(carrier, *a, **kw)

    monkeypatch.setitem(crawl.FETCH_PLANS, "html_table", boom)
    trace = RuleTrace()
    results = crawl_all(CARRIERS, FIXTURES / "day1", DAY1, trace)
    northstar = next(r for r in results if r.carrier == "Northstar Shipping")
    others = [r for r in results if r.carrier != "Northstar Shipping"]
    assert "parser bug" in northstar.crashed and all(not r.crashed and r.raw_rows for r in others)
    assert trace.count("SC-02") >= 1


def test_a_missing_carrier_site_fails_only_that_carrier(tmp_path):
    ghost = Carrier("Ghost Line", "ghost_line", "json_api", [Route("VNHPH", "KRPUS")])
    results = crawl_all([ghost, carrier_by_name("Bluewave Lines")], FIXTURES / "day1", DAY1, RuleTrace())
    assert results[0].errors and "404" in results[0].errors[0]
    assert not results[1].errors and len(results[1].raw_rows) == 18


def test_month_helpers():
    assert months_of((date(2026, 11, 17), date(2026, 12, 28))) == ["202611", "202612"]
    assert month_window(["202611", "202612"]) == (date(2026, 11, 1), date(2026, 12, 31))
    assert split_window(date(2026, 11, 1), date(2026, 11, 10)) == (
        (date(2026, 11, 1), date(2026, 11, 5)), (date(2026, 11, 6), date(2026, 11, 10)))
