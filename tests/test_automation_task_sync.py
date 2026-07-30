"""Reconciling Windows tasks from the running app, off the UI thread.

The compiler itself is covered in test_automation_windows_tasks; what matters here
is that the app actually calls it at startup — otherwise orphan cleanup exists only
in tests — and that the rules are read on the calling thread rather than from the
window's settings dict while the user is editing it.
"""

from __future__ import annotations

from time import monotonic, sleep
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.automation import task_sync as task_sync_module
from app.automation.journal import KIND_ERROR, AutomationJournal
from app.automation.task_sync import CODE_TASK_SYNC_FAILED, AutomationTaskSync
from app.automation.windows_tasks import TaskSyncResult
from app.main_window import MainWindow
from app.storage import automation_journal_path

RULE = {
    "id": "evening-off",
    "name": "Evening off",
    "trigger": {"kind": "time", "time_at": "23:00", "days": [0, 1, 2, 3, 4, 5, 6]},
    "action": {"type": "set_power", "power": False, "target": "primary"},
    "execution": "background",
    "enabled": True,
}


def _settings(**automations: Any) -> dict[str, Any]:
    block = {"enabled": True, "rules": [RULE]}
    block.update(automations)
    return {"automations": block}


def _synced(
    monkeypatch, settings: dict[str, Any], result: TaskSyncResult | None = None
) -> tuple[list, AutomationTaskSync]:
    """Run one reconciliation with the compiler stubbed out, and wait for it.

    Returns the rule lists the compiler was handed, and the controller itself.
    """
    seen: list = []

    def fake_sync(rules, **kwargs):
        seen.append(list(rules))
        return result or TaskSyncResult()

    monkeypatch.setattr(task_sync_module, "sync_tasks", fake_sync)
    controller = AutomationTaskSync(lambda: settings)
    finished: list = []
    controller.finished.connect(finished.append)

    controller.sync()
    _wait_for(finished)
    return seen, controller


def _wait_for(reported: list, timeout: float = 5.0) -> None:
    """Spin the Qt loop while waiting.

    ``finished`` is emitted from the worker thread, so Qt delivers it as a queued
    connection: nothing arrives unless an event loop is turning. The app always has
    one; a test has to do it by hand.
    """
    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + timeout
    while not reported and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    app.processEvents()
    assert reported, "the reconciliation never reported back"


def test_the_rules_reach_the_compiler(monkeypatch) -> None:
    seen, _controller = _synced(monkeypatch, _settings())

    assert [rule.id for rule in seen[0]] == ["evening-off"]


def test_automations_switched_off_take_every_task_with_them(monkeypatch) -> None:
    """Not "leave the tasks alone": an empty rule list is what makes reconciliation
    remove them, which is the whole point of switching automations off."""
    seen, _controller = _synced(monkeypatch, _settings(enabled=False))

    assert seen == [[]]


def test_two_reconciliations_never_overlap(monkeypatch) -> None:
    """A request made during a run is answered *after* it, not alongside it: two at
    once would each decide against a task list the other was changing."""
    order: list[str] = []

    def slow_sync(rules, **kwargs):
        order.append("enter")
        sleep(0.1)
        order.append("exit")
        return TaskSyncResult()

    monkeypatch.setattr(task_sync_module, "sync_tasks", slow_sync)
    controller = AutomationTaskSync(_settings)
    finished: list = []
    controller.finished.connect(finished.append)

    controller.sync()
    controller.sync()
    _wait_for(finished)
    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + 5.0
    while len(order) < 4 and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)

    assert order == ["enter", "exit", "enter", "exit"], "the two runs overlapped"


def test_settings_that_cannot_be_read_stop_the_run_instead_of_emptying_it(monkeypatch) -> None:
    """An empty rule list is an instruction — take every task off the machine — so a
    failed read must never turn into one. Nothing is created, nothing is deleted,
    and Task Scheduler is not contacted at all."""

    def broken() -> dict[str, Any]:
        raise RuntimeError("settings are gone")

    calls: list = []
    monkeypatch.setattr(
        task_sync_module, "sync_tasks", lambda rules, **kwargs: calls.append(list(rules))
    )
    controller = AutomationTaskSync(broken)
    finished: list = []
    controller.finished.connect(finished.append)

    controller.sync()
    _wait_for(finished)

    assert calls == [], "a failed settings read reached the task compiler"
    assert finished[0].ok is False
    assert controller.last_result is finished[0]


def test_a_refusal_is_written_where_the_user_can_find_it(monkeypatch) -> None:
    """Windows declining to write a task must not be silent: a background schedule
    that never got set up looks exactly like one that works."""
    refused = TaskSyncResult(errors=(("evening-off", "ERROR: Access is denied."),))
    _seen, controller = _synced(monkeypatch, _settings(), result=refused)
    assert controller.last_result is refused

    journal = AutomationJournal(automation_journal_path())
    journal.load()
    entry = journal.entries()[-1]
    assert (entry.kind, entry.rule_id) == (KIND_ERROR, "evening-off")
    assert entry.message_code == CODE_TASK_SYNC_FAILED
    # Stable code for the app, Windows' own wording alongside it for the user.
    assert entry.context["detail"] == "ERROR: Access is denied."


def test_the_last_result_stays_readable_for_a_screen_opened_later(monkeypatch) -> None:
    """The automations screen does not exist yet, and when it does it must be able
    to show the state of things without provoking another reconciliation."""
    done = TaskSyncResult(created=("evening-off",))
    _seen, controller = _synced(monkeypatch, _settings(), result=done)

    assert controller.last_result is done


def test_a_successful_run_writes_nothing_to_the_journal(monkeypatch) -> None:
    _synced(monkeypatch, _settings(), result=TaskSyncResult(created=("evening-off",)))


    journal = AutomationJournal(automation_journal_path())
    journal.load()
    assert journal.entries() == [], "a quiet success left noise in the journal"


def test_the_app_reconciles_tasks_at_startup(monkeypatch) -> None:
    """Without this call site the orphan cleanup only ever runs in tests. The window
    asks the controller, which owns the reconciliation."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_start_deferred", lambda self, delay_ms, callback: None)
    synced: list = []
    window = MainWindow()
    try:
        monkeypatch.setattr(window._automations, "start", lambda: None)
        monkeypatch.setattr(window._automations, "sync_tasks", lambda: synced.append(True))

        window._start_automations()
        for _ in range(20):
            app.processEvents()
            sleep(0.02)
            if synced:
                break

        assert synced == [True], "startup never reconciles the tasks"
    finally:
        window._ble.shutdown()
        window.close()
        # Closing defers the real close to a timer, and that close posts app.quit().
        # Left pending, both would fire inside whichever test next runs an event loop
        # — and the headless runs do exactly that, so their loop would end before
        # anything happened in it. Drained here instead, where quit() has no loop to
        # stop.
        for _ in range(5):
            app.processEvents()


def test_a_change_during_a_run_gets_its_own_reconciliation(monkeypatch) -> None:
    """Create a rule, and while that reconciliation is out at schtasks, change its
    time. Dropping the second request is how Windows ends up holding yesterday's
    task until the next launch of the app."""
    import threading

    settings = _settings()
    release = threading.Event()
    seen: list[list[str]] = []

    def blocking_sync(rules, **kwargs):
        seen.append([f"{rule.id}@{rule.trigger.time_at}" for rule in rules])
        if len(seen) == 1:
            release.wait(timeout=5.0)
        return TaskSyncResult()

    monkeypatch.setattr(task_sync_module, "sync_tasks", blocking_sync)
    controller = AutomationTaskSync(lambda: settings)
    finished: list = []
    controller.finished.connect(finished.append)

    controller.sync()
    while not seen:  # the first run is inside sync_tasks, holding the door
        sleep(0.01)

    # The user changes the rule while that is still out.
    settings["automations"]["rules"] = [{**RULE, "trigger": {**RULE["trigger"], "time_at": "07:30"}}]
    controller.sync()
    release.set()

    deadline = monotonic() + 5.0
    app = QApplication.instance() or QApplication([])
    while len(seen) < 2 and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)

    assert len(seen) == 2, "the change made during a run never reached Windows"
    assert seen[0] == ["evening-off@23:00"]
    assert seen[1] == ["evening-off@07:30"], "the second run used a stale snapshot"


def test_nothing_is_repeated_when_no_one_asked_twice(monkeypatch) -> None:
    seen, _controller = _synced(monkeypatch, _settings())
    app = QApplication.instance() or QApplication([])
    for _ in range(5):
        app.processEvents()
        sleep(0.02)

    assert len(seen) == 1, "a reconciliation repeated itself for no reason"
