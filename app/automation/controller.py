"""Everything the interface is allowed to know about automations.

One object, deliberately. Behind it are the engine, the headless path, the Windows
task compiler, the migration and the journal — five things with their own locks,
their own files and their own reasons to be careful, none of which a screen should
have to hold in its head. A panel that reached past this would end up making
decisions the rest of the system has already made: which rules exist, whether a
pause reached the machine, when it is safe to retire the 0.3.5 bridge.

Three things this facade is responsible for, beyond passing calls along:

* **Editing rules is a transaction, not an assignment.** Every change goes through
  the locked read-modify-write in storage and is then taken into the window's own
  settings, because the engine reads that copy on its next tick and the window
  writes it back on close. Saving to one and not the other is how a rule comes back
  from the dead.
* **The applied state is only ever a confirmed one.** ``applied`` carries what the
  main strip shows after a rule completed every step; a partial or failed run says
  nothing at all, because the strip is then in a state nobody can describe.
* **Nothing here touches the strip.** Reflecting the applied state in the window is
  a matter of moving controls with their signals blocked — sending the same colour
  back to the light would be a second write nobody asked for.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from app.automation.journal import AutomationJournal, JournalEntry
from app.automation.migration import (
    MIGRATED_KEYS,
    HandoffResult,
    complete_legacy_handoff,
    finish_pending_cleanup,
    migrate,
)
from app.automation.resolver import DEFAULT_PAUSE_SECONDS
from app.automation.rules import (
    ACTION_APPLY_SCENE,
    ACTION_SET_POWER,
    ALL_DAYS,
    TRIGGER_ALWAYS,
    TRIGGER_APP_FOREGROUND,
    TRIGGER_LUMABLE_START,
    TRIGGER_NO_INPUT,
    TRIGGER_STRIP_CONNECTED,
    TRIGGER_TIME,
    Rule,
    rule_to_dict,
    validate_rule,
    validate_rules,
)
from app.automation.runtime import (
    PAUSE_ACTIVE,
    PAUSE_ENDING,
    PAUSE_OFF,
    PAUSE_PENDING,
    AppliedState,
    AutomationRuntime,
)
from app.automation.task_sync import AutomationTaskSync
from app.automation.windows_tasks import TaskSyncResult
from app.crash_logging import write_current_exception
from app.storage import (
    automation_journal_path,
    load_settings,
    update_settings,
    validate_automations,
)

# The rule vocabulary is re-exported rather than left to be imported from
# ``app.automation.rules``: a screen has to name a trigger kind to draw one, and
# that is the one thing about the engine's insides the interface legitimately knows.
# Going to the source module for it would put the boundary back where it was.
__all__ = [
    "ACTION_APPLY_SCENE",
    "ACTION_SET_POWER",
    "ALL_DAYS",
    "PAUSE_ACTIVE",
    "PAUSE_ENDING",
    "PAUSE_OFF",
    "PAUSE_PENDING",
    "TRIGGER_ALWAYS",
    "TRIGGER_APP_FOREGROUND",
    "TRIGGER_LUMABLE_START",
    "TRIGGER_NO_INPUT",
    "TRIGGER_STRIP_CONNECTED",
    "TRIGGER_TIME",
    "AppliedState",
    "AutomationController",
    "HandoffResult",
    "JournalEntry",
    "Rule",
    "TaskSyncResult",
]

# Long enough to be worth pressing, short enough that forgetting to lift it does not
# cost the user their evening.
DEFAULT_PAUSE = DEFAULT_PAUSE_SECONDS


class AutomationController(QObject):
    """The automations, as a screen needs them."""

    # The rule list or the master switch changed here. A view redraws from
    # ``rules()``; it is not told what changed, because the list is small and a
    # redraw cannot go stale.
    changed = Signal()
    # An AppliedState, after a rule completed every step.
    applied = Signal(object)
    # A TaskSyncResult, whenever the Windows tasks have been reconciled.
    tasks_synced = Signal(object)
    # The 0.3.5 handoff has begun, and later: a HandoffResult. Two signals rather
    # than one because the work takes seconds of Windows' time, and a button that
    # cannot say "working" for those seconds looks broken.
    handoff_started = Signal()
    handoff_finished = Signal(object)

    def __init__(
        self,
        host: Any,
        backend_provider: Callable[[], Any],
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._backend_provider = backend_provider
        self._runtime: AutomationRuntime | None = None
        self._tasks = AutomationTaskSync(lambda: self._settings(), parent=self)
        self._tasks.finished.connect(self._on_tasks_synced)
        self._last_task_result: TaskSyncResult | None = None
        self._handoff_running = False
        # Queued back onto this object's thread: what follows a handoff belongs to the
        # window, and the handoff itself answers from a worker.
        self.handoff_finished.connect(self._after_handoff)

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        """Migrate if needed, then bring the engine up. Order matters.

        The migration switches the old App Trigger watcher off, so the engine that
        takes over from it is built first — and only started once the migrated rules
        are in the window's own settings, which is what the engine reads.
        """
        try:
            runtime = AutomationRuntime(self._host, self._backend_provider(), parent=self)
        except Exception:
            # No engine, so nothing may be stood down in favour of it.
            write_current_exception(context="automation_runtime")
            return
        runtime.applied.connect(self.applied)

        try:
            report = migrate()
            if report.ok:
                # Even a migration with nothing to migrate records its version, and
                # the window would otherwise save the old one back on close.
                self._adopt_migrated()
            cleanup = finish_pending_cleanup()
            if cleanup.done:
                self._adopt_migrated()
        except Exception:
            write_current_exception(context="automation_migration")

        self._runtime = runtime
        runtime.start()
        self.changed.emit()

    def stop(self) -> None:
        """Stop the engine before the app lets go of the strip."""
        runtime, self._runtime = self._runtime, None
        if runtime is not None:
            runtime.stop()

    def note_connected(self, connected: bool = True) -> None:
        """The main strip connected. Passed along as an edge the engine can use."""
        if self._runtime is not None:
            self._runtime.note_connected(connected)

    def is_running(self) -> bool:
        return self._runtime is not None

    # ── the rules ─────────────────────────────────────────────────────
    def is_enabled(self) -> bool:
        return bool(self._automations().get("enabled"))

    def set_enabled(self, enabled: bool) -> bool:
        return self._write(lambda block: block.update({"enabled": bool(enabled)}))

    def rules(self) -> list[Rule]:
        """Every rule, in the order the user arranged them.

        Order is presentation only — the resolver settles conflicts by priority and
        freshness — but it is the user's arrangement and is kept.
        """
        return validate_rules(self._automations().get("rules", []))

    def rule(self, rule_id: str) -> Rule | None:
        return next((rule for rule in self.rules() if rule.id == rule_id), None)

    def save_rule(self, data: dict[str, Any]) -> Rule | None:
        """Add or replace one rule. None when the schema will not have it.

        Validated here rather than on the way out: a rule that cannot be stored must
        be refused while the user is still looking at it, not silently dropped by
        the next read.
        """
        rule = validate_rule(data)
        if rule is None:
            return None
        stored = rule_to_dict(rule)

        def mutate(block: dict[str, Any]) -> None:
            rules = list(block.get("rules", []))
            for index, existing in enumerate(rules):
                if str(existing.get("id", "")) == rule.id:
                    rules[index] = stored
                    break
            else:
                rules.append(stored)
            block["rules"] = rules

        return rule if self._write(mutate) else None

    def delete_rule(self, rule_id: str) -> bool:
        rule_id = str(rule_id)
        if self.rule(rule_id) is None:
            return False

        def mutate(block: dict[str, Any]) -> None:
            block["rules"] = [
                stored
                for stored in block.get("rules", [])
                if str(stored.get("id", "")) != rule_id
            ]

        return self._write(mutate)

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        rule = self.rule(str(rule_id))
        if rule is None:
            return False
        return self.save_rule(rule_to_dict(rule) | {"enabled": bool(enabled)}) is not None

    # ── the pause ─────────────────────────────────────────────────────
    def pause(self, seconds: int = DEFAULT_PAUSE) -> bool:
        """Hold automations off. False when only *this app* has been told.

        The difference is not cosmetic: until the machine knows, a Windows task can
        still switch the light. See :meth:`pause_status`.
        """
        return bool(self._runtime is not None and self._runtime.pause(seconds))

    def resume(self) -> bool:
        return bool(self._runtime is not None and self._runtime.resume())

    def pause_status(self) -> str:
        """One of off / active / pending / ending — four states, not two."""
        if self._runtime is None:
            return PAUSE_OFF
        return self._runtime.pause_status()

    def paused_until(self) -> datetime | None:
        return self._runtime.paused_until() if self._runtime is not None else None

    # ── the Windows tasks ─────────────────────────────────────────────
    def sync_tasks(self) -> None:
        """Reconcile the tasks in the background. Answers on ``tasks_synced``."""
        self._tasks.sync()

    def last_task_result(self) -> TaskSyncResult | None:
        return self._last_task_result

    # ── the 0.3.5 bridge ──────────────────────────────────────────────
    def bridge_active(self) -> bool:
        """Whether the old schedule tasks are still the ones doing the waking."""
        return bool(self._automations().get("legacy_bridge"))

    def handoff_in_progress(self) -> bool:
        return self._handoff_running

    def complete_handoff(self) -> bool:
        """Ask to retire the 0.3.5 tasks in favour of native ones.

        Returns at once, and answers on ``handoff_finished``; the returned bool only
        says whether this call is the one doing it. Asked again while it is running,
        it declines rather than starting a second one — the work compiles tasks,
        proves them and deletes the old pair, and two of those at once would each be
        deciding against a machine the other is changing.

        It has to be asynchronous because it is several ``schtasks`` processes deep.
        On the thread that draws the window that is a visible freeze, and the button
        this sits behind would look broken at the moment it was working hardest.

        Still the user's decision, never automatic: it switches the old schedule off
        for good, and a rollback to 0.3.5 afterwards finds no schedule running.
        """
        if self._handoff_running:
            return False
        self._handoff_running = True
        self.handoff_started.emit()
        threading.Thread(target=self._run_handoff, daemon=True).start()
        return True

    def _run_handoff(self) -> None:
        """The slow part, off the UI thread. Nothing here touches Qt or the window.

        An interrupted handoff is safe by its own ordering: the flags are committed
        before the old pair is touched, so a window that closed mid-way leaves a
        cleanup the next start finishes.
        """
        try:
            result = complete_legacy_handoff()
        except Exception as exc:  # pragma: no cover - the handoff reports, never raises
            result = HandoffResult(errors=(("handoff", str(exc)),))
        finally:
            self._handoff_running = False
        try:
            self.handoff_finished.emit(result)
        except RuntimeError:
            # The window can be closed while the handoff is still running.
            pass

    def _after_handoff(self, result: Any) -> None:
        """Runs on this object's thread, because the signal above is queued to it.

        Which is what makes it the right place for the parts that belong to the
        window: taking the committed settings into its copy, telling a view to
        redraw, and reconciling the tasks that the retired pair used to stand for.
        """
        if not getattr(result, "done", False):
            return
        self._adopt_migrated()
        self.changed.emit()
        self.sync_tasks()

    # ── the journal ───────────────────────────────────────────────────
    def journal(self, limit: int = 100) -> list[JournalEntry]:
        """The most recent entries, newest first."""
        book = AutomationJournal(automation_journal_path())
        book.load()
        entries = book.entries()
        entries.reverse()
        return entries[: max(0, int(limit))]

    # ── internals ─────────────────────────────────────────────────────
    def _settings(self) -> dict[str, Any]:
        settings = getattr(self._host, "_settings", None)
        return settings if isinstance(settings, dict) else {}

    def _automations(self) -> dict[str, Any]:
        return validate_automations(self._settings().get("automations", {}))

    def _write(self, mutate: Callable[[dict[str, Any]], None]) -> bool:
        """Change the stored automations, then take the result into memory.

        Both halves matter. The file is what a Windows task reads; the window's own
        copy is what the engine ticks against and what closing writes back. Updating
        one and not the other is how an edit undoes itself an hour later.
        """
        try:

            def apply(stored: dict[str, Any]) -> None:
                block = validate_automations(stored.get("automations", {}))
                mutate(block)
                stored["automations"] = validate_automations(block)

            committed = update_settings(apply)
        except Exception:
            return False
        self._settings()["automations"] = committed.get("automations", {})
        self.changed.emit()
        self.sync_tasks()
        return True

    def _adopt_migrated(self) -> None:
        fresh = load_settings()
        settings = self._settings()
        for key in MIGRATED_KEYS:
            if key in fresh:
                settings[key] = fresh[key]

    def _on_tasks_synced(self, result: Any) -> None:
        self._last_task_result = result
        self.tasks_synced.emit(result)


def schedule_first_sync(controller: AutomationController, delay_ms: int = 200) -> None:
    """Reconcile the tasks once, shortly after the engine is up.

    Deferred so a start-up is not spent waiting on several ``schtasks`` processes,
    and separate from :meth:`AutomationController.start` so a caller that has its
    own idea of when to do slow work can leave it out.
    """
    QTimer.singleShot(delay_ms, controller.sync_tasks)
