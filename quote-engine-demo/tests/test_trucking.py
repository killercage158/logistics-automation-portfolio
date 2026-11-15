"""TR-01 .. TR-07."""
from datetime import date, timedelta

import pytest

from conftest import AS_OF
from engine.ai_reader import system_prompt
from engine.runlog import RunLog
from engine.trucking import (OUTPUT_SPEC, FIXED_SHARE, TruckOption, current_diesel, drop_expired,
                             flag_duplicate_prices, fuel_factor, rank_alternatives, read_haulier_file,
                             run_trucking, truck_for_container)
from engine.verify import verify_haulier_row


@pytest.fixture
def lead_request():
    from engine.request import build_request
    return build_request("Hai Phong", "Busan", "40HC", "charcoal")


def run(sample_dir, mock_llm, req, trace, **kw):
    return run_trucking(req, "Bac Ninh", AS_OF, sample_dir, mock_llm, RunLog(echo=False), trace, **kw)


def opt(haulier, quoted, source="price file", valid=AS_OF + timedelta(days=30), factor=1.0):
    return TruckOption(haulier, quoted, factor, quoted * factor, 1, valid, source, "t")


# TR-01 ------------------------------------------------------------------------------------
def test_tr01_the_ai_prompt_contains_the_trucking_skill_file():
    prompt = system_prompt("trucking-rates", OUTPUT_SPEC)
    assert "TR-03 Fuel-indexed price" in prompt and "diesel_source" in prompt


def test_tr01_every_haulier_file_is_read_whatever_its_layout(sample_dir, mock_llm):
    counts = {}
    for path in sorted((sample_dir / "trucking").glob("*.xlsx")):
        rows, problems = read_haulier_file(mock_llm, path, RunLog(echo=False))
        counts[path.stem] = (len(rows), len(problems))
    assert counts == {"alpha_transport": (7, 0), "beta_transport": (9, 0), "gamma_haulage": (2, 0)}


def test_tr01_a_run_records_which_files_the_ai_read(sample_dir, mock_llm, lead_request, trace):
    run(sample_dir, mock_llm, lead_request, trace)
    assert trace.count("TR-01") == 3


# TR-02 ------------------------------------------------------------------------------------
def test_tr02_wrong_cell_is_rejected(sample_dir, mock_llm, lead_request, trace):
    result = run(sample_dir, mock_llm, lead_request, trace)
    why = [w for r, ok, w in result.verified if not ok and r.haulier == "Beta Transport"][0]
    assert "holds '2.900.000'" in why


def test_tr02_invented_price_is_rejected_because_the_cell_is_empty(sample_dir, mock_llm, lead_request, trace):
    result = run(sample_dir, mock_llm, lead_request, trace)
    assert any("is empty" in w for r, ok, w in result.verified if not ok and r.haulier == "Alpha Transport")


def test_tr02_all_other_rows_pass_including_text_and_email_layouts(sample_dir, mock_llm, lead_request, trace):
    result = run(sample_dir, mock_llm, lead_request, trace)
    assert sum(1 for _, ok, _ in result.verified if ok) == 16


def test_tr02_the_diesel_cell_is_checked_too(sample_dir, mock_llm):
    path = sample_dir / "trucking" / "alpha_transport.xlsx"
    rows, _ = read_haulier_file(mock_llm, path, RunLog(echo=False))
    good = rows[0]
    assert verify_haulier_row(good, sample_dir / "trucking")[0]
    good.diesel_base_vnd = 25000
    ok, why = verify_haulier_row(good, sample_dir / "trucking")
    assert not ok and why.startswith("diesel base")


def test_tr02_the_truck_type_must_be_named_by_the_cited_column(sample_dir, mock_llm):
    path = sample_dir / "trucking" / "alpha_transport.xlsx"
    row = read_haulier_file(mock_llm, path, RunLog(echo=False))[0][0]      # a 20ft price (column C)
    row.truck = "40ft"
    ok, why = verify_haulier_row(row, sample_dir / "trucking")
    assert not ok and "40ft" in why


# TR-03 ------------------------------------------------------------------------------------
def test_tr03_price_moves_with_diesel_using_the_made_up_split():
    assert FIXED_SHARE == 0.70
    assert fuel_factor(22000, 20000) == pytest.approx(0.70 + 0.30 * 1.1)
    assert fuel_factor(20000, 20000) == pytest.approx(1.0)
    assert fuel_factor(18000, 20000) < 1.0                              # cheaper diesel lowers the price


def test_tr03_unknown_diesel_leaves_the_price_unchanged():
    assert fuel_factor(None, 20000) == 1.0


def test_tr03_latest_diesel_on_or_before_the_pricing_date(sample_dir):
    from engine.trucking import _csv
    rows = _csv(sample_dir / "diesel_price.csv")
    assert current_diesel(rows, AS_OF) == 22000
    assert current_diesel(rows, date(2026, 11, 5)) == 21400
    assert current_diesel(rows, date(2026, 9, 1)) is None


def test_tr03_options_carry_the_adjusted_price(sample_dir, mock_llm, lead_request, trace):
    options = run(sample_dir, mock_llm, lead_request, trace).options
    assert {o.haulier: o.adjusted_vnd for o in options} == {"Beta Transport": 4159000, "Alpha Transport": 4223000}


# TR-04 ------------------------------------------------------------------------------------
def test_tr04_expired_quote_is_dropped_and_listed(trace):
    kept, dropped = drop_expired([opt("A", 100, valid=AS_OF - timedelta(days=1)), opt("B", 100)], AS_OF, trace)
    assert [o.haulier for o in kept] == ["B"] and dropped[0][2] == "TR-04"


def test_tr04_the_expired_email_quote_is_left_out_of_the_run(sample_dir, mock_llm, lead_request, trace):
    result = run(sample_dir, mock_llm, lead_request, trace)
    assert any("Gamma" in text and "expired" in why for text, why, _ in result.dropped)


# TR-05 ------------------------------------------------------------------------------------
@pytest.mark.parametrize("container, truck", [("20GP", "20ft"), ("40GP", "40ft"), ("40HC", "40ft")])
def test_tr05_truck_type_follows_the_container(container, truck):
    assert truck_for_container(container) == truck


def test_tr05_a_20gp_request_uses_the_20ft_prices(sample_dir, mock_llm, trace):
    from engine.request import build_request
    req = build_request("Hai Phong", "Busan", "20GP", "general")
    options = run(sample_dir, mock_llm, req, trace).options
    assert {o.quoted_vnd for o in options} == {3200000, 3050000}


# TR-06 ------------------------------------------------------------------------------------
def test_tr06_every_verified_haulier_stays_in_the_ranked_list(sample_dir, mock_llm, lead_request, trace):
    options = run(sample_dir, mock_llm, lead_request, trace).options
    assert [o.haulier for o in options] == ["Beta Transport", "Alpha Transport"]


def test_tr06_ranking_is_by_total_and_removes_nothing():
    ranked = rank_alternatives([opt("B", 500), opt("A", 400), opt("C", 400)])
    assert [o.haulier for o in ranked] == ["A", "C", "B"]


def test_tr06_two_trips_double_the_total(sample_dir, mock_llm, trace):
    from engine.request import build_request
    req = build_request("Hai Phong", "Busan", "40HC", "charcoal", qty=2)
    best = run(sample_dir, mock_llm, req, trace).options[0]
    assert best.total_vnd == 2 * best.adjusted_vnd


# TR-07 ------------------------------------------------------------------------------------
def test_tr07_identical_quoted_prices_from_two_hauliers_are_flagged_not_dropped(trace):
    options = flag_duplicate_prices([opt("A", 4100000), opt("B", 4100000), opt("C", 3900000)], trace)
    assert len(options) == 3
    assert any("same quoted price as B" in f for f in options[0].flags) and not options[2].flags
    assert "TR-07" in trace.ids_for("A")


def test_tr07_the_same_haulier_twice_is_not_a_duplicate():
    assert not any(o.flags for o in flag_duplicate_prices([opt("A", 100), opt("A", 100)]))


def test_tr07_flags_appear_in_the_lead_run(sample_dir, mock_llm, lead_request, trace):
    assert all(any("possible copied file" in f for f in o.flags) for o in run(sample_dir, mock_llm, lead_request, trace).options)
