"""Gate 2 and publishing (MK-12 to MK-17), checked on the scripted day."""
import pytest

from conftest import FIXTURES, make_state
from engine.models import Post
from engine.publish import MockPlatforms


def log_of(day, post_id):
    return [(t, ch, result) for t, p, ch, result, _ in day.state.publish_log if p == post_id]


def test_rejected_draft_is_never_published(day):
    assert day.state.posts["P-04"].status == "rejected" and log_of(day, "P-04") == []


def test_failed_facebook_post_is_retried_next_cycle_and_the_article_is_unaffected(day):
    assert log_of(day, "P-01")[:3] == [("10:00", "facebook", "failed"), ("10:00", "oa", "created hidden"),
                                        ("10:30", "facebook", "posted")]


def test_instagram_mirrors_single_image_posts_only(day):
    ig = {p.id: p.channel_state["instagram"]["status"] for p in day.state.posts.values() if "instagram" in p.channel_state}
    assert ig == {"P-01": "posted", "P-06": "posted", "P-08": "posted", "P-09": "skipped", "P-03": "skipped"}


def test_messaging_articles_are_created_hidden():
    platforms = MockPlatforms(FIXTURES, make_state())
    post = Post("P-99", "I-99", "news card", "h", "c")
    assert "status=hidden" in platforms.oa_create(post, {"title": "t", "body": "b"})
    with pytest.raises(ValueError):
        platforms.oa_create(post, {"title": "t", "body": "b"}, status="published")


def test_quota_reached_article_waits_while_facebook_and_instagram_go_out(day):
    p6 = day.state.posts["P-06"].channel_state
    assert p6["oa"]["status"] == "waiting" and p6["facebook"]["status"] == "posted" and p6["instagram"]["status"] == "posted"
    assert day.state.oa_used == day.state.oa_quota == 3


def test_golden_hours_give_each_post_its_own_slot(day):
    slots = {p.id: p.slot.strftime("%H:%M") for p in day.state.posts.values() if p.schedule == "golden"}
    assert slots == {"P-06": "12:00", "P-08": "18:00", "P-03": "21:00"}


def test_redo_request_is_used_once_and_the_rewrite_is_published(day):
    p9 = day.state.posts["P-09"]
    assert ("rewrite", "I-09") in day.llm.log and day.llm.log.count(("rewrite", "I-09")) == 1
    assert p9.status == "published" and "?" not in p9.headline and p9.slot.strftime("%H:%M") == "15:30"


def test_text_post_gets_its_author_comment_under_it(day):
    assert ("15:30", "facebook", "author comment") in log_of(day, "P-09")
