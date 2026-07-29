"""Background rules, compiled into Windows tasks.

A rule the user marked for background execution has to fire while LumaBLE is
closed, and on Windows that means a scheduled task. This module turns the rule
list into those tasks and keeps the machine in step with it.

**The task is a wake-up, nothing more.** Every one of them runs the same command —
``LumaBLE.exe --run-automations`` — with no rule id in it. Which rule gets carried
out is decided by the process that starts, against the rules and the clock as they
are *then*. A task that named its rule would be a second, stale copy of the
schedule: it would keep firing a rule the user has since edited, and after a sleep
several such tasks would each apply their own instead of one winner. All a task
carries is *when* to wake up; the rule it stands for lives only in its name.

That also means a task drifting out of step is a mistimed wake-up, never a wrong
action — the process still checks what is actually due. It is why the record below
can be trusted for "has this changed", instead of parsing schedules back out of
Windows.

**Tasks are registered from XML, not from ``schtasks`` switches**, because the
defaults of the plain command line quietly undo the point of the whole thing. A
task created that way does not start when its time was missed
(``StartWhenAvailable`` defaults to false), and on a laptop it does not start at
all while on battery (``DisallowStartIfOnBatteries`` defaults to true). Both are
exactly the situations a background schedule exists for: the machine was asleep at
23:00, or it is a laptop that is rarely plugged in. So the definition states them,
and its shape is versioned into the signature — changing a setting here rewrites
every task that already exists.

What gets compiled is deliberately narrow: a time trigger, a power action on the
main strip, background execution, at least one weekday. Everything else is a
runtime rule, and the app has to be open for it.

The old ``LumaBLE Schedule On``/``Off`` pair is left strictly alone. It is the
rollback bridge for 0.3.5, and everything here is scoped to its own task-name
prefix so no reconciliation can reach it. Rules migrated from that old schedule
must not be compiled here either until the handover is designed — this module
compiles the rules it is handed, and the migration decides when to hand them over.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from xml.sax.saxutils import escape

from app.app_info import APP_NAME
from app.automation.file_lock import file_lock
from app.automation.headless import seed_seen_since
from app.automation.rules import ACTION_SET_POWER, TARGET_PRIMARY, TRIGGER_TIME, Rule
from app.storage import APP_DIR, automation_tasks_path

# Every task this module owns starts with this. Reconciliation only ever looks at,
# and only ever deletes, names beginning with it — which is what keeps the 0.3.5
# schedule pair, and anything else on the machine, out of reach.
TASK_PREFIX = f"{APP_NAME} Automation "

RECORD_VERSION = 1
RECORD_LOCK_TIMEOUT_SECONDS = 5.0

# The shape of the task definition below. Part of every signature, so that changing
# anything about how a task is described — a setting, the trigger, the action —
# rewrites the tasks already on the machine instead of applying only to new ones.
DEFINITION_VERSION = 1

_DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}
# A calendar trigger needs a date to start from as well as a time. Fixed and in the
# past, so the definition depends only on the rule: a boundary of "today" would make
# the same rule produce different XML every day.
_START_DATE = "2020-01-01"
# Rule ids are already restricted at the schema, but this module is what hands a
# string to Windows, so it does not take that on trust.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class TaskCommand:
    """What a task runs, split the way the definition needs it."""

    executable: str
    arguments: str = ""

    def as_text(self) -> str:
        return f"{self.executable} {self.arguments}".strip()


@dataclass(frozen=True)
class TaskPlan:
    """One rule, as the task it should become."""

    rule_id: str
    name: str
    time_text: str
    days: tuple[int, ...]
    command: TaskCommand

    @property
    def signature(self) -> str:
        """What has to change for the task to need rewriting.

        The command is part of it: after an update installs LumaBLE somewhere else,
        every task still points at the old path and has to be re-pointed. So is the
        definition version — see :data:`DEFINITION_VERSION`.
        """
        days = ",".join(str(day) for day in self.days)
        return (
            f"v{DEFINITION_VERSION}|{self.time_text}|{days}|"
            f"{self.command.executable}|{self.command.arguments}"
        )

    @property
    def definition(self) -> str:
        return build_task_xml(self)


@dataclass(frozen=True)
class TaskSyncResult:
    """What a synchronisation did, in terms the caller can show or log.

    ``created``/``updated``/``unchanged`` are rule ids; ``removed`` are task names,
    since a task without a rule is all that is left of one. ``errors`` pair the
    subject — a rule id, or a task name — with what Windows said.
    """

    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    errors: tuple[tuple[str, str], ...] = ()
    # False when this machine has no task scheduler to talk to, or it is switched
    # off for this process. Nothing was looked at and nothing was changed.
    available: bool = True
    # Set when tasks that no longer belong were left in place on purpose: see the
    # ordering rule in sync_tasks.
    deferred_removals: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.removed)


class TaskScheduler(Protocol):
    """The one way this module is allowed to touch Windows.

    Injectable so that everything above it can be tested without a machine-wide
    side effect: a test passes a fake and no real task is ever created.
    """

    def list_names(self, prefix: str) -> list[str]:
        """Existing task names starting with ``prefix``. Raises OSError if it cannot
        be determined — which must stop reconciliation rather than be read as "there
        are none", or the next step would delete every task as an orphan."""

    def create(self, name: str, *, definition: str) -> None:
        """Create or replace one task from its XML definition. Raises OSError."""

    def delete(self, name: str) -> None:
        """Delete one task. A task that is already gone is not a failure."""


# ── what a rule compiles to ───────────────────────────────────────────
def compilable(rule: Rule) -> bool:
    """Whether this rule is one Windows can be asked to wake us for.

    Narrow on purpose. The schema already refuses background execution to anything
    but a timed power action, and this repeats the check rather than trusting it:
    the consequence of getting it wrong is a task that fires for a rule the headless
    path will not run.
    """
    return bool(
        rule.enabled
        and rule.runs_in_background
        and rule.trigger.kind == TRIGGER_TIME
        and rule.trigger.time_at
        # No weekday means the rule can never come round, so there is nothing to
        # wake up for. Same answer as a disabled rule: no task.
        and rule.trigger.days
        and rule.action.type == ACTION_SET_POWER
        and rule.action.target == TARGET_PRIMARY
    )


def task_name_for(rule_id: str) -> str:
    """The stable task name for a rule.

    Stable across edits: the time and the days are *inside* the task, so changing
    them rewrites this task instead of leaving the old one behind next to a new one.

    The digest is not decoration. Windows task names are case-insensitive while rule
    ids are not, so "evening" and "Evening" would otherwise be one task — and one of
    those two rules would silently never be woken for.
    """
    rule_id = str(rule_id)
    safe = _UNSAFE.sub("_", rule_id)[:64] or "rule"
    digest = hashlib.sha1(rule_id.encode("utf-8")).hexdigest()[:8]
    return f"{TASK_PREFIX}{safe}-{digest}"


def automation_command() -> TaskCommand:
    """The command every task runs: wake up and let the process decide."""
    if getattr(sys, "frozen", False):
        return TaskCommand(sys.executable, "--run-automations")
    main_path = Path(APP_DIR) / "main.py"
    return TaskCommand(sys.executable, f'"{main_path}" --run-automations')


def build_task_xml(plan: TaskPlan) -> str:
    """The task definition Windows is registered from.

    Everything in ``<Settings>`` is stated rather than left to the defaults, and
    four of them are the reason this module does not use plain ``schtasks``
    switches at all:

    * ``StartWhenAvailable`` — run a start that was missed. Windows defaults this
      to false, which would mean an evening rule slept through is simply never run,
      and the whole catch-up path behind ``--run-automations`` never gets a chance.
    * ``DisallowStartIfOnBatteries`` and ``StopIfGoingOnBatteries`` — a laptop on
      battery would otherwise skip the task, or have it killed part way through a
      BLE write, which is precisely when someone is most likely to be using it.
    * ``MultipleInstancesPolicy`` — one wake-up at a time for this task. (It says
      nothing about two *different* tasks coming due together; that is what the
      execution lock in the headless path is for.)

    ``WakeToRun`` is deliberately false: bringing a sleeping machine up to switch a
    lamp is not something the user asked for. ``StartWhenAvailable`` covers the case
    that matters — running it once they wake it themselves.
    """
    chosen = sorted({int(day) for day in plan.days if int(day) in _DAY_NAMES})
    if len(chosen) >= 7:
        schedule = "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    else:
        days = "".join(f"<{_DAY_NAMES[day]} />" for day in chosen)
        schedule = (
            f"<ScheduleByWeek><DaysOfWeek>{days}</DaysOfWeek>"
            "<WeeksInterval>1</WeeksInterval></ScheduleByWeek>"
        )
    return _TASK_XML.format(
        description=escape(f"{APP_NAME} automation wake-up for rule {plan.rule_id}"),
        start_boundary=f"{_START_DATE}T{plan.time_text}:00",
        schedule=schedule,
        executable=escape(plan.command.executable),
        arguments=escape(plan.command.arguments),
    )


# Element order follows what Task Scheduler itself exports, so a definition written
# here reads the same as one the user might export from the Windows UI.
_TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
      {schedule}
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{executable}</Command>
      <Arguments>{arguments}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def plan_tasks(rules: Iterable[Rule], *, command: TaskCommand | None = None) -> list[TaskPlan]:
    """The tasks a rule list should amount to, in rule order."""
    command = command if command is not None else automation_command()
    plans: list[TaskPlan] = []
    for rule in rules:
        if not compilable(rule):
            continue
        plans.append(
            TaskPlan(
                rule_id=rule.id,
                name=task_name_for(rule.id),
                time_text=rule.trigger.time_at,
                days=tuple(sorted(set(rule.trigger.days))),
                command=command,
            )
        )
    return plans


# ── keeping the machine in step ───────────────────────────────────────
def sync_tasks(
    rules: Iterable[Rule],
    *,
    scheduler: TaskScheduler | None = None,
    command: TaskCommand | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> TaskSyncResult:
    """Make the machine's tasks match the rules. Safe to call at any time.

    Idempotent: a second call with the same rules finds every task already right and
    touches nothing. Pass ``force`` to rewrite them all anyway, which is how a task
    someone edited by hand in Windows gets put back.

    The whole reconciliation happens under one lock — listing, reading the record,
    writing tasks, deleting tasks, saving the record. Two of these running at once
    would each decide against a list the other was in the middle of changing, and
    then overwrite each other's record. Without the lock nothing is touched at all:
    a synchronisation that cannot be serialised is one that must not happen.
    """
    scheduler = default_scheduler() if scheduler is None else scheduler
    if scheduler is None:
        # No Windows, or switched off for this process. Nothing was read, so nothing
        # may be concluded about what is on the machine.
        return TaskSyncResult(available=False)

    # Only ever this lock, then the automation state's inside it (see
    # seed_seen_since). Nothing takes them the other way round, so there is no order
    # for two processes to disagree on.
    with file_lock(_record_lock_path(), timeout=RECORD_LOCK_TIMEOUT_SECONDS) as locked:
        if not locked:
            return TaskSyncResult(
                errors=((TASK_PREFIX, "another synchronisation is already in progress"),)
            )
        return _reconcile(plan_tasks(rules, command=command), scheduler, now=now, force=force)


def _reconcile(
    plans: list[TaskPlan],
    scheduler: TaskScheduler,
    *,
    now: datetime | None,
    force: bool,
) -> TaskSyncResult:
    """The reconciliation itself. Runs with the record lock held, never without.

    The order is fixed and matters. Everything that should exist is proved first,
    and only then is anything taken away — and if a single create failed, the taking
    away is skipped entirely this round. An orphan task left behind is one wasted
    wake-up that finds nothing due; a working task deleted because its replacement
    could not be written is a schedule that silently stops.
    """
    try:
        existing = set(scheduler.list_names(TASK_PREFIX))
    except OSError as exc:
        # Reconciling against a list we could not read would mean deleting tasks
        # because we failed to see them.
        return TaskSyncResult(errors=((TASK_PREFIX, str(exc)),))

    record = load_record()
    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    errors: list[tuple[str, str]] = []

    # Before Windows can wake us for any of these, they have to be rules we are
    # watching — otherwise the first occurrence to be missed is discarded as having
    # happened before our time. A busy lock is a reason not to arm anything new.
    armed = seed_seen_since([plan.rule_id for plan in plans], now=now)

    for plan in plans:
        known = record.get(plan.rule_id) or {}
        on_machine = plan.name in existing
        if on_machine and not force and known.get("signature") == plan.signature:
            unchanged.append(plan.rule_id)
            continue
        if not on_machine and not armed:
            errors.append((plan.rule_id, "automation state is busy; not arming a new task yet"))
            continue
        try:
            scheduler.create(plan.name, definition=plan.definition)
        except OSError as exc:
            # The previous task, if there was one, is still in place: schtasks
            # replaces a task or leaves it alone, and this module never deletes one
            # before its replacement exists.
            errors.append((plan.rule_id, str(exc)))
            continue
        record[plan.rule_id] = {"name": plan.name, "signature": plan.signature}
        (updated if on_machine else created).append(plan.rule_id)

    wanted = {plan.name for plan in plans}
    wanted_ids = {plan.rule_id for plan in plans}
    stale = sorted(name for name in existing if name not in wanted)
    removed: list[str] = []
    deferred: list[str] = []
    if errors:
        # Prove the new configuration first. With a create still failing, a name
        # that looks stale may be the only working task the user has left.
        deferred = stale
    else:
        for name in stale:
            try:
                scheduler.delete(name)
            except OSError as exc:
                errors.append((name, str(exc)))
                continue
            removed.append(name)
        # A clean pass leaves the record mirroring the rules exactly, so a rule that
        # comes back later is treated as new rather than as one we still know about.
        record = {rule_id: entry for rule_id, entry in record.items() if rule_id in wanted_ids}

    _save_record(record)
    return TaskSyncResult(
        created=tuple(created),
        updated=tuple(updated),
        removed=tuple(removed),
        unchanged=tuple(unchanged),
        errors=tuple(errors),
        deferred_removals=tuple(deferred),
    )


def remove_all_tasks(*, scheduler: TaskScheduler | None = None) -> TaskSyncResult:
    """Take every task this module owns off the machine.

    For switching automations off wholesale. Scoped by the same prefix, so the 0.3.5
    schedule pair is not among them.
    """
    return sync_tasks((), scheduler=scheduler)


# ── the record of what we last compiled ───────────────────────────────
def load_record() -> dict[str, dict[str, str]]:
    """What the last synchronisation put on the machine, by rule id.

    A missing or damaged file is not an error: it means the next synchronisation
    rewrites every task instead of skipping the ones it thought were current.
    """
    try:
        raw = json.loads(automation_tasks_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tasks = raw.get("tasks") if isinstance(raw, dict) else None
    if not isinstance(tasks, dict):
        return {}
    record: dict[str, dict[str, str]] = {}
    for rule_id, entry in tasks.items():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if name:
            record[str(rule_id)] = {"name": name, "signature": str(entry.get("signature", ""))}
    return record


def _save_record(record: dict[str, dict[str, str]]) -> None:
    """Write the record. Private, and only called from inside the reconcile lock.

    There is deliberately no public writer: a caller that could save the record on
    its own could also save one it had read before someone else changed the tasks.
    """
    path = Path(automation_tasks_path())
    payload = {"version": RECORD_VERSION, "tasks": record}
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # Losing the record costs one round of rewriting every task, which the next
        # synchronisation does by itself. Never worth raising for.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - nothing more we can do
            pass


def _record_lock_path() -> Path:
    path = Path(automation_tasks_path())
    return path.with_suffix(f"{path.suffix}.lock")


# ── the real Windows adapter ──────────────────────────────────────────
def is_supported() -> bool:
    return os.name == "nt"


def schtasks_disabled() -> bool:
    """The escape hatch the test suite and packaging use to stay off the machine."""
    return os.environ.get("LUMABLE_DISABLE_SCHTASKS", "").strip().lower() in {"1", "true", "yes"}


def default_scheduler() -> TaskScheduler | None:
    """The real scheduler, or None when this process must not touch tasks."""
    if not is_supported() or schtasks_disabled():
        return None
    return SchtasksScheduler()


class SchtasksScheduler:
    """Talks to ``schtasks.exe``. The only place in the package that runs a process."""

    def list_names(self, prefix: str) -> list[str]:
        completed = self._run(["/Query", "/FO", "CSV", "/NH"])
        if completed.returncode != 0:
            raise OSError(self._message(completed) or "schtasks could not list tasks")
        names: list[str] = []
        for row in csv.reader(io.StringIO(completed.stdout or "")):
            if not row:
                continue
            # Task Scheduler reports names with their folder, and ours live at the
            # root: "\LumaBLE Automation evening-3f2a1b9c".
            name = row[0].strip().lstrip("\\")
            if name.startswith(prefix):
                names.append(name)
        return names

    def create(self, name: str, *, definition: str) -> None:
        """Register the task from its XML.

        Written out as UTF-16: ``schtasks /XML`` rejects the file otherwise, and the
        declaration at the top of the definition says so too.
        """
        handle, path = tempfile.mkstemp(prefix="lumable-task-", suffix=".xml")
        os.close(handle)
        definition_path = Path(path)
        try:
            definition_path.write_text(definition, encoding="utf-16")
            completed = self._run(["/Create", "/F", "/TN", name, "/XML", str(definition_path)])
        finally:
            try:
                definition_path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - a temp file we no longer need
                pass
        if completed.returncode != 0:
            raise OSError(self._message(completed) or f"schtasks could not create {name}")

    def delete(self, name: str) -> None:
        completed = self._run(["/Delete", "/F", "/TN", name])
        if completed.returncode == 0:
            return
        message = self._message(completed)
        if self._missing(message):
            return  # already gone is the state we wanted
        raise OSError(message or f"schtasks could not delete {name}")

    @staticmethod
    def _run(args: list[str]) -> Any:
        return subprocess.run(
            ["schtasks", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )

    @staticmethod
    def _message(completed: Any) -> str:
        return ((completed.stderr or "") or (completed.stdout or "")).strip()

    @staticmethod
    def _missing(message: str) -> bool:
        lowered = message.lower()
        return "cannot find" in lowered or "не удается найти" in lowered
