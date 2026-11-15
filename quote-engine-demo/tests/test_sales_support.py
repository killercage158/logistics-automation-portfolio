"""SS-01 .. SS-05."""
from datetime import date

import pytest

from conftest import AS_OF
from engine.customs import CustomsResult
from engine.models import Charge, Option, Price
from engine.request import build_request
from engine.sales_support import (apply_margin, build_combined_quote, count_options, enough_options,
                                  lead_code, pick_options)
from engine.trucking import TruckOption


def boption(carrier, freight, source="portal", local=245):
    return Option(Price(carrier, freight, date(2026, 12, 31), source, "t"), {"THC": Charge(local)}, None)


def toption(haulier, vnd, source="price file"):
    return TruckOption(haulier, vnd, 1.0, vnd, 1, date(2026, 12, 31), source, "t")


def customs_ok():
    return CustomsResult("wood charcoal", "export", 20000, hs_code="44029000", duty_pct=5, duty_usd=1000,
                         fees=[("Customs declaration (broker fee)", 1_200_000)])


REQ = build_request("Hai Phong", "Busan", "40HC", "charcoal")
BOOKING = [boption("A", 900), boption("B", 950)]
TRUCKING = [toption("T1", 4_000_000), toption("T2", 4_200_000)]


# SS-01 ------------------------------------------------------------------------------------
def test_ss01_without_a_pick_the_recommended_option_is_used_and_labelled_default(trace):
    chosen = pick_options(BOOKING, TRUCKING, {}, trace)
    assert chosen["Booking"][0].carrier == "A" and "default" in chosen["Booking"][1]
    assert "SS-01" in trace.ids_for("Booking")


def test_ss01_sales_support_can_pick_any_option_by_number():
    chosen = pick_options(BOOKING, TRUCKING, {"booking": 2, "trucking": 2})
    assert chosen["Booking"][0].carrier == "B" and chosen["Trucking"][0].haulier == "T2"
    assert "picked by Sales Support" in chosen["Booking"][1]


def test_ss01_an_option_number_that_does_not_exist_is_an_error():
    with pytest.raises(ValueError, match="no option number 3"):
        pick_options(BOOKING, TRUCKING, {"booking": 3})


def test_ss01_the_quote_is_built_from_the_pick_not_from_the_recommendation():
    quote = build_combined_quote("LD-1", REQ, BOOKING, TRUCKING, customs_ok(), {"booking": 2}, 100)
    assert "B (40HC x 1)" in quote.lines[0][1]


# SS-02 ------------------------------------------------------------------------------------
def test_ss02_margin_is_added_to_the_freight_cost(trace):
    assert apply_margin(900, 100, 1, trace) == 1000 and "SS-02" in trace.ids_for("quote")


def test_ss02_margin_applies_per_container():
    quote = build_combined_quote("LD-1", build_request("Hai Phong", "Busan", "40HC", "charcoal", 2),
                                 [boption("A", 900), boption("B", 950)], TRUCKING, customs_ok(), {}, 100)
    assert quote.lines[0][2] == (900 + 100) * 2


def test_ss02_the_quote_records_the_margin_sales_support_typed():
    assert build_combined_quote("LD-1", REQ, BOOKING, TRUCKING, customs_ok(), {}, 75).margin == 75


# SS-03 ------------------------------------------------------------------------------------
def test_ss03_enough_options_means_ready(trace):
    assert enough_options(2, 2, True, trace) == [] and "SS-03" in trace.ids_for("lead")


@pytest.mark.parametrize("nb, nt, customs, missing", [
    (1, 2, True, "Booking has 1"), (2, 0, True, "Trucking has 0"), (2, 2, False, "Customs has no verified")])
def test_ss03_a_shortage_is_named(nb, nt, customs, missing):
    assert any(missing in m for m in enough_options(nb, nt, customs))


def test_ss03_a_short_department_makes_the_quote_a_draft():
    quote = build_combined_quote("LD-1", REQ, BOOKING[:1], TRUCKING, customs_ok(), {}, 100)
    assert quote.status == "DRAFT" and quote.missing


def test_ss03_all_departments_enough_makes_the_quote_ready():
    assert build_combined_quote("LD-1", REQ, BOOKING, TRUCKING, customs_ok(), {}, 100).status == "READY"


# SS-04 ------------------------------------------------------------------------------------
def test_ss04_manual_options_count_like_any_other(trace):
    options = [boption("A", 900), boption("B", 950, source="manual")]
    assert count_options(options, trace) == 2 and "SS-04" in trace.ids_for("B")


def test_ss04_one_system_option_plus_one_manual_option_is_enough():
    mixed = [boption("A", 900), boption("M", 880, source="manual")]
    assert build_combined_quote("LD-1", REQ, mixed, TRUCKING, customs_ok(), {}, 100).status == "READY"


def test_ss04_a_manual_trucking_option_counts_too(trace):
    assert count_options([toption("T1", 1), toption("M", 1, source="manual")], trace) == 2
    assert "SS-04" in trace.ids_for("M")


# SS-05 ------------------------------------------------------------------------------------
def test_ss05_lead_code_is_readable_and_repeatable():
    code = lead_code(REQ, AS_OF, "Bac Ninh", "wood charcoal")
    assert code == lead_code(REQ, AS_OF, "Bac Ninh", "wood charcoal")
    assert code.startswith("LD-20261116-") and len(code) == 15


def test_ss05_different_leads_get_different_codes():
    assert lead_code(REQ, AS_OF, "Bac Ninh", "wood charcoal") != lead_code(REQ, AS_OF, "Ha Noi", "wood charcoal")


def test_ss05_the_code_comes_first_in_the_quote_document(sample_dir, mock_llm):
    from quote import run_quote
    from engine.lead import run_lead
    from engine.report import render_combined_quote
    lead = run_lead(REQ, "Bac Ninh", "wood charcoal", AS_OF, sample_dir, mock_llm, run_quote,
                    log=__import__("engine.runlog", fromlist=["RunLog"]).RunLog(echo=False))
    html = render_combined_quote(lead)
    assert html.index(lead.code) < html.index("Ocean freight")


# SS-06 ------------------------------------------------------------------------------------
import re

from engine.lead import run_lead                           # noqa: E402
from engine.report import render_combined_quote, render_customer_quote, render_lead_report   # noqa: E402
from engine.runlog import RunLog                           # noqa: E402
from engine.sales_support import customer_conditions       # noqa: E402

INTERNAL_PHRASES = ["copied file", "check it", "confirm the right", "plausible", "confirm before quoting",
                    "ask the carrier", "could not be verified", "confirm dangerous-goods declaration",
                    "far below the median", "no validity date", "carrier-specific", "AI is unsure"]


def lead_for(sample_dir, mock_llm, **kw):
    from quote import run_quote
    return run_lead(REQ, "Bac Ninh", "wood charcoal", AS_OF, sample_dir, mock_llm, run_quote,
                    log=RunLog(echo=False), **kw)


def customer_body(html):
    return html.split("</style>")[1]


def test_ss06_customer_conditions_are_written_for_the_customer(sample_dir, mock_llm):
    notes = lead_for(sample_dir, mock_llm).quote.customer_notes
    assert "Charcoal ships as dangerous goods: a DG declaration and suitable packing are required." in notes
    assert "An export licence is required before customs clearance." in notes
    assert "Goods are subject to physical inspection at the port." in notes
    assert notes[-1] == "Subject to space and equipment availability."


def test_ss06_the_customer_quotation_contains_no_internal_phrase(sample_dir, mock_llm):
    body = customer_body(render_combined_quote(lead_for(sample_dir, mock_llm)))
    for phrase in INTERNAL_PHRASES:
        assert phrase.lower() not in body.lower(), phrase


def test_ss06_no_rule_ids_file_names_cell_references_or_tool_words_on_the_customer_quotation(sample_dir, mock_llm):
    body = customer_body(render_combined_quote(lead_for(sample_dir, mock_llm)))
    assert not re.search(r"\b(BK|LC|FT|TR|CU|SS|DP)-\d\d\b", body)
    assert not re.search(r"\.xlsx|\.csv|\.txt|/ Rate|\b[A-Z]{1,2}[0-9]{1,3}\b", body.replace("USD", "").replace("VND", ""))
    text = re.sub(r"<[^>]+>", " ", body)
    for word in ("mock", "verified", "rejected", "warning", "fixture", "simulated"):
        assert word not in text.lower(), word
    assert not re.search(r"AI", text)


def test_ss06_the_internal_lead_report_still_shows_every_doubt(sample_dir, mock_llm):
    html = render_lead_report(lead_for(sample_dir, mock_llm))
    assert "Internal notes: never shown to the customer" in html
    for phrase in ("possible copied file", "confirm the right one", "confirm dangerous-goods declaration"):
        assert phrase in html


def test_ss06_internal_flags_are_collected_in_internal_notes(sample_dir, mock_llm, trace):
    quote = lead_for(sample_dir, mock_llm).quote
    text = " ".join(quote.internal_notes)
    assert "possible copied file" in text and "other plausible HS codes" in text and "dangerous-goods" in text
    assert not set(quote.internal_notes) & set(quote.customer_notes)


def test_ss06_a_draft_quotation_does_not_say_what_is_missing(sample_dir, mock_llm):
    lead = lead_for(sample_dir, mock_llm, declines={"Customs": "need the invoice"})
    html = render_combined_quote(lead)
    assert "DRAFT" in html and "not final" in html and "Customs has no verified answer" not in html
    assert "Customs has no verified answer" in render_lead_report(lead)


def test_ss06_the_single_lane_customer_quote_also_hides_internal_flags(sample_dir, mock_llm):
    from engine.request import build_request
    from quote import run_quote
    req = build_request("Hai Phong", "Busan", "40HC", "charcoal")
    html = render_customer_quote(run_quote(req, AS_OF, sample_dir, mock_llm, log=RunLog(echo=False)), 100)
    assert "dangerous goods" in html and "confirm dangerous-goods" not in html and "before quoting" not in html


def test_ss06_general_cargo_gets_no_dangerous_goods_condition(general_lane):
    assert customer_conditions(general_lane) == ["Subject to space and equipment availability."]


def test_ss06_the_rule_is_traced(sample_dir, mock_llm):
    assert "SS-06" in lead_for(sample_dir, mock_llm).trace.all_ids()
