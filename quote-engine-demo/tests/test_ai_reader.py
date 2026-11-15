import json

import pytest

from engine.ai_reader import ReplyError, parse_json_reply, read_price_file, to_price_row
from engine.runlog import RunLog

ITEM = {"carrier": "X", "pol": "HPH", "pod": "SIN", "container": "40 HQ", "cargo": None,
        "price_usd": 610, "valid_until": "2026-12-31", "source": {"sheet": "S", "cell": "c5"}}


def test_plain_json():
    assert parse_json_reply(json.dumps([ITEM]))[0]["carrier"] == "X"


def test_fenced_json_with_chatter():
    text = "Here you go:\n```json\n" + json.dumps([ITEM]) + "\n```\nAnything else?"
    assert len(parse_json_reply(text)) == 1


def test_trailing_comma_is_repaired():
    assert len(parse_json_reply('[{"a": 1},]')) == 1


@pytest.mark.parametrize("bad", ["I could not read it", '```json\n[{"a": 1}, {"b"', ""])
def test_unusable_reply_raises(bad):
    with pytest.raises(ReplyError):
        parse_json_reply(bad)


def test_item_is_normalised():
    row = to_price_row(ITEM, "f.xlsx")
    assert (row.pol, row.pod, row.container, row.cell, row.file) == \
        ("Hai Phong", "Singapore", "40HC", "C5", "f.xlsx")


def test_item_with_unknown_port_is_an_error():
    with pytest.raises(ValueError):
        to_price_row({**ITEM, "pol": "Atlantis"}, "f.xlsx")


class FakeLLM:
    """Gives a broken reply first, then a good one: shows the single re-ask."""
    name = "fake"

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def complete(self, system, user):
        self.calls.append(user)
        return self.replies.pop(0)


def test_one_re_ask_when_first_reply_is_broken(sample_dir):
    path = sample_dir / "price_files" / "bluewave_spot_nov.xlsx"
    llm = FakeLLM(["sorry, here are the prices: [{", json.dumps([ITEM])])
    rows, problems = read_price_file(llm, path, RunLog(echo=False))
    assert len(rows) == 1 and problems == [] and len(llm.calls) == 2
    assert "was not valid JSON" in llm.calls[1]


def test_file_is_reported_unreadable_after_second_failure(sample_dir):
    path = sample_dir / "price_files" / "bluewave_spot_nov.xlsx"
    rows, problems = read_price_file(FakeLLM(["nope", "still nope"]), path, RunLog(echo=False))
    assert rows == [] and "unreadable" in problems[0][1]
