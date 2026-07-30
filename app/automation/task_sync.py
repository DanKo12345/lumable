"""Keeping the machine's tasks in step with the rules, off the UI thread.

``schtasks`` is a process per call, and a reconciliation runs several of them. On
the UI thread that is a visible stall at exactly the moment the window is trying to
appear, so the work goes to a short-lived thread — the same shape as the license
refresher.

The rules are read on the *calling* thread and handed over as an immutable list.
The settings dict belongs to the window, and a background thread must not be
reading it while the user changes something.

Two distinctions this module exists to keep straight:

* **No rules is not the same as no answer.** An empty list is an instruction — take
  every task off the machine, which is what switching automations off must do. So a
  settings read that *failed* may never turn into one: it stops the whole
  reconciliation instead, and nothing is created or deleted.
* **A refusal has to be visible.** Windows can decline to write a task, and a
  background schedule that silently never got set up is worse than one that failed
  loudly. Errors go to the automation journal, where the rest of "what automation
  did and why it didn't" already lives, and the last result stays on the controller
  for the automations screen to show.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, Signal

from app.automation.journal import AutomationJournal
from app.automation.rules import ORIGIN_LEGACY_SCHEDULE, Rule, validate_rules
from app.automation.windows_tasks import TaskSyncResult, sync_tasks
from app.storage import automation_journal_path, validate_automations

# Journal message codes. Stable identifiers, never localised text.
CODE_TASK_SYNC_FAILED = "task_sync_failed"
CODE_SETTINGS_UNREADABLE = "automation_settings_unreadable"


class AutomationTaskSync(QObject):
    """Runs :func:`sync_tasks` in the background and reports what it did.

    ``finished`` carries a :class:`TaskSyncResult`, and the same result stays
    readable afterwards as :attr:`last_result`, so a screen opened later can show
    the state of things without provoking another reconciliation.
    """

    finished = Signal(object)

    def __init__(
        self, settings_provider: Callable[[], dict[str, Any]], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._settings_provider = settings_provider
        self._running = False
        # Something changed while a reconciliation was out. Answered when it returns.
        self._again = False
        self._last_result: TaskSyncResult | None = None
        # Queued back onto this object's thread: the run reports from a worker, and
        # the rules must be read where they are owned, not from that thread.
        self.finished.connect(self._sync_again_if_asked)

    @property
    def last_result(self) -> TaskSyncResult | None:
        """What the last reconciliation did, or None if none has finished yet."""
        return self._last_result

    def sync(self) -> None:
        """Reconcile once, and once more if anything changed while it was running.

        Dropping the second request is how Windows ends up holding yesterday's task:
        create a rule, and while that reconciliation is out at ``schtasks``, change
        its time — the change would find the door shut and wait for the next launch
        of the app. So a request that arrives mid-run is remembered and answered
        afterwards, from a fresh reading of the rules rather than the one being
        worked on now.
        """
        if self._running:
            self._again = True
            return
        rules = self._rules()
        self._again = False
        if rules is None:
            # The settings could not be read. Handing on an empty list here would
            # read as "the user has no rules" and take every task off the machine,
            # so nothing is touched at all — not even looked at.
            self._report(
                TaskSyncResult(errors=(("", "the automation settings could not be read"),)),
                fallback_code=CODE_SETTINGS_UNREADABLE,
            )
            return
        self._running = True
        thread = threading.Thread(target=self._run, args=(rules,), daemon=True)
        thread.start()

    def _sync_again_if_asked(self, _result: Any) -> None:
        if not self._again:
            return
        self._again = False
        self.sync()

    def _rules(self) -> list[Rule] | None:
        """The background rules to compile, or None when settings cannot be read.

        The empty list is a real answer — automations are off, so every task should
        go. None is the absence of an answer, and the two must never be confused.
        """
        try:
            settings = self._settings_provider() or {}
            automations = validate_automations(settings.get("automations", {}))
        except Exception:
            return None
        if not automations.get("enabled"):
            # Automations switched off wholesale: no rule may keep a task, and the
            # empty list is what makes the reconciliation take them all away.
            return []
        try:
            rules = validate_rules(automations.get("rules", []))
        except Exception:  # pragma: no cover - validate_rules is documented not to raise
            return None
        if automations.get("legacy_bridge"):
            # The 0.3.5 task pair is still the thing that wakes the machine for these
            # rules. Giving them native tasks as well would put two schedulers on one
            # schedule; they get theirs when the handoff retires the old pair.
            rules = [rule for rule in rules if rule.origin != ORIGIN_LEGACY_SCHEDULE]
        return rules

    def _run(self, rules: list[Rule]) -> None:
        try:
            result = sync_tasks(rules)
        except Exception as exc:  # pragma: no cover - sync_tasks reports, never raises
            result = TaskSyncResult(errors=(("", str(exc)),))
        finally:
            self._running = False
        self._report(result)

    def _report(self, result: TaskSyncResult, *, fallback_code: str = "") -> None:
        self._last_result = result
        self._record_errors(result, fallback_code=fallback_code)
        try:
            self.finished.emit(result)
        except RuntimeError:
            # The window can be closed while the reconciliation is still running.
            pass

    @staticmethod
    def _record_errors(result: TaskSyncResult, *, fallback_code: str = "") -> None:
        """Put a refusal where the user can find it.

        The journal is the record of what automation did and did not do, and a rule
        whose task was never written is exactly that. The code stays stable and
        Windows' own wording goes in the context: it is localised and version
        specific, so it can be shown as detail but never matched on.
        """
        if not result.errors:
            return
        journal = AutomationJournal(automation_journal_path())
        journal.load()
        now = datetime.now()
        for subject, message in result.errors:
            journal.record_error(
                str(subject),
                message_code=fallback_code or CODE_TASK_SYNC_FAILED,
                now=now,
                context={"task_sync": True, "detail": str(message)},
            )
        journal.flush(monotonic(), force=True)
