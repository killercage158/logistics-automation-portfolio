"""End-to-end: the scripted day, the board and the saved files."""
import json

from engine.rules import RULES
from marketing import save_outputs


def test_end_of_day_statuses(day):
    status = {i.id: i.status for i in day.state.ideas.values()}
    assert status == {"I-01": "drafted", "I-02": "filtered", "I-03": "drafted", "I-04": "drafted", "I-05": "rejected",
                      "I-06": "drafted", "I-07": "filtered", "I-08": "drafted", "I-09": "drafted", "I-10": "filtered",
                      "I-11": "needs_source", "I-12": "pending", "I-13": "pending"}
    assert sorted(p.id for p in day.state.posts.values() if p.status == "published") == ["P-01", "P-03", "P-06", "P-08", "P-09"]


def test_every_rule_fires_during_the_day(day):
    assert [r for r in RULES if day.trace.count(r) == 0] == []


def test_ai_was_never_asked_to_write_the_thin_source_before_the_editor_fixed_it(day):
    assert day.llm.log.count(("draft", "I-03")) == 1                     # once, after the 09:30 edit
    events = [text for _, text in day.state.ideas["I-03"].history]
    assert events.index("needs source (main text 282 characters < 500, no AI call)") < events.index("draft P-03 created")


def test_decision_for_a_filtered_idea_is_ignored(day):
    assert day.state.ideas["I-07"].status == "filtered" and "P-07" not in day.state.posts


def test_board_lists_every_idea_post_and_rule(day, tmp_path):
    board = save_outputs(day, tmp_path).read_text(encoding="utf-8")
    assert all(i in board for i in day.state.ideas) and all(p in board for p in day.state.posts)
    assert all(r in board for r in RULES) and "data:image/svg+xml;base64," in board


def test_state_and_ledger_files_are_valid_json(day, tmp_path):
    save_outputs(day, tmp_path)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert len(state["ideas"]) == 13 and len(ledger) == 13 and (tmp_path / "cards" / "P-01.svg").exists()
