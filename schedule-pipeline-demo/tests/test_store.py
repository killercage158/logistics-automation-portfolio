"""Steps 3 to 5: key, de-duplication, upsert, ETD changes, retirement, booking protection (SC-09 to SC-15)."""
from datetime import date, timedelta

from conftest import DAY1, DAY2
from engine import store
from engine.dedupe import dedupe
from engine.models import CarrierResult, Route, RouteResult, Voyage
from engine.rules import RuleTrace

ROUTE = Route("VNHPH", "KRPUS")
WINDOW = (DAY1, DAY1 + timedelta(days=41))


def voy(vessel="TEST STAR", voyage="2648N", etd=date(2026, 11, 27), seen_at=0.0, carrier="Bluewave Lines"):
    return Voyage(carrier, vessel, voyage, "VNHPH", "KRPUS", etd, etd + timedelta(days=5), None, None,
                  "VKX", "", "test", seen_at)


def crawl(rows=1, status="ok", window=WINDOW, carrier="Bluewave Lines"):
    return [CarrierResult(carrier, routes=[RouteResult(carrier, ROUTE, status, rows, "", window if status == "ok" else None)])]


def count(conn, where="1=1"):
    return conn.execute(f"SELECT COUNT(*) FROM voyages WHERE {where}").fetchone()[0]


def test_voyage_key_has_no_dates():
    assert voy(etd=date(2026, 11, 27)).key == voy(etd=date(2026, 11, 29)).key
    assert voy().key == "BLUEWAVE LINES|TEST STAR|2648N|VNHPH|KRPUS"


def test_dedupe_keeps_the_row_fetched_last():
    unique, dropped = dedupe([voy(etd=date(2026, 11, 27), seen_at=1), voy(etd=date(2026, 12, 1), seen_at=9)])
    assert len(unique) == 1 and unique[0].etd == date(2026, 12, 1) and len(dropped) == 1


def test_second_crawl_updates_in_place_instead_of_copying(conn):
    store.upsert(conn, [voy()], DAY1)
    res = store.upsert(conn, [voy(etd=date(2026, 11, 28))], DAY2)
    assert count(conn) == 1 and res.updated and not res.new


def test_older_crawl_never_overwrites_newer_data(conn):
    store.upsert(conn, [voy(etd=date(2026, 11, 28))], DAY2)
    res = store.upsert(conn, [voy(etd=date(2026, 11, 27))], DAY1)
    assert res.skipped_older and conn.execute("SELECT etd FROM voyages").fetchone()[0] == "2026-11-28"


def test_etd_change_is_recorded_with_days_moved(conn):
    store.upsert(conn, [voy()], DAY1)
    res = store.upsert(conn, [voy(etd=date(2026, 11, 29))], DAY2)
    assert res.etd_changes == [(voy().key, "2026-11-27", "2026-11-29", 2, [])]
    assert conn.execute("SELECT delta_days FROM etd_changes").fetchone()[0] == 2


def test_etd_change_on_a_booked_voyage_names_the_booking(conn):
    booked = voy("BLUEWAVE ARIES", "2648N")                       # B-1001 in data/bookings.csv
    store.upsert(conn, [booked], DAY1)
    res = store.upsert(conn, [voy("BLUEWAVE ARIES", "2648N", etd=date(2026, 11, 29))], DAY2)
    assert res.etd_changes[0][4] == ["B-1001"]


def test_missing_voyage_on_a_good_route_is_retired_not_deleted(conn):
    store.upsert(conn, [voy("A"), voy("B")], DAY1)
    res = store.retire(conn, crawl(rows=1), {voy("A").key}, DAY2, RuleTrace())
    assert [k for k, _, _ in res.retired] == [voy("B").key]
    assert count(conn) == 2 and count(conn, "is_active = 0") == 1


def test_failed_route_retires_nothing(conn):
    store.upsert(conn, [voy("A")], DAY1)
    res = store.retire(conn, crawl(status="failed"), set(), DAY2)
    assert not res.retired and res.held and count(conn, "is_active = 1") == 1


def test_route_with_zero_rows_retires_nothing(conn):
    store.upsert(conn, [voy("A")], DAY1)
    res = store.retire(conn, crawl(rows=0), set(), DAY2)
    assert not res.retired and "zero rows" in res.held[0][2]


def test_voyage_outside_the_crawled_window_is_not_retired(conn):
    store.upsert(conn, [voy("A", etd=date(2027, 2, 1))], DAY1)
    res = store.retire(conn, crawl(rows=3), set(), DAY2)
    assert not res.retired and count(conn, "is_active = 1") == 1


def test_booked_voyage_is_never_retired(conn):
    booked = voy("BLUEWAVE ARIES", "2648N")                       # B-1001
    store.upsert(conn, [booked], DAY1)
    res = store.retire(conn, crawl(rows=4), set(), DAY2, RuleTrace())
    assert not res.retired and res.protected[0][3] == ["B-1001"] and count(conn, "is_active = 1") == 1


def test_retired_voyage_that_comes_back_is_revived_on_the_same_row(conn):
    store.upsert(conn, [voy("A")], DAY1)
    store.retire(conn, crawl(rows=2), set(), DAY1)
    res = store.upsert(conn, [voy("A")], DAY2)
    assert res.revived == [voy("A").key] and count(conn) == 1 and count(conn, "is_active = 1") == 1
