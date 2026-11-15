"""DP-01 .. DP-07."""
import pytest

from engine.dispatch import (DEADLINE_MIN, REMINDER_MIN, WorkItem, all_answered, clock, create_items,
                             deadline_for, due_reminders, needed_departments, record_answer, respond, simulate)

TIMELINE = {"Booking": [("accept", 2), ("answer", 11, "system")],
            "Trucking": [("accept", 3), ("answer", 14, "system")],
            "Customs": [("accept", 6), ("answer", 47, "system")]}


def item(status="open", created=0):
    return WorkItem("LD-1", "Customs", created, created + DEADLINE_MIN, status)


# DP-01 ------------------------------------------------------------------------------------
@pytest.mark.parametrize("pickup, product, expected", [
    ("Bac Ninh", "wood charcoal", ["Booking", "Trucking", "Customs"]),
    ("", "wood charcoal", ["Booking", "Customs"]),
    ("Bac Ninh", "", ["Booking", "Trucking"]),
    ("", "", ["Booking"])])
def test_dp01_only_the_needed_departments_get_an_item(pickup, product, expected):
    assert needed_departments(pickup, product) == expected


def test_dp01_items_are_created_with_a_trace(trace):
    items = create_items({}, "LD-1", ["Booking", "Customs"], 0, trace)
    assert [i.department for i in items] == ["Booking", "Customs"] and trace.count("DP-01") == 2


# DP-02 ------------------------------------------------------------------------------------
def test_dp02_deadline_is_30_minutes_after_creation():
    assert DEADLINE_MIN == 30 and deadline_for(0) == 30 and deadline_for(15) == 45


def test_dp02_created_items_carry_the_deadline(trace):
    assert create_items({}, "LD-1", ["Booking"], 10, trace)[0].deadline == 40


# DP-03 ------------------------------------------------------------------------------------
def test_dp03_no_reminder_before_the_first_reminder_time():
    assert due_reminders(item(), REMINDER_MIN[0] - 1) == []


def test_dp03_first_reminder_goes_to_the_assignee_only():
    assert due_reminders(item(), 40) == [(40, "assignee")]


def test_dp03_later_reminders_also_go_to_the_leader():
    assert [w for _, w in due_reminders(item(), 90)] == ["assignee", "assignee + leader", "assignee + leader"]


def test_dp03_an_answered_item_gets_no_reminders():
    assert due_reminders(item("answered"), 120) == []


def test_dp03_reminders_count_from_creation_time():
    assert due_reminders(item(created=10), 49) == [] and due_reminders(item(created=10), 50) == [(50, "assignee")]


def test_dp03_a_late_department_is_reminded_in_the_timeline():
    _, events = simulate("LD-1", ["Booking", "Trucking", "Customs"], TIMELINE)
    reminders = [e for e in events if e.text.startswith("reminder")]
    assert [(e.minute, e.text) for e in reminders] == [(40, "reminder to Customs assignee")]


# DP-04 ------------------------------------------------------------------------------------
def test_dp04_a_department_can_accept(trace):
    i = item()
    respond(i, "accept", 5, trace=trace)
    assert i.status == "accepted" and i.accepted_at == 5 and "DP-04" in trace.ids_for("Customs")


def test_dp04_a_decline_keeps_the_reason_and_does_not_count_as_an_answer():
    i = item()
    respond(i, "decline", 4, "no trailer free")
    assert i.status == "declined" and i.decline_reason == "no trailer free" and not all_answered([i])


def test_dp04_an_unknown_action_is_an_error():
    with pytest.raises(ValueError):
        respond(item(), "ignore", 1)


def test_dp04_a_decline_goes_back_to_sales_support_who_answers_by_hand():
    plan = {"Trucking": [("decline", 4, "no trailer free"), ("answer", 33, "manual")]}
    items, events = simulate("LD-1", ["Booking", "Trucking"], {**plan, "Booking": [("answer", 10, "system")]})
    text = [e for e in events if "DECLINED" in e.text or "manual" in e.text]
    assert "back to Sales Support" in text[0].text and text[1].who == "Sales Support"
    assert all(i.status == "answered" for i in items)


# DP-05 ------------------------------------------------------------------------------------
def test_dp05_a_manual_entry_completes_the_item(trace):
    i = item()
    record_answer(i, "manual", 20, trace)
    assert i.status == "answered" and i.answer_kind == "manual" and "DP-05" in trace.ids_for("Customs")


def test_dp05_a_system_answer_completes_the_item_too():
    i = item()
    record_answer(i, "system", 20)
    assert i.status == "answered"


def test_dp05_only_system_or_manual_are_valid_kinds():
    with pytest.raises(ValueError):
        record_answer(item(), "guess", 1)


# DP-06 ------------------------------------------------------------------------------------
def test_dp06_everyone_answered_triggers_the_notice(trace):
    items, events = simulate("LD-1", ["Booking", "Trucking", "Customs"], TIMELINE, trace)
    assert all_answered(items) and "DP-06" in trace.all_ids()
    assert events[-1].text.startswith("every department has answered") and events[-1].minute == 47


def test_dp06_one_open_item_means_no_notice():
    partial = {"Booking": [("answer", 10, "system")], "Customs": [("accept", 6)]}
    items, events = simulate("LD-1", ["Booking", "Customs"], partial)
    assert not all_answered(items) and not any("every department" in e.text for e in events)


def test_dp06_no_items_is_not_done():
    assert not all_answered([])


# DP-07 ------------------------------------------------------------------------------------
def test_dp07_dispatching_twice_creates_one_item_per_department(trace):
    store = {}
    first = create_items(store, "LD-1", ["Booking", "Customs"], 0, trace)
    second = create_items(store, "LD-1", ["Booking", "Customs"], 5, trace)
    assert first[0] is second[0] and len(store) == 2 and trace.count("DP-07") == 2


def test_dp07_the_same_department_on_another_lead_gets_its_own_item():
    store = {}
    create_items(store, "LD-1", ["Booking"], 0)
    create_items(store, "LD-2", ["Booking"], 0)
    assert len(store) == 2


def test_dp07_simulation_dispatches_twice_without_duplicating():
    items, events = simulate("LD-1", ["Booking"], {"Booking": [("answer", 5, "system")]})
    assert len(items) == 1 and sum(1 for e in events if "work item created" in e.text) == 1


# the clock ----------------------------------------------------------------------------------
def test_clock_shows_wall_clock_time():
    assert clock(0) == "09:00" and clock(47) == "09:47" and clock(90, "23:30") == "01:00"
