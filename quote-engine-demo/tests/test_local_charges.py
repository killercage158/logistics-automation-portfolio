"""LC-01 .. LC-04."""
from conftest import AS_OF
from engine.local_charges import (charge_cascade, charge_unit, missing_required_fees, remove_included_fees)
from engine.models import Charge, Option, Price
from engine.request import build_request
from engine.rules import build_option


def test_lc01_general_table_is_the_fallback(tables, general_lane):
    general, specific, _ = tables
    charges = charge_cascade("Bluewave Lines", general_lane, general, specific)
    assert {k: c.usd for k, c in charges.items()} == {"THC": 165, "DOC": 45, "SEAL": 10, "TLX": 25}
    assert {c.source for c in charges.values()} == {"general table"}


def test_lc01_carrier_table_beats_general_and_general_fills_the_rest(tables, general_lane, trace):
    general, specific, _ = tables
    charges = charge_cascade("Kestrel Line", general_lane, general, specific, trace)
    assert charges["THC"].usd == 195 and charges["THC"].source == "Kestrel Line table"
    assert charges["DOC"].source == "general table"
    assert "LC-01" in trace.ids_for("Kestrel Line")


def test_lc01_carrier_plus_cargo_table_beats_the_carrier_table(tables, charcoal_lane):
    general, specific, _ = tables
    assert charge_cascade("Kestrel Line", charcoal_lane, general, specific)["THC"].usd == 230


def test_lc01_another_carriers_table_is_not_used(tables, general_lane):
    general, specific, _ = tables
    assert charge_cascade("Bluewave Lines", general_lane, general, specific)["THC"].usd == 165


def test_lc02_complete_tables_have_no_missing_fee(tables, general_lane, trace):
    general, specific, _ = tables
    charges = charge_cascade("Bluewave Lines", general_lane, general, specific)
    assert missing_required_fees("Bluewave Lines", charges, general_lane, trace) == []
    assert "LC-02" in trace.ids_for("Bluewave Lines")


def test_lc02_missing_required_fee_is_flagged_on_the_option(tables, general_lane):
    general, specific, free = tables
    option = build_option(Price("Bluewave Lines", 600, None, "portal", "t"), general_lane,
                          [r for r in general if r["charge"] != "TLX"], specific, free, AS_OF)
    assert any("TLX missing" in f for f in option.flags)


def test_lc02_ams_is_required_only_for_us_and_europe(tables):
    general, specific, _ = tables
    asia = build_request("Hai Phong", "Busan", "40HC", "general")
    us = build_request("Hai Phong", "Los Angeles", "40HC", "general")
    assert "AMS" not in charge_cascade("X", asia, general, specific)
    assert charge_cascade("X", us, general, specific)["AMS"].usd == 35
    assert missing_required_fees("X", {}, us) == ["THC", "DOC", "SEAL", "TLX", "AMS"]


def test_lc03_doc_and_telex_default_to_per_bl_thc_to_per_container():
    assert [charge_unit(n) for n in ("THC", "SEAL", "DOC", "TLX", "AMS")] == \
        ["per_container", "per_container", "per_bl", "per_bl", "per_bl"]


def test_lc03_a_unit_written_in_the_table_wins():
    assert charge_unit("DOC", "per_container") == "per_container"


def test_lc03_two_containers_pay_thc_twice_and_doc_once():
    option = Option(Price("X", 600, None, "portal", "t"),
                    {"THC": Charge(165), "DOC": Charge(45, "per_bl")}, None, qty=2)
    assert option.local_total == 165 * 2 + 45 and option.total == 600 * 2 + 375


def test_lc04_included_fee_is_zeroed_but_kept_visible(tables, general_lane, trace):
    general, specific, _ = tables
    charges = charge_cascade("Redsea Express", general_lane, general, specific)
    charges = remove_included_fees("Redsea Express", charges, ("DOC",), trace)
    assert charges["DOC"].usd == 0 and "included" in charges["DOC"].source
    assert "LC-04" in trace.ids_for("Redsea Express")


def test_lc04_included_fee_is_not_reported_as_missing(tables, general_lane):
    general, specific, _ = tables
    charges = remove_included_fees("X", charge_cascade("X", general_lane, general, specific), ("DOC",))
    assert missing_required_fees("X", charges, general_lane) == []
