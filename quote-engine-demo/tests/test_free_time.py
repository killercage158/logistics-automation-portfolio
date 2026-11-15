"""FT-01 .. FT-03."""
from engine.free_time import free_time, missing_free_time_flag, pick_guide_row
from engine.request import build_request


def test_ft01_default_days_come_from_the_carriers_guide(tables, general_lane, trace):
    ft = free_time("Jade Ocean", general_lane, tables[2], trace)
    assert (ft["pol_days"], ft["pod_days"]) == (10, 14) and "guide" in ft["guide"]
    assert "FT-01" in trace.ids_for("Jade Ocean")


def test_ft01_nothing_but_the_guide_is_consulted(tables, general_lane):
    # same answer whatever the price source says: free time has no connection to the price
    assert free_time("Jade Ocean", general_lane, tables[2]) == free_time("Jade Ocean", general_lane, tables[2])


def test_ft02_port_exception_beats_the_carrier_default(tables, general_lane, trace):
    ft = free_time("Bluewave Lines", general_lane, tables[2], trace)      # Singapore exception: 12 days
    assert ft["pod_days"] == 12 and ft["pol_days"] == 7 and "FT-02" in trace.ids_for("Bluewave Lines")


def test_ft02_cargo_and_port_exception_is_the_most_specific(tables, charcoal_lane):
    assert free_time("Kestrel Line", charcoal_lane, tables[2])["pod_days"] == 5


def test_ft02_exception_for_another_port_is_ignored(tables):
    other = build_request("Hai Phong", "Singapore", "40HC", "general")
    assert free_time("Pacific Arrow", other, tables[2])["pod_days"] == 7        # Busan exception does not apply


def test_ft02_pick_guide_row_prefers_port_plus_cargo(tables, charcoal_lane):
    row = pick_guide_row(tables[2], "Kestrel Line", "POD", "Busan", "charcoal")
    assert row["port"] == "Busan" and row["cargo"] == "charcoal"


def test_ft03_carrier_missing_from_the_guide_is_flagged_not_guessed(tables, general_lane, trace):
    assert free_time("Redsea Express", general_lane, tables[2]) is None
    assert "ask the carrier" in missing_free_time_flag("Redsea Express", None, trace)
    assert "FT-03" in trace.ids_for("Redsea Express")


def test_ft03_one_missing_end_is_flagged(general_lane):
    rows = [{"carrier": "X", "place": "POL", "port": "", "cargo": "", "free_days": "5", "guide": "g"}]
    ft = free_time("X", general_lane, rows)
    assert ft["pod_days"] is None and "POD" in missing_free_time_flag("X", ft)


def test_ft03_complete_entry_has_no_flag(tables, general_lane):
    assert missing_free_time_flag("Jade Ocean", free_time("Jade Ocean", general_lane, tables[2])) is None
