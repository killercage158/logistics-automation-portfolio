"""Step 2: ports, vessel/voyage, dates and cut-offs (SC-05 to SC-08)."""
from datetime import date

import pytest

from conftest import DAY1
from engine.models import RawRow, Route
from engine.normalise import normalise_row, parse_when, port_code, split_vessel_voyage
from engine.rules import RuleTrace


def raw(**kw):
    base = dict(carrier="Test Line", route=Route("VNHPH", "KRPUS"), vessel="TEST STAR", voyage="2648N",
                pol="HAI PHONG", pod="BUSAN, KOREA", etd="27/11/2026", eta="02/12/2026",
                cutoff_si="", cutoff_cy="26/11/2026 12:00")
    base.update(kw)
    return RawRow(**base)


@pytest.mark.parametrize("text", ["HAIPHONG", "Hai Phong", "HAI PHONG (HICT)", "VIETNAM, HAIPHONG", "VNHPH", "Hải Phòng"])
def test_every_hai_phong_spelling_becomes_one_code(text):
    assert port_code(text) == "VNHPH"


@pytest.mark.parametrize("text,code", [("KOREA, PUSAN", "KRPUS"), ("BUSAN, KOREA", "KRPUS"),
                                       ("HO CHI MINH (CAT LAI)", "VNSGN"), ("INCHON", "KRINC")])
def test_country_first_or_last_and_old_names(text, code):
    assert port_code(text) == code


def test_unknown_port_rejects_the_row_with_a_reason():
    v, why = normalise_row(raw(pod="ATLANTIS"), DAY1)
    assert v is None and "unknown port of discharge 'ATLANTIS'" in why and "SC-05" in why


def test_glued_vessel_and_voyage_are_split():
    assert split_vessel_voyage("NORTHSTAR LYRA 2647N", "")[:2] == ("NORTHSTAR LYRA", "2647N")


def test_vessel_code_glued_to_voyage_is_stripped():
    vessel, voyage, done = split_vessel_voyage("KESTREL DAWN", "KSDW2645N")
    assert (vessel, voyage) == ("KESTREL DAWN", "2645N") and "KSDW" in done[0]


def test_voyage_repeated_in_vessel_name_is_removed():
    assert split_vessel_voyage("STAR ORCHID 2647N", "2647N")[:2] == ("STAR ORCHID", "2647N")


@pytest.mark.parametrize("text,expected", [
    ("2026-11-20T09:00:00+07:00", (date(2026, 11, 20), "09:00")),
    ("20261120", (date(2026, 11, 20), None)),
    ("20261118 1700", (date(2026, 11, 18), "17:00")),
    ("20/11/2026", (date(2026, 11, 20), None)),
    ("Nov 20 17:00", (date(2026, 11, 20), "17:00")),
])
def test_date_formats(text, expected):
    assert parse_when(text, DAY1) == expected


def test_date_without_year_in_january_seen_in_december_is_next_year():
    assert parse_when("Jan 05", date(2026, 12, 20))[0] == date(2027, 1, 5)


@pytest.mark.parametrize("text", ["TBA", "Contact", "", "31/02/2026"])
def test_text_that_is_not_a_date_becomes_none(text):
    assert parse_when(text, DAY1) == (None, None)


def test_row_without_departure_date_is_rejected_not_crashed():
    v, why = normalise_row(raw(etd="TBA"), DAY1)
    assert v is None and "ETD 'TBA' is not a date" in why


def test_cut_off_goes_to_its_own_field_never_into_etd():
    trace = RuleTrace()
    v, _ = normalise_row(raw(), DAY1, trace)
    assert v.etd == date(2026, 11, 27) and v.cutoff_cy == "2026-11-26 12:00" and trace.count("SC-08") == 1


def test_row_for_another_route_is_rejected():
    v, why = normalise_row(raw(pod="TOKYO"), DAY1)
    assert v is None and "not the route asked" in why
