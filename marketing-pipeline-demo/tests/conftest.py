"""Shared test setup: makes the engine importable, runs the scripted day once, and offers a fake AI."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "fixtures"
DECISIONS = ROOT / "decisions"
NOON = datetime(2026, 11, 16, 12, 0)
LONG_TEXT = ("Shipping lines serving the main export route announced a new surcharge from 1 December. " * 8).strip()


class FakeLLM:
    """Answers from a list, in order. An Exception in the list is raised; a dict is sent as JSON."""

    name = "fake"

    def __init__(self, *replies, default=None):
        self.replies = list(replies)
        self.default = default
        self.calls = []

    def complete(self, system, user):
        self.calls.append((system, user))
        reply = self.replies.pop(0) if self.replies else self.default
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(user)
        return reply if isinstance(reply, str) else json.dumps(reply)


def make_idea(idea_id="I-01", kind="news", text=LONG_TEXT, fmt="news card", status="approved", **kw):
    from engine.models import Idea
    idea = Idea(idea_id, kind, kw.pop("source", "Trade News Wire"), kw.pop("title", "Rates rise"), text,
                "https://tradenews.example/a", f"news:{idea_id}", kw.pop("published_at", datetime(2026, 11, 15, 20)),
                kw.pop("photos", []), status=status, fmt=fmt)
    return idea


def make_state(*ideas):
    from engine.ledger import Ledger
    from engine.models import State
    state = State(ledger=Ledger())
    for i in ideas:
        state.ideas[i.id] = i
    return state


@pytest.fixture(scope="session")
def day():
    """The scripted day with the recorded AI answers."""
    from engine.llm import MockLLM
    from engine.runlog import RunLog
    from marketing import run_day
    return run_day(FIXTURES, DECISIONS, MockLLM(FIXTURES), RunLog(echo=False))


@pytest.fixture
def prompts():
    from engine.prompts import Prompts
    return Prompts()
