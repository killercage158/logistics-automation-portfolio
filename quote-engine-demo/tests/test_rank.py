from datetime import date

from engine.models import Charge, Option, Price
from engine.rank import rank_options, recommend


def option(carrier, freight, local, source="portal"):
    return Option(Price(carrier, freight, date(2026, 12, 31), source, "t"), {"THC": Charge(local)}, None)


def test_lowest_total_wins_not_lowest_freight():
    cheap_freight = option("A", 585, 275)       # total 860
    cheap_total = option("B", 610, 245)         # total 855
    assert [o.carrier for o in rank_options([cheap_freight, cheap_total])] == ["B", "A"]


def test_tie_goes_to_the_more_trusted_source():
    ranked = rank_options([option("A", 600, 0, "price file"), option("B", 600, 0, "contract")])
    assert ranked[0].carrier == "B"


def test_order_is_stable_when_everything_ties():
    ranked = rank_options([option("Z", 600, 0), option("A", 600, 0)])
    assert [o.carrier for o in ranked] == ["A", "Z"]


def test_recommendation_has_reasons_and_gap():
    rec = recommend(rank_options([option("A", 600, 0), option("B", 650, 0)]))
    assert rec.option.carrier == "A"
    assert any("USD 50 cheaper" in r for r in rec.reasons)


def test_recommendation_warns_about_price_file_source():
    rec = recommend(rank_options([option("A", 600, 0, "price file")]))
    assert any("confirm with the carrier" in r for r in rec.reasons)


def test_no_options_gives_no_recommendation():
    assert recommend([]) is None
