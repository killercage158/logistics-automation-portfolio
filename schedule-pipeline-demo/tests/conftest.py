"""Shared test setup: makes the engine importable and runs the two crawl days once."""
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

DAY1, DAY2 = date(2026, 11, 16), date(2026, 11, 17)
FIXTURES = ROOT / "fixtures"


@pytest.fixture
def conn():
    """An empty in-memory database with the demo bookings loaded."""
    from engine import store
    c = store.connect(":memory:")
    store.load_bookings(c, ROOT / "data" / "bookings.csv")
    yield c
    c.close()


@pytest.fixture(scope="session")
def two_days(tmp_path_factory):
    """Run day 1 then day 2 into a temporary folder. Returns (day1 result, day2 result, connection, out dir)."""
    from engine import store
    from engine.runlog import RunLog
    from schedule import run_day
    out = tmp_path_factory.mktemp("out")
    c = store.connect(out / "schedule.db")
    store.load_bookings(c, ROOT / "data" / "bookings.csv")
    d1 = run_day(1, c, FIXTURES, out, RunLog(echo=False))
    d2 = run_day(2, c, FIXTURES, out, RunLog(echo=False))
    return d1, d2, c, out
