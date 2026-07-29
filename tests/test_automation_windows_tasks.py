"""Compiling background rules into Windows tasks.

Every test drives an injected scheduler, so the suite never puts a real task on the
machine. What they pin is the part that is easy to get quietly wrong: that editing
a rule rewrites its task instead of leaving a second one behind, that a task is
only ever taken away once its replacement exists, and that nothing here can reach
the 0.3.5 schedule pair.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from app.automation import headless as headless_module
from app.automation import windows_tasks
from app.automation.file_lock import file_lock
from app.automation.rules import validate_rule
from app.automation.windows_tasks import (
    DEFINITION_VERSION,
    TASK_PREFIX,
    SchtasksScheduler,
    TaskCommand,
    TaskPlan,
    build_task_xml,
    default_scheduler,
    load_record,
    plan_tasks,
    sync_tasks,
    task_name_for,
)

TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
COMMAND = TaskCommand("C:/LumaBLE/LumaBLE.exe", "--run-automations")


def _parsed(definition: str):
    return ElementTree.fromstring(definition)


def _setting(definition: str, name: str) -> str:
    found = _parsed(definition).find(f"t:Settings/t:{name}", TASK_NS)
    assert found is not None, f"the definition says nothing about {name}"
    return (found.text or "").strip()


def _time_of(definition: str) -> str:
    boundary = _parsed(definition).find("t:Triggers/t:CalendarTrigger/t:StartBoundary", TASK_NS)
    assert boundary is not None and boundary.text
    return boundary.text.split("T")[1][:5]


def _days_of(definition: str) -> tuple[str, ...]:
    trigger = _parsed(definition).find("t:Triggers/t:CalendarTrigger", TASK_NS)
    assert trigger is not None
    if trigger.find("t:ScheduleByDay", TASK_NS) is not None:
        return ("DAILY",)
    weekdays = trigger.find("t:ScheduleByWeek/t:DaysOfWeek", TASK_NS)
    assert weekdays is not None
    return tuple(child.tag.split("}")[-1] for child in weekdays)


def _command_of(definition: str) -> tuple[str, str]:
    action = _parsed(definition).find("t:Actions/t:Exec", TASK_NS)
    assert action is not None
    command = action.find("t:Command", TASK_NS)
    arguments = action.find("t:Arguments", TASK_NS)
    assert command is not None and arguments is not None
    return (command.text or "", arguments.text or "")

RULE_ID = "evening-off"
NOW = datetime(2026, 7, 27, 22, 0)
# The rollback bridge for 0.3.5. Nothing in this module may look at it or touch it.
LEGACY_TASKS = ("LumaBLE Schedule On", "LumaBLE Schedule Off")


class FakeScheduler:
    """Stands in for schtasks: a dict of tasks and a log of what was asked of it."""

    def __init__(
        self,
        *,
        existing: dict[str, dict[str, Any]] | None = None,
        fail_create: set[str] | None = None,
        fail_delete: set[str] | None = None,
        fail_list: bool = False,
        on_create=None,
    ) -> None:
        self.tasks: dict[str, dict[str, Any]] = dict(existing or {})
        self.fail_create = fail_create or set()
        self.fail_delete = fail_delete or set()
        self.fail_list = fail_list
        self.on_create = on_create
        self.calls: list[tuple[str, str]] = []

    def list_names(self, prefix: str) -> list[str]:
        self.calls.append(("list", prefix))
        if self.fail_list:
            raise OSError("access is denied")
        return [name for name in self.tasks if name.startswith(prefix)]

    def create(self, name: str, *, definition: str) -> None:
        self.calls.append(("create", name))
        if self.on_create is not None:
            self.on_create(name)
        if name in self.fail_create:
            raise OSError("access is denied")
        self.tasks[name] = {"definition": definition}

    def definition(self, name: str) -> str:
        return self.tasks[name]["definition"]

    def delete(self, name: str) -> None:
        self.calls.append(("delete", name))
        if name in self.fail_delete:
            raise OSError("access is denied")
        self.tasks.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self.tasks)

    def kinds(self) -> list[str]:
        return [kind for kind, _name in self.calls]


def _rule(**overrides: Any):
    data: dict[str, Any] = {
        "id": RULE_ID,
        "name": "Evening off",
        "trigger": {"kind": "time", "time_at": "23:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        "action": {"type": "set_power", "power": False, "target": "primary"},
        "execution": "background",
        "enabled": True,
    }
    data.update(overrides)
    rule = validate_rule(data)
    assert rule is not None, "the test rule itself is invalid"
    return rule


def _plan(**overrides: Any) -> TaskPlan:
    fields: dict[str, Any] = {
        "rule_id": RULE_ID,
        "name": task_name_for(RULE_ID),
        "time_text": "23:00",
        "days": (0, 1, 2, 3, 4, 5, 6),
        "command": COMMAND,
    }
    fields.update(overrides)
    return TaskPlan(**fields)


def _sync(rules, scheduler: FakeScheduler, **kwargs):
    return sync_tasks(rules, scheduler=scheduler, command=COMMAND, now=NOW, **kwargs)


# ── what a rule compiles to ───────────────────────────────────────────
def test_a_background_rule_becomes_one_task() -> None:
    scheduler = FakeScheduler()

    result = _sync([_rule()], scheduler)

    assert result.created == (RULE_ID,)
    assert scheduler.names() == [task_name_for(RULE_ID)]
    definition = scheduler.definition(task_name_for(RULE_ID))
    assert _time_of(definition) == "23:00"
    assert _days_of(definition) == ("DAILY",)


def test_the_task_wakes_the_app_up_without_naming_a_rule() -> None:
    """The task carries when to wake, never which rule to run: after a sleep several
    tasks fire, and the process that starts has to pick one winner among them."""
    scheduler = FakeScheduler()

    _sync([_rule()], scheduler)

    executable, arguments = _command_of(scheduler.definition(task_name_for(RULE_ID)))
    assert arguments == "--run-automations"
    assert RULE_ID not in f"{executable} {arguments}"
    assert "--run-rule" not in arguments


@pytest.mark.parametrize(
    "overrides",
    [
        {"execution": "runtime"},
        {"enabled": False},
        {"trigger": {"kind": "lumable_start"}},
        {"trigger": {"kind": "time", "time_at": "23:00", "days": []}},
        {"action": {"type": "apply_scene", "scene_id": "scene-1"}},
    ],
    ids=["runtime", "disabled", "not-a-time-rule", "no-weekday", "scene-action"],
)
def test_only_a_timed_power_rule_gets_a_task(overrides) -> None:
    scheduler = FakeScheduler()

    result = _sync([_rule(**overrides)], scheduler)

    assert plan_tasks([_rule(**overrides)], command=COMMAND) == []
    assert scheduler.names() == []
    assert result.created == ()


def test_two_rules_differing_only_in_case_get_a_task_each() -> None:
    """Windows task names are case-insensitive and rule ids are not. Sharing a name
    would leave one of the two rules with nothing to wake it."""
    scheduler = FakeScheduler()

    _sync([_rule(id="evening"), _rule(id="Evening")], scheduler)

    names = scheduler.names()
    assert len(names) == 2
    assert len({name.lower() for name in names}) == 2


# ── the definition Windows is given ───────────────────────────────────
@pytest.mark.parametrize(
    ("setting", "expected"),
    [
        # The whole point of a background schedule: a start missed while the machine
        # slept still happens. Windows defaults this to false.
        ("StartWhenAvailable", "true"),
        # Windows defaults to refusing to start on battery, which on a laptop means
        # the schedule simply does not work unless it happens to be plugged in.
        ("DisallowStartIfOnBatteries", "false"),
        # And it kills a running task when the charger comes out — mid BLE write.
        ("StopIfGoingOnBatteries", "false"),
        # One wake-up at a time for this task. (Two *different* tasks coming due
        # together is what the headless execution lock is for.)
        ("MultipleInstancesPolicy", "IgnoreNew"),
        # Waking a sleeping machine to switch a lamp is not what the user asked for.
        ("WakeToRun", "false"),
        ("Enabled", "true"),
    ],
)
def test_the_definition_states_what_the_defaults_would_get_wrong(setting, expected) -> None:
    assert _setting(build_task_xml(_plan()), setting) == expected


def test_every_weekday_becomes_a_daily_trigger() -> None:
    assert _days_of(build_task_xml(_plan())) == ("DAILY",)


def test_a_few_weekdays_become_a_weekly_trigger() -> None:
    definition = build_task_xml(_plan(days=(0, 2, 6)))

    assert _days_of(definition) == ("Monday", "Wednesday", "Sunday")


def test_the_definition_carries_the_command_split_the_way_windows_wants_it() -> None:
    assert _command_of(build_task_xml(_plan())) == (COMMAND.executable, COMMAND.arguments)


def test_a_path_with_an_ampersand_does_not_break_the_definition() -> None:
    definition = build_task_xml(_plan(command=TaskCommand("C:/Luma & Co/LumaBLE.exe", "--run-automations")))

    assert _command_of(definition)[0] == "C:/Luma & Co/LumaBLE.exe"


def test_the_definition_version_is_part_of_the_signature() -> None:
    """Changing a setting above has to rewrite the tasks already on the machine, not
    just apply to the next one created."""
    assert _plan().signature.startswith(f"v{DEFINITION_VERSION}|")


def test_a_new_definition_version_rewrites_existing_tasks(monkeypatch) -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)

    monkeypatch.setattr(windows_tasks, "DEFINITION_VERSION", DEFINITION_VERSION + 1)
    result = _sync([_rule()], scheduler)

    assert result.updated == (RULE_ID,)


# ── editing a rule ────────────────────────────────────────────────────
def test_changing_the_time_rewrites_the_same_task() -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)

    result = _sync([_rule(trigger={"kind": "time", "time_at": "21:30", "days": [0, 1, 2, 3, 4, 5, 6]})], scheduler)

    assert result.updated == (RULE_ID,)
    assert result.created == ()
    assert scheduler.names() == [task_name_for(RULE_ID)], "editing left a second task behind"
    assert _time_of(scheduler.definition(task_name_for(RULE_ID))) == "21:30"


def test_changing_the_days_rewrites_the_same_task() -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)

    result = _sync([_rule(trigger={"kind": "time", "time_at": "23:00", "days": [0, 2, 4]})], scheduler)

    assert result.updated == (RULE_ID,)
    assert scheduler.names() == [task_name_for(RULE_ID)]
    assert _days_of(scheduler.definition(task_name_for(RULE_ID))) == (
        "Monday",
        "Wednesday",
        "Friday",
    )


def test_moving_the_app_reaches_every_task() -> None:
    """After an update installs LumaBLE elsewhere, every task still points at the old
    executable. The command is part of what counts as a change."""
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)

    moved = TaskCommand("C:/new/LumaBLE.exe", "--run-automations")
    result = sync_tasks([_rule()], scheduler=scheduler, command=moved, now=NOW)

    assert result.updated == (RULE_ID,)
    assert _command_of(scheduler.definition(task_name_for(RULE_ID)))[0] == "C:/new/LumaBLE.exe"


def test_running_the_same_sync_again_changes_nothing() -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)
    scheduler.calls.clear()

    result = _sync([_rule()], scheduler)

    assert result.unchanged == (RULE_ID,)
    assert (result.created, result.updated, result.removed) == ((), (), ())
    assert scheduler.kinds() == ["list"], "an unchanged rule was written to Windows again"


def test_force_rewrites_a_task_someone_edited_by_hand() -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)
    # Someone opened Task Scheduler and moved it.
    scheduler.tasks[task_name_for(RULE_ID)]["definition"] = "<Task />"

    result = _sync([_rule()], scheduler, force=True)

    assert result.updated == (RULE_ID,)
    assert _time_of(scheduler.definition(task_name_for(RULE_ID))) == "23:00"


def test_a_task_deleted_outside_the_app_comes_back() -> None:
    """The record says it is current; the machine says it is gone. The machine wins."""
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)
    scheduler.tasks.clear()

    result = _sync([_rule()], scheduler)

    assert result.created == (RULE_ID,)
    assert scheduler.names() == [task_name_for(RULE_ID)]


# ── rules that stop deserving a task ──────────────────────────────────
@pytest.mark.parametrize(
    "overrides",
    [{"enabled": False}, {"execution": "runtime"}],
    ids=["disabled", "runtime-downgrade"],
)
def test_a_rule_that_stops_qualifying_loses_its_task(overrides) -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)

    result = _sync([_rule(**overrides)], scheduler)

    assert result.removed == (task_name_for(RULE_ID),)
    assert scheduler.names() == []


def test_a_deleted_rule_loses_its_task() -> None:
    scheduler = FakeScheduler()
    _sync([_rule()], scheduler)

    result = _sync([], scheduler)

    assert result.removed == (task_name_for(RULE_ID),)
    assert scheduler.names() == []
    assert load_record() == {}, "the record kept a rule that no longer exists"


def test_a_task_no_rule_claims_is_cleaned_up() -> None:
    """A task left over from a build that crashed mid-edit, or a rule deleted while
    the app was closed. Reconciliation is what finds it."""
    orphan = f"{TASK_PREFIX}gone-00000000"
    scheduler = FakeScheduler(existing={orphan: {"definition": "<Task />"}})

    result = _sync([_rule()], scheduler)

    assert result.removed == (orphan,)
    assert scheduler.names() == [task_name_for(RULE_ID)]


def test_the_legacy_schedule_pair_is_never_touched() -> None:
    """0.3.5's tasks are the rollback bridge. Reconciliation must not see them as
    orphans, and nothing here may query or delete them."""
    scheduler = FakeScheduler(existing={name: {"definition": "<Task />"} for name in LEGACY_TASKS})

    _sync([_rule()], scheduler)
    _sync([], scheduler)  # every rule gone: the most eager cleanup there is

    assert set(LEGACY_TASKS).issubset(scheduler.names())
    assert not any(name in LEGACY_TASKS for _kind, name in scheduler.calls)


# ── when Windows says no ──────────────────────────────────────────────
def test_one_task_failing_does_not_stop_the_others() -> None:
    stubborn = task_name_for("morning-on")
    scheduler = FakeScheduler(fail_create={stubborn})

    result = _sync([_rule(), _rule(id="morning-on")], scheduler)

    assert result.created == (RULE_ID,)
    assert [rule_id for rule_id, _message in result.errors] == ["morning-on"]
    assert result.ok is False
    assert scheduler.names() == [task_name_for(RULE_ID)]


def test_a_failed_create_never_takes_the_last_working_task_away() -> None:
    """The rule was edited and its rewrite failed, while another rule was deleted.
    Removing the deleted one is right, but not this round: with a create still
    failing, the safe thing is to prove the new configuration first. An orphan left
    behind costs one wasted wake-up; a working task deleted costs the schedule.

    The half of this the fake cannot prove — that a rejected ``/Create /F`` leaves
    the previous definition alone rather than removing it first — was checked
    against real Windows on a disposable task, for a malformed value and for an
    unexpected node: both were refused with a non-zero exit and the existing task
    kept its command, its time and its weekdays."""
    scheduler = FakeScheduler()
    _sync([_rule(), _rule(id="morning-on")], scheduler)
    scheduler.fail_create = {task_name_for(RULE_ID)}

    result = _sync([_rule(trigger={"kind": "time", "time_at": "21:00", "days": [0]})], scheduler)

    assert [rule_id for rule_id, _message in result.errors] == [RULE_ID]
    assert result.removed == ()
    assert result.deferred_removals == (task_name_for("morning-on"),)
    assert set(scheduler.names()) == {task_name_for(RULE_ID), task_name_for("morning-on")}
    assert _time_of(scheduler.definition(task_name_for(RULE_ID))) == "23:00", "the working task was lost"

    # And once the failure clears, the stale one goes.
    scheduler.fail_create = set()
    again = _sync([_rule(trigger={"kind": "time", "time_at": "21:00", "days": [0]})], scheduler)
    assert again.removed == (task_name_for("morning-on"),)


def test_a_machine_that_cannot_be_listed_is_left_alone() -> None:
    """Reconciling against a list we failed to read would mean deleting tasks because
    we could not see them."""
    scheduler = FakeScheduler(fail_list=True)

    result = _sync([_rule()], scheduler)

    assert result.ok is False
    assert scheduler.kinds() == ["list"]


def test_a_delete_that_failed_is_reported_and_the_rest_go() -> None:
    first = f"{TASK_PREFIX}one-00000000"
    second = f"{TASK_PREFIX}two-00000000"
    scheduler = FakeScheduler(
        existing={first: {}, second: {}},
        fail_delete={first},
    )

    result = _sync([], scheduler)

    assert result.removed == (second,)
    assert [name for name, _message in result.errors] == [first]


# ── arming a rule ─────────────────────────────────────────────────────
def test_a_new_rule_is_watched_before_its_task_can_fire() -> None:
    """Whoever runs first must already know the rule exists. Otherwise a rule created
    in the evening, whose task fires late the next morning because the machine slept,
    has its missed occurrence discarded as being from before our time."""
    seen_at_create: list[bool] = []

    def watching(_name: str) -> None:
        seen_at_create.append(RULE_ID in headless_module.load_state()["seen_since"])

    scheduler = FakeScheduler(on_create=watching)

    _sync([_rule()], scheduler)

    assert seen_at_create == [True], "the task was armed before the rule was being watched"
    assert headless_module.load_state()["seen_since"][RULE_ID] <= NOW


def test_a_rule_already_being_watched_keeps_its_original_moment() -> None:
    """Re-syncing must not move the window forward, or a missed occurrence would stop
    being catchable."""
    first_seen = datetime(2026, 7, 20, 9, 0)
    headless_module.save_state({"seen_since": {RULE_ID: first_seen}})
    scheduler = FakeScheduler()

    _sync([_rule()], scheduler)

    assert headless_module.load_state()["seen_since"][RULE_ID] == first_seen


def test_nothing_is_armed_while_the_automation_state_is_busy(monkeypatch) -> None:
    """A run is in progress and holds the lock. Creating the task anyway would arm a
    rule nobody is watching yet."""
    monkeypatch.setattr(windows_tasks, "seed_seen_since", lambda rule_ids, now=None: False)
    scheduler = FakeScheduler()

    result = _sync([_rule()], scheduler)

    assert scheduler.names() == []
    assert [rule_id for rule_id, _message in result.errors] == [RULE_ID]


# ── the escape hatch ──────────────────────────────────────────────────
def test_nothing_happens_when_schtasks_is_switched_off(monkeypatch) -> None:
    """LUMABLE_DISABLE_SCHTASKS is what keeps this suite — and a packaging run — off
    the machine's task list."""
    monkeypatch.setenv("LUMABLE_DISABLE_SCHTASKS", "1")

    assert default_scheduler() is None

    result = sync_tasks([_rule()], now=NOW)

    assert result.available is False
    assert (result.created, result.updated, result.removed, result.errors) == ((), (), (), ())


def test_the_scheduler_is_absent_off_windows(monkeypatch) -> None:
    monkeypatch.delenv("LUMABLE_DISABLE_SCHTASKS", raising=False)
    monkeypatch.setattr(windows_tasks.os, "name", "posix")

    assert default_scheduler() is None


# ── the schtasks adapter itself ───────────────────────────────────────
class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _captured(monkeypatch, completed: _Completed) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(args: list[str]) -> _Completed:
        calls.append(list(args))
        return completed

    monkeypatch.setattr(SchtasksScheduler, "_run", staticmethod(run))
    return calls


def test_a_task_is_registered_from_its_xml(monkeypatch) -> None:
    """Not from command-line switches: those cannot say StartWhenAvailable."""
    calls = _captured(monkeypatch, _Completed())
    written: list[str] = []

    SchtasksScheduler().create("T", definition=build_task_xml(_plan()))

    assert calls[0][:5] == ["/Create", "/F", "/TN", "T", "/XML"]
    definition_path = calls[0][5]
    assert definition_path.endswith(".xml")
    assert not Path(definition_path).exists(), "the definition file was left behind"
    del written


def test_the_definition_file_is_written_as_utf16(monkeypatch) -> None:
    """schtasks rejects the file otherwise, and the declaration inside says UTF-16."""
    seen: list[bytes] = []

    def run(args: list[str]) -> _Completed:
        seen.append(Path(args[5]).read_bytes())
        return _Completed()

    monkeypatch.setattr(SchtasksScheduler, "_run", staticmethod(run))

    SchtasksScheduler().create("T", definition=build_task_xml(_plan()))

    assert seen[0][:2] in (b"\xff\xfe", b"\xfe\xff"), "no UTF-16 byte order mark"
    assert "StartWhenAvailable" in seen[0].decode("utf-16")


def test_only_our_own_tasks_are_listed(monkeypatch) -> None:
    output = (
        '"\\LumaBLE Automation evening-79f6e061","28.07.2026 23:00:00","Ready"\r\n'
        '"\\LumaBLE Schedule On","28.07.2026 19:00:00","Ready"\r\n'
        '"\\OneDrive Reporting Task","N/A","Ready"\r\n'
    )
    _captured(monkeypatch, _Completed(stdout=output))

    names = SchtasksScheduler().list_names(TASK_PREFIX)

    assert names == ["LumaBLE Automation evening-79f6e061"]


def test_a_query_that_failed_is_raised_not_read_as_empty(monkeypatch) -> None:
    _captured(monkeypatch, _Completed(returncode=1, stderr="ERROR: Access is denied."))

    with pytest.raises(OSError):
        SchtasksScheduler().list_names(TASK_PREFIX)


def test_deleting_a_task_that_is_already_gone_is_not_a_failure(monkeypatch) -> None:
    _captured(monkeypatch, _Completed(returncode=1, stderr="ERROR: The system cannot find the file specified."))

    SchtasksScheduler().delete("T")  # must not raise


def test_a_delete_that_really_failed_is_raised(monkeypatch) -> None:
    _captured(monkeypatch, _Completed(returncode=1, stderr="ERROR: Access is denied."))

    with pytest.raises(OSError):
        SchtasksScheduler().delete("T")


# ── one reconciliation at a time ──────────────────────────────────────
def test_nothing_is_touched_while_another_synchronisation_holds_the_lock(monkeypatch) -> None:
    """Two of these running at once would each decide against a task list the other
    was in the middle of changing, and then overwrite each other's record. Without
    the lock, the safe number of changes to make is none."""
    monkeypatch.setattr(windows_tasks, "RECORD_LOCK_TIMEOUT_SECONDS", 0.2)
    scheduler = FakeScheduler()

    with file_lock(windows_tasks._record_lock_path(), timeout=1.0) as locked:
        assert locked, "the lock could not be taken by the test itself"
        result = _sync([_rule()], scheduler)

    assert scheduler.calls == [], "Windows was changed without holding the lock"
    assert result.ok is False
    assert load_record() == {}


def test_the_record_is_only_written_from_inside_the_lock() -> None:
    """There is deliberately no public writer: one would let a caller save a record
    it had read before someone else changed the tasks."""
    assert not hasattr(windows_tasks, "save_record")
