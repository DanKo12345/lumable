"""Automations carried out with LumaBLE closed.

A rule marked for background execution is compiled into a Windows task that starts
LumaBLE headless. Nothing here may assume a window, a tray icon or a running app:
there is one console process, one BLE connection, and a journal to write to.

**A task invocation is a wake-up, not an instruction.** Which rule fired the task
is deliberately not what gets run. After the machine sleeps through both an "on at
19:00" and an "off at 23:00", Task Scheduler starts *both* tasks, and running each
one independently would leave the light wherever the last process to finish put it
— priority and freshness ignored, the outcome decided by process scheduling. That
is the conflict the resolver exists to settle, so this path settles it the same
way: every due background rule is gathered, one winner is chosen with
:func:`~app.automation.resolver.rank`, and the losers are recorded as outranked.

Two things make that safe across processes:

* **One execution lock.** At most one automation run happens at a time, machine
  wide. A sibling task waits for it and then finds nothing left due — or finds its
  own rule due, if its time passed while the first was still running.
* **Handled occurrences on disk.** The winner's occurrence, and its losers', are
  written down, so a second process cannot repeat what the first has done.

The event loop cannot be skipped either. ``operation_finished`` is delivered
through a queued connection, so without a turning ``QCoreApplication`` the write's
result would never arrive and every background run would end in a timeout. Turning
it is also what makes the exit code mean something: it is decided by what the
controller confirmed, not by waiting a couple of seconds and hoping — which is what
the 0.3.5 scheduled action had to do.

Exit codes are chosen for Task Scheduler's benefit. A task that fires for a rule
the user has since switched off is *not* a failure: it exits 0 and leaves a line in
the journal, because a red cross in Windows the user can do nothing about teaches
them to ignore the ones that matter.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QTimer

from app import scene_store
from app.automation.ble_executor import BleActionExecutor
from app.automation.dispatcher import (
    CODE_TIMEOUT,
    decision_context,
    failure_code_for,
    steps_context,
    success_code_for,
)
from app.automation.file_lock import file_lock
from app.automation.journal import AutomationJournal
from app.automation.resolver import (
    SKIP_COOLDOWN,
    SKIP_OUTRANKED,
    SKIP_PAUSED,
    Decision,
    last_crossing,
    rank,
)
from app.automation.rules import ACTION_SET_POWER, Rule, validate_rules
from app.ble import BleController
from app.feature_gate import can_use
from app.storage import (
    automation_control_path,
    automation_journal_path,
    automation_state_path,
    load_settings,
    update_power_setting,
    validate_automations,
)

RUN_TIMEOUT_MS = 30_000
# Long enough to outlast a sibling's whole run — connect, write, tear down — so a
# task whose time came while another was running still gets its turn.
LOCK_TIMEOUT_SECONDS = 45.0
# The app only wants to note a rule as being watched, so it must not sit behind a
# whole background run: it gives up and says so instead.
SEED_TIMEOUT_SECONDS = 10.0
# Pausing is a button press. Waiting on a lock here freezes the window, so it barely
# waits at all — and the caller is told when the machine has not been reached.
PAUSE_TIMEOUT_SECONDS = 0.5
# How far back a missed run is still worth doing. A machine off for a week must not
# replay last Tuesday's evening rule on Monday morning.
CATCHUP = timedelta(hours=24)
# Task Scheduler can start a task a hair before this process reads the clock.
# Without this, a rule due at exactly 23:00 could be found "not due yet".
DUE_GRACE = timedelta(seconds=60)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PRO_REQUIRED = 3
EXIT_NO_ADDRESS = 4

# Why a task fired and nothing happened. Journal codes, never localised text.
SKIP_AUTOMATIONS_DISABLED = "automations_disabled"
SKIP_NO_BACKGROUND_RULES = "no_background_rules"
SKIP_NOTHING_DUE = "nothing_due"
SKIP_BUSY = "another_run_in_progress"

CODE_NO_ADDRESS = "no_saved_address"
CODE_CONNECT_FAILED = "connect_failed"

STATE_VERSION = 1
CONTROL_VERSION = 1

# Marks an entry as having happened while the app was closed. The user reads the
# same journal either way, and "this ran without LumaBLE open" is the difference
# between a working schedule and a mystery.
_BACKGROUND_CONTEXT = {"background": True}


def run_automations(
    *, woken_by: str = "", timeout_ms: int = RUN_TIMEOUT_MS, now: datetime | None = None
) -> int:
    """Run at most one due background rule.

    ``woken_by`` names the task that started this process. It is recorded and
    otherwise ignored: after a sleep several tasks fire, and only one of the rules
    they stand for may win.

    ``now`` is the moment the run is reckoned from — the clock, unless a caller has
    already read it. Injectable for the same reason the dispatcher takes one: "which
    rules are overdue" is otherwise untestable without waiting for a time of day.
    """
    context = dict(_BACKGROUND_CONTEXT) | ({"woken_by": woken_by} if woken_by else {})

    with file_lock(execution_lock_path(), timeout=LOCK_TIMEOUT_SECONDS) as locked:
        if not locked:
            # A sibling held the lock for the whole wait. It gathers due rules
            # itself, so the one wrong thing to do here is run one alongside it.
            journal = _loaded_journal()
            return _nothing_to_do(
                journal,
                SKIP_BUSY,
                rule_id=woken_by,
                now=now or datetime.now(),
                context=context,
            )

        # Everything below is authoritative only after the lock. A sibling may
        # have handled an occurrence while we waited, and the user may have
        # disabled or edited a rule. Reading before the wait would execute a stale
        # snapshot. The live clock matters for the same reason: a crossing can
        # happen during a long BLE run ahead of us.
        current_now = now or datetime.now()
        settings = load_settings()
        automations = validate_automations(settings.get("automations", {}))
        journal = _loaded_journal()

        if not automations.get("enabled"):
            return _nothing_to_do(
                journal,
                SKIP_AUTOMATIONS_DISABLED,
                rule_id=woken_by,
                now=current_now,
                context=context,
            )

        rules = [
            rule
            for rule in validate_rules(automations.get("rules", []))
            if rule.enabled and rule.runs_in_background
        ]
        if not rules:
            # Every background rule is gone, switched off, or runtime-only now:
            # the task outlived what created it. Removing the task is the app's job.
            return _nothing_to_do(
                journal,
                SKIP_NO_BACKGROUND_RULES,
                rule_id=woken_by,
                now=current_now,
                context=context,
            )

        # Background rules are the old schedule's capability, so they answer to
        # the same gate — this path is not the place to invent a new paywall.
        if not can_use("schedule"):
            print("LumaBLE automations require Pro; nothing to do.", file=sys.stderr)
            return EXIT_PRO_REQUIRED

        return _run_one(rules, settings, journal, current_now, context, timeout_ms)


def _loaded_journal() -> AutomationJournal:
    journal = AutomationJournal(automation_journal_path())
    # Read what is already there so this run adds a line instead of replacing the
    # history with one entry of its own.
    journal.load()
    return journal


def _nothing_to_do(
    journal: AutomationJournal,
    reason: str,
    *,
    rule_id: str,
    now: datetime,
    context: dict[str, Any],
) -> int:
    journal.record_skip(rule_id, reason, now=now, context=dict(context))
    journal.flush(monotonic(), force=True)
    print(f"LumaBLE automation: nothing to do ({reason}).")
    return EXIT_OK


def _run_one(
    rules: list[Rule],
    settings: dict[str, Any],
    journal: AutomationJournal,
    now: datetime,
    context: dict[str, Any],
    timeout_ms: int,
) -> int:
    """Decide and carry out a single run. The execution lock is held throughout."""
    state, paused = settle_pause(load_state(), rules, now)
    if paused:
        # The user took the light over by hand in the app. A task firing meanwhile
        # must not undo that, and this process has no other way of knowing.
        journal.record_skip("", SKIP_PAUSED, now=now, context=dict(context))
        journal.flush(monotonic(), force=True)
        print(f"LumaBLE automation: nothing to do ({SKIP_PAUSED}).")
        return EXIT_OK
    state = remember_seen(state, rules, now)
    due, cooling = due_rules(rules, state, now)
    for rule in cooling:
        journal.record_skip(rule.id, SKIP_COOLDOWN, now=now, context=dict(context))
    if not due:
        # Only when nothing was due at all. A rule held back by its cooldown has
        # already said so above, and adding "nothing was due" on top would
        # contradict it.
        reason = SKIP_COOLDOWN if cooling else SKIP_NOTHING_DUE
        if not cooling:
            journal.record_skip("", SKIP_NOTHING_DUE, now=now, context=dict(context))
        journal.flush(monotonic(), force=True)
        print(f"LumaBLE automation: nothing to do ({reason}).")
        return EXIT_OK

    winner, occurred_at = max(due, key=lambda pair: rank(*pair))
    losers = [(rule, occurred) for rule, occurred in due if rule.id != winner.id]
    for rule, _occurred in losers:
        journal.record_skip(
            rule.id,
            SKIP_OUTRANKED,
            now=now,
            context=dict(context) | {"winner_rule_id": winner.id},
        )
    # The losers are marked handled before anything is sent: they wanted the light
    # where the winner is about to put it, and a sibling task must not undo that a
    # second later.
    remember_handled(state, {rule.id: occurred for rule, occurred in losers})

    address = str(settings.get("last_device_address", "")).strip()
    if not address:
        journal.record_error(
            winner.id,
            message_code=CODE_NO_ADDRESS,
            now=now,
            occurred_at=occurred_at,
            context=dict(context),
        )
        journal.flush(monotonic(), force=True)
        print("LumaBLE automation has no saved controller address.", file=sys.stderr)
        return EXIT_NO_ADDRESS

    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    runner = _RuleRunner(
        winner,
        address,
        settings,
        journal,
        occurred_at=occurred_at,
        context=context,
        timeout_ms=timeout_ms,
    )
    QTimer.singleShot(0, runner.start)
    app.exec()

    if runner.exit_code == EXIT_OK:
        # Recorded only on success, exactly as the engine's ack does: a run that
        # failed leaves the rule un-applied, so a sibling task — or the app on its
        # next start — is still free to try it.
        remember_handled(load_state(), {winner.id: occurred_at}, fired={winner.id: now})
    return runner.exit_code


def remember_handled(
    state: dict[str, Any],
    handled: dict[str, datetime],
    *,
    fired: dict[str, datetime] | None = None,
) -> None:
    if not handled and not fired:
        return
    state["handled"] = dict(state.get("handled", {})) | handled
    state["fired"] = dict(state.get("fired", {})) | (fired or {})
    save_state(state)


def remember_seen(state: dict[str, Any], rules: Iterable[Rule], now: datetime) -> dict[str, Any]:
    """Note the rules we are seeing for the first time, and from when.

    Written down rather than recomputed each pass: a run that failed leaves no
    handled occurrence, and the next task has to be able to tell "this was due and
    did not get done" from "this was due before we were watching".
    """
    if _seed_seen_since(state, (rule.id for rule in rules), now):
        save_state(state)
    return state


def _seed_seen_since(state: dict[str, Any], rule_ids: Iterable[str], now: datetime) -> bool:
    """Add the rules not yet in view. True when the state changed.

    Only ever fills gaps: a rule already being watched keeps the moment it was
    first seen, or every pass would move the window forward and a missed
    occurrence would never be caught up.
    """
    seen_since = _timestamps(state.get("seen_since"))
    fresh = {rule_id: now - DUE_GRACE for rule_id in rule_ids if rule_id not in seen_since}
    if not fresh:
        return False
    state["seen_since"] = seen_since | fresh
    return True


def seed_seen_since(
    rule_ids: Iterable[str], *, now: datetime | None = None, timeout: float = SEED_TIMEOUT_SECONDS
) -> bool:
    """Start watching these rules, before anything can fire them.

    Called by the task compiler just before it hands a rule to Windows. Without it
    the rule's first occurrence is only ever "seen" by the pass that the task itself
    starts — so a rule created in the evening, whose task then fires late the next
    morning because the machine slept, would have that missed occurrence discarded
    as being from before we were watching.

    False means the execution lock was busy and nothing was written; the caller must
    treat that as "not ready to arm this rule yet" rather than carry on.
    """
    ids = [str(rule_id).strip() for rule_id in rule_ids if str(rule_id).strip()]
    if not ids:
        return True
    moment = now or datetime.now()
    with file_lock(execution_lock_path(), timeout=timeout) as locked:
        if not locked:
            return False
        state = load_state()
        if _seed_seen_since(state, ids, moment):
            save_state(state)
        return True


def due_rules(
    rules: Iterable[Rule], state: dict[str, Any], now: datetime
) -> tuple[list[tuple[Rule, datetime]], list[Rule]]:
    """Which rules came due unhandled, and which are still cooling down.

    The window ends a moment past ``now`` and starts at whichever of these the rule
    can appeal to, in order: the last occurrence already handled, or else the moment
    the rule first came into view. It never reaches further back than
    :data:`CATCHUP`. The crossing itself is found by the resolver's own function, so
    a missed evening rule is discovered here exactly as a tick of the running app
    would discover it.

    That "first came into view" bound is what keeps a first pass honest. Without it a
    task firing at 22:00 would look back a full day, find last night's 23:00 rule
    unhandled and switch the light then and there — the same trap the engine avoids
    by never firing a time rule on its very first tick.
    """
    handled = _timestamps(state.get("handled"))
    fired = _timestamps(state.get("fired"))
    seen_since = _timestamps(state.get("seen_since"))
    horizon = now + DUE_GRACE
    earliest = horizon - CATCHUP
    due: list[tuple[Rule, datetime]] = []
    cooling: list[Rule] = []
    for rule in rules:
        previous = handled.get(rule.id)
        if previous is None:
            # Never handled: watch from when we first saw it, and for a rule we are
            # seeing right now that means only a crossing from the last moment — the
            # one whose task woke us.
            previous = seen_since.get(rule.id, now - DUE_GRACE)
        occurred_at = last_crossing(rule, max(previous, earliest), horizon)
        if occurred_at is None:
            continue
        if _is_cooling(rule, fired.get(rule.id), now):
            cooling.append(rule)
            continue
        due.append((rule, occurred_at))
    return due, cooling


def _is_cooling(rule: Rule, last_fired: datetime | None, now: datetime) -> bool:
    if rule.cooldown_seconds <= 0 or last_fired is None:
        return False
    return (now - last_fired).total_seconds() < rule.cooldown_seconds


# ── handled occurrences on disk ───────────────────────────────────────
def load_state() -> dict[str, Any]:
    """What has already been handled. A damaged file costs at most a repeated run.

    Three books, deliberately separate: ``handled`` is the occurrence each rule has
    already had (so no process repeats it), ``fired`` is when each rule last actually
    succeeded (so a cooldown means something), and ``seen_since`` is when each rule
    first came into view (so nothing from before that is replayed).

    ``pause_generation`` is not a fourth book but a receipt: the number of the pause
    intent whose ending has already been tidied up, so it is done exactly once. The
    intent itself lives in the control file — see load_control.
    """
    empty: dict[str, Any] = {
        "version": STATE_VERSION,
        "handled": {},
        "fired": {},
        "seen_since": {},
        "pause_generation": 0,
    }
    try:
        raw = json.loads(automation_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    return {
        "version": STATE_VERSION,
        "handled": _timestamps(raw.get("handled")),
        "fired": _timestamps(raw.get("fired")),
        "seen_since": _timestamps(raw.get("seen_since")),
        "pause_generation": _pause_generation(raw.get("pause_generation")),
    }


def save_state(state: dict[str, Any]) -> bool:
    """Write the state out, reporting whether it landed.

    Only ever called with the execution lock held. Most callers can ignore the
    answer — a lost ``handled`` costs one repeated run — but a pause cannot: telling
    the user automations are held off when nothing was written would leave a task
    free to switch their light while they believe it is paused.
    """
    payload = {
        "version": STATE_VERSION,
        **{
            book: {
                rule_id: at.isoformat()
                for rule_id, at in _timestamps(state.get(book)).items()
            }
            for book in ("handled", "fired", "seen_since")
        },
        "pause_generation": _pause_generation(state.get("pause_generation")),
    }
    path = Path(automation_state_path())
    # One temporary name is safe here, unlike the journal's: this file is only ever
    # written with the execution lock held, so there is never a second writer.
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # Never raised: for the books above, the worst case is a later task
        # repeating a run. The caller decides whether it can live with that.
        return False
    return True


def _pause_generation(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _timestamps(raw: Any) -> dict[str, datetime]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, datetime] = {}
    for rule_id, value in raw.items():
        if isinstance(value, datetime):
            parsed[str(rule_id)] = value
            continue
        try:
            parsed[str(rule_id)] = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            continue  # one unreadable entry costs a repeated run, not the file
    return parsed


# ── the pause both sides honour ───────────────────────────────────────
# The intent lives in its own small file with its own lock, and says one thing: the
# moment the pause ends. In the future, automations are held off; in the past, the
# pause is over and what it covered is no longer owed. A resume is simply that
# moment moved to now.
#
# The generation beside it is what makes "already tidied up" answerable: the run
# path records the generation it settled, so an intent is consumed exactly once and
# a stale copy cannot bring an old pause back.
def load_control() -> dict[str, Any]:
    """What the user has asked for. A damaged file reads as "nothing asked"."""
    empty: dict[str, Any] = {"version": CONTROL_VERSION, "generation": 0, "paused_until": None}
    try:
        raw = json.loads(automation_control_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    try:
        generation = int(raw.get("generation", 0))
    except (TypeError, ValueError):
        return empty
    return {
        "version": CONTROL_VERSION,
        "generation": max(0, generation),
        "paused_until": _timestamp(raw.get("paused_until")),
    }


def _save_control(control: dict[str, Any]) -> bool:
    paused_until = _timestamp(control.get("paused_until"))
    payload = {
        "version": CONTROL_VERSION,
        "generation": int(control.get("generation", 0)),
        "paused_until": paused_until.isoformat() if paused_until else None,
    }
    path = Path(automation_control_path())
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return False
    return True


def _write_intent(ends_at: datetime, *, timeout: float) -> bool:
    with file_lock(control_lock_path(), timeout=timeout) as locked:
        if not locked:
            return False
        return _save_control({"generation": _next_generation(), "paused_until": ends_at})


def _next_generation() -> int:
    """One past the highest number either file has seen.

    Not simply the control file's own: if that file is lost or damaged its
    generation reads as zero, and a fresh intent numbered below the receipt already
    in the state would look like one that had been dealt with — so the end of that
    pause would never be tidied up. Called with the control lock held.
    """
    control = int(load_control().get("generation", 0) or 0)
    receipt = int(load_state().get("pause_generation", 0) or 0)
    return max(control, receipt) + 1


def pause_automations(now: datetime, seconds: int, *, timeout: float = PAUSE_TIMEOUT_SECONDS) -> bool:
    """Hold automations off everywhere, not just in the process that was asked.

    The app is where a user pauses, but a Windows task starts its own process and
    would know nothing about it — so the moment it runs until is written where both
    can see it, behind a lock that is never held by a run in progress.

    True only when that write actually landed. Saying otherwise would leave a task
    free to switch the light while the user believes automations are held off.
    """
    return _write_intent(now + timedelta(seconds=max(1, int(seconds))), timeout=timeout)


def resume_automations(now: datetime, *, timeout: float = PAUSE_TIMEOUT_SECONDS) -> bool:
    """End the pause now, if one is running. What it covered is let go of after.

    Only an *active* pause is ended. Writing an intent regardless would create a
    pause that began and ended in the same instant — and the run path, seeing an
    ending it had not dealt with, would let go of everything owed up to that moment.
    A resume with nothing to resume would silently swallow a rule that had been
    waiting to run, which is the opposite of what the word means.
    """
    with file_lock(control_lock_path(), timeout=timeout) as locked:
        if not locked:
            return False
        ends_at = _timestamp(load_control().get("paused_until"))
        if ends_at is None or ends_at <= now:
            return True  # nothing is holding automations off; nothing to say
        return _save_control({"generation": _next_generation(), "paused_until": now})


def paused_until(control: dict[str, Any] | None = None) -> datetime | None:
    """The moment the pause ends, whether or not that moment has passed.

    Deliberately not "None once it has expired": the caller has the clock it cares
    about — the runtime's is injectable for tests — and an ended pause still has a
    moment worth showing.
    """
    control = control if control is not None else load_control()
    return _timestamp(control.get("paused_until"))


def settle_pause(
    state: dict[str, Any], rules: Iterable[Rule], now: datetime
) -> tuple[dict[str, Any], bool]:
    """Answer "are we paused", and tidy up once the pause is over.

    Returns the state and whether automations are still held off. Called with the
    execution lock held, by whichever side got there first — the tidying writes to
    the state, so it belongs to whoever is about to run something.
    """
    control = load_control()
    ends_at = _timestamp(control.get("paused_until"))
    if ends_at is None:
        return state, False
    if now < ends_at:
        return state, True
    if int(state.get("pause_generation", 0) or 0) >= int(control.get("generation", 0)):
        return state, False  # this one has already been tidied up
    settled, _written = _consume_pause(state, rules, control)
    return settled, False


def _consume_pause(
    state: dict[str, Any], rules: Iterable[Rule], control: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Let go of what the pause covered, and record that it has been dealt with.

    A pause is the user taking over. Coming back to a light that switches itself
    twenty minutes later because an occurrence was waiting out the pause is not
    "automations resumed", it is a surprise — so what came due while they were held
    off is marked handled rather than run.

    Only what the pause actually covered. Dueness is reckoned as of the moment the
    pause *ended*, not the moment somebody got round to noticing: with the app shut
    for a day, "everything due now" would swallow an occurrence that came round long
    after the pause was over, and that one is still owed.
    """
    ended = _timestamp(control.get("paused_until")) or datetime.now()
    covered, _cooling = due_rules(rules, state, ended)
    state["pause_generation"] = int(control.get("generation", 0))
    if covered:
        state["handled"] = dict(state.get("handled", {})) | {
            rule.id: occurred for rule, occurred in covered
        }
    return state, save_state(state)


def control_lock_path() -> Path:
    """The control file's own lock. Only ever held for one small write."""
    path = Path(automation_control_path())
    return path.with_suffix(f"{path.suffix}.lock")


def execution_lock_path() -> Path:
    """The machine-wide execution lock, beside the state it protects."""
    path = Path(automation_state_path())
    return path.with_suffix(f"{path.suffix}.lock")


class _RuleRunner(QObject):
    """Connects, runs one rule's action, and reports what actually happened."""

    def __init__(
        self,
        rule: Rule,
        address: str,
        settings: dict[str, Any],
        journal: AutomationJournal,
        *,
        occurred_at: datetime | None = None,
        context: dict[str, Any] | None = None,
        timeout_ms: int = RUN_TIMEOUT_MS,
    ) -> None:
        super().__init__()
        self._rule = rule
        self._address = address
        self._settings = settings
        self._journal = journal
        self._context = dict(context or _BACKGROUND_CONTEXT)
        self._timeout_ms = int(timeout_ms)
        self._ble = BleController()
        now = datetime.now()
        # Synthesised rather than resolved: the winner has already been chosen.
        # ``occurred_at`` is when it was *due*, which after a night asleep is not
        # now — and "should have run at 23:00, ran at 08:10" is the line the journal
        # needs, which one timestamp cannot say.
        self._decision = Decision(
            rule=rule,
            action=rule.action,
            occurred_at=occurred_at or now,
            decided_at=now,
            token=1,
        )
        self._executor = BleActionExecutor(
            self._ble,
            scene_for=lambda scene_id: scene_store.get_scene(self._settings, scene_id),
            resolve_targets=self._resolve_targets,
            parent=self,
        )
        self._handle: Any = None
        self._dispatched = False
        self._finished = False
        # Nothing has been confirmed yet, so the pessimistic code is the honest
        # default: every path that ends well sets it explicitly.
        self.exit_code = EXIT_FAILED
        self._ble.connected_changed.connect(self._on_connected_changed)
        self._ble.error_occurred.connect(self._on_error)
        self._ble.status_changed.connect(self._on_status)

    def start(self) -> None:
        print(f"LumaBLE automation: {self._rule.id} -> {self._address}")
        QTimer.singleShot(self._timeout_ms, self._on_timeout)
        self._ble.connect_to_address(self._address)

    # ── the run ───────────────────────────────────────────────────────
    def _on_connected_changed(self, connected: bool, _address: str) -> None:
        if self._finished or not connected or self._dispatched:
            return  # a reconnect mid-run must not send the action a second time
        self._dispatched = True
        self._handle = self._executor.execute(self._decision, self._on_result)

    def _resolve_targets(self, target: Any) -> list[str] | None:
        """This process holds exactly one connection: the main strip.

        A scene's target still goes through the same resolver the app uses, so one
        aimed at strips this process never connected to resolves to nothing and is
        reported as unavailable — rather than quietly landing on the primary.
        (Today only ``set_power`` may run in the background, so this is here to be
        correct if that ever widens, not as a feature.)
        """
        primary = str(self._ble.primary_address() or "").strip()
        connected = [primary] if primary else []
        resolved = scene_store.resolve_target(
            self._settings, target, primary=primary or None, all_addresses=connected
        )
        return [address for address in resolved if address in set(connected)]

    def _on_result(self, result: Any) -> None:
        if self._finished:
            return
        context = decision_context(self._decision) | steps_context(result) | dict(self._context)
        now = datetime.now()
        if result.ok:
            self._journal.record_success(
                self._rule.id,
                message_code=result.code or success_code_for(self._decision),
                now=now,
                occurred_at=self._decision.occurred_at,
                decided_at=self._decision.decided_at,
                context=context,
            )
            self._remember_power()
            print(f"LumaBLE automation: {self._rule.id} done.")
            self._finish(EXIT_OK)
            return
        self._journal.record_error(
            self._rule.id,
            message_code=failure_code_for(result),
            now=now,
            occurred_at=self._decision.occurred_at,
            decided_at=self._decision.decided_at,
            context=context,
        )
        print(f"LumaBLE automation failed: {failure_code_for(result)}", file=sys.stderr)
        self._finish(EXIT_FAILED)

    def _remember_power(self) -> None:
        """Keep the app's idea of the light in step with what just happened.

        Reconnecting restores the *desired* power state, so without this the next
        launch would undo the background run.

        A targeted update rather than a saved snapshot: this process has been alive
        for the length of a BLE connection, and writing back the settings it read at
        the start would erase whatever the open app changed in the meantime.
        """
        if self._rule.action.type != ACTION_SET_POWER:
            return
        update_power_setting(bool(self._rule.action.power))

    # ── things going wrong ────────────────────────────────────────────
    def _on_error(self, message: str) -> None:
        if self._finished or self._dispatched:
            # Once the command is out, its own tracked result is the verdict. A BLE
            # complaint arriving alongside it must not report a failure for a write
            # that landed.
            return
        print(f"LumaBLE automation error: {message}", file=sys.stderr)
        self._journal.record_error(
            self._rule.id,
            message_code=CODE_CONNECT_FAILED,
            now=datetime.now(),
            occurred_at=self._decision.occurred_at,
            decided_at=self._decision.decided_at,
            context=decision_context(self._decision) | dict(self._context),
        )
        self._finish(EXIT_FAILED)

    def _on_status(self, message: str) -> None:
        if message:
            print(message)

    def _on_timeout(self) -> None:
        if self._finished:
            return
        context = decision_context(self._decision) | dict(self._context)
        if self._dispatched:
            # The write went out and never reported. Whether it reached the strip is
            # genuinely unknown, so the journal says "possibly" instead of picking
            # the comfortable story.
            context |= {"partial_possible": True}
        self._journal.record_error(
            self._rule.id,
            message_code=CODE_TIMEOUT,
            now=datetime.now(),
            occurred_at=self._decision.occurred_at,
            decided_at=self._decision.decided_at,
            context=context,
        )
        print("LumaBLE automation timed out.", file=sys.stderr)
        self._finish(EXIT_FAILED)

    def _finish(self, exit_code: int) -> None:
        if self._finished:
            return
        self._finished = True
        self.exit_code = exit_code
        if self._handle is not None:
            # Best effort, and never a rollback: it only stops a late result from
            # being counted and keeps the next command from starting.
            self._handle.cancel()
        # Written before the connection is torn down: a shutdown that hangs must not
        # cost the user the record of what happened.
        self._journal.flush(monotonic(), force=True)
        try:
            self._ble.shutdown()
        finally:
            QCoreApplication.quit()
