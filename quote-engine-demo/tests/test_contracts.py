from datetime import date

from conftest import AS_OF
from engine.contracts import carriers_for_portal, find_contracts, load_contracts
from engine.portals import PORTAL_ORDER


def test_valid_contract_is_found(sample_dir, general_lane):
    valid, ignored = find_contracts(load_contracts(sample_dir / "contracts.csv"), general_lane, AS_OF)
    assert list(valid) == ["Jade Ocean"]
    assert valid["Jade Ocean"].source == "contract" and valid["Jade Ocean"].price_usd == 590
    assert ignored == []


def test_expired_contract_is_ignored_and_reported(sample_dir, charcoal_lane):
    valid, ignored = find_contracts(load_contracts(sample_dir / "contracts.csv"), charcoal_lane, AS_OF)
    assert "Redsea Express" not in valid
    assert len(ignored) == 1 and "expired" in ignored[0]


def test_contract_for_another_cargo_does_not_match(sample_dir, general_lane):
    # Kestrel's contract is for charcoal, so it must not appear on the general-cargo lane.
    valid, _ = find_contracts(load_contracts(sample_dir / "contracts.csv"), general_lane, AS_OF)
    assert "Kestrel Line" not in valid


def test_contract_carrier_skips_the_portal(sample_dir, general_lane):
    valid, _ = find_contracts(load_contracts(sample_dir / "contracts.csv"), general_lane, AS_OF)
    to_check = carriers_for_portal(PORTAL_ORDER, valid)
    assert "Jade Ocean" not in to_check and len(to_check) == len(PORTAL_ORDER) - 1


def test_contract_valid_on_its_last_day(sample_dir, general_lane):
    valid, _ = find_contracts(load_contracts(sample_dir / "contracts.csv"), general_lane, date(2026, 12, 31))
    assert "Jade Ocean" in valid
