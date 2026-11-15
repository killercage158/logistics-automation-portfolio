"""Shared test setup: makes the engine importable and builds the fake data once."""
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

AS_OF = date(2026, 11, 16)


@pytest.fixture(scope="session")
def sample_dir(tmp_path_factory):
    """Generate the fake data in a temporary folder (the real data/sample is left alone)."""
    import make_sample_data
    make_sample_data.OUT = tmp_path_factory.mktemp("sample")
    make_sample_data.main()
    return make_sample_data.OUT


@pytest.fixture
def general_lane():
    from engine.request import build_request
    return build_request("Hai Phong", "Singapore", "40HC", "general")


@pytest.fixture
def charcoal_lane():
    from engine.request import build_request
    return build_request("Ho Chi Minh", "Busan", "40HC", "charcoal")


@pytest.fixture
def trace():
    from engine.rulebook import RuleTrace
    return RuleTrace()


@pytest.fixture
def mock_llm():
    from engine.llm import MockLLM
    return MockLLM(ROOT / "fixtures")


@pytest.fixture
def tables(sample_dir):
    """The local charge and free-time tables as lists of rows."""
    from engine.rules import load_csv
    return (load_csv(sample_dir / "local_charges_general.csv"),
            load_csv(sample_dir / "local_charges_carrier.csv"),
            load_csv(sample_dir / "freetime.csv"))
