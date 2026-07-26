"""The journal on its own: collapsing, capacity, and surviving a bad file."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.automation.journal import (
    KIND_ERROR,
    KIND_SKIPPED,
    KIND_SUCCESS,
    AutomationJournal,
)

T0 = datetime(2026, 7, 27, 20, 0)


def _journal(tmp_path, **kwargs) -> AutomationJournal:
    return AutomationJournal(tmp_path / "automation_journal.json", **kwargs)


def test_the_same_skip_folds_into_one_row_with_a_count(tmp_path) -> None:
    journal = _journal(tmp_path)

    for seconds in range(5):
        journal.record_skip(
            "game", "disconnected", now=T0 + timedelta(seconds=seconds), context={"target": "primary"}
        )

    entries = journal.entries()
    assert len(entries) == 1
    assert entries[0].count == 5
    assert entries[0].first_seen == T0
    assert entries[0].last_seen == T0 + timedelta(seconds=4)


def test_a_long_gap_starts_a_new_episode(tmp_path) -> None:
    """Two strips going offline a week apart are two events, not one row that
    has been "happening" for seven days."""
    journal = _journal(tmp_path, collapse_window=300)

    journal.record_skip("game", "disconnected", now=T0)
    journal.record_skip("game", "disconnected", now=T0 + timedelta(days=7))

    entries = journal.entries()
    assert len(entries) == 2
    assert [entry.count for entry in entries] == [1, 1]


def test_moving_details_update_in_place_instead_of_splitting_the_row(tmp_path) -> None:
    """paused_until changes on every tick; if it decided identity there would be
    no collapsing at all."""
    journal = _journal(tmp_path)

    journal.record_skip("game", "paused", now=T0, context={"paused_until": "20:10:00"})
    journal.record_skip("game", "paused", now=T0 + timedelta(seconds=1),
                        context={"paused_until": "20:10:00"})

    entries = journal.entries()
    assert len(entries) == 1
    assert entries[0].count == 2


def test_a_different_context_is_a_different_row(tmp_path) -> None:
    journal = _journal(tmp_path)

    journal.record_skip("game", "missing_scene", now=T0, context={"scene_id": "a"})
    journal.record_skip("game", "missing_scene", now=T0 + timedelta(seconds=1),
                        context={"scene_id": "b"})

    assert len(journal.entries()) == 2


def test_successes_and_errors_never_collapse(tmp_path) -> None:
    journal = _journal(tmp_path)

    for seconds in range(3):
        journal.record_success("game", message_code="scene_applied", now=T0 + timedelta(seconds=seconds))
        journal.record_error("game", message_code="execution_failed", now=T0 + timedelta(seconds=seconds))

    kinds = [entry.kind for entry in journal.entries()]
    assert kinds.count(KIND_SUCCESS) == 3
    assert kinds.count(KIND_ERROR) == 3


def test_the_oldest_entries_are_dropped_when_the_cap_is_reached(tmp_path) -> None:
    journal = _journal(tmp_path, max_entries=5)

    for index in range(12):
        journal.record_success(f"rule{index}", message_code="power_set", now=T0)

    entries = journal.entries()
    assert len(entries) == 5
    assert [entry.rule_id for entry in entries] == [f"rule{index}" for index in range(7, 12)]


def test_a_damaged_file_costs_the_history_not_the_run(tmp_path) -> None:
    """Automations must keep working after a bad shutdown."""
    path = tmp_path / "automation_journal.json"
    path.write_text("{ this is not json", encoding="utf-8")

    journal = AutomationJournal(path)
    journal.load()

    assert journal.entries() == []
    journal.record_skip("game", "disconnected", now=T0)
    assert journal.flush(0.0, force=True) is True
    assert len(journal.entries()) == 1


def test_entries_that_make_no_sense_are_dropped_one_by_one(tmp_path) -> None:
    path = tmp_path / "automation_journal.json"
    path.write_text(
        '{"entries": [{"id": 1, "kind": "success", "rule_id": "a"},'
        ' "nonsense", {"kind": "success"}, {"id": 4, "kind": "teleport"}]}',
        encoding="utf-8",
    )

    journal = AutomationJournal(path)
    journal.load()

    assert [entry.id for entry in journal.entries()] == [1]


def test_writing_is_debounced_but_shutdown_always_gets_through(tmp_path) -> None:
    journal = _journal(tmp_path, flush_interval=5.0)
    path = tmp_path / "automation_journal.json"

    journal.record_skip("game", "disconnected", now=T0)
    assert journal.flush(100.0) is True  # first write always goes
    journal.record_skip("other", "cooldown", now=T0 + timedelta(seconds=1))
    assert journal.flush(101.0) is False, "wrote again inside the debounce window"
    assert journal.flush(101.0, force=True) is True

    reloaded = AutomationJournal(path)
    reloaded.load()
    assert len(reloaded.entries()) == 2


def test_a_round_trip_keeps_what_the_user_reads(tmp_path) -> None:
    journal = _journal(tmp_path)
    path = tmp_path / "automation_journal.json"

    journal.record_success(
        "night",
        message_code="power_set",
        now=T0,
        occurred_at=T0 - timedelta(hours=9),
        decided_at=T0,
        context={"target": "primary", "power": False},
    )
    journal.record_skip("game", "outranked", now=T0, context={"winner_rule_id": "night"})
    journal.flush(0.0, force=True)

    reloaded = AutomationJournal(path)
    reloaded.load()
    success, skip = reloaded.entries()

    assert success.kind == KIND_SUCCESS
    assert success.message_code == "power_set"
    assert success.occurred_at == T0 - timedelta(hours=9)
    assert success.decided_at == T0
    assert success.context == {"target": "primary", "power": False}
    assert skip.kind == KIND_SKIPPED
    assert skip.context == {"winner_rule_id": "night"}


def test_a_skip_does_not_reach_back_across_a_success(tmp_path) -> None:
    """disconnected → success → disconnected is two episodes. Merging them would
    claim the strip was offline throughout a period it demonstrably was not."""
    journal = _journal(tmp_path)

    journal.record_skip("game", "disconnected", now=T0, context={"target": "primary"})
    journal.record_success("game", message_code="scene_applied", now=T0 + timedelta(seconds=1))
    journal.record_skip(
        "game", "disconnected", now=T0 + timedelta(seconds=2), context={"target": "primary"}
    )

    kinds = [(entry.kind, entry.count) for entry in journal.entries()]
    assert kinds == [(KIND_SKIPPED, 1), (KIND_SUCCESS, 1), (KIND_SKIPPED, 1)]


def test_a_skip_does_not_reach_back_across_a_different_reason(tmp_path) -> None:
    journal = _journal(tmp_path)

    journal.record_skip("game", "disconnected", now=T0)
    journal.record_skip("game", "cooldown", now=T0 + timedelta(seconds=1))
    journal.record_skip("game", "disconnected", now=T0 + timedelta(seconds=2))

    reasons = [(entry.reason, entry.count) for entry in journal.entries()]
    assert reasons == [("disconnected", 1), ("cooldown", 1), ("disconnected", 1)]


def test_another_rule_in_between_does_not_break_an_episode(tmp_path) -> None:
    """A busy log interleaves rules; that says nothing about this one."""
    journal = _journal(tmp_path)

    journal.record_skip("game", "disconnected", now=T0)
    journal.record_success("other", message_code="scene_applied", now=T0 + timedelta(seconds=1))
    journal.record_skip("game", "disconnected", now=T0 + timedelta(seconds=2))

    game = [entry for entry in journal.entries() if entry.rule_id == "game"]
    assert len(game) == 1
    assert game[0].count == 2


def test_one_nonsense_number_costs_that_entry_only(tmp_path) -> None:
    path = tmp_path / "automation_journal.json"
    path.write_text(
        '{"entries": [{"id": 1, "kind": "success", "rule_id": "a", "count": "banana"},'
        ' {"id": 2, "kind": "success", "rule_id": "b"}]}',
        encoding="utf-8",
    )

    journal = AutomationJournal(path)
    journal.load()

    assert [entry.rule_id for entry in journal.entries()] == ["b"]
