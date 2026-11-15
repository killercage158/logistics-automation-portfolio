"""The full lead, end to end (Booking + Trucking + Customs + dispatch + Sales Support)."""
import pytest

from conftest import AS_OF
from engine.lead import run_lead
from engine.report import render_combined_quote, render_lead_report
from engine.request import build_request
from engine.runlog import RunLog
from quote import run_quote


@pytest.fixture
def req():
    return build_request("Hai Phong", "Busan", "40HC", "charcoal")


def lead(sample_dir, mock_llm, req, **kw):
    return run_lead(req, "Bac Ninh", "wood charcoal", AS_OF, sample_dir, mock_llm, run_quote,
                    log=RunLog(echo=False), **kw)


def test_a_full_lead_produces_a_ready_combined_quote(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req)
    assert result.quote.status == "READY" and result.code.startswith("LD-20261116-")
    assert {"Booking", "Trucking"} == set(result.quote.picks)


def test_the_default_pick_is_the_recommended_option_of_each_department(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req)
    assert result.quote.picks["Booking"][0].carrier == result.booking.ranked[0].carrier
    assert result.quote.picks["Trucking"][0].haulier == result.trucking.options[0].haulier


def test_sales_support_can_pick_another_option_and_set_the_margin(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req, picks={"booking": 2, "trucking": 2}, margin=150)
    assert result.quote.picks["Booking"][0].carrier == result.booking.ranked[1].carrier
    assert result.quote.lines[0][2] == (result.booking.ranked[1].price.price_usd + 150)


def test_customs_duty_and_taxes_are_kept_apart_from_service_lines(sample_dir, mock_llm, req):
    q = lead(sample_dir, mock_llm, req).quote
    assert q.taxes_total == 1000.0 and all(s != "Government" for s, _, _ in q.lines)
    assert {s for s, _, _ in q.lines} >= {"Ocean freight", "Local charges", "Trucking", "Customs service"}


def test_the_timeline_shows_the_late_customs_department_and_its_reminder(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req)
    texts = [e.text for e in result.events]
    assert any("Customs: 30-minute deadline passed" in t for t in texts)
    assert any("reminder to Customs" in t for t in texts)
    assert texts[-1].startswith("every department has answered")


def test_a_declining_department_with_a_manual_entry_still_completes_the_lead(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req, declines={"Trucking": "no trailer free"},
                  manual_trucking=sample_dir / "manual_trucking_example.csv")
    trucking = next(i for i in result.items if i.department == "Trucking")
    assert trucking.status == "answered" and trucking.answer_kind == "manual" and result.quote.status == "READY"
    assert all(o.source == "manual" for o in result.trucking.options) and len(result.trucking.options) == 2


def test_a_declining_department_without_an_answer_leaves_a_draft(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req, declines={"Customs": "need the invoice first"})
    assert result.quote.status == "DRAFT" and any("Customs" in m for m in result.quote.missing)
    assert any("reminder to Customs" in e.text for e in result.events)


def test_a_manual_hs_code_answers_for_customs(sample_dir, mock_llm, req):
    result = run_lead(req, "Bac Ninh", "unknown gadget", AS_OF, sample_dir, mock_llm, run_quote,
                      manual_hs="44021000", log=RunLog(echo=False))
    assert result.customs.source == "entered by staff" and result.quote.status == "READY"


def test_two_containers_double_the_container_lines(sample_dir, mock_llm):
    q1 = lead(sample_dir, mock_llm, build_request("Hai Phong", "Busan", "40HC", "charcoal")).quote
    q2 = lead(sample_dir, mock_llm, build_request("Hai Phong", "Busan", "40HC", "charcoal", qty=2)).quote
    assert q2.lines[0][2] == 2 * q1.lines[0][2]


def test_the_lead_report_shows_the_timeline_the_departments_and_the_rule_ids(sample_dir, mock_llm, req):
    result = lead(sample_dir, mock_llm, req)
    html = render_lead_report(result)
    for needle in ("Dispatch timeline", "Booking: ocean freight", "Trucking: pickup to port", "Customs",
                   "Sales Support", "Rules applied", "DP-03", "TR-03", "CU-04", "SS-01", "LC-01", "FT-02"):
        assert needle in html
    assert html.index(result.code) < html.index("Dispatch timeline")


def test_the_combined_quote_is_a_clean_customer_document(sample_dir, mock_llm, req):
    html = render_combined_quote(lead(sample_dir, mock_llm, req))
    assert "Quotation" in html and "Government duty and VAT" in html
    assert "REJECTED" not in html and "rid" not in html.split("</style>")[1]      # no internal rule tags


def test_every_rule_family_fires_in_one_lead(sample_dir, mock_llm, req):
    ids = lead(sample_dir, mock_llm, req).trace.all_ids()
    assert {i[:2] for i in ids} == {"BK", "LC", "FT", "TR", "CU", "SS", "DP"}


def test_a_booking_decline_is_not_simulated(sample_dir, mock_llm, req):
    with pytest.raises(ValueError, match="not simulated"):
        lead(sample_dir, mock_llm, req, declines={"Booking": "busy"})
