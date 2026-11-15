import pytest
from openpyxl import Workbook

from engine.models import PriceRow
from engine.price_files import parse_numbers
from engine.verify import verify_all, verify_row


@pytest.fixture
def folder(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Rates"
    ws.append(["Hai Phong", "Singapore", 610, "USD 1,250"])      # row 1
    ws.append(["Ho Chi Minh", "Busan", 900, 950])                 # row 2
    wb.save(tmp_path / "t.xlsx")
    return tmp_path


def make_row(cell="C1", price=610, pol="Hai Phong", pod="Singapore", sheet="Rates", file="t.xlsx"):
    return PriceRow("Test Line", pol, pod, "40HC", None, price, None, file, sheet, cell)


def test_matching_number_is_accepted(folder):
    assert verify_row(make_row(), folder)[0] is True


def test_text_number_with_currency_is_accepted(folder):
    assert verify_row(make_row(cell="D1", price=1250), folder)[0] is True


def test_wrong_value_is_rejected_with_reason(folder):
    ok, why = verify_row(make_row(price=650), folder)
    assert not ok and "610" in why and "650" in why


def test_empty_cell_is_rejected(folder):
    ok, why = verify_row(make_row(cell="C9"), folder)
    assert not ok and "empty" in why


def test_right_number_in_a_different_lane_row_is_rejected(folder):
    # 900 really is in the file, but in the Ho Chi Minh - Busan row.
    ok, why = verify_row(make_row(cell="C2", price=900), folder)
    assert not ok and "does not mention" in why


@pytest.mark.parametrize("bad", [make_row(file="nope.xlsx"), make_row(sheet="Nope"), make_row(cell="C")])
def test_bad_citation_is_rejected(folder, bad):
    assert verify_row(bad, folder)[0] is False


def test_verify_all_keeps_order(folder):
    results = verify_all([make_row(), make_row(price=1)], folder)
    assert [ok for _, ok, _ in results] == [True, False]


@pytest.mark.parametrize("value, expected", [
    (2150, [2150.0]), ("USD 3,450", [3450.0]), ("1.250,00", [1250.0]), ("12,5", [12.5]),
    ("1.250.000", [1250000.0]), ("1.250", [1.25]), (None, []), ("n/a", []),
])
def test_parse_numbers(value, expected):
    assert parse_numbers(value) == expected
