"""The rulebook itself: skill files, rule functions, tests and the trace must all agree."""
import re
from pathlib import Path

import pytest

from engine.rulebook import RULES, RuleTrace, hit, import_all_rule_modules, load_skill, rule, skill_rule_ids

import_all_rule_modules()
TESTS = Path(__file__).parent


def test_every_rule_in_a_skill_file_has_a_function_and_the_other_way_round():
    assert set(RULES) == skill_rule_ids()


def test_every_rule_has_a_title_a_department_and_a_function_name():
    for r in RULES.values():
        assert r.title and r.department and "." in r.function


def test_every_rule_id_has_at_least_one_test_named_after_it():
    text = "".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py"))
    untested = [i for i in RULES if not re.search(rf"def test_{i.lower().replace('-', '')}_", text)]
    assert untested == []


def test_rule_ids_have_the_expected_shape():
    assert all(re.fullmatch(r"(BK|LC|FT|TR|CU|SS|DP)-\d\d", i) for i in RULES)


def test_every_skill_file_can_be_loaded_for_the_ai_prompt():
    names = [p.stem for p in (Path(__file__).parents[1] / "skills").glob("*.md")]
    assert len(names) == 7 and all("###" in load_skill(n) for n in names)


def test_registering_a_rule_twice_is_an_error():
    with pytest.raises(ValueError):
        rule("BK-02", "again")(lambda: None)


def test_a_trace_records_hits_per_subject_and_counts_them():
    t = RuleTrace()
    t.hit("BK-04", "A", "x")
    t.hit("BK-04", "B", "y")
    t.hit("LC-01", "A", "z")
    assert t.ids_for("A") == ["BK-04", "LC-01"] and t.count("BK-04") == 2 and t.all_ids() == ["BK-04", "LC-01"]


def test_a_trace_refuses_unknown_rule_ids():
    with pytest.raises(KeyError):
        RuleTrace().hit("XX-99", "A")


def test_hit_without_a_trace_does_nothing():
    hit(None, "BK-04", "A")
