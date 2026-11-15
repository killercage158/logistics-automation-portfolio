"""One or more tests per booking rule (BK-01 .. BK-09). Test names start with the rule ID."""
from datetime import timedelta

import pytest
from openpyxl import Workbook

from conftest import AS_OF
from engine.manual import load_manual
from engine.models import Option, Price, PriceRow
from engine.portals import FakePortal, PortalReply, assert_price_check_only, make_portals, run_portals
from engine.rules import (canonical_carrier, charcoal_handling_flags, choose_per_carrier, filter_cargo,
                          filter_validity, flag_doubtful)
from engine.runlog import RunLog
from engine.verify import verify_row


def price(carrier="A", usd=100, valid=AS_OF + timedelta(days=10), source="portal", cargo=None):
    return Price(carrier, usd, valid, source, "test", cargo)


def option(carrier, usd, valid=AS_OF + timedelta(days=30), source="portal"):
    return Option(price(carrier, usd, valid, source), {}, None)


# BK-01 ------------------------------------------------------------------------------------
def test_bk01_price_check_only_accepts_the_fake_portals():
    for portal in make_portals().values():
        assert_price_check_only(portal)


def test_bk01_an_adapter_that_can_book_is_refused():
    class Booker:
        def check_price(self, req, attempt): ...
        def book_space(self): ...
    with pytest.raises(RuntimeError, match="booking"):
        assert_price_check_only(Booker())


def test_bk01_portal_adapters_expose_nothing_but_check_price():
    assert [n for n in dir(FakePortal) if not n.startswith("_")] == ["check_price"]


# BK-02 ------------------------------------------------------------------------------------
def test_bk02_valid_contract_skips_the_portal_and_is_traced(sample_dir, general_lane, trace):
    from engine.contracts import carriers_for_portal, find_contracts, load_contracts
    valid, _ = find_contracts(load_contracts(sample_dir / "contracts.csv"), general_lane, AS_OF, trace)
    assert "Jade Ocean" not in carriers_for_portal(["Jade Ocean", "Kestrel Line"], valid)
    assert "BK-02" in trace.ids_for("Jade Ocean")


def test_bk02_expired_contract_keeps_the_portal_check(sample_dir, charcoal_lane, trace):
    from engine.contracts import carriers_for_portal, find_contracts, load_contracts
    valid, ignored = find_contracts(load_contracts(sample_dir / "contracts.csv"), charcoal_lane, AS_OF, trace)
    assert "Redsea Express" in carriers_for_portal(["Redsea Express"], valid) and ignored


# BK-03 ------------------------------------------------------------------------------------
def test_bk03_live_portal_price_beats_a_cheaper_price_file():
    chosen, superseded = choose_per_carrier([price(usd=500, source="price file"), price(usd=600)])
    assert chosen["A"].source == "portal" and superseded[0][2] == "BK-03"


def test_bk03_order_of_trust_is_contract_manual_portal_file():
    sources = ["price file", "portal", "manual", "contract"]
    chosen, _ = choose_per_carrier([price(usd=100 + i, source=s) for i, s in enumerate(sources)])
    assert chosen["A"].source == "contract"
    chosen, _ = choose_per_carrier([price(source=s) for s in sources[:3]])
    assert chosen["A"].source == "manual"


def test_bk03_cheapest_wins_inside_the_same_source():
    assert choose_per_carrier([price(usd=700), price(usd=650)])[0]["A"].price_usd == 650


# BK-04 ------------------------------------------------------------------------------------
def test_bk04_expired_price_is_dropped_with_reason_and_rule_id(trace):
    kept, dropped = filter_validity([price(valid=AS_OF - timedelta(days=1)), price(carrier="B")], AS_OF, trace)
    assert [p.carrier for p in kept] == ["B"]
    assert "expired" in dropped[0][1] and dropped[0][2] == "BK-04" and trace.count("BK-04") == 1


def test_bk04_price_valid_today_is_kept():
    assert len(filter_validity([price(valid=AS_OF)], AS_OF)[0]) == 1


# BK-05 ------------------------------------------------------------------------------------
def test_bk05_missing_validity_date_is_flagged_not_dropped(trace):
    options = [option("A", 600, valid=None), option("B", 610), option("C", 620)]
    flag_doubtful(options, AS_OF, trace)
    assert len(options) == 3 and any("no validity date" in f for f in options[0].flags)
    assert "BK-05" in trace.ids_for("A")


def test_bk05_price_far_below_the_median_is_flagged():
    options = [option("A", 200), option("B", 610), option("C", 620), option("D", 630)]
    flag_doubtful(options, AS_OF)
    assert any("far below the median" in f for f in options[0].flags)
    assert not options[1].flags


def test_bk05_price_from_a_spreadsheet_says_confirm_before_quoting():
    options = [option("A", 600, source="price file")]
    flag_doubtful(options, AS_OF)
    assert any("before quoting" in f for f in options[0].flags)


def test_bk05_validity_ending_within_a_week_is_flagged():
    options = [option("A", 600, valid=AS_OF + timedelta(days=3))]
    flag_doubtful(options, AS_OF)
    assert any("valid only until" in f for f in options[0].flags)


# BK-06 ------------------------------------------------------------------------------------
def test_bk06_price_for_the_other_cargo_is_not_used(trace):
    kept, dropped = filter_cargo([price(cargo="general"), price(carrier="B", cargo=None)], "charcoal", trace)
    assert [p.carrier for p in kept] == ["B"] and dropped[0][2] == "BK-06"


def test_bk06_charcoal_gets_a_handling_note_general_does_not(charcoal_lane, general_lane):
    assert any("dangerous-goods" in f for f in charcoal_handling_flags(charcoal_lane, "A"))
    assert charcoal_handling_flags(general_lane, "A") == []


def test_bk06_a_carrier_that_refuses_charcoal_gives_a_final_answer(charcoal_lane, trace):
    outcomes, *_ = run_portals(charcoal_lane, ["Northstar Shipping"], make_portals(), RunLog(echo=False), AS_OF, trace=trace)
    assert outcomes[0].status == "no_price" and "BK-06" in trace.ids_for("Northstar Shipping")


# BK-07 ------------------------------------------------------------------------------------
def test_bk07_manual_price_matches_the_lane_and_is_labelled_manual(sample_dir, general_lane, trace):
    prices = load_manual(sample_dir / "manual_prices_example.csv", general_lane, trace)
    assert len(prices) == 1 and prices[0].source == "manual" and "BK-07" in trace.ids_for("Redsea Express")


def test_bk07_manual_price_is_for_this_request_only(sample_dir, charcoal_lane):
    # the example file has a Hai Phong -> Singapore price; it must not leak into a charcoal Busan request
    assert all(p.carrier == "Pacific Arrow" for p in load_manual(sample_dir / "manual_prices_example.csv", charcoal_lane))


# BK-08 ------------------------------------------------------------------------------------
class Stub:
    def __init__(self, *replies):
        self.replies = list(replies)

    def check_price(self, req, attempt):
        return self.replies[min(attempt, len(self.replies)) - 1]


def test_bk08_temporary_failure_is_retried_in_a_new_run(general_lane, trace):
    portals = {"A": Stub(PortalReply("temporary", 0.5, "site down"), PortalReply("ok", 1.0, "", 500.0))}
    out, *_ = run_portals(general_lane, ["A"], portals, RunLog(echo=False), AS_OF, trace=trace)
    assert out[0].status == "price" and len(out[0].attempts) == 2 and "BK-08" in trace.ids_for("A")


def test_bk08_no_price_is_final_and_never_retried(general_lane):
    portals = {"A": Stub(PortalReply("no_price", 0.5, "no service"))}
    out, *_ = run_portals(general_lane, ["A"], portals, RunLog(echo=False), AS_OF)
    assert out[0].status == "no_price" and len(out[0].attempts) == 1


def test_bk08_a_carrier_that_keeps_failing_gives_up_after_three_runs(general_lane):
    portals = {"A": Stub(PortalReply("temporary", 0.5, "site down"))}
    out, *_ = run_portals(general_lane, ["A"], portals, RunLog(echo=False), AS_OF)
    assert out[0].status == "gave_up" and len(out[0].attempts) == 3


# BK-09 ------------------------------------------------------------------------------------
@pytest.fixture
def book(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Rates"
    ws.append(["Hai Phong", "Singapore", 610])
    wb.save(tmp_path / "t.xlsx")
    return tmp_path


def row(price=610, cell="C1", pod="Singapore"):
    return PriceRow("X", "Hai Phong", pod, "40HC", None, price, None, "t.xlsx", "Rates", cell)


def test_bk09_matching_cell_is_accepted_and_traced(book, trace):
    assert verify_row(row(), book, trace)[0] and "BK-09" in trace.ids_for("X")


def test_bk09_wrong_number_is_rejected_with_both_numbers(book):
    ok, why = verify_row(row(price=650), book)
    assert not ok and "610" in why and "650" in why


def test_bk09_empty_cell_is_rejected(book):
    assert "empty" in verify_row(row(cell="C9"), book)[1]


def test_bk09_row_that_names_another_port_is_rejected(book):
    ok, why = verify_row(row(pod="Busan"), book)
    assert not ok and "does not mention Busan" in why


@pytest.mark.parametrize("written", ["BLUEWAVE LINES", "bluewave lines", "Bluewave Lines "])
def test_carrier_names_are_matched_whatever_the_spelling(written):
    assert canonical_carrier(written, ["Bluewave Lines"]) == "Bluewave Lines"
