"""CU-01 .. CU-06."""
import json

import pytest

from engine.customs import (CustomsResult, doubt_warnings, duty_and_vat, find_tariff_row, normalise_text,
                            procedure_fees, quote_is_in_document, rates_from_tariff, run_customs)
from engine.runlog import RunLog


@pytest.fixture
def tariff(sample_dir):
    from engine.customs import _csv
    return _csv(sample_dir / "customs" / "tariff.csv")


def lookup(sample_dir, llm, product="wood charcoal", trace=None, **kw):
    return run_customs(product, kw.pop("direction", "export"), kw.pop("value", 20000.0), sample_dir, llm,
                       RunLog(echo=False), trace, **kw)


class FixedLLM:
    name = "fixed"

    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, user):
        return self.reply


# CU-01 ------------------------------------------------------------------------------------
def test_cu01_code_in_the_tariff_is_found(tariff):
    assert find_tariff_row("44029000", tariff)["description"].startswith("Wood charcoal")
    assert find_tariff_row("4402.90.00", tariff) is not None              # punctuation is ignored


@pytest.mark.parametrize("code", ["44029999", "4402", "", "abc"])
def test_cu01_unknown_or_short_codes_are_not_found(tariff, code):
    assert find_tariff_row(code, tariff) is None


def test_cu01_an_invented_code_proposed_by_the_ai_is_rejected(sample_dir, mock_llm, trace):
    result = lookup(sample_dir, mock_llm, trace=trace)
    rejected = [(c, why) for c, ok, why, _ in result.candidates if not ok]
    assert rejected[0][0]["hs_code"] == "44029999" and "not in the tariff table" in rejected[0][1]
    assert result.hs_code == "44029000"


# CU-02 ------------------------------------------------------------------------------------
LEGAL = "Wood charcoal for export shall be declared under heading 4402 and requires an export permit issued before customs clearance."


def test_cu02_verbatim_quote_is_found(sample_dir):
    assert quote_is_in_document("fictional_decree_12_2026.txt", LEGAL, sample_dir / "customs" / "legal")


def test_cu02_case_accents_and_spacing_are_ignored(sample_dir):
    shouty = LEGAL.upper().replace(" ", "   ")
    assert quote_is_in_document("fictional_decree_12_2026.txt", shouty, sample_dir / "customs" / "legal")


def test_cu02_a_paraphrase_is_not_found(sample_dir):
    assert not quote_is_in_document("fictional_decree_12_2026.txt",
                                    "Charcoal needs a permit before it can leave the country.", sample_dir / "customs" / "legal")


def test_cu02_the_ai_cannot_point_at_a_file_outside_the_legal_folder(sample_dir):
    assert not quote_is_in_document("../tariff.csv", "hs_code", sample_dir / "customs" / "legal")


def test_cu02_verified_basis_is_shown_unverified_basis_is_not(sample_dir, mock_llm):
    good = lookup(sample_dir, mock_llm)
    bad = lookup(sample_dir, mock_llm, product="ceramic tiles", direction="import", value=10000.0)
    assert LEGAL in good.basis and bad.basis == ""
    assert any("could not be verified" in w for w in bad.warnings)


def test_normalise_text_removes_accents_and_punctuation():
    assert normalise_text("  Điều 3:  Wood-charcoal! ") == "dieu 3 wood charcoal"


# CU-03 ------------------------------------------------------------------------------------
def test_cu03_rates_are_copied_from_the_tariff_row(tariff):
    row = find_tariff_row("44029000", tariff)
    assert rates_from_tariff(row, "export") == {"duty_pct": 5.0, "vat_pct": 0.0, "licence": True, "inspection": "physical"}
    assert rates_from_tariff(row, "import")["duty_pct"] == 10.0


def test_cu03_rates_the_ai_writes_are_ignored(sample_dir):
    reply = json.dumps([{"hs_code": "44029000", "description": "x", "duty_pct": 99, "vat_pct": 99,
                         "legal_basis": {"document": "x", "quote": "x"}, "doubt": ""}])
    result = lookup(sample_dir, FixedLLM(reply))
    assert (result.duty_pct, result.vat_pct) == (5.0, 0.0)


# CU-04 ------------------------------------------------------------------------------------
def test_cu04_duty_is_rate_times_value():
    assert duty_and_vat(20000, 5, 0) == (1000.0, 0.0)


def test_cu04_vat_is_charged_on_value_plus_duty():
    duty, vat = duty_and_vat(10000, 10, 8)
    assert duty == 1000.0 and vat == 880.0                                # 8% of 11,000, not of 10,000


def test_cu04_an_import_lookup_uses_the_import_rates(sample_dir, mock_llm):
    result = lookup(sample_dir, mock_llm, product="ceramic tiles", direction="import", value=10000.0)
    assert (result.duty_usd, result.vat_usd) == (1200.0, 896.0)           # 12% duty, 8% VAT on 11,200


# CU-05 ------------------------------------------------------------------------------------
def test_cu05_licence_and_physical_inspection_add_their_fees(sample_dir, tariff):
    from engine.customs import _csv
    fees, notes = procedure_fees(rates_from_tariff(find_tariff_row("44029000", tariff), "export"),
                                 _csv(sample_dir / "customs" / "customs_fees.csv"))
    assert [n for n, _ in fees] == ["Customs declaration (broker fee)", "Licence processing", "Physical inspection handling"]
    assert any("licence" in n for n in notes) and any("physically" in n for n in notes)


def test_cu05_no_flags_means_only_the_broker_fee(sample_dir, tariff):
    from engine.customs import _csv
    fees, notes = procedure_fees(rates_from_tariff(find_tariff_row("09011110", tariff), "export"),
                                 _csv(sample_dir / "customs" / "customs_fees.csv"))
    assert len(fees) == 1 and notes == []


def test_cu05_document_inspection_adds_its_own_fee(sample_dir, mock_llm):
    result = lookup(sample_dir, mock_llm, product="ceramic tiles", direction="import", value=10000.0)
    assert [n for n, _ in result.fees] == ["Customs declaration (broker fee)", "Document inspection handling"]


# CU-06 ------------------------------------------------------------------------------------
def test_cu06_a_second_plausible_code_is_a_warning_not_a_silent_choice(sample_dir, mock_llm, trace):
    result = lookup(sample_dir, mock_llm, trace=trace)
    assert any("44021000" in w for w in result.warnings) and "CU-06" in trace.ids_for("customs")


def test_cu06_a_doubt_stated_by_the_ai_is_shown():
    warnings = doubt_warnings({"doubt": "could be bamboo"}, [], True, True)
    assert warnings == ["AI is unsure: could be bamboo"]


def test_cu06_no_ai_answer_asks_for_a_manual_hs_code(sample_dir, mock_llm):
    result = lookup(sample_dir, mock_llm, product="unknown gadget")
    assert not result.ok and any("enter the HS code by hand" in w for w in result.warnings)


def test_cu06_manual_hs_code_goes_through_the_same_checks(sample_dir, mock_llm, trace):
    result = lookup(sample_dir, mock_llm, product="unknown gadget", manual_hs="44021000", trace=trace)
    assert result.ok and result.source == "entered by staff" and result.duty_pct == 0.0
    assert not lookup(sample_dir, mock_llm, product="x", manual_hs="99999999").ok


def test_cu06_a_clean_answer_has_no_warning():
    assert doubt_warnings({"doubt": ""}, [], True, True) == []
