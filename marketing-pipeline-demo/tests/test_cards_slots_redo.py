"""Card rules, Instagram ratios, golden hours and the redo scope (MK-11, MK-13, MK-14, MK-16)."""
from datetime import datetime

import pytest

from engine.cards import COVER, fit_for_instagram, fit_headline, render_card, shorten
from engine.redo import infer_scope
from engine.slots import next_golden_slot, resolve_slot

DAY = datetime(2026, 11, 16)


def test_headline_fits_in_three_lines_and_short_ones_get_bigger_type():
    short_lines, short_font, _, _ = fit_headline("Rates rise")
    long_lines, long_font, _, _ = fit_headline("E-invoices required for every export shipment from 1 January")
    assert len(long_lines) <= 3 and short_font > long_font


def test_shorten_never_cuts_inside_a_word():
    text, cut = shorten("Northgate terminal adds a daily fee for containers delivered too early before cut-off")
    assert cut and text == "Northgate terminal adds a daily fee for containers..."


def test_card_sizes():
    assert "width='1080' height='1080'" in render_card("Rates rise")
    assert "width='1280' height='720'" in render_card("Rates rise", COVER, "cover")


@pytest.mark.parametrize("w,h,expected", [(1080, 1080, ("ok", 1080, 1080)), (1600, 600, ("crop", 1146, 600)),
                                          (1080, 1920, ("pad", 1536, 1920))])
def test_instagram_ratio_rule(w, h, expected):
    assert fit_for_instagram(w, h) == expected


def test_golden_hour_picks_the_nearest_free_slot():
    assert next_golden_slot(DAY.replace(hour=10), set()) == DAY.replace(hour=12)
    assert next_golden_slot(DAY.replace(hour=10), {DAY.replace(hour=12)}) == DAY.replace(hour=18)


def test_golden_hour_after_the_last_slot_goes_to_seven_tomorrow():
    assert next_golden_slot(DAY.replace(hour=21, minute=30), set()) == datetime(2026, 11, 17, 7)


def test_fixed_time_in_the_past_means_now():
    now = DAY.replace(hour=16)
    assert resolve_slot("15:30", now, set())[0] == now
    assert resolve_slot("17:15", now, set())[0] == DAY.replace(hour=17, minute=15)


@pytest.mark.parametrize("feedback,scope", [
    ("Make the caption shorter and drop the question in the headline.", "caption"),
    ("Use a darker background image", "image"),
    ("Redo it", "both")])
def test_redo_scope_is_guessed_from_the_feedback_words(feedback, scope):
    assert infer_scope(feedback) == scope
