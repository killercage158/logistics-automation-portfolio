"""End-to-end: both crawl days, the database, the Excel and the HTML report."""
from openpyxl import load_workbook

from conftest import ROOT
from engine.rules import RULES


def test_day1_is_healthy(two_days):
    d1 = two_days[0]
    assert d1.health.healthy and len(d1.upsert.new) == 91 and not d1.retire.retired


def test_day2_job_says_success_but_health_check_finds_four_problems(two_days):
    d2 = two_days[1]
    assert d2.job_success
    assert sorted((p.flag, p.carrier, p.route) for p in d2.health.problems) == [
        ("DROP", "Kestrel Line", "VNHPH-KRINC"), ("FAILED", "Pacific Arrow", "VNHPH-JPTYO"),
        ("FAILED", "Pacific Arrow", "VNSGN-KRINC"), ("ZERO", "Northstar Shipping", "VNHPH-KRINC")]


def test_etd_change_flags_booking_b1001(two_days):
    changes = {k: (d, refs) for k, _, _, d, refs in two_days[1].upsert.etd_changes}
    assert changes["BLUEWAVE LINES|BLUEWAVE ARIES|2648N|VNHPH|KRPUS"] == (2, ["B-1001"])
    assert len(changes) == 3


def test_vessel_swap_retires_the_old_name_and_adds_the_new_one(two_days):
    d2 = two_days[1]
    assert "BLUEWAVE LINES|BLUEWAVE TBN|2650N|VNHPH|JPTYO" in [k for k, _, _ in d2.retire.retired]
    assert "BLUEWAVE LINES|BLUEWAVE PISCES|2650N|VNHPH|JPTYO" in d2.upsert.new


def test_booked_voyages_are_kept_when_the_carrier_stops_listing_them(two_days):
    protected = {refs[0] for _, _, _, refs in two_days[1].retire.protected}
    assert protected == {"B-1002", "B-1003"}


def test_nothing_is_ever_deleted(two_days):
    conn = two_days[2]
    total = conn.execute("SELECT COUNT(*) FROM voyages").fetchone()[0]
    inactive = conn.execute("SELECT COUNT(*) FROM voyages WHERE is_active = 0").fetchone()[0]
    assert total == 91 + len(two_days[1].upsert.new) and inactive == len(two_days[1].retire.retired) == 5


def test_failed_and_empty_routes_retire_nothing(two_days):
    held = {(c, r) for c, r, _ in two_days[1].retire.held}
    assert held == {("Northstar Shipping", "VNHPH-KRINC"), ("Pacific Arrow", "VNHPH-JPTYO"),
                    ("Pacific Arrow", "VNSGN-KRINC")}


def test_excel_follows_the_segment_rules(two_days):
    export = two_days[1].export
    wb = load_workbook(export.path)
    assert "Notes" in wb.sheetnames and set(export.per_tab) <= set(wb.sheetnames)
    values = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]
    assert not any("Jade Ocean" == v for v in values)                 # carrier not in the segment
    assert not any(v == "NSX2" for v in values)                       # loop that does not take charcoal
    assert any("STALE" in v for v in values) and export.stale == {"Pacific Arrow": "2026-11-16"}


def test_excel_shows_the_etd_change(two_days):
    wb = load_workbook(two_days[1].export.path)
    values = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]
    assert "moved +2 d (was 27-Nov)" in values


def test_html_report_has_the_verdict_and_every_rule(two_days):
    html = (two_days[3] / "health_day2.html").read_text(encoding="utf-8")
    assert "Job result: success=true" in html and "4 problems found" in html
    assert all(rule_id in html for rule_id in RULES)


def test_every_rule_fires_at_least_once_over_the_two_days(two_days):
    d1, d2 = two_days[0], two_days[1]
    silent = [r for r in RULES if d1.trace.count(r) + d2.trace.count(r) == 0 and r != "SC-15"]
    assert silent == []      # SC-15 (revive) needs a third day; test_store.py proves it


CRLF, LF = bytes([13, 10]), bytes([10])     # Windows and Unix line endings


def _tree(root):
    """Every file under root -> its bytes, with Windows line endings turned into Unix ones, so the check gives the
    same answer on every operating system (Git on Windows may check text files out with CRLF)."""
    return {p.relative_to(root).as_posix(): p.read_bytes().replace(CRLF, LF)
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_committed_fixtures_match_their_generator(tmp_path):
    import make_fixtures
    make_fixtures.write_all(tmp_path / "fixtures", tmp_path)
    made, committed = _tree(tmp_path / "fixtures"), _tree(ROOT / "fixtures")
    assert sorted(made) == sorted(committed)
    assert [name for name in made if made[name] != committed[name]] == []
    same_text = lambda f: f.read_bytes().replace(CRLF, LF)
    assert same_text(tmp_path / "bookings.csv") == same_text(ROOT / "data" / "bookings.csv")
