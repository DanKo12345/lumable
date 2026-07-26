"""The dispatcher: one decision at a time, executed for real, then acked.

A fake executor stands in for BLE so the whole decide/execute/confirm cycle is
exercised without hardware or Qt.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.automation.dispatcher import (
    CODE_CANCELLED,
    CODE_PARTIAL,
    CODE_SCENE_APPLIED,
    CODE_SHUTDOWN,
    CODE_TIMEOUT,
    AutomationDispatcher,
    ExecutionResult,
)
from app.automation.journal import (
    KIND_CANCELLED,
    KIND_ERROR,
    KIND_SKIPPED,
    KIND_SUCCESS,
    AutomationJournal,
)
from app.automation.resolver import AutomationEngine, Event, Snapshot
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_STRIP_CONNECTED,
    validate_rule,
)

T0 = datetime(2026, 7, 27, 20, 0)


class FakeHandle:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeExecutor:
    """Records what it was asked to do and answers when the test says so."""

    def __init__(self, *, auto: bool | None = True, code: str = "") -> None:
        self.calls: list = []
        self.pending: list = []
        self.handles: list[FakeHandle] = []
        self._auto = auto
        self._code = code

    def execute(self, decision, done) -> FakeHandle:
        self.calls.append(decision)
        handle = FakeHandle()
        self.handles.append(handle)
        if self._auto is None:
            self.pending.append(done)  # never answers on its own
            return handle
        done(ExecutionResult(ok=self._auto, code=self._code))
        return handle

    def answer(self, ok: bool, code: str = "", *, index: int | None = None, **fields) -> None:
        callbacks = self.pending if index is None else [self.pending[index]]
        for done in callbacks:
            done(ExecutionResult(ok=ok, code=code, **fields))
        if index is None:
            self.pending = []


def _app_rule(rule_id: str, app: str, scene: str, **extra):
    rule = validate_rule(
        {
            "id": rule_id,
            "name": rule_id,
            "trigger": {"kind": TRIGGER_APP_FOREGROUND, "app": app},
            "action": {"type": ACTION_APPLY_SCENE, "scene_id": scene},
            **extra,
        }
    )
    assert rule is not None
    return rule


def _build(tmp_path, executor, **kwargs):
    journal = AutomationJournal(tmp_path / "automation_journal.json", flush_interval=0.0)
    return AutomationDispatcher(AutomationEngine(), executor, journal, **kwargs), journal


def _snap(now, **kwargs) -> Snapshot:
    return Snapshot(now=now, **kwargs)


def test_a_successful_action_is_acked_once_and_logged_on_its_own(tmp_path) -> None:
    executor = FakeExecutor(auto=True)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.tick(rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"), monotonic_now=2.0)

    assert len(executor.calls) == 1, "a settled winner must not be re-applied"
    successes = [entry for entry in journal.entries() if entry.kind == KIND_SUCCESS]
    assert len(successes) == 1
    assert successes[0].message_code == CODE_SCENE_APPLIED
    assert successes[0].context == {"scene_id": "scene-game"}


def test_a_failing_executor_is_logged_as_an_error_and_retried(tmp_path) -> None:
    executor = FakeExecutor(auto=False)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.tick(rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"), monotonic_now=2.0)

    assert len(executor.calls) == 2, "a failed apply must be offered again"
    errors = [entry for entry in journal.entries() if entry.kind == KIND_ERROR]
    assert len(errors) == 2, "errors are never collapsed"


def test_a_lost_callback_times_out_instead_of_freezing_automations(tmp_path) -> None:
    """A callback that never arrives would otherwise hold the single pending
    slot forever, and no rule would ever run again."""
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=10)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    assert dispatcher.in_flight() is not None

    dispatcher.tick(rules, _snap(T0 + timedelta(seconds=30), foreground_app="game.exe"), monotonic_now=30.0)

    codes = [entry.message_code for entry in journal.entries() if entry.kind == KIND_ERROR]
    assert CODE_TIMEOUT in codes
    assert len(executor.calls) == 2, "the rule must be offered again after a timeout"


def test_a_callback_arriving_after_its_timeout_is_ignored(tmp_path) -> None:
    """The timed-out attempt must not report success later and be recorded as
    applied — the retry that replaced it is the one that counts."""
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=10)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.tick(rules, _snap(T0 + timedelta(seconds=30), foreground_app="game.exe"), monotonic_now=30.0)
    before = len(journal.entries())

    executor.answer(True, index=0)  # only the abandoned first attempt answers

    assert len(journal.entries()) == before, "a stale callback wrote to the journal"
    assert dispatcher.in_flight() is not None, "the retry was cancelled by a stale callback"


def test_an_event_during_execution_is_handled_after_it_completes(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    dispatcher, _journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [
        _app_rule("game", "game.exe", "scene-game"),
        validate_rule(
            {
                "id": "on_connect",
                "name": "on_connect",
                "trigger": {"kind": TRIGGER_STRIP_CONNECTED},
                "action": {"type": ACTION_APPLY_SCENE, "scene_id": "scene-hello"},
                "priority": 5,
            }
        ),
    ]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    connected_at = T0 + timedelta(seconds=1)
    dispatcher.tick(
        rules,
        _snap(connected_at, foreground_app="game.exe"),
        events=(Event(kind=TRIGGER_STRIP_CONNECTED, occurred_at=connected_at),),
    )
    executor.answer(True)
    dispatcher.tick(rules, _snap(T0 + timedelta(seconds=5), foreground_app="game.exe"), monotonic_now=5.0)

    assert [call.rule_id for call in executor.calls] == ["game", "on_connect"]


def test_repeated_skips_collapse_but_a_new_reason_starts_a_row(tmp_path) -> None:
    executor = FakeExecutor(auto=True)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [_app_rule("game", "game.exe", "scene-gone")]
    known = frozenset({"scene-other"})

    for seconds in (0, 2, 4):
        dispatcher.tick(
            rules,
            _snap(T0 + timedelta(seconds=seconds), foreground_app="game.exe",
                  available_scene_ids=known),
        )
    dispatcher.tick(
        rules,
        _snap(T0 + timedelta(seconds=6), foreground_app="game.exe", connected=False),
    )

    skips = [entry for entry in journal.entries() if entry.kind == KIND_SKIPPED]
    assert len(skips) == 2, "the same skip must fold into one row"
    assert skips[0].count == 3
    assert skips[0].context["scene_id"] == "scene-gone"
    assert skips[1].count == 1


def test_shutdown_leaves_nothing_pending_and_writes_the_journal(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [_app_rule("game", "game.exe", "scene-game")]
    path = tmp_path / "automation_journal.json"

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.shutdown(T0 + timedelta(seconds=1))

    assert dispatcher.in_flight() is None
    assert path.exists()
    codes = [entry.message_code for entry in journal.entries() if entry.kind == KIND_ERROR]
    assert CODE_SHUTDOWN in codes

    reloaded = AutomationJournal(path)
    reloaded.load()
    assert [entry.id for entry in reloaded.entries()] == [entry.id for entry in journal.entries()]


def test_the_paused_skip_carries_the_moment_it_lifts(tmp_path) -> None:
    executor = FakeExecutor(auto=True)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [_app_rule("game", "game.exe", "scene-game")]
    engine = dispatcher._engine
    engine.pause(T0, seconds=600)

    dispatcher.tick(rules, _snap(T0 + timedelta(seconds=1), foreground_app="game.exe"))

    skips = [entry for entry in journal.entries() if entry.kind == KIND_SKIPPED]
    assert skips and skips[0].context["paused_until"].startswith("2026-07-27T20:10")


def test_an_outranked_skip_names_the_rule_that_won(tmp_path) -> None:
    executor = FakeExecutor(auto=True)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [
        _app_rule("game", "game.exe", "scene-game", priority=5),
        validate_rule(
            {
                "id": "fallback",
                "name": "fallback",
                "trigger": {"kind": TRIGGER_ALWAYS},
                "action": {"type": ACTION_APPLY_SCENE, "scene_id": "scene-default"},
                "priority": -10,
            }
        ),
    ]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)

    skips = [entry for entry in journal.entries() if entry.kind == KIND_SKIPPED]
    assert skips and skips[0].context == {"winner_rule_id": "game"}


def test_the_timeout_is_measured_on_the_monotonic_clock(tmp_path) -> None:
    """Windows moving the wall clock must not hang the pending slot or fire an
    instant timeout on a healthy command."""
    executor = FakeExecutor(auto=None)
    dispatcher, _journal = _build(tmp_path, executor, timeout_seconds=10)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=100.0)

    # Wall clock jumps an hour forward; only 2s of real time have passed.
    dispatcher.tick(
        rules, _snap(T0 + timedelta(hours=1), foreground_app="game.exe"), monotonic_now=102.0
    )
    assert dispatcher.in_flight() is not None, "a wall-clock jump timed out a live command"

    # And jumping back must not postpone a genuine timeout.
    dispatcher.tick(
        rules, _snap(T0 - timedelta(hours=1), foreground_app="game.exe"), monotonic_now=200.0
    )
    assert dispatcher.in_flight() is not None  # the retry is now in flight
    assert len(executor.calls) == 2


def test_a_timeout_calls_the_old_attempt_off_before_retrying(tmp_path) -> None:
    """Otherwise the replacement writes to the strip while the abandoned one
    still is — two real commands racing for the same light."""
    executor = FakeExecutor(auto=None)
    dispatcher, _journal = _build(tmp_path, executor, timeout_seconds=10)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.tick(
        rules, _snap(T0 + timedelta(seconds=30), foreground_app="game.exe"), monotonic_now=30.0
    )

    assert executor.handles[0].cancelled is True
    assert executor.handles[1].cancelled is False


def test_pausing_calls_off_the_action_already_on_its_way(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.pause(T0 + timedelta(seconds=1), seconds=600)

    assert executor.handles[0].cancelled is True
    assert dispatcher.in_flight() is None
    executor.answer(True)  # the cancelled command answers anyway
    assert not [entry for entry in journal.entries() if entry.kind == KIND_SUCCESS]

    dispatcher.tick(
        rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"), monotonic_now=2.0
    )
    assert len(executor.calls) == 1, "a paused dispatcher started a new action"


def test_shutdown_calls_the_running_action_off(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    dispatcher, _journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.shutdown(T0 + timedelta(seconds=1))

    assert executor.handles[0].cancelled is True


def test_a_success_is_logged_when_it_completed_not_when_it_started(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    completed_at = T0 + timedelta(seconds=15)
    journal = AutomationJournal(tmp_path / "j.json", flush_interval=0.0)
    dispatcher = AutomationDispatcher(
        AutomationEngine(), executor, journal, timeout_seconds=600, clock=lambda: completed_at
    )
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    executor.answer(True)

    success = next(entry for entry in journal.entries() if entry.kind == KIND_SUCCESS)
    assert success.last_seen == completed_at
    assert success.decided_at == T0, "the decision time must stay the decision time"


def test_a_cooldown_skip_says_when_the_rule_may_run_again(tmp_path) -> None:
    executor = FakeExecutor(auto=True)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [
        validate_rule(
            {
                "id": "welcome",
                "name": "welcome",
                "trigger": {"kind": TRIGGER_STRIP_CONNECTED},
                "action": {"type": ACTION_APPLY_SCENE, "scene_id": "scene-hello"},
                "cooldown_seconds": 300,
            }
        )
    ]

    dispatcher.tick(rules, _snap(T0), events=(TRIGGER_STRIP_CONNECTED,), monotonic_now=0.0)
    dispatcher.tick(
        rules, _snap(T0 + timedelta(seconds=10)), events=(TRIGGER_STRIP_CONNECTED,), monotonic_now=10.0
    )

    skip = next(entry for entry in journal.entries() if entry.kind == KIND_SKIPPED)
    assert skip.reason == "cooldown"
    assert skip.context["retry_at"].startswith("2026-07-27T20:05")


def test_a_disconnected_skip_names_the_strip_it_meant(tmp_path) -> None:
    executor = FakeExecutor(auto=True)
    dispatcher, journal = _build(tmp_path, executor)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(
        rules, _snap(T0, foreground_app="game.exe", connected=False), monotonic_now=0.0
    )

    skip = next(entry for entry in journal.entries() if entry.kind == KIND_SKIPPED)
    assert skip.context == {"target": "primary"}


def test_a_half_applied_scene_is_a_failure_and_gets_another_go(tmp_path) -> None:
    """The rule did not do what it promised. Counting it as done would settle
    the winner and start the cooldown on a scene that only half landed."""
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    executor.answer(False, completed_steps=2, total_steps=5, partial=True)

    entry = next(e for e in journal.entries() if e.kind == KIND_ERROR)
    assert entry.message_code == CODE_PARTIAL
    assert entry.context["completed_steps"] == 2
    assert entry.context["total_steps"] == 5

    dispatcher.tick(
        rules, _snap(T0 + timedelta(seconds=2), foreground_app="game.exe"), monotonic_now=2.0
    )
    assert len(executor.calls) == 2, "a partial apply was remembered as done"


def test_a_result_cannot_claim_to_be_both_partial_and_successful() -> None:
    """Caught in the type rather than by the reader: the one place this went
    wrong, the engine started a cooldown on a scene that never fully applied."""
    import pytest

    with pytest.raises(ValueError):
        ExecutionResult(ok=True, partial=True, completed_steps=2, total_steps=5)
    with pytest.raises(ValueError):
        ExecutionResult(ok=False, partial=True, partial_possible=True, completed_steps=2, total_steps=5)
    with pytest.raises(ValueError):
        ExecutionResult(ok=False, partial=True, completed_steps=5, total_steps=5)
    with pytest.raises(ValueError):
        ExecutionResult(ok=True, completed_steps=2, total_steps=5)
    with pytest.raises(ValueError):
        ExecutionResult(ok=True, completed_steps=-1)


def test_a_fully_applied_scene_is_a_plain_success(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    executor.answer(True, completed_steps=5, total_steps=5)

    entry = next(e for e in journal.entries() if e.kind == KIND_SUCCESS)
    assert entry.message_code == CODE_SCENE_APPLIED


def test_a_cancelled_action_is_not_filed_as_a_fault(tmp_path) -> None:
    """Nothing went wrong; the user took over. Painting it red would teach them
    to ignore the errors that matter."""
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=600)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.pause(T0 + timedelta(seconds=1), seconds=600)

    assert not [e for e in journal.entries() if e.kind == KIND_ERROR]
    entry = next(e for e in journal.entries() if e.kind == KIND_CANCELLED)
    assert entry.message_code == CODE_CANCELLED
    # A write already on its way cannot be recalled, so the journal says
    # "possibly", never "nothing happened".
    assert entry.context["partial_possible"] is True


def test_a_timeout_admits_it_does_not_know_what_landed(tmp_path) -> None:
    executor = FakeExecutor(auto=None)
    dispatcher, journal = _build(tmp_path, executor, timeout_seconds=10)
    rules = [_app_rule("game", "game.exe", "scene-game")]

    dispatcher.tick(rules, _snap(T0, foreground_app="game.exe"), monotonic_now=0.0)
    dispatcher.tick(
        rules, _snap(T0 + timedelta(seconds=30), foreground_app="game.exe"), monotonic_now=30.0
    )

    entry = next(e for e in journal.entries() if e.message_code == CODE_TIMEOUT)
    assert entry.context["partial_possible"] is True
