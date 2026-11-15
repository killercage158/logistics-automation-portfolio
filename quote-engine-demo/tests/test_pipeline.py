"""End-to-end tests: the whole pipeline with the recorded (mock) AI answers."""
from conftest import AS_OF, ROOT
from engine.llm import MockLLM
from engine.manual import load_manual
from engine.report import render_comparison, render_customer_quote
from engine.runlog import RunLog
from quote import run_quote


def run(sample_dir, req, manual=None):
    return run_quote(req, AS_OF, sample_dir, MockLLM(ROOT / "fixtures"), manual, RunLog(echo=False))


def test_general_lane_recommends_the_contract_carrier(sample_dir, general_lane):
    result = run(sample_dir, general_lane)
    assert result.recommendation.option.carrier == "Jade Ocean"
    assert [o.carrier for o in result.ranked][:3] == ["Jade Ocean", "Bluewave Lines", "Kestrel Line"]


def test_contract_carrier_was_not_checked_on_the_portal(sample_dir, general_lane):
    jade = next(o for o in run(sample_dir, general_lane).portal_outcomes if o.carrier == "Jade Ocean")
    assert jade.status == "contract" and jade.attempts == []


def test_wrong_cell_and_invented_price_are_rejected_and_visible(sample_dir, general_lane):
    result = run(sample_dir, general_lane)
    reasons = [why for _, ok, why in result.verified if not ok]
    assert len(reasons) == 2
    assert any("holds 'USD 600'" in r for r in reasons) and any("is empty" in r for r in reasons)
    html = render_comparison(result)
    assert "Why rejected" in html and "is empty" in html


def test_price_file_fills_the_gap_when_a_portal_is_down(sample_dir, general_lane):
    pacific = next(o for o in run(sample_dir, general_lane).ranked if o.carrier == "Pacific Arrow")
    assert pacific.price.source == "price file" and pacific.price.price_usd == 655


def test_expired_file_price_is_listed_as_left_out(sample_dir, general_lane):
    dropped = run(sample_dir, general_lane).dropped
    assert any("expired" in why and p.price_usd == 620 for p, why, _ in dropped)


def test_charcoal_lane_uses_charcoal_contract_and_ignores_expired_one(sample_dir, charcoal_lane):
    result = run(sample_dir, charcoal_lane)
    kestrel = next(o for o in result.ranked if o.carrier == "Kestrel Line")
    assert kestrel.price.source == "contract" and kestrel.local_charges["THC"].usd == 230   # carrier + cargo table
    assert result.recommendation.option.carrier == "Bluewave Lines"                         # cheaper all-in than the contract
    assert result.contracts_ignored and "Redsea Express" not in result.contracts_used


def test_manual_price_flows_into_the_same_ranking(sample_dir, general_lane):
    manual = sample_dir / "manual_prices_example.csv"
    assert len(load_manual(manual, general_lane)) == 1
    result = run(sample_dir, general_lane, manual)
    best = result.recommendation.option
    assert best.carrier == "Redsea Express" and best.price.source == "manual"


def test_reports_are_written_as_html(sample_dir, general_lane):
    result = run(sample_dir, general_lane)
    assert "Recommendation: Jade Ocean" in render_comparison(result)
    quote = render_customer_quote(result, 100)
    assert "Quotation" in quote and "690" in quote          # 590 freight + 100 margin
    assert "Pacific Arrow" not in quote
