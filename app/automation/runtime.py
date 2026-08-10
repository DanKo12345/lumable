"""The automation engine, running inside the open app.

This is the other half of the headless path. Windows tasks wake a process for the
rules that must work with LumaBLE closed; everything else — an app coming to the
front, a time of day the user is happy to have honoured only while the app is open
— is evaluated here, on a timer, through the same engine, executor and journal.

Background rules are run here too, and that needs saying carefully. They belong to
the Windows tasks — but a task starts a *second* LumaBLE process, and that process
cannot take the strip while this one is holding it. Leaving them to the tasks alone
therefore means the schedule quietly fails whenever the app happens to be open,
which is the state most people's machines are in when the evening rule comes round.

So both may run them, and the arbitration is the one the headless path already
uses: the machine-wide execution lock, and the record of which occurrence has been
handled. Whoever gets there first does it; the other finds the work done and stands
down. Nothing is coordinated by timing, and neither side has to know the other
exists.

The one exception is the 0.3.5 bridge. While that is up, the old in-app schedule
controller is still running and still switching the light on time, so the rules it
stands for are left alone here — otherwise the two of them would do it twice.

Two behaviours are carried over from the App Trigger watcher it replaces, because
they are what made it pleasant rather than intrusive:

* nothing is applied while a streaming mode owns the strip — screen sync, music or
  a running effect. Only the rules that describe a *situation* stand down for that;
  a time of day still gets honoured, exactly as the old schedule did.
* nothing is applied while the strip is disconnected, which the engine already
  treats as a reason to skip and to say so.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from app import scene_store
from app.automation.ble_executor import BleActionExecutor
from app.automation.dispatcher import (
    CODE_CANCELLED,
    CODE_SHUTDOWN,
    CODE_TIMEOUT,
    AutomationDispatcher,
    decision_context,
    failure_code_for,
    steps_context,
    success_code_for,
)
from app.automation.file_lock import ProcessLock
from app.automation.headless import (
    due_rules,
    execution_lock_path,
    load_state,
    pause_automations,
    paused_until,
    remember_handled,
    remember_seen,
    resume_automations,
    settle_pause,
)
from app.automation.journal import AutomationJournal
from app.automation.resolver import (
    SKIP_OUTRANKED,
    AutomationEngine,
    Decision,
    Event,
    Snapshot,
    rank,
)
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    ORIGIN_LEGACY_SCHEDULE,
    Rule,
    validate_rules,
)
from app.crash_logging import write_current_exception
from app.foreground import foreground_process_name
from app.idle_time import idle_seconds
from app.storage import automation_journal_path, validate_automations

TICK_INTERVAL_MS = 1500
# Longer than a BLE write has any business taking, and the point is only that the
# machine-wide lock is never held by a run nobody is waiting for any more.
BACKGROUND_TIMEOUT_MS = 45_000

# Edge events the engine understands, raised by the app rather than polled.
EVENT_APP_START = "lumable_start"
EVENT_STRIP_CONNECTED = "strip_connected"
# Raised by the Windows session listener. Same shape as the two above: a moment
# the app is told about, queued for the next tick rather than acted on inline.
EVENT_WINDOWS_LOCKED = "windows_locked"
EVENT_WINDOWS_UNLOCKED = "windows_unlocked"
EVENT_WINDOWS_SLEEP = "windows_sleep"
EVENT_WINDOWS_WAKE = "windows_wake"
# How long a wake event waits for Bluetooth to come back before it is dropped.
# Long enough for a normal reconnect, short enough that the light never comes on
# by itself well after the person has settled in.
WAKE_GRACE_SECONDS = 45.0
WINDOWS_EVENTS = (
    EVENT_WINDOWS_LOCKED,
    EVENT_WINDOWS_UNLOCKED,
    EVENT_WINDOWS_SLEEP,
    EVENT_WINDOWS_WAKE,
)

# What the pause looks like from outside. "Pending" and "ending" are the states
# where this app and the machine disagree, and a UI that collapses them into
# "paused" would be promising something it cannot deliver.
PAUSE_OFF = "off"
PAUSE_ACTIVE = "active"
PAUSE_PENDING = "pending"
PAUSE_ENDING = "ending"

# The effect code every driver uses for "just show this colour".
STATIC_EFFECT_CODE = 0

# Marks a journal entry as having been carried out by the open app. The headless
# path marks its own as background, and telling them apart is what makes "why did
# this run twice" answerable.
_IN_APP_CONTEXT = {"in_app": True}


@dataclass(frozen=True)
class AppliedState:
    """What the main strip shows after an automation confirmed every step.

    Only fields the rule actually applied are set; ``None`` means "this rule said
    nothing about it", which is what lets a scene carrying only a brightness leave
    the colour where the user put it.

    Emitted solely on a *confirmed full success*. A partial or failed run has left
    the strip somewhere nobody can describe, and moving the window's controls to a
    state that may not exist would be worse than leaving them where they were.
    """

    rule_id: str
    scene_id: str = ""
    power: bool | None = None
    rgb: tuple[int, int, int] | None = None
    brightness: int | None = None
    # Firmware effects only: a software or DIY effect is not something the strip
    # itself is running, so the effect control has nothing true to show for it.
    #
    # No ``cct`` field on purpose. A scene carrying a white point either finds a
    # controller without the channel — reported as skipped — or reaches the one
    # branch that answers "not wired". Both are skipped steps, so a scene with a cct
    # can never be a confirmed full success, and a field for it here would be a
    # promise nothing could keep.
    effect: dict[str, Any] | None = None


@dataclass
class _BackgroundRun:
    """A background rule being carried out here, and the lock it is holding."""

    lock: ProcessLock
    decision: Any
    occurred_at: datetime
    handle: Any = None
    timeout: Any = None


class AutomationRuntime(QObject):
    """Ticks the automation engine against the world the app can see."""

    # What the main strip shows after a rule confirmed every one of its steps.
    # Nothing here writes to the strip: it is an announcement, not a command.
    applied = Signal(object)

    def __init__(
        self,
        host: Any,
        backend: Any,
        *,
        interval_ms: int = TICK_INTERVAL_MS,
        idle_provider: Callable[[], float] | None = None,
        parent: QObject | None = None,
    ) -> None:
        # Only a real QObject may be the parent: the host is one in the app, but this
        # class is deliberately usable with anything that answers the same questions.
        super().__init__(parent)
        self._host = host
        self._backend = backend
        self._engine = AutomationEngine()
        self._journal = AutomationJournal(automation_journal_path())
        self._journal.load()
        self._executor = BleActionExecutor(
            host._ble,
            scene_for=self._scene_for,
            resolve_targets=backend.resolve_scene_targets,
            capabilities_for=backend.capabilities_for_device,
            set_pc_mode=backend.set_pc_mode,
            parent=self,
        )
        self._dispatcher = AutomationDispatcher(self._engine, self, self._journal)
        self._idle_provider = idle_provider or idle_seconds
        self._pending: list[str] = []
        self._held_wake_since: float | None = None
        # What the rules were last tick. The engine remembers which stateful rule is
        # in force, and that memory is about a rule as it was — see _note_rules.
        self._known: tuple[Rule, ...] | None = None
        # The background rule being carried out here, if any. While it is set the
        # execution lock is held and nothing else may touch the strip.
        self._background: _BackgroundRun | None = None
        # A pause the user asked for that the machine has not been told about yet,
        # and the same for a resume. Retried from the tick until one of them lands.
        self._pause_wanted: tuple[datetime, int] | None = None
        self._resume_wanted = False
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_ms))
        self._timer.timeout.connect(self._tick)

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        # A pause outlives the window it was set in. Without this the shared state
        # goes on holding the background rules off while the runtime ones — the app
        # triggers the user paused in the first place — start again immediately.
        self._restore_pause()
        # The app has just come up: a rule waiting for that gets its one chance.
        self._pending.append(EVENT_APP_START)
        if bool(getattr(self._host, "_is_connected", False)):
            # The strip connected before the engine was up — during the autoconnect
            # that runs well ahead of this. The edge still happened, so a rule
            # waiting for it must not be cheated of it by our own start-up order.
            self._pending.append(EVENT_STRIP_CONNECTED)
        self._timer.start()

    def stop(self) -> None:
        """Shut the engine down. Called before the app lets go of the strip.

        The background run goes first: it is holding a machine-wide lock, and a
        window that closed without releasing it would keep every Windows task from
        running an automation until the next restart.
        """
        self._timer.stop()
        self._abandon_background(CODE_SHUTDOWN)
        # One last go at telling the machine about a pause the user asked for. The
        # lock was almost certainly ours a moment ago, so this is the likeliest
        # moment for it to succeed — and after this there are no more ticks to
        # retry from. What still fails is reported by pause_status(), never
        # pretended away.
        self._settle_shared_pause()
        self._dispatcher.shutdown(datetime.now(), monotonic())

    def note_connected(self, connected: bool = True) -> None:
        """The main strip connected. Raised by the app, not polled for.

        Only the rising edge is an event: ``connected_changed`` also reports the
        drop, and a rule that waits for the strip to come back must not be handed
        the moment it went away.
        """
        if connected:
            self._pending.append(EVENT_STRIP_CONNECTED)

    def note_windows_event(self, event: str) -> bool:
        """The workstation locked, unlocked, slept or woke.

        Queued like every other edge event rather than acted on where it
        arrives: it comes in on a native message, and running a rule from there
        would put BLE work inside a Windows message handler. Returns whether the
        event was one we know — an unknown name is dropped rather than queued,
        so a typo cannot sit in the queue forever.
        """
        if event not in WINDOWS_EVENTS:
            return False
        self._pending.append(event)
        return True

    def pause(self, seconds: int = 3600) -> bool:
        """The user took over by hand; hold the automations off for a while.

        Written to the shared state as well as told to the engine, because a Windows
        task starts its own process and would otherwise walk straight through a
        pause it never heard about.

        Returns whether the *machine* was told. This process always obeys either
        way — refusing to pause anything because a lock was busy would be the worse
        answer — but a caller that shows the user "automations paused" needs to know
        the difference, and the write is retried on the next tick until it lands.
        """
        now = datetime.now()
        # Whatever is being carried out right now is part of what they are taking
        # over from.
        self._abandon_background(CODE_CANCELLED)
        self._dispatcher.pause(now, seconds=seconds)
        self._pause_wanted = (now, int(seconds))
        # A resume that never reached the machine is no longer wanted. Left set, the
        # next tick would carry it out and lift the pause the user has just asked
        # for — their older instruction undoing their newer one.
        self._resume_wanted = False
        return self._settle_shared_pause()

    def resume(self) -> bool:
        """Let the automations go again. Returns whether the machine was told."""
        self._dispatcher.resume()
        self._pause_wanted = None
        self._resume_wanted = True
        return self._settle_shared_pause()

    def _settle_shared_pause(self) -> bool:
        """Try to put the pause — or its end — where every process can see it.

        Called again from each tick while it has not landed: the lock is usually
        busy because an automation is running right now, which is exactly the moment
        a pause matters most, and one failed attempt must not leave the two sides
        disagreeing for the rest of the hour.
        """
        if self._pause_wanted is not None:
            since, seconds = self._pause_wanted
            if not pause_automations(since, seconds):
                return False
            self._pause_wanted = None
            return True
        if self._resume_wanted:
            if not resume_automations(datetime.now()):
                return False
            self._resume_wanted = False
        return True

    def paused_until(self) -> datetime | None:
        """When the shared pause runs out, for anything that wants to show it."""
        return paused_until()

    def pause_status(self) -> str:
        """What the user can honestly be told about the pause.

        The distinction is not pedantry. ``PAUSE_PENDING`` means this app is holding
        automations off but the machine has not been told, so a Windows task could
        still switch the light — presenting that as a pause would be a promise the
        app cannot keep. ``PAUSE_ENDING`` is the mirror: the app has resumed while
        the machine is still holding off.
        """
        if self._pause_wanted is not None:
            return PAUSE_PENDING
        if self._resume_wanted:
            return PAUSE_ENDING
        ends_at = paused_until()
        if ends_at is None or ends_at <= datetime.now():
            return PAUSE_OFF
        return PAUSE_ACTIVE

    def _restore_pause(self) -> None:
        ends_at = paused_until()
        if ends_at is None:
            return
        remaining = (ends_at - datetime.now()).total_seconds()
        if remaining <= 0:
            return  # it ran out while the app was closed; the tick settles the rest
        self._dispatcher.pause(datetime.now(), seconds=int(remaining) + 1)

    def _automations(self) -> dict[str, Any]:
        return validate_automations(self._settings().get("automations", {}))

    # ── the tick ──────────────────────────────────────────────────────
    def _tick(self) -> None:
        settings = self._settings()
        automations = validate_automations(settings.get("automations", {}))
        if not automations.get("enabled"):
            # Switched off. Recorded as "no rules", so switching back on is seen for
            # what it is: whatever was in force before means nothing now — and
            # anything being carried out right now is no longer wanted either.
            self._abandon_background(CODE_CANCELLED)
            self._note_rules(None)
            self._pending.clear()
            return
        if self._pause_wanted is not None or self._resume_wanted:
            # The lock was busy when the user asked. Keep trying: until this lands,
            # a task's process knows nothing about the pause.
            self._settle_shared_pause()
        if self._background is not None:
            # A background rule is being carried out. One strip, one action at a
            # time — and the execution lock is held until it answers.
            return
        rules = self._runtime_rules(automations)
        events: list[Event] = [
            Event(kind=kind, occurred_at=datetime.now()) for kind in self._take_pending()
        ]
        if rules:
            self._dispatcher.tick(
                rules, self._snapshot(settings), events, monotonic_now=monotonic()
            )
        self._tick_background(settings, automations)

    def _take_pending(self) -> list[str]:
        """The edge events to act on now, holding back a wake the link cannot serve.

        Waking is the one case where the event and the ability to act on it are
        seconds apart: Windows says "awake" while Bluetooth is still coming back,
        and a rule fired there would be skipped as disconnected and never run —
        which for "restore my light when I wake" is the whole feature missing.
        So a wake waits for the strip, but not forever: past the deadline it is
        dropped, because a scene applied two minutes after someone sat down is a
        light turning on by itself.
        """
        pending, self._pending = self._pending, []
        if self._connected():
            self._held_wake_since = None
            return pending

        now = monotonic()
        deliver: list[str] = []
        held: list[str] = []
        for kind in pending:
            if kind != EVENT_WINDOWS_WAKE:
                # Locking and sleeping usually turn the light off, and holding
                # those until a strip that is going away comes back would leave
                # it on all night.
                deliver.append(kind)
                continue
            if self._held_wake_since is None:
                self._held_wake_since = now
            if now - self._held_wake_since <= WAKE_GRACE_SECONDS:
                held.append(kind)
            else:
                # Let go rather than delivered: past the deadline this would be
                # a rule firing at a strip that is still not there, and the next
                # wake deserves its own grace rather than this one's leftovers.
                self._held_wake_since = None
        self._pending.extend(held)
        return deliver

    def _note_rules(self, rules: tuple[Rule, ...] | None) -> None:
        """Notice that the rules are not the ones the engine has been reasoning about.

        A stateful rule only acts when it takes over, so the engine remembers the one
        in force. Edit the scene behind that rule — or delete it and add it back with
        the same id — and it is a different rule wearing a familiar name, which the
        engine would otherwise go on considering already applied. Comparing the rules
        themselves catches every version of that: the id alone would not.
        """
        if rules == self._known:
            return
        self._known = rules
        self._dispatcher.rules_changed()

    def _runtime_rules(self, automations: dict[str, Any]) -> list[Rule]:
        rules = [
            rule
            for rule in validate_rules(automations.get("rules", []))
            if rule.enabled and not rule.runs_in_background
        ]
        # Compared before the streaming filter below: what the *rules* are is a
        # different question from what the world is doing to them, and mixing the two
        # would reset the engine every time a stream started or stopped.
        # List order is presentation only; conflict resolution deliberately ignores
        # it. Reordering rows must not cancel an in-flight action or make the winner
        # assert itself again.
        self._note_rules(tuple(sorted(rules, key=lambda rule: rule.id)))
        if not self._streaming_mode_running():
            return rules
        # A stream owns the strip. The rules that describe a lasting situation stand
        # down for it — walking into an app must not interrupt screen sync — while a
        # time of day is still honoured, which is what the old schedule did.
        return [rule for rule in rules if not rule.trigger.is_stateful]

    # ── background rules, while the app is open ───────────────────────
    def _tick_background(self, settings: dict[str, Any], automations: dict[str, Any]) -> None:
        """Carry out a background rule that has come due, unless someone else is.

        The lock is taken without waiting: if a task's process has it, that process
        is doing exactly this work, and the right answer is to leave it to them.
        Once taken it is held until the write answers — releasing it earlier would
        let a task start the same rule in the gap between deciding and finishing.
        """
        if self._background is not None or self._dispatcher.in_flight() is not None:
            return
        if not bool(getattr(self._host, "_is_connected", False)):
            # No strip here. A task's process connects on demand, so this is one of
            # the cases where leaving it to them is the *better* answer.
            return
        rules = self._background_rules(automations)
        if not rules:
            return
        now = datetime.now()
        if not due_rules(rules, load_state(), now)[0]:
            return  # cheap answer first: the lock is only worth taking if there is work

        lock = ProcessLock(execution_lock_path())
        if not lock.acquire():
            return
        try:
            self._start_background(rules, now, lock)
        except Exception:
            # Leaving the run in place would stop the engine ticking for good: every
            # tick from here on would see a background run that never ends.
            if self._background is not None:
                self._abandon_background(CODE_CANCELLED)
            else:
                lock.release()
            raise

    def _background_rules(self, automations: dict[str, Any]) -> list[Rule]:
        rules = [
            rule
            for rule in validate_rules(automations.get("rules", []))
            if rule.enabled and rule.runs_in_background
        ]
        if automations.get("legacy_bridge"):
            # The old in-app schedule controller is still running and still switching
            # the light at these times. Until the handoff retires it, doing it here
            # as well would do it twice.
            rules = [rule for rule in rules if rule.origin != ORIGIN_LEGACY_SCHEDULE]
        return rules

    def _start_background(self, rules: list[Rule], now: datetime, lock: ProcessLock) -> None:
        """Decide and dispatch, with the lock held. Releases it if nothing is due."""
        # Read again under the lock: a task's process may have handled an occurrence
        # while we were deciding to look, and a pause may have been set or run out.
        state, paused = settle_pause(load_state(), rules, now)
        if paused:
            lock.release()
            return
        state = remember_seen(state, rules, now)
        due, _cooling = due_rules(rules, state, now)
        if not due:
            lock.release()
            return
        winner, occurred_at = max(due, key=lambda pair: rank(*pair))

        # Everything else that came due is settled here, before a single write goes
        # out. After a sleep through both an "on" and an "off", the later one wins —
        # and if the earlier one were left owed, the next tick would find it due and
        # put the light straight back the way the user did not ask for.
        losers = [(rule, occurred) for rule, occurred in due if rule.id != winner.id]
        for rule, _occurred in losers:
            self._journal.record_skip(
                rule.id,
                SKIP_OUTRANKED,
                now=now,
                context=dict(_IN_APP_CONTEXT) | {"winner_rule_id": winner.id},
            )
        if losers:
            remember_handled(state, {rule.id: occurred for rule, occurred in losers})

        decision = Decision(
            rule=winner,
            action=winner.action,
            occurred_at=occurred_at,
            decided_at=now,
            token=0,
        )
        run = _BackgroundRun(lock=lock, decision=decision, occurred_at=occurred_at)
        # Recorded before dispatching: the executor may answer inside the call, and
        # the callback has to find the run it is answering for.
        self._background = run
        run.timeout = QTimer(self)
        run.timeout.setSingleShot(True)
        run.timeout.timeout.connect(lambda: self._background_timed_out(run))
        run.timeout.start(BACKGROUND_TIMEOUT_MS)
        run.handle = self._executor.execute(decision, lambda result: self._background_done(run, result))

    def _background_done(self, run: _BackgroundRun, result: Any) -> None:
        if self._background is not run:
            return  # already finished, or timed out and let go of
        self._background = None
        if run.timeout is not None:
            run.timeout.stop()
        rule = run.decision.rule
        now = datetime.now()
        context = decision_context(run.decision) | steps_context(result) | dict(_IN_APP_CONTEXT)
        # Everything that must happen, before anything that merely should. The lock
        # is machine-wide: a failure while describing what happened must not be able
        # to keep it, or one bad announcement stops every automation on the machine.
        try:
            if result.ok:
                self._journal.record_success(
                    rule.id,
                    message_code=result.code or success_code_for(run.decision),
                    now=now,
                    occurred_at=run.occurred_at,
                    decided_at=run.decision.decided_at,
                    context=context,
                )
                # Recorded only on success, exactly as the headless path does: a run
                # that failed leaves the occurrence for whoever tries next.
                remember_handled(load_state(), {rule.id: run.occurred_at}, fired={rule.id: now})
            else:
                self._journal.record_error(
                    rule.id,
                    message_code=failure_code_for(result),
                    now=now,
                    occurred_at=run.occurred_at,
                    decided_at=run.decision.decided_at,
                    context=context,
                )
            self._journal.flush(monotonic(), force=True)
        finally:
            run.lock.release()
        if result.ok:
            self._safe_reflect(run.decision)

    def _background_timed_out(self, run: _BackgroundRun) -> None:
        """Give up on a write that never answered, rather than hold the lock for ever.

        The lock is machine-wide: keeping it after we have stopped waiting would
        block every task's process too, and none of them would ever find out why.
        """
        if self._background is not run:
            return
        self._abandon_background(CODE_TIMEOUT)

    def _abandon_background(self, code: str) -> None:
        """Call off a background run, whatever the reason, and let the lock go.

        The one path out for every ending that is not the write answering: the app
        closing, a pause, automations switched off, a start that raised. The order
        matters — the run is dropped *first*, so a result that arrives afterwards
        finds nothing to answer for and cannot release a lock somebody else now
        holds — and the release itself is in a ``finally``, because a lock nobody
        holds is at worst a repeated run, while a lock nobody releases stops every
        automation on the machine.
        """
        run, self._background = self._background, None
        if run is None:
            return
        try:
            if run.timeout is not None:
                run.timeout.stop()
            if run.handle is not None:
                run.handle.cancel()
            self._journal.record_cancelled(
                run.decision.rule.id,
                message_code=code,
                now=datetime.now(),
                occurred_at=run.occurred_at,
                decided_at=run.decision.decided_at,
                # A write already handed to the BLE stack cannot be recalled, so
                # whether it landed is genuinely unknown.
                context=decision_context(run.decision)
                | dict(_IN_APP_CONTEXT)
                | {"partial_possible": True},
            )
            self._journal.flush(monotonic(), force=True)
        finally:
            run.lock.release()

    def _connected(self) -> bool:
        return bool(getattr(self._host, "_is_connected", False))

    def _snapshot(self, settings: dict[str, Any]) -> Snapshot:
        return Snapshot(
            now=datetime.now(),
            foreground_app=self._foreground(),
            idle_seconds=self._idle(),
            connected=self._connected(),
            # Checked, so a rule pointing at a deleted scene is reported as such
            # rather than tried and failed.
            available_scene_ids=frozenset(
                scene["scene_id"] for scene in scene_store.list_scenes(settings)
            ),
        )

    @staticmethod
    def _foreground() -> str:
        try:
            return foreground_process_name()
        except Exception:  # pragma: no cover - platform quirk, never worth a crash
            return ""

    def _idle(self) -> float:
        try:
            return max(0.0, float(self._idle_provider()))
        except Exception:  # pragma: no cover - the same reasoning as above
            return 0.0

    def _streaming_mode_running(self) -> bool:
        for name in ("_ambient_ui", "_music_ui", "_software_fx_ui", "_diy_ui"):
            controller = getattr(self._host, name, None)
            try:
                if controller is not None and controller.is_running():
                    return True
            except Exception:  # pragma: no cover - a controller mid-teardown
                continue
        return False

    def _settings(self) -> dict[str, Any]:
        settings = getattr(self._host, "_settings", None)
        return settings if isinstance(settings, dict) else {}

    def _scene_for(self, scene_id: str) -> dict[str, Any] | None:
        return scene_store.get_scene(self._settings(), scene_id)

    # ── the executor seam ─────────────────────────────────────────────
    # The dispatcher is handed this object rather than the BLE executor directly, so
    # that what the app knows about itself can be kept in step with what an
    # automation just did to the strip.
    def execute(self, decision: Any, done: Any) -> Any:
        def finished(result: Any) -> None:
            # The dispatcher is owed exactly one answer and is stuck until it gets
            # one, so it is answered first. Saying what the light now shows is worth
            # doing and worth reporting when it fails, but it is not worth holding a
            # decision in flight for.
            done(result)
            if result.ok:
                self._safe_reflect(decision)

        return self._executor.execute(decision, finished)

    def _safe_reflect(self, decision: Any) -> None:
        """Describe what happened, and never let the describing break the run.

        Called only after the run's own bookkeeping is finished — the ack given, the
        occurrence recorded, the lock released — so that a fault in building the
        state, or in a slot listening for it, costs a stale set of controls and a
        crash log rather than an automation that never completes.
        """
        try:
            self._reflect(decision)
        except Exception:
            write_current_exception(context="automation_reflect")

    def _reflect(self, decision: Any) -> None:
        """Say what the light now shows, and remember the part that must persist.

        Two different needs. Persisting the power state is correctness: reconnecting
        restores what the app believes in, so without it the next reconnect would
        undo the automation. Announcing the state is presentation, and belongs to
        whoever is showing controls — so it goes out as a signal rather than by
        reaching into the window from here.
        """
        state = self._applied_state(decision)
        if state is None:
            return
        if state.power is not None:
            remember = getattr(self._host, "_remember_power_setting", None)
            try:
                if callable(remember):
                    remember(state.power)
            except Exception:  # pragma: no cover - the run itself already succeeded
                pass
        self.applied.emit(state)

    def _applied_state(self, decision: Any) -> AppliedState | None:
        """What the *main strip* is showing now, as far as this rule decided it."""
        action = getattr(decision, "action", None)
        rule_id = getattr(getattr(decision, "rule", None), "id", "")
        kind = getattr(action, "type", "")
        if kind == ACTION_SET_POWER:
            power = getattr(action, "power", None)
            return AppliedState(rule_id=rule_id, power=power) if isinstance(power, bool) else None
        if kind != ACTION_APPLY_SCENE:
            return None
        scene = self._scene_for(getattr(action, "scene_id", ""))
        if not isinstance(scene, dict) or not self._targets_primary(scene):
            # A scene aimed at a group the main strip is not in changed some other
            # light. Moving these controls for it would be a plain untruth.
            return None
        state = scene.get("state") or {}
        rgb = state.get("rgb")
        effect = state.get("effect")
        firmware = effect if isinstance(effect, dict) and effect.get("kind") == "firmware" else None
        if firmware is None and rgb is not None:
            # A colour and no effect means the strip is showing that colour and
            # nothing else. The app has always taken that view — applying a colour
            # preset puts the effect control back to static — and leaving the control
            # showing a rainbow the strip is no longer running would be the same
            # half-truth this whole signal exists to avoid.
            firmware = {"kind": "firmware", "ref": STATIC_EFFECT_CODE, "speed": None}
        return AppliedState(
            rule_id=rule_id,
            scene_id=str(scene.get("scene_id", "")),
            power=state.get("power") if isinstance(state.get("power"), bool) else None,
            rgb=tuple(int(part) for part in rgb) if isinstance(rgb, (list, tuple)) else None,
            brightness=state.get("brightness"),
            effect=firmware,
        )

    def _targets_primary(self, scene: dict[str, Any]) -> bool:
        try:
            targets = self._backend.resolve_scene_targets(scene.get("target"))
        except Exception:  # pragma: no cover - the run itself already succeeded
            return False
        if targets is None:
            return True  # every connected strip, which is where these controls point
        primary = str(self._host._ble.primary_address() or "").strip()
        return bool(primary) and primary in {str(address).strip() for address in targets}
