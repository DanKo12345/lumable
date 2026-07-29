"""Drives the engine: one decision at a time, executed for real, then acked.

The dispatcher is the only place that knows an action can take time and fail. It
holds no Qt and no BLE — the executor behind :class:`ActionExecutor` does — so
the whole decide/execute/confirm cycle is testable with a fake.

The contract with the executor is deliberately blunt: it is handed a decision and
a callback, and must call that callback exactly once. If it never does, the
timeout below reports a failure anyway, because a lost callback that quietly
freezes every automation is worse than a wrong entry in the journal.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.automation.journal import AutomationJournal
from app.automation.resolver import (
    SKIP_COOLDOWN,
    SKIP_DISCONNECTED,
    SKIP_MISSING_SCENE,
    SKIP_OUTRANKED,
    SKIP_PAUSED,
    AutomationEngine,
    Decision,
    Event,
    Snapshot,
)
from app.automation.rules import ACTION_APPLY_SCENE, TARGET_PRIMARY, Rule

DEFAULT_TIMEOUT_SECONDS = 20.0

# Journal message codes. Stable identifiers, never localised text.
CODE_SCENE_APPLIED = "scene_applied"
CODE_POWER_SET = "power_set"
CODE_EXECUTION_FAILED = "execution_failed"
CODE_TIMEOUT = "execution_timeout"  # the executor never answered
CODE_SHUTDOWN = "execution_abandoned"  # the app is closing
CODE_CANCELLED = "execution_cancelled"  # the user took over; not a fault
CODE_PARTIAL = "execution_partial"  # some steps of a scene confirmed, not all


@dataclass(frozen=True)
class ExecutionResult:
    """How an action ended, in the executor's own words.

    Richer than a bare ``ok`` because a scene is several writes: it can end up
    half applied, and the journal has to be able to say so without pretending to
    know more than it does.
    """

    ok: bool
    code: str = ""
    completed_steps: int = 0
    total_steps: int = 0
    # True only when at least one step is *confirmed* done and not all are.
    # A partial result is never ``ok``: the rule has not done what it promised,
    # so the engine must be free to try again rather than start a cooldown on a
    # scene that only half landed.
    partial: bool = False
    # True when the executor cannot tell — a write may have reached the
    # controller before the cancellation did. Never claimed as fact.
    partial_possible: bool = False
    message: str = ""

    def __post_init__(self) -> None:
        # These are contract violations by the executor, not bad user data, so
        # they fail loudly here instead of quietly producing a wrong journal.
        if self.completed_steps < 0 or self.total_steps < 0:
            raise ValueError("step counts cannot be negative")
        if self.total_steps and self.completed_steps > self.total_steps:
            raise ValueError("completed_steps cannot exceed total_steps")
        if self.partial and self.partial_possible:
            raise ValueError("partial is a confirmed fact; partial_possible is a maybe")
        if self.partial and not 0 < self.completed_steps < self.total_steps:
            raise ValueError("partial means some steps confirmed and some not")
        if self.ok and self.partial:
            raise ValueError("a partial result is not a success")
        if self.ok and self.total_steps and self.completed_steps != self.total_steps:
            raise ValueError("ok means every step completed")


# ── context for the journal ───────────────────────────────────────────────
# Module-level, not private to the dispatcher: the headless ``--run-rule`` path
# writes to the same journal, and two spellings of "how a run is recorded" would
# drift apart entry by entry.


def success_code_for(decision: Decision) -> str:
    return CODE_SCENE_APPLIED if decision.action.type == ACTION_APPLY_SCENE else CODE_POWER_SET


def failure_code_for(result: ExecutionResult) -> str:
    """What to file a failed run under when the executor named no code itself."""
    return result.code or (CODE_PARTIAL if result.partial else CODE_EXECUTION_FAILED)


def steps_context(result: ExecutionResult) -> dict:
    if result.total_steps <= 0 and not result.partial_possible:
        return {}
    context: dict = {}
    if result.total_steps > 0:
        context["completed_steps"] = result.completed_steps
        context["total_steps"] = result.total_steps
    if result.partial_possible:
        context["partial_possible"] = True
    return context


def decision_context(decision: Decision) -> dict:
    if decision.action.type == ACTION_APPLY_SCENE:
        return {"scene_id": decision.action.scene_id}
    return {"target": decision.action.target, "power": decision.action.power}


class ExecutionHandle(Protocol):
    def cancel(self) -> None:
        """Best-effort cancellation, without rollback. Safe to call late.

        What it guarantees: a result arriving afterwards is not counted, and no
        further step of a multi-step action is started.

        What it cannot guarantee: that nothing reached the strip. A write
        already handed to the BLE stack will finish, so a cancelled ``set_power``
        may well have taken effect — hence ``partial_possible`` rather than a
        claim either way. It does not undo anything.
        """


class ActionExecutor(Protocol):
    def execute(
        self, decision: Decision, done: Callable[[ExecutionResult], None]
    ) -> ExecutionHandle | None:
        """Carry out the decision, then call ``done(result)`` exactly once.

        The executor is responsible for ordering: a replacement command must
        queue *behind* an abandoned one on the same connection, because
        cancelling cannot recall a write that is already on its way.
        """


@dataclass
class _InFlight:
    decision: Decision
    started_monotonic: float
    handle: ExecutionHandle | None


class AutomationDispatcher:
    def __init__(
        self,
        engine: AutomationEngine,
        executor: ActionExecutor,
        journal: AutomationJournal,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._executor = executor
        self._journal = journal
        self._timeout_seconds = float(timeout_seconds)
        # Read when an action *completes*, not when it started: a success that
        # took fifteen seconds must not be logged as having happened fifteen
        # seconds ago.
        self._clock = clock or datetime.now
        self._in_flight: _InFlight | None = None

    # ── the loop ──────────────────────────────────────────────────────
    def tick(
        self,
        rules: list[Rule],
        snapshot: Snapshot,
        events: Sequence[Event | str] = (),
        *,
        monotonic_now: float = 0.0,
    ) -> None:
        self._expire_in_flight(monotonic_now, snapshot.now)
        outcome = self._engine.evaluate(rules, snapshot, events)
        for skip in outcome.skips:
            self._journal.record_skip(
                skip.rule_id,
                skip.reason,
                now=snapshot.now,
                context=self._skip_context(skip.reason, skip.rule_id, outcome, rules),
            )
        if outcome.decision is not None:
            self._start(outcome.decision, monotonic_now)
        self._journal.flush(monotonic_now)

    def _start(self, decision: Decision, monotonic_now: float) -> None:
        token = decision.token

        def done(result: ExecutionResult) -> None:
            # Bound to this decision's token: a callback that arrives after the
            # decision has been abandoned must not answer for a later one.
            self._finish(token, result)

        # Recorded before executing: a synchronous executor calls back inside
        # execute(), and _finish must already know what it is answering for.
        self._in_flight = _InFlight(
            decision=decision, started_monotonic=monotonic_now, handle=None
        )
        handle = self._executor.execute(decision, done)
        if self._in_flight is not None and self._in_flight.decision.token == token:
            self._in_flight.handle = handle

    def _finish(self, token: int, result: ExecutionResult) -> None:
        in_flight = self._in_flight
        if in_flight is None or in_flight.decision.token != token:
            return  # stale: timed out, superseded by shutdown, or already answered
        decision = in_flight.decision
        self._in_flight = None
        now = self._clock()
        if not self._engine.ack(decision, success=result.ok):
            return  # the engine had already moved on (a pause, for instance)
        context = decision_context(decision) | steps_context(result)
        if result.ok:
            self._journal.record_success(
                decision.rule_id,
                message_code=result.code or success_code_for(decision),
                now=now,
                occurred_at=decision.occurred_at,
                decided_at=decision.decided_at,
                context=context,
            )
        else:
            # A half-applied scene is filed as a failure, not a lesser success:
            # the rule did not do what it promised, and the engine has just been
            # told so, which is what lets it try again.
            self._journal.record_error(
                decision.rule_id,
                message_code=failure_code_for(result),
                now=now,
                occurred_at=decision.occurred_at,
                decided_at=decision.decided_at,
                context=context,
            )

    def _expire_in_flight(self, monotonic_now: float, now: datetime) -> None:
        """Give up on an executor that never answered.

        Measured on the monotonic clock: with wall time, Windows moving the
        clock back would hang the single pending slot indefinitely, and moving
        it forward would time out a healthy command instantly.
        """
        in_flight = self._in_flight
        if in_flight is None:
            return
        if monotonic_now - in_flight.started_monotonic < self._timeout_seconds:
            return
        self._abandon(in_flight, CODE_TIMEOUT, now)

    def _abandon(self, in_flight: _InFlight, code: str, now: datetime) -> None:
        """Call the work off, release the engine, and say so in the journal.

        ``cancel()`` only *asks* the executor to stop and stops its result from
        counting; keeping a replacement command behind the abandoned one is the
        executor's job, since a write already in flight cannot be recalled.
        """
        self._in_flight = None
        if in_flight.handle is not None:
            in_flight.handle.cancel()
        self._engine.ack(in_flight.decision, success=False)
        self._journal.record_error(
            in_flight.decision.rule_id,
            message_code=code,
            now=now,
            occurred_at=in_flight.decision.occurred_at,
            decided_at=in_flight.decision.decided_at,
            # Whether anything reached the strip is genuinely unknown here, so
            # the journal says "possibly" rather than picking a story.
            context=decision_context(in_flight.decision) | {"partial_possible": True},
        )

    # ── lifecycle ─────────────────────────────────────────────────────
    def pause(self, now: datetime, *, seconds: int = 3600) -> None:
        """Hand control back to the user, stopping anything already on its way.

        Goes through the dispatcher rather than the engine directly so the order
        holds: cancel the running action, drop it, then start the pause. Pausing
        first would leave a live executor free to land on top of the manual
        change the user just made.
        """
        in_flight, self._in_flight = self._in_flight, None
        if in_flight is not None:
            if in_flight.handle is not None:
                in_flight.handle.cancel()
            # Recorded, but not as a fault: nothing went wrong, the user simply
            # took over. Marked as possibly partial because a write already on
            # its way to the controller cannot be recalled.
            self._journal.record_cancelled(
                in_flight.decision.rule_id,
                message_code=CODE_CANCELLED,
                now=now,
                occurred_at=in_flight.decision.occurred_at,
                decided_at=in_flight.decision.decided_at,
                context=decision_context(in_flight.decision) | {"partial_possible": True},
            )
        self._engine.pause(now, seconds)

    def resume(self) -> None:
        self._engine.resume()

    def rules_changed(self) -> None:
        """The rule set has been edited. Drop what was decided about the old one.

        Anything in flight was decided for rules that no longer exist in that form,
        so it is called off rather than allowed to land and be recorded as that
        rule's doing. Not journalled: the user edited their automations, which is
        not an event that happened to their light.
        """
        in_flight, self._in_flight = self._in_flight, None
        if in_flight is not None:
            if in_flight.handle is not None:
                in_flight.handle.cancel()
            self._engine.ack(in_flight.decision, success=False)
        self._engine.rules_changed()

    def shutdown(self, now: datetime, monotonic_now: float = 0.0) -> None:
        """Abandon anything in flight and get the journal onto disk."""
        in_flight, self._in_flight = self._in_flight, None
        if in_flight is not None:
            self._abandon(in_flight, CODE_SHUTDOWN, now)
        self._journal.flush(monotonic_now, force=True)

    def in_flight(self) -> Decision | None:
        return self._in_flight.decision if self._in_flight is not None else None

    # ── context for the journal ───────────────────────────────────────
    # Only the skip reasons are the dispatcher's own: they read the engine. How a
    # *run* is recorded lives at module level, shared with the headless path.
    def _skip_context(self, reason: str, rule_id: str, outcome, rules: list[Rule]) -> dict:
        """The detail that makes a skip actionable rather than just a label."""
        if reason == SKIP_OUTRANKED and outcome.decision is not None:
            return {"winner_rule_id": outcome.decision.rule_id}
        if reason == SKIP_MISSING_SCENE:
            rule = next((item for item in rules if item.id == rule_id), None)
            return {"scene_id": rule.action.scene_id} if rule is not None else {}
        if reason == SKIP_PAUSED:
            paused_until = self._engine.paused_until()
            return {"paused_until": paused_until.isoformat() if paused_until else ""}
        if reason == SKIP_COOLDOWN:
            rule = next((item for item in rules if item.id == rule_id), None)
            if rule is None:
                return {}
            retry_at = self._engine.retry_at(rule)
            # The moment it can run again is the actionable part; the configured
            # length alone leaves the user counting seconds themselves.
            return {
                "cooldown_seconds": rule.cooldown_seconds,
                "retry_at": retry_at.isoformat() if retry_at else "",
            }
        if reason == SKIP_DISCONNECTED:
            rule = next((item for item in rules if item.id == rule_id), None)
            target = rule.action.target if rule is not None and rule.action.target else TARGET_PRIMARY
            return {"target": target}
        return {}
