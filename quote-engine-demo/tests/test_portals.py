import pytest

from conftest import AS_OF
from engine.portals import (BUDGET_BASE_MIN, BUDGET_CAP_MIN, BUDGET_PER_CARRIER_MIN, PORTAL_ORDER,
                            RETRY_DELAYS_MIN, FakePortal, PortalReply, make_portals, run_budget,
                            run_portals)
from engine.runlog import RunLog


def run(req, carriers=None, portals=None):
    log = RunLog(echo=False)
    outcomes, first, total = run_portals(req, carriers or PORTAL_ORDER, portals or make_portals(), log, AS_OF)
    return {o.carrier: o for o in outcomes}, first, total, log


class Stub:
    """A portal with scripted replies: {run number: PortalReply}. Used to test the runner alone."""

    def __init__(self, replies):
        self.replies = replies

    def check_price(self, req, attempt):
        return self.replies.get(attempt, self.replies[max(self.replies)])


def ok(minutes, price=500.0):
    return PortalReply("ok", minutes, "", price)


def temp(minutes=0.5):
    return PortalReply("temporary", minutes, "site down")


# --- the shared budget -------------------------------------------------------------------
def test_budget_constants_match_the_real_system():
    assert (BUDGET_BASE_MIN, BUDGET_PER_CARRIER_MIN, BUDGET_CAP_MIN) == (2.0, 8.5, 30.0)
    assert RETRY_DELAYS_MIN == [10, 25]


@pytest.mark.parametrize("carriers, minutes", [(1, 10.5), (2, 19.0), (3, 27.5), (4, 30.0), (6, 30.0)])
def test_run_budget_is_2_plus_8_5_per_carrier_capped_at_30(carriers, minutes):
    assert run_budget(carriers) == minutes


def test_first_pass_budget_is_shared_by_all_carriers(general_lane):
    *_, log = run(general_lane)
    assert "first pass: 6 carriers, shared budget 30.0 min" in log.lines[0]


def test_retry_run_gets_a_smaller_budget_for_fewer_carriers(general_lane):
    *_, log = run(general_lane)
    text = "\n".join(log.lines)
    assert "retry 1: 2 carriers, shared budget 19.0 min" in text
    assert "retry 2: 1 carrier, shared budget 10.5 min" in text


def test_budget_exhaustion_stops_the_whole_run(general_lane):
    # One carrier, budget 10.5 min, but the portal needs 12 min: timeout, run stopped at the budget.
    portals = {"A": Stub({1: ok(12), 2: ok(2)})}
    out, first, total, log = run(general_lane, ["A"], portals)
    assert first == 10.5 and "timeout" in out["A"].attempts[0]
    assert out["A"].status == "price" and len(out["A"].attempts) == 2     # fixed in the retry run


def test_carriers_after_a_timeout_are_not_reached_and_go_to_the_retry_run(general_lane):
    portals = {"A": Stub({1: ok(1)}), "B": Stub({1: ok(99), 2: ok(1)}), "C": Stub({1: ok(1)})}
    out, first, _, log = run(general_lane, ["A", "B", "C"], portals)
    assert out["A"].status == "price" and len(out["A"].attempts) == 1      # finished before the stop
    assert "not reached" in "\n".join(log.lines)
    assert out["C"].status == "price" and len(out["C"].attempts) == 2      # C was never checked in run 1
    assert first == run_budget(3)


def test_hanging_portal_in_charcoal_run_stops_the_first_pass(charcoal_lane):
    out, first, _, _ = run(charcoal_lane)
    assert first == 30.0
    for name in ("Pacific Arrow", "Redsea Express", "Jade Ocean"):
        assert out[name].status == "price" and len(out[name].attempts) == 2
    assert out["Bluewave Lines"].status == "price" and len(out["Bluewave Lines"].attempts) == 1


# --- order, retries, final answers -----------------------------------------------------------
def test_carriers_are_checked_one_after_another_in_order(general_lane):
    *_, log = run(general_lane)
    names = [l.split()[0] for l in log.lines if l.split() and l.split()[0] in
             ("Bluewave", "Northstar", "Pacific", "Redsea", "Jade", "Kestrel")]
    assert names[:6] == ["Bluewave", "Northstar", "Pacific", "Redsea", "Jade", "Kestrel"]


def test_normal_carrier_gets_a_price_on_the_first_run(general_lane):
    out = run(general_lane)[0]["Bluewave Lines"]
    assert out.status == "price" and out.price.price_usd == 610 and len(out.attempts) == 1


def test_temporary_failure_is_retried_in_a_new_run_and_can_succeed(general_lane):
    out = run(general_lane)[0]["Northstar Shipping"]
    assert out.status == "price" and len(out.attempts) == 2 and "login problem" in out.attempts[0]


def test_retry_run_contains_only_the_carriers_that_failed(general_lane):
    *_, log = run(general_lane)
    assert any("only for: Northstar Shipping, Pacific Arrow" in l for l in log.lines)


def test_permanent_no_price_is_final_and_not_retried(general_lane):
    out = run(general_lane)[0]["Redsea Express"]
    assert out.status == "no_price" and len(out.attempts) == 1


def test_cargo_not_accepted_is_a_permanent_answer(charcoal_lane):
    out = run(charcoal_lane)[0]["Northstar Shipping"]
    assert out.status == "no_price" and "cargo" in out.message and len(out.attempts) == 1


def test_carrier_that_stays_down_gives_up_after_three_runs(general_lane):
    out = run(general_lane)[0]["Pacific Arrow"]
    assert out.status == "gave_up" and len(out.attempts) == 3 and out.price is None


def test_other_carriers_are_not_held_back_by_retry_waits(general_lane):
    _, first, total, _ = run(general_lane)
    assert first < 10 < total                 # the first run is short; the waits come after it


def test_total_time_includes_the_10_and_25_minute_waits(general_lane):
    _, _, total, _ = run(general_lane, ["Pacific Arrow"])
    assert total > 10 + 25


def test_lane_not_served_gives_no_price():
    from engine.request import build_request
    req = build_request("Da Nang", "Rotterdam", "40HC", "general")
    out = run(req, ["Bluewave Lines"])[0]["Bluewave Lines"]
    assert out.status == "no_price" and "not served" in out.message


def test_portals_can_only_check_prices_never_book():
    assert [n for n in dir(FakePortal) if not n.startswith("_")] == ["check_price"]
