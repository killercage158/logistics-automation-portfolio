"""The rulebook: every business rule has an ID, a plain-English title and a function.

Why this exists. A quote engine is mostly rules, and rules are what staff argue
about ("why was this carrier left out?"). So in this demo:

  1. Each rule lives in ONE function, tagged with its ID by the @rule decorator.
  2. The same ID appears in the department's skill file (skills/*.md), which is
     the document the AI reader is given. The tests check that the two lists match.
  3. Every time a rule changes the outcome, the code records a "hit" in a
     RuleTrace. The reports print those IDs next to each option or rejected item,
     so any result can be traced back to the rules that shaped it.

Rule ID prefixes:  BK booking prices   LC local charges   FT free time
                   TR trucking         CU customs         SS sales support
                   DP dispatch (who gets which work, deadlines, reminders)

In production, each department has its own guide document and its own AI reader
that follows it; code checks every citation the AI gives.
"""
import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

DEPARTMENTS = {"BK": "Booking", "LC": "Local charges", "FT": "Free time", "TR": "Trucking",
               "CU": "Customs", "SS": "Sales support", "DP": "Dispatch"}

RULES = {}          # rule id -> Rule, filled in as the modules are imported


@dataclass
class Rule:
    id: str
    title: str
    function: str

    @property
    def department(self):
        return DEPARTMENTS[self.id[:2]]


def rule(rule_id, title):
    """Decorator: register `function` as the code that implements rule `rule_id`."""
    def register(function):
        if rule_id in RULES:
            raise ValueError(f"rule {rule_id} is registered twice")
        RULES[rule_id] = Rule(rule_id, title, f"{function.__module__}.{function.__name__}")
        function.rule_id = rule_id
        return function
    return register


class RuleTrace:
    """Collects (rule id, subject, text) every time a rule changes an outcome.

    `subject` is whatever the rule acted on: a carrier name, a haulier, an HS code.
    The reports use ids_for(subject) to fill the "rules applied" column.
    """

    def __init__(self):
        self.entries = []

    def hit(self, rule_id, subject, text=""):
        if rule_id not in RULES:
            raise KeyError(f"unknown rule {rule_id}")
        self.entries.append((rule_id, subject, text))

    def ids_for(self, subject):
        return sorted({r for r, s, _ in self.entries if s == subject})

    def all_ids(self):
        return sorted({r for r, _, _ in self.entries})

    def count(self, rule_id):
        return sum(1 for r, _, _ in self.entries if r == rule_id)


def hit(trace, rule_id, subject, text=""):
    """Record a hit if a trace was passed in (rules also work without one, e.g. in unit tests)."""
    if trace is not None:
        trace.hit(rule_id, subject, text)


# --- skill files ---------------------------------------------------------------------------
def load_skill(name):
    """Return the text of skills/<name>.md. The AI reader puts it into its prompt."""
    return (SKILLS_DIR / f"{name}.md").read_text(encoding="utf-8")


def skill_rule_ids():
    """Rule IDs written in the skill files (headings like '### BK-02 Contract first')."""
    ids = set()
    for path in SKILLS_DIR.glob("*.md"):
        ids.update(re.findall(r"^### ([A-Z]{2}-\d{2})\b", path.read_text(encoding="utf-8"), re.M))
    return ids


def import_all_rule_modules():
    """Import every module that registers rules, so RULES is complete (used by tests)."""
    import engine.contracts, engine.customs, engine.dispatch, engine.free_time        # noqa: F401
    import engine.local_charges, engine.manual, engine.portals, engine.rules          # noqa: F401
    import engine.sales_support, engine.trucking, engine.verify                       # noqa: F401
