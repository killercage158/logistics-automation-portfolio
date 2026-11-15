"""Step 2: AI relevance filter (MK-03, MK-04)."""
import re

from conftest import NOON, FakeLLM, make_idea, make_state
from engine.llm import AIUnavailable
from engine.relevance import relevance_sweep
from engine.rules import RuleTrace


def new_ideas(n):
    return [make_idea(f"I-{i:02d}", status="new") for i in range(1, n + 1)]


def answer(relevant=lambda i: True, drop=0):
    """A fake AI that judges every idea in the prompt (optionally forgetting the last `drop`)."""
    def reply(user):
        ids = re.findall(r"^(I-\d+) \|", user, re.M)
        ids = ids[: len(ids) - drop] if drop else ids
        return {"verdicts": [{"id": i, "relevant": relevant(i), "reason": "test"} for i in ids]}
    return reply


def sweep(state, llm):
    log, trace = [], RuleTrace()
    n = relevance_sweep(state, llm, __import__("engine.prompts", fromlist=["Prompts"]).Prompts(), NOON, log, trace)
    return n, log, trace


def test_ai_outage_marks_nothing_and_waits_for_the_next_cycle():
    state = make_state(*new_ideas(3))
    n, log, trace = sweep(state, FakeLLM(AIUnavailable("down")))
    assert n == 0 and all(i.status == "new" for i in state.ideas.values()) and trace.count("MK-04") == 1


def test_off_topic_ideas_are_filtered_with_the_reason():
    state = make_state(*new_ideas(4))
    sweep(state, FakeLLM(default=answer(relevant=lambda i: i != "I-02")))
    assert state.ideas["I-02"].status == "filtered" and "off-topic: test" == state.ideas["I-02"].reason
    assert sum(i.status == "pending" for i in state.ideas.values()) == 3


def test_unusable_reply_is_asked_again_then_the_batch_is_split():
    state = make_state(*new_ideas(4))
    llm = FakeLLM(answer(drop=1), answer(drop=1), default=answer())
    _, log, _ = sweep(state, llm)
    assert len(llm.calls) == 4 and any("splitting the batch" in line for line in log)
    assert all(i.status == "pending" for i in state.ideas.values())


def test_one_idea_that_never_gets_a_verdict_is_kept_for_a_human():
    state = make_state(*new_ideas(1))
    sweep(state, FakeLLM(default="sorry, I cannot help with that"))
    assert state.ideas["I-01"].status == "pending" and "kept so an editor can decide" in state.ideas["I-01"].reason


def test_ideas_are_judged_once():
    state = make_state(*new_ideas(2))
    llm = FakeLLM(default=answer())
    sweep(state, llm)
    sweep(state, llm)
    assert len(llm.calls) == 1


def test_batches_hold_at_most_25_ideas():
    state = make_state(*new_ideas(30))
    llm = FakeLLM(default=answer())
    sweep(state, llm)
    assert [len(re.findall(r"^I-\d+ \|", u, re.M)) for _, u in llm.calls] == [25, 5]
