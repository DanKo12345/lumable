"""Decides which rule wins, and says why the others did not.

The engine is a pure state machine: it is handed a :class:`Snapshot` of the
world and returns at most one :class:`Decision` per tick plus a :class:`Skip`
for every rule that wanted to act and could not. The skips are what the journal
shows the user, so "nothing happened" is never unexplained.

Two shapes of rule are resolved differently, on purpose:

* **Stateful** triggers (an app is in front, no input for a while, the fallback)
  describe a situation that lasts. The engine picks one winner among them and
  only acts when that winner *changes* — so switching from one matched app
  straight to another applies a single scene instead of passing through a
  fallback in between.
* **Edge** triggers (a time of day, the app starting, the strip connecting)
  happen once and are dispatched as they occur.

Conflicts are settled by priority, then by which candidate became current most
recently. Rule order in the list is deliberately *not* a tiebreaker: dragging a
row to tidy the list must never change behaviour.

Deciding and acting are two phases. ``evaluate()`` mutates nothing that records
success; the caller executes the decision and calls :meth:`AutomationEngine.ack`
with the result. A rule whose BLE write failed therefore stays un-applied and is
retried, instead of being remembered as done.

The engine reports the truth on every tick, including a rule that is still
blocked for the same reason as a second ago. Collapsing those repeats is the
journal's job — the engine has no business deciding what is worth telling the
user twice.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import count

from app.automation.rules import (
    ACTION_APPLY_SCENE,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_NO_INPUT,
    TRIGGER_TIME,
    Action,
    Rule,
)

DEFAULT_PAUSE_SECONDS = 60 * 60  # one hour, then automations resume by themselves

# Held events are a stopgap for a decision in flight, not a backlog: the queue
# keeps the last 32 events and drops the oldest beyond that.
_MAX_DEFERRED_EVENTS = 32

# Skip reasons, as stored in the journal.
SKIP_PAUSED = "paused"
SKIP_COOLDOWN = "cooldown"
SKIP_OUTRANKED = "outranked"
SKIP_MISSING_SCENE = "missing_scene"
SKIP_DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class Snapshot:
    """Everything the engine is allowed to know about the world."""

    now: datetime
    foreground_app: str = ""
    idle_seconds: float = 0.0
    connected: bool = True
    # None means "not checked" — the caller does not know the scene list yet.
    available_scene_ids: frozenset[str] | None = None


@dataclass(frozen=True)
class Decision:
    rule: Rule
    action: Action
    # When the rule became due, and when the engine got round to it. They differ
    # whenever the machine was asleep: "should have run at 23:00, ran at 08:10"
    # is the line the journal needs, and one timestamp cannot say it.
    occurred_at: datetime
    decided_at: datetime
    # Identifies this decision for exactly one ack. Without it a late callback
    # from a superseded decision could put the engine back into a state the user
    # has already moved on from.
    token: int
    # Which stateful rule was in force when this was decided. A successful edge
    # action counts as having handled that context too, so a time-based "off"
    # is not undone a second later by a fallback that had never been acked.
    stateful_context_id: str = ""

    @property
    def rule_id(self) -> str:
        return self.rule.id


@dataclass(frozen=True)
class Event:
    """A one-off thing that happened, with the moment it happened.

    Timestamped because an event can wait: if a decision is already out being
    executed, the event is held until the engine is free again, and the journal
    must still be able to say when it actually occurred rather than when it was
    finally handled.
    """

    kind: str
    occurred_at: datetime


@dataclass(frozen=True)
class Skip:
    rule_id: str
    reason: str


@dataclass(frozen=True)
class Outcome:
    decision: Decision | None = None
    skips: tuple[Skip, ...] = field(default=())


def _matches_stateful(rule: Rule, snapshot: Snapshot) -> bool:
    kind = rule.trigger.kind
    if kind == TRIGGER_ALWAYS:
        return True
    if kind == TRIGGER_APP_FOREGROUND:
        process = str(snapshot.foreground_app or "").strip().lower()
        return bool(process) and rule.trigger.app in process
    if kind == TRIGGER_NO_INPUT:
        return snapshot.idle_seconds >= rule.trigger.minutes * 60
    return False


def last_crossing(rule: Rule, previous: datetime, now: datetime) -> datetime | None:
    """When the rule's time of day last fell in (previous, now], else None.

    Returns the moment rather than a bool because a tick may span several: a
    laptop asleep from 19:00 to 23:00 crossed both an "on at 19:00" and an
    "off at 23:00" rule, and the later one has to win. With only a bool both
    would carry the tick's timestamp and the tie would fall through to the id.

    Public because the headless path has to answer the same question about the
    same window. Two implementations of "which crossings did we miss" would drift,
    and the drift would show as a schedule that behaves differently depending on
    whether the app happened to be open.
    """
    hours, _, minutes = rule.trigger.time_at.partition(":")
    hour, minute = int(hours), int(minutes)
    latest: datetime | None = None
    day = previous.date()
    while day <= now.date():
        target = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
        if previous < target <= now and target.weekday() in rule.trigger.days:
            latest = target
        day += timedelta(days=1)
    return latest


def rank(rule: Rule, occurred_at: datetime) -> tuple[int, float, str]:
    """How one candidate compares to another: priority, then freshness.

    The single spelling of the conflict rule. Rule order in the list is
    deliberately absent, and the trailing id is only there to make a complete tie
    deterministic — it is never presented to the user as a rule of the system.

    Public for the same reason as :func:`last_crossing`: the headless path settles
    the same conflict between rules that came due while the machine was asleep, and
    a second implementation would decide it differently.
    """
    return (rule.priority, occurred_at.timestamp(), rule.id)


class AutomationEngine:
    """Holds the bookkeeping a decision needs: when each rule last fired, which
    stateful rule is currently in force, and whether the user has paused us."""

    def __init__(self) -> None:
        self._last_tick: datetime | None = None
        self._last_fired: dict[str, datetime] = {}
        self._activated_at: dict[str, datetime] = {}
        self._current_stateful_id: str = ""
        self._paused_until: datetime | None = None
        self._pending: Decision | None = None
        self._tokens = count(1)
        self._deferred_events: list[Event] = []

    # ── manual pause ──────────────────────────────────────────────────
    def pause(self, now: datetime, seconds: int = DEFAULT_PAUSE_SECONDS) -> None:
        """Hold automations off after the user takes manual control.

        Time-boxed on purpose: a pause with no end is indistinguishable from
        automations being broken.

        Everything in flight is abandoned here: the decision awaiting an answer
        and any events held behind it. The user has just taken the light
        somewhere by hand, so a command already on its way must not report
        success afterwards, and an event from before that moment must not come
        back to life on resume and move the light again.
        """
        self._paused_until = now + timedelta(seconds=max(1, int(seconds)))
        self._pending = None
        self._deferred_events.clear()
        self._forget_current_state()

    def resume(self) -> None:
        self._paused_until = None
        self._forget_current_state()

    def rules_changed(self) -> None:
        """The rules are no longer the ones that were applied. Forget the winner.

        A stateful rule only acts when it *takes over*, so the engine remembers which
        one is in force. That memory is about a rule as it was: edit the scene behind
        the winning rule, or switch automations off and on again, and "already
        applied" stops being true while still being remembered. The caller notices
        the change; this is how it says so.
        """
        self._forget_current_state()

    def paused_until(self) -> datetime | None:
        return self._paused_until

    def is_paused(self, now: datetime) -> bool:
        if self._paused_until is None:
            return False
        if now >= self._paused_until:
            self._paused_until = None  # the TTL ran out; resume by itself
            self._forget_current_state()
            return False
        return True

    def _forget_current_state(self) -> None:
        """Drop the memory of which stateful rule was in force.

        The user paused because they took the light somewhere by hand, so on
        resume the winning rule has to assert itself again — treating it as
        "already applied" would leave the manual colour in place indefinitely.
        """
        self._current_stateful_id = ""

    # ── evaluation ────────────────────────────────────────────────────
    def evaluate(
        self, rules: list[Rule], snapshot: Snapshot, events: Sequence[Event | str] = ()
    ) -> Outcome:
        """Decide what should happen. Records nothing: see :meth:`ack`.

        ``events`` are one-off occurrences; a bare kind is accepted as shorthand
        for one that happened at ``snapshot.now``.
        """
        incoming = [
            event if isinstance(event, Event) else Event(kind=event, occurred_at=snapshot.now)
            for event in events
        ]
        if self._pending is not None:
            # A decision is already out being executed. Handing out the same one
            # again would queue a duplicate command behind the first. The tick
            # window is deliberately left open too, so a time crossing that
            # happens while we wait is still there afterwards — and one-off
            # events are held rather than dropped, since unlike a time of day
            # they leave no trace to rediscover later.
            self._defer(incoming)
            return Outcome()

        pending_events = self._take_deferred() + incoming
        previous_tick, self._last_tick = self._last_tick, snapshot.now
        active = [rule for rule in rules if rule.enabled]

        winner, stateful_losers, stateful_blocked = self._stateful_candidates(active, snapshot)
        edges = self._fired_edges(active, previous_tick, snapshot, pending_events)

        recency: dict[str, datetime] = {rule.id: at for rule, at in edges}
        # A stateful rule only acts when it takes over from a different one;
        # while it stays the winner the light is already where it wants it.
        candidates: list[Rule] = [rule for rule, _ in edges]
        if winner is not None and winner.id != self._current_stateful_id:
            candidates.append(winner)
            recency[winner.id] = self._activated_at.get(winner.id, snapshot.now)

        blocked_skips = [Skip(rule.id, reason) for rule, reason in stateful_blocked]

        if not candidates:
            return Outcome(skips=tuple(blocked_skips))

        if self.is_paused(snapshot.now):
            return Outcome(skips=tuple(Skip(rule.id, SKIP_PAUSED) for rule in candidates))

        skips = list(blocked_skips)
        runnable: list[Rule] = []
        for rule in candidates:
            reason = self._blocked_reason(rule, snapshot)
            if reason is None:
                runnable.append(rule)
            else:
                skips.append(Skip(rule.id, reason))

        if not runnable:
            return Outcome(skips=tuple(skips))

        best = max(runnable, key=lambda rule: self._rank(rule, recency, snapshot.now))
        skips.extend(Skip(rule.id, SKIP_OUTRANKED) for rule in runnable if rule.id != best.id)
        # The rules that matched but lost to the winner belong in the journal
        # too: "why didn't my idle rule run" is exactly the question it answers.
        skips.extend(Skip(rule.id, SKIP_OUTRANKED) for rule in stateful_losers)
        decision = Decision(
            rule=best,
            action=best.action,
            occurred_at=recency.get(best.id, snapshot.now),
            decided_at=snapshot.now,
            token=next(self._tokens),
            stateful_context_id=winner.id if winner is not None else "",
        )
        self._pending = decision
        return Outcome(decision=decision, skips=tuple(skips))

    def ack(self, decision: Decision, *, success: bool) -> bool:
        """Record the outcome of executing a decision. True when it was accepted.

        Only the one decision currently awaiting an answer counts, and only
        once. A late callback from a decision that has already been superseded
        would otherwise drag the engine back to a state the user has moved on
        from. Only a success is recorded: a failed BLE write leaves the rule
        un-applied, so the next tick offers it again instead of the engine
        believing the light is somewhere it never went.
        """
        pending = self._pending
        if pending is None or pending.token != decision.token:
            return False
        self._pending = None
        if not success:
            return True
        self._last_fired[decision.rule_id] = decision.decided_at
        if decision.rule.trigger.is_stateful:
            self._current_stateful_id = decision.rule_id
        else:
            # An edge action has just set the light, so the stateful situation
            # that was in force at the time counts as handled. Without this a
            # scheduled "off" would be undone a second later by a fallback rule
            # that simply had not been acked yet — the same event behaving
            # differently depending on history.
            self._current_stateful_id = decision.stateful_context_id
        return True

    def pending(self) -> Decision | None:
        return self._pending

    def retry_at(self, rule: Rule) -> datetime | None:
        """When a cooled-down rule becomes eligible again, if it is waiting."""
        if rule.cooldown_seconds <= 0:
            return None
        last = self._last_fired.get(rule.id)
        if last is None:
            return None
        return last + timedelta(seconds=rule.cooldown_seconds)

    # ── internals ─────────────────────────────────────────────────────
    def _stateful_candidates(
        self, rules: list[Rule], snapshot: Snapshot
    ) -> tuple[Rule | None, list[Rule], list[tuple[Rule, str]]]:
        """The stateful rule in force, the ones it beat, and the unusable ones.

        Eligibility is checked *before* the winner is picked. A top-priority rule
        pointing at a deleted scene must not shadow a working fallback — it loses
        its turn and says why, and the light still follows the next best rule.
        """
        matching = [rule for rule in rules if rule.trigger.is_stateful and _matches_stateful(rule, snapshot)]
        # Remember when each rule started matching: that is the "recency" a tie
        # on priority is settled by. Forgetting it when a rule stops matching is
        # what makes re-entering an app count as a fresh activation.
        matched_ids = {rule.id for rule in matching}
        for rule in matching:
            self._activated_at.setdefault(rule.id, snapshot.now)
        for rule_id in list(self._activated_at):
            if rule_id not in matched_ids:
                del self._activated_at[rule_id]

        runnable: list[Rule] = []
        blocked: list[tuple[Rule, str]] = []
        for rule in matching:
            reason = self._blocked_reason(rule, snapshot)
            if reason is None:
                runnable.append(rule)
            else:
                blocked.append((rule, reason))

        if not runnable:
            return None, [], blocked
        winner = max(runnable, key=lambda rule: self._rank(rule, self._activated_at, snapshot.now))
        return winner, [rule for rule in runnable if rule.id != winner.id], blocked

    def _fired_edges(
        self,
        rules: list[Rule],
        previous_tick: datetime | None,
        snapshot: Snapshot,
        events: list[Event],
    ) -> list[tuple[Rule, datetime]]:
        # Latest occurrence per kind: if the strip reconnected twice while a
        # decision was in flight, the rule runs once, for the newer one.
        latest: dict[str, datetime] = {}
        for event in events:
            if event.occurred_at >= latest.get(event.kind, event.occurred_at):
                latest[event.kind] = event.occurred_at

        fired: list[tuple[Rule, datetime]] = []
        for rule in rules:
            kind = rule.trigger.kind
            if kind == TRIGGER_TIME:
                # Never fire on the very first tick: there is no window to have
                # crossed yet, and launching the app at 21:05 must not replay
                # the 21:00 rule.
                if previous_tick is None:
                    continue
                occurred_at = last_crossing(rule, previous_tick, snapshot.now)
                if occurred_at is not None:
                    fired.append((rule, occurred_at))
            elif kind in latest:
                fired.append((rule, latest[kind]))
        return fired

    def _defer(self, events: list[Event]) -> None:
        """Hold events until the engine is free, newest kept if the queue fills."""
        self._deferred_events.extend(events)
        overflow = len(self._deferred_events) - _MAX_DEFERRED_EVENTS
        if overflow > 0:
            del self._deferred_events[:overflow]

    def _take_deferred(self) -> list[Event]:
        held, self._deferred_events = self._deferred_events, []
        return held

    def _blocked_reason(self, rule: Rule, snapshot: Snapshot) -> str | None:
        if not snapshot.connected:
            return SKIP_DISCONNECTED
        if rule.action.type == ACTION_APPLY_SCENE and snapshot.available_scene_ids is not None:
            if rule.action.scene_id not in snapshot.available_scene_ids:
                return SKIP_MISSING_SCENE
        if rule.cooldown_seconds > 0:
            last = self._last_fired.get(rule.id)
            if last is not None and (snapshot.now - last).total_seconds() < rule.cooldown_seconds:
                return SKIP_COOLDOWN
        return None

    def _rank(
        self, rule: Rule, recency: dict[str, datetime], now: datetime
    ) -> tuple[int, float, str]:
        return rank(rule, recency.get(rule.id, now))
