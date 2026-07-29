"""Automations with the app closed: one winner, whatever Windows fires.

The case that matters most is the machine waking after both an "on at 19:00" and
an "off at 23:00" have come due. Task Scheduler starts both tasks; if each one ran
its own rule the light would end up wherever the last process happened to finish.
So these tests pin that a task invocation is only a wake-up, that the winner is
chosen by the resolver's own rule, and that a sibling process finds nothing left to
do rather than racing the first.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import count
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QTimer, Signal

from app import storage
from app.automation import headless as headless_module
from app.automation.dispatcher import CODE_EXECUTION_FAILED, CODE_POWER_SET, CODE_TIMEOUT
from app.automation.file_lock import file_lock
from app.automation.headless import (
    CODE_CONNECT_FAILED,
    EXIT_FAILED,
    EXIT_NO_ADDRESS,
    EXIT_OK,
    EXIT_PRO_REQUIRED,
    SKIP_AUTOMATIONS_DISABLED,
    SKIP_BUSY,
    SKIP_NO_BACKGROUND_RULES,
    SKIP_NOTHING_DUE,
    _RuleRunner,
    due_rules,
    load_state,
    run_automations,
)
from app.automation.journal import (
    KIND_ERROR,
    KIND_SKIPPED,
    KIND_SUCCESS,
    AutomationJournal,
)
from app.automation.resolver import SKIP_COOLDOWN, SKIP_OUTRANKED
from app.automation.rules import validate_rule, validate_rules

RULE_ID = "evening-off"
ADDRESS = "AA:BB:CC:DD:EE:01"
# The machine was awake in the evening, slept through both the "on" and the "off",
# and woke the next morning with them overdue.
EVENING_BEFORE = datetime(2026, 7, 26, 18, 0)
MORNING_AFTER = datetime(2026, 7, 27, 8, 10)
DUE_OCCURRENCE = datetime(2026, 7, 26, 23, 0)


@dataclass(frozen=True)
class _Result:
    operation_id: int
    ok: bool
    code: str


class FakeController(QObject):
    """The bits of BleController this path touches, minus the BLE thread."""

    status_changed = Signal(str)
    connected_changed = Signal(bool, str)
    error_occurred = Signal(str)
    operation_finished = Signal(object)

    instances: list[FakeController] = []
    refuse_writes = False

    def __init__(self) -> None:
        super().__init__()
        self.connect_requests: list[str] = []
        self.submitted: list[tuple[int, bool, str]] = []
        self.cancelled: list[int] = []
        self.shutdown_calls = 0
        self._address = ""
        self._ids = count(1)
        FakeController.instances.append(self)

    # what the runner uses
    def connect_to_address(self, address: str) -> None:
        self.connect_requests.append(address)

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    # what the executor uses
    def primary_address(self) -> str:
        return self._address

    def mirror_addresses(self) -> list[str]:
        return []

    def set_power_for_address_tracked(self, enabled: bool, address: str) -> int:
        operation_id = next(self._ids)
        self.submitted.append((operation_id, bool(enabled), address))
        return operation_id

    def cancel_operation(self, operation_id: int) -> bool:
        self.cancelled.append(operation_id)
        return True

    # the world happening to it
    def arrive(self, address: str = ADDRESS) -> None:
        self._address = address
        self.connected_changed.emit(True, address)

    def answer(self, operation_id: int, *, ok: bool = True, code: str = "") -> None:
        self.operation_finished.emit(
            _Result(operation_id, ok, code or ("success" if ok else "ble_error"))
        )

    def powers(self) -> list[bool]:
        return [enabled for _id, enabled, _address in self.submitted]


class Answering(FakeController):
    """Connects and answers from the event loop, the way the real one does.

    Used by every run that goes through ``run_automations``: nothing arrives unless a
    ``QCoreApplication`` is turning, which is itself part of what is being tested.
    """

    def connect_to_address(self, address: str) -> None:
        super().connect_to_address(address)
        QTimer.singleShot(0, lambda: self.arrive(address))

    def set_power_for_address_tracked(self, enabled: bool, address: str) -> int:
        operation_id = super().set_power_for_address_tracked(enabled, address)
        QTimer.singleShot(0, lambda: self.answer(operation_id, ok=not self.refuse_writes))
        return operation_id


class Refusing(Answering):
    refuse_writes = True


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    """No hardware and no Pro check. ``quit()`` is left real: with no event loop
    running it does nothing, and the runs that turn one need it to work."""
    FakeController.instances = []
    monkeypatch.setattr(headless_module, "BleController", FakeController)
    monkeypatch.setattr(headless_module, "can_use", lambda feature: True)
    yield


def _rule(**overrides: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": RULE_ID,
        "name": "Evening off",
        "trigger": {"kind": "time", "time_at": "23:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        "action": {"type": "set_power", "power": False, "target": "primary"},
        "execution": "background",
        "enabled": True,
    }
    rule.update(overrides)
    return rule


def _time_rule(rule_id: str, time_at: str, *, power: bool, **overrides: Any) -> dict[str, Any]:
    return _rule(
        id=rule_id,
        trigger={"kind": "time", "time_at": time_at, "days": [0, 1, 2, 3, 4, 5, 6]},
        action={"type": "set_power", "power": power, "target": "primary"},
        **overrides,
    )


def _store(
    *, enabled: bool = True, rules: list[dict[str, Any]] | None = None, address: str = ADDRESS
) -> None:
    settings = storage.load_settings()
    settings["automations"] = {
        "enabled": enabled,
        "rules": rules if rules is not None else [_rule()],
    }
    settings["last_device_address"] = address
    storage.save_settings(settings)


def _watching_since(when: datetime, *rule_ids: str) -> None:
    """Say that these rules were already in view at ``when``.

    Without it a rule is one this pass is seeing for the first time, and nothing from
    before that moment counts as due — which is what stops a task firing at 22:00
    from replaying last night's 23:00 rule.
    """
    headless_module.save_state({"seen_since": dict.fromkeys(rule_ids, when)})


def _journal() -> list:
    journal = AutomationJournal(storage.automation_journal_path())
    journal.load()
    return journal.entries()


def _lines() -> list[tuple[str, str, str]]:
    return [
        (entry.kind, entry.rule_id, entry.reason or entry.message_code) for entry in _journal()
    ]


# ── the rules are stored and survive a round trip ─────────────────────
def test_a_background_rule_survives_being_saved() -> None:
    """The settings validator drops what it does not know, so a rule that is not in
    its whitelist would vanish on the next save."""
    _store()

    stored = storage.load_settings()["automations"]

    assert stored["enabled"] is True
    assert [rule["id"] for rule in stored["rules"]] == [RULE_ID]
    assert stored["rules"][0]["execution"] == "background"


def test_a_corrupt_rule_does_not_cost_the_others() -> None:
    _store(rules=[{"id": "", "trigger": {}}, _rule()])

    assert [rule["id"] for rule in storage.load_settings()["automations"]["rules"]] == [RULE_ID]


# ── one winner among everything that came due ─────────────────────────
def test_only_one_of_two_overdue_rules_is_carried_out(monkeypatch) -> None:
    """The regression this path exists for. Two tasks fire after a sleep; running
    each one independently would leave the light wherever the last process to finish
    put it. The later crossing wins, the other is recorded as outranked, and the
    sibling task finds nothing left to do."""
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store(
        rules=[
            _time_rule("evening-on", "19:00", power=True),
            _time_rule("evening-off", "23:00", power=False),
        ]
    )
    _watching_since(EVENING_BEFORE, "evening-on", "evening-off")

    assert run_automations(woken_by="evening-on", timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK

    controller = FakeController.instances[-1]
    assert controller.powers() == [False], "the later crossing should win, and be applied once"
    assert (KIND_SUCCESS, "evening-off", CODE_POWER_SET) in _lines()
    assert (KIND_SKIPPED, "evening-on", SKIP_OUTRANKED) in _lines()

    # The sibling task, fired for the rule that lost.
    assert run_automations(woken_by="evening-off", timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK

    assert len(FakeController.instances) == 1, "a second process ran an already-handled rule"
    assert (KIND_SKIPPED, "", SKIP_NOTHING_DUE) in _lines()


def test_priority_beats_freshness_among_overdue_rules(monkeypatch) -> None:
    """The same conflict rule as the resolver: priority first, and only then which
    crossing is the most recent."""
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store(
        rules=[
            _time_rule("evening-on", "19:00", power=True, priority=10),
            _time_rule("evening-off", "23:00", power=False),
        ]
    )
    _watching_since(EVENING_BEFORE, "evening-on", "evening-off")

    assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK

    assert FakeController.instances[-1].powers() == [True]
    assert (KIND_SKIPPED, "evening-off", SKIP_OUTRANKED) in _lines()


def test_a_handled_occurrence_is_not_run_again(monkeypatch) -> None:
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store()
    _watching_since(EVENING_BEFORE, RULE_ID)

    assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK
    assert run_automations(timeout_ms=1500, now=MORNING_AFTER + timedelta(minutes=5)) == EXIT_OK

    assert len(FakeController.instances) == 1
    assert load_state()["handled"][RULE_ID] == DUE_OCCURRENCE


def test_a_run_that_failed_is_left_for_the_next_task(monkeypatch) -> None:
    """The engine records only successes, so a failed rule stays un-applied and may
    be tried again. That has to hold across processes too, or a strip that was busy
    for a second would cost the user the whole evening."""
    monkeypatch.setattr(headless_module, "BleController", Refusing)
    _store()
    _watching_since(EVENING_BEFORE, RULE_ID)

    assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_FAILED
    assert load_state()["handled"] == {}, "a failed run was recorded as handled"

    monkeypatch.setattr(headless_module, "BleController", Answering)

    assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK
    assert load_state()["handled"][RULE_ID] == DUE_OCCURRENCE


def test_a_rule_still_cooling_down_is_skipped(monkeypatch) -> None:
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store(rules=[_rule(cooldown_seconds=3600)])
    headless_module.save_state(
        {
            "seen_since": {RULE_ID: EVENING_BEFORE},
            "fired": {RULE_ID: MORNING_AFTER - timedelta(minutes=5)},
        }
    )

    assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK

    assert FakeController.instances == []
    assert (KIND_SKIPPED, RULE_ID, SKIP_COOLDOWN) in _lines()


def test_nothing_overdue_means_nothing_happens(monkeypatch) -> None:
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store()
    _watching_since(EVENING_BEFORE, RULE_ID)
    # Woken at 22:00 by some other task: the 23:00 rule is not due yet, and its own
    # last occurrence was handled the night before.
    headless_module.save_state(
        {"seen_since": {RULE_ID: EVENING_BEFORE}, "handled": {RULE_ID: DUE_OCCURRENCE}}
    )

    assert run_automations(timeout_ms=1500, now=datetime(2026, 7, 27, 22, 0)) == EXIT_OK

    assert FakeController.instances == []
    assert (KIND_SKIPPED, "", SKIP_NOTHING_DUE) in _lines()


def test_a_first_pass_does_not_replay_last_nights_rule(monkeypatch) -> None:
    """No state at all — a fresh install, or a deleted state file. A task firing at
    22:00 must not decide that last night's 23:00 rule is still owed and switch the
    light there and then; the engine refuses the same thing on its first tick."""
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store()

    assert run_automations(timeout_ms=1500, now=datetime(2026, 7, 27, 22, 0)) == EXIT_OK

    assert FakeController.instances == [], "a rule from before we were watching was replayed"
    assert (KIND_SKIPPED, "", SKIP_NOTHING_DUE) in _lines()


def test_the_crossing_that_woke_us_counts_on_a_first_pass(monkeypatch) -> None:
    """The other side of that: with no state, the task firing *now* still gets its
    run, or a fresh install's very first evening would silently do nothing."""
    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store()

    assert run_automations(timeout_ms=1500, now=datetime(2026, 7, 27, 23, 0, 2)) == EXIT_OK

    assert FakeController.instances[-1].powers() == [False]
    assert load_state()["handled"][RULE_ID] == datetime(2026, 7, 27, 23, 0)


def test_a_missed_run_reaches_no_further_back_than_the_catch_up_window() -> None:
    """A machine off for a week must not replay last Tuesday's evening on Monday."""
    rules = validate_rules([_rule()])
    week_later = datetime(2026, 8, 3, 12, 0)

    due, _cooling = due_rules(
        rules, {"handled": {RULE_ID: datetime(2026, 7, 20, 23, 0)}}, week_later
    )

    assert [rule.id for rule, _occurred in due] == [RULE_ID]
    assert due[0][1] == datetime(2026, 8, 2, 23, 0), "the run should be the most recent crossing"


def test_a_task_that_starts_a_moment_early_still_counts_as_due() -> None:
    """Task Scheduler can fire just before this process reads the clock; refusing to
    act there would silently drop the run."""
    rules = validate_rules([_rule()])

    due, _cooling = due_rules(rules, {}, datetime(2026, 7, 27, 22, 59, 59))

    assert [occurred for _rule, occurred in due] == [datetime(2026, 7, 27, 23, 0)]


# ── one run at a time, across processes ───────────────────────────────
def test_a_run_waits_for_another_process_and_then_stands_down(monkeypatch) -> None:
    """Holding the execution lock stands in for a sibling task mid-run: the second
    process must not write to the strip alongside it."""
    monkeypatch.setattr(headless_module, "BleController", Answering)
    monkeypatch.setattr(headless_module, "LOCK_TIMEOUT_SECONDS", 0.2)
    _store()
    _watching_since(EVENING_BEFORE, RULE_ID)

    with file_lock(headless_module.execution_lock_path(), timeout=1.0) as locked:
        assert locked, "the lock could not be taken by the test itself"
        assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK

    assert FakeController.instances == [], "a run started while another was in progress"
    assert (KIND_SKIPPED, "", SKIP_BUSY) in _lines()


def test_rules_are_reloaded_after_waiting_for_the_execution_lock(monkeypatch) -> None:
    """A queued task must not execute a rule the user disabled while it waited."""
    from contextlib import contextmanager

    monkeypatch.setattr(headless_module, "BleController", Answering)
    _store()
    _watching_since(EVENING_BEFORE, RULE_ID)

    @contextmanager
    def changed_while_waiting(_path, *, timeout):
        _store(enabled=False)
        yield True

    monkeypatch.setattr(headless_module, "file_lock", changed_while_waiting)

    assert run_automations(timeout_ms=1500, now=MORNING_AFTER) == EXIT_OK
    assert FakeController.instances == [], "a stale enabled rule was executed"
    assert (KIND_SKIPPED, "", SKIP_AUTOMATIONS_DISABLED) in _lines()


def test_the_due_clock_is_read_after_waiting_for_the_execution_lock(monkeypatch) -> None:
    """A crossing during the wait belongs to this run, not to a stale start time."""
    from contextlib import contextmanager

    before = datetime(2026, 7, 27, 22, 59, 30)
    after = datetime(2026, 7, 27, 23, 0, 5)

    class MovingDateTime(datetime):
        current = before

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(headless_module, "BleController", Answering)
    monkeypatch.setattr(headless_module, "datetime", MovingDateTime)
    _store()
    _watching_since(before - timedelta(minutes=1), RULE_ID)

    @contextmanager
    def crossing_while_waiting(_path, *, timeout):
        MovingDateTime.current = after
        yield True

    monkeypatch.setattr(headless_module, "file_lock", crossing_while_waiting)

    assert run_automations(timeout_ms=1500) == EXIT_OK
    assert FakeController.instances[0].powers() == [False]


# ── a task that fires with nothing to run ─────────────────────────────
@pytest.mark.parametrize(
    ("store_kwargs", "reason"),
    [
        ({"enabled": False}, SKIP_AUTOMATIONS_DISABLED),
        ({"rules": [_rule(enabled=False)]}, SKIP_NO_BACKGROUND_RULES),
        ({"rules": [_rule(execution="runtime")]}, SKIP_NO_BACKGROUND_RULES),
        ({"rules": []}, SKIP_NO_BACKGROUND_RULES),
    ],
)
def test_a_task_with_nothing_to_run_is_not_a_failure(store_kwargs, reason) -> None:
    """Task Scheduler shows a non-zero exit as a red cross the user cannot act on.
    Nothing went wrong here, so it exits 0 — and says why in the journal."""
    _store(**store_kwargs)

    assert run_automations(woken_by=RULE_ID, now=MORNING_AFTER) == EXIT_OK
    assert FakeController.instances == [], "a rule that must not run opened a connection"

    entries = _journal()
    assert [(entry.kind, entry.reason) for entry in entries] == [(KIND_SKIPPED, reason)]
    assert entries[0].context.get("background") is True
    assert entries[0].context.get("woken_by") == RULE_ID


def test_pro_is_required_for_a_background_run(monkeypatch) -> None:
    _store()
    monkeypatch.setattr(headless_module, "can_use", lambda feature: False)

    assert run_automations(now=MORNING_AFTER) == EXIT_PRO_REQUIRED
    assert FakeController.instances == []


def test_no_saved_controller_is_reported_as_an_error() -> None:
    """Nothing to connect to is a real fault: the user has a rule that cannot run
    until they pair a strip again."""
    _store(address="")
    _watching_since(EVENING_BEFORE, RULE_ID)

    assert run_automations(now=MORNING_AFTER) == EXIT_NO_ADDRESS
    assert (KIND_ERROR, RULE_ID, headless_module.CODE_NO_ADDRESS) in _lines()


def test_the_journal_keeps_what_was_already_on_disk() -> None:
    """A background run adds a line. Rewriting the file with only its own entry would
    wipe the history the app collected while it was open."""
    journal = AutomationJournal(storage.automation_journal_path())
    journal.record_success(
        "other-rule", message_code=CODE_POWER_SET, now=datetime(2026, 7, 26, 9, 0)
    )
    assert journal.flush(0.0, force=True) is True
    _store(enabled=False)

    run_automations(woken_by=RULE_ID, now=MORNING_AFTER)

    assert [entry.rule_id for entry in _journal()] == ["other-rule", RULE_ID]


# ── the run itself ────────────────────────────────────────────────────
def _runner(**rule_overrides: Any) -> tuple[_RuleRunner, FakeController, AutomationJournal]:
    """A runner wired to a fake controller, started but not yet connected."""
    _store()
    stored = validate_rule(_rule(**rule_overrides))
    assert stored is not None
    journal = AutomationJournal(storage.automation_journal_path())
    runner = _RuleRunner(
        stored,
        ADDRESS,
        storage.load_settings(),
        journal,
        occurred_at=DUE_OCCURRENCE,
        timeout_ms=60_000,
    )
    runner.start()
    controller = FakeController.instances[-1]
    assert controller.connect_requests == [ADDRESS]
    return runner, controller, journal


def test_a_confirmed_write_is_a_success() -> None:
    runner, controller, journal = _runner()

    controller.arrive()
    assert controller.submitted == [(1, False, ADDRESS)], "the main strip was not switched"
    assert runner.exit_code == EXIT_FAILED, "the run was called done before the write answered"

    controller.answer(1, ok=True)

    assert runner.exit_code == EXIT_OK
    assert controller.shutdown_calls == 1
    entry = journal.entries()[-1]
    assert (entry.kind, entry.message_code) == (KIND_SUCCESS, CODE_POWER_SET)
    assert entry.context["completed_steps"] == 1
    assert entry.context["background"] is True
    # The scheduled time, not the moment Windows got round to it: after a night
    # asleep those differ, and the journal has to be able to show both.
    assert entry.occurred_at == DUE_OCCURRENCE
    assert entry.decided_at is not None and entry.decided_at > DUE_OCCURRENCE


def test_a_successful_run_updates_the_power_the_app_will_restore() -> None:
    """Reconnecting restores the desired power state, so without this the next launch
    would undo the background run."""
    storage.save_settings({**storage.load_settings(), "last_state": {"power": True}})
    runner, controller, _journal_obj = _runner(action={"type": "set_power", "power": False})

    controller.arrive()
    controller.answer(1, ok=True)

    assert runner.exit_code == EXIT_OK
    assert storage.load_settings()["last_state"]["power"] is False


def test_recording_the_power_does_not_undo_what_the_app_changed_meanwhile() -> None:
    """This process stays alive for the length of a BLE connection. Writing back the
    settings it read at the start would erase everything the open app did in between,
    so only the one key it owns is touched."""
    _runner_obj, controller, _journal_obj = _runner(action={"type": "set_power", "power": False})

    # The app, still open, changes something else while the run is in flight.
    settings = storage.load_settings()
    settings["color_temperature"] = 3000
    storage.save_settings(settings)

    controller.arrive()
    controller.answer(1, ok=True)

    saved = storage.load_settings()
    assert saved["last_state"]["power"] is False, "the background run was not recorded"
    assert saved["color_temperature"] == 3000, "a stale snapshot overwrote the app's change"


def test_a_write_the_strip_refused_is_a_failure() -> None:
    """The verdict carries the run's own stable code, not the BLE layer's: a scene of
    several writes could not pick one of them to speak for the rule. What the user is
    told instead is how many steps of it landed."""
    runner, controller, journal = _runner()

    controller.arrive()
    controller.answer(1, ok=False, code="ble_error")

    assert runner.exit_code == EXIT_FAILED
    entry = journal.entries()[-1]
    assert (entry.kind, entry.message_code) == (KIND_ERROR, CODE_EXECUTION_FAILED)
    assert (entry.context["completed_steps"], entry.context["total_steps"]) == (0, 1)


def test_a_reconnect_does_not_send_the_action_twice() -> None:
    runner, controller, _journal_obj = _runner()

    controller.arrive()
    controller.arrive()  # the link dropped and came back

    assert len(controller.submitted) == 1
    controller.answer(1, ok=True)
    assert runner.exit_code == EXIT_OK


def test_a_strip_that_never_came_up_times_out() -> None:
    runner, controller, journal = _runner()

    runner._on_timeout()

    assert runner.exit_code == EXIT_FAILED
    entry = journal.entries()[-1]
    assert (entry.kind, entry.message_code) == (KIND_ERROR, CODE_TIMEOUT)
    assert "partial_possible" not in entry.context, "nothing was sent, so nothing can be in doubt"
    assert controller.shutdown_calls == 1


def test_a_write_that_never_reported_times_out_with_the_doubt_attached() -> None:
    runner, controller, journal = _runner()

    controller.arrive()
    runner._on_timeout()

    assert runner.exit_code == EXIT_FAILED
    entry = journal.entries()[-1]
    assert (entry.kind, entry.message_code) == (KIND_ERROR, CODE_TIMEOUT)
    assert entry.context["partial_possible"] is True
    assert controller.cancelled == [1], "the abandoned operation was left running"


def test_a_late_result_after_the_timeout_changes_nothing() -> None:
    runner, controller, journal = _runner()

    controller.arrive()
    runner._on_timeout()
    controller.answer(1, ok=True)

    assert runner.exit_code == EXIT_FAILED
    assert [entry.message_code for entry in journal.entries()] == [CODE_TIMEOUT]


def test_a_connection_that_failed_is_reported_before_anything_is_sent() -> None:
    runner, controller, journal = _runner()

    controller.error_occurred.emit("device not found")

    assert runner.exit_code == EXIT_FAILED
    assert controller.submitted == []
    entry = journal.entries()[-1]
    assert (entry.kind, entry.message_code) == (KIND_ERROR, CODE_CONNECT_FAILED)


def test_a_ble_complaint_alongside_the_result_does_not_overrule_it() -> None:
    """Once the command is out, its own tracked result is the verdict."""
    runner, controller, journal = _runner()

    controller.arrive()
    controller.error_occurred.emit("write retried")
    assert runner.exit_code == EXIT_FAILED, "the run ended on a complaint about a live write"

    controller.answer(1, ok=True)

    assert runner.exit_code == EXIT_OK
    assert [entry.kind for entry in journal.entries()] == [KIND_SUCCESS]


# ── the command line Windows actually runs ────────────────────────────
def test_both_switches_reach_the_same_shared_decision(monkeypatch) -> None:
    """``--run-rule <id>`` is a wake-up hint, not an instruction: the id is recorded
    and the process still decides for itself which rule may run."""
    import main

    calls: list[str] = []
    monkeypatch.setattr(main, "install_crash_logging", lambda: None)
    monkeypatch.setattr(
        headless_module,
        "run_automations",
        lambda *, woken_by="": calls.append(woken_by) or EXIT_OK,
    )

    monkeypatch.setattr(sys, "argv", ["LumaBLE.exe", "--run-rule", RULE_ID])
    assert main.main() == EXIT_OK
    monkeypatch.setattr(sys, "argv", ["LumaBLE.exe", "--run-automations"])
    assert main.main() == EXIT_OK

    assert calls == [RULE_ID, ""]
