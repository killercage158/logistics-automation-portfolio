"""Step 1: thresholds, content keys, the ledger and collector health (MK-01, MK-02, MK-18)."""
from conftest import FIXTURES, NOON, make_state
from engine.collect import collect_all
from engine.ledger import Ledger, canonical_url, news_key, social_key, video_key
from engine.rules import RuleTrace


def collect_visit1():
    state, trace, log = make_state(), RuleTrace(), []
    new = collect_all(FIXTURES / "sources", 1, state, NOON.replace(hour=6), trace, log)
    return state, trace, new


def test_thresholds_keep_low_engagement_and_old_news_off_the_board():
    state, trace, new = collect_visit1()
    titles = [i.title for i in new]
    assert len(new) == 12 and trace.count("MK-01") == 3
    assert "Packing tips for fragile cargo" not in titles and "Port association elects a new chair" not in titles


def test_same_social_post_with_a_new_link_has_the_same_key():
    text = "Northgate Container Terminal will charge a congestion fee on export containers from 1 December."
    assert social_key("Port Watch Asia", text, "https://social.example/p/pfx8a1c?ref=a91f") == \
        social_key("Port Watch Asia", text, "https://social.example/p/pfx2d9b?ref=c37e")


def test_very_short_social_text_falls_back_to_the_link():
    assert social_key("Page", "Nice!", "https://social.example/p/1?x=2").startswith("social-link:")


def test_news_key_ignores_tracking_parameters_case_and_trailing_slash():
    assert news_key("https://TradeNews.example/a/b/?utm_source=rss#top") == news_key("https://tradenews.example/a/b")
    assert canonical_url("HTTPS://X.example/Path/") == "https://x.example/path"


def test_video_key_uses_the_platform_id_not_the_link():
    assert video_key("vx-1001") == "video:vx-1001"


def test_second_visit_only_adds_the_genuinely_new_post(day):
    visit2 = [i for i in day.state.ideas.values() if i.history[0][0] == "14:00"]
    assert [i.id for i in visit2] == ["I-13"] and day.trace.count("MK-02") >= 9


def test_an_empty_source_is_reported_as_a_broken_collector():
    state, trace, _ = collect_visit1()
    notes = {name: note for _, _, name, seen, _, note in state.collector_log}
    assert notes["Harbour Bulletin"].startswith("BROKEN") and trace.count("MK-18") == 1


def test_rejected_idea_keeps_its_key_in_the_ledger(day):
    idea = day.state.ideas["I-05"]
    assert idea.status == "rejected" and idea.key in day.state.ledger


def test_ledger_survives_a_save_and_load(tmp_path):
    ledger = Ledger(["video:a", "news:https://x.example/b"])
    ledger.save(tmp_path / "ledger.json")
    assert Ledger.load(tmp_path / "ledger.json").keys == ledger.keys
