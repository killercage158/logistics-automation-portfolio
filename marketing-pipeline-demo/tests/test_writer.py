"""Step 4: Gate 1 writing (MK-06 to MK-11)."""
from conftest import LONG_TEXT, NOON, FakeLLM, make_idea, make_state
from engine.rules import RuleTrace
from engine.writer import fingerprint, ready, source_facts, write_one

DRAFT = {"headline": "New surcharge on the main export route", "caption": "Lines add a surcharge from 1 December.",
         "image_prompt": "ship"}


def write(idea, llm, prompts):
    state, log, trace = make_state(idea), [], RuleTrace()
    post = write_one(state, idea, llm, prompts, NOON, log, trace)
    return post, log, trace


def test_thin_source_is_flagged_without_calling_the_ai(prompts):
    llm = FakeLLM(default=DRAFT)
    post, _, trace = write(make_idea(text="Short note about a new HS code. " * 5), llm, prompts)
    assert post is None and llm.calls == [] and trace.count("MK-06") == 1


def test_visibly_cut_source_is_flagged(prompts):
    idea = make_idea(text=LONG_TEXT + " ... See more")
    write(idea, FakeLLM(default=DRAFT), prompts)
    assert idea.status == "needs_source" and "visibly cut" in idea.reason


def test_flagged_idea_runs_again_only_when_its_text_changes():
    idea = make_idea(status="needs_source", text="thin")
    idea.fingerprint = fingerprint("thin")
    assert not ready(idea)
    idea.text = LONG_TEXT
    assert ready(idea)


def test_ai_refusal_at_gate1_flags_needs_source(prompts):
    idea = make_idea()
    write(idea, FakeLLM("NOT ENOUGH SOURCE: no dates given"), prompts)
    assert idea.status == "needs_source" and "no dates given" in idea.reason


def test_gate1_prompt_allows_refusal_but_only_gate1(prompts):
    llm = FakeLLM(default=DRAFT)
    write(make_idea(), llm, prompts)
    assert "NOT ENOUGH SOURCE" in llm.calls[0][0]
    assert "NOT ENOUGH SOURCE" not in prompts.post_system("Source: X", allow_refuse=False)


def test_banned_phrase_triggers_one_regeneration(prompts):
    bad = dict(DRAFT, caption="Guaranteed savings. Act now.")
    llm = FakeLLM(bad, DRAFT)
    post, _, trace = write(make_idea(), llm, prompts)
    assert len(llm.calls) == 2 and "guaranteed" in llm.calls[1][1] and not post.flags


def test_banned_phrase_twice_keeps_the_draft_but_flags_it(prompts):
    bad = dict(DRAFT, caption="Guaranteed savings.")
    post, _, _ = write(make_idea(), FakeLLM(bad, bad), prompts)
    assert post.flags == ["voice: still uses guaranteed"]


def test_code_appends_the_source_line_when_the_ai_drops_it(prompts):
    post, _, _ = write(make_idea(), FakeLLM(default=DRAFT), prompts)
    assert post.caption.endswith("Source: Trade News Wire, 15/11/2026")


def test_social_page_sources_are_not_credited():
    assert source_facts(make_idea(kind="social")) == (False, "")


def test_text_card_is_short_and_has_an_author_comment(prompts):
    llm = FakeLLM(DRAFT, "- detail one\n- detail two")
    post, _, _ = write(make_idea(fmt="text card"), llm, prompts)
    assert len(post.caption) <= 120 and post.comment.startswith("- detail") and not post.card_svg


def test_news_card_has_a_card_and_no_author_comment(prompts):
    post, _, _ = write(make_idea(), FakeLLM(default=DRAFT), prompts)
    assert post.card_svg.startswith("<svg") and post.comment == "" and "1280" in post.cover_svg


def test_photo_album_uses_the_source_photos(prompts):
    photos = [{"w": 1080, "h": 1350}] * 3
    post, _, _ = write(make_idea(fmt="photo album", kind="social", photos=photos), FakeLLM(default=DRAFT), prompts)
    assert post.photos == photos and not post.single_image


def test_long_headline_is_cut_at_a_word(prompts):
    long = dict(DRAFT, headline="Northgate terminal adds a daily fee for containers delivered too early before cut-off")
    post, _, trace = write(make_idea(), FakeLLM(default=long), prompts)
    assert len(post.headline) <= 60 and post.headline.endswith("containers...") and trace.count("MK-11") >= 1
