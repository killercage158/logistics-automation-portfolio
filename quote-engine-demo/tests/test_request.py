import pytest

from engine.request import (build_request, normalise_cargo, normalise_container,
                            normalise_port, port_in_text)


@pytest.mark.parametrize("text", ["Hai Phong", "haiphong", "HPH", "Hải Phòng", "VNHPH", " hai  phong "])
def test_port_aliases_all_give_hai_phong(text):
    assert normalise_port(text) == "Hai Phong"


@pytest.mark.parametrize("text", ["HCM", "Saigon", "Cat Lai", "Hồ Chí Minh", "SGN"])
def test_port_aliases_all_give_ho_chi_minh(text):
    assert normalise_port(text) == "Ho Chi Minh"


@pytest.mark.parametrize("text, expected", [
    ("40HC", "40HC"), ("40'HC", "40HC"), ("40 HQ", "40HC"), ("40hq", "40HC"),
    ("20'", "20GP"), ("20DC", "20GP"), ("40", "40GP"), ("40ft", "40GP"),
])
def test_container_aliases(text, expected):
    assert normalise_container(text) == expected


@pytest.mark.parametrize("text, expected", [("Charcoal", "charcoal"), ("than", "charcoal"), ("GEN", "general")])
def test_cargo_aliases(text, expected):
    assert normalise_cargo(text) == expected


def test_unknown_port_gives_helpful_error():
    with pytest.raises(ValueError, match="Unknown port"):
        normalise_port("Atlantis")


def test_same_port_twice_is_rejected():
    with pytest.raises(ValueError):
        build_request("HPH", "Hai Phong", "40HC", "general")


def test_region_us_eu_for_los_angeles():
    assert build_request("Hai Phong", "LAX", "40HC", "general").region == "us_eu"
    assert build_request("Hai Phong", "Busan", "40HC", "general").region == "asia"


def test_port_in_text_uses_aliases():
    assert port_in_text("Hai Phong", "HPH > SIN 40HC")
    assert not port_in_text("Hai Phong", "Ho Chi Minh to Busan")
