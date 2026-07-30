"""The one object the interface talks to.

Two things are being pinned here. First that editing a rule is a transaction: it
reaches the file *and* the copy the engine ticks against, because writing one and
not the other is how an edit undoes itself. Second that the applied state is only
ever a confirmed one — a screen that moved its controls for a half-applied scene
would be describing a strip that is not in that state.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from app import storage
from app.automation.controller import (
    PAUSE_ACTIVE,
    PAUSE_OFF,
    AppliedState,
    AutomationController,
)
from app.automation.rules import ORIGIN_APP_TRIGGER
from app.automation.windows_tasks import TaskSyncResult

APP_RULE = {
    "id": "app-chrome",
    "name": "Chrome",
    "trigger": {"kind": "app_foreground", "app": "chrome"},
    "action": {"type": "apply_scene", "scene_id": "scene-chrome"},
    "execution": "runtime",
    "enabled": True,
}


class FakeHost:
    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = settings
        self._ble = QObject()


class FakeRuntime(QObject):
    applied = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False
        self.paused: list[int] = []
        self.resumed = 0
        self.status = PAUSE_OFF
        self.pause_result = True
        self.connected: list[bool] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def note_connected(self, connected: bool = True) -> None:
        self.connected.append(connected)

    def pause(self, seconds: int) -> bool:
        self.paused.append(seconds)
        return self.pause_result

    def resume(self) -> bool:
        self.resumed += 1
        return self.pause_result

    def pause_status(self) -> str:
        return self.status

    def paused_until(self) -> datetime | None:
        return datetime(2026, 7, 27, 0, 0)


def _controller(monkeypatch, settings: dict[str, Any] | None = None) -> AutomationController:
    """A controller whose engine and task compiler are stand-ins."""
    settings = settings if settings is not None else storage.load_settings()
    controller = AutomationController(FakeHost(settings), lambda: object())
    monkeypatch.setattr(controller._tasks, "sync", lambda: None)
    return controller


def _started(monkeypatch, settings: dict[str, Any] | None = None):
    from app.automation import controller as controller_module

    runtime = FakeRuntime()
    monkeypatch.setattr(controller_module, "AutomationRuntime", lambda *a, **k: runtime)
    controller = _controller(monkeypatch, settings)
    controller.start()
    return controller, runtime


# ── editing rules ─────────────────────────────────────────────────────
def test_a_saved_rule_reaches_both_the_file_and_the_running_engine(monkeypatch) -> None:
    """The engine ticks against the window's own settings and the window writes them
    back on close, while a Windows task reads the file. An edit that landed in only
    one of those would come back from the dead."""
    controller = _controller(monkeypatch, storage.load_settings())

    saved = controller.save_rule(APP_RULE)

    assert saved is not None and saved.id == "app-chrome"
    in_memory = [rule["id"] for rule in controller._settings()["automations"]["rules"]]
    on_disk = [rule["id"] for rule in storage.load_settings()["automations"]["rules"]]
    assert in_memory == ["app-chrome"], "the engine would not see the new rule"
    assert on_disk == ["app-chrome"], "a task's process would not see the new rule"


def test_saving_the_same_id_replaces_rather_than_repeats(monkeypatch) -> None:
    controller = _controller(monkeypatch, storage.load_settings())
    controller.save_rule(APP_RULE)

    controller.save_rule(APP_RULE | {"name": "Chrome, but louder"})

    assert [rule.name for rule in controller.rules()] == ["Chrome, but louder"]


def test_a_rule_the_schema_will_not_have_is_refused_now_not_later(monkeypatch) -> None:
    """Dropped on the next read instead, it would look saved and then vanish."""
    controller = _controller(monkeypatch, storage.load_settings())

    assert controller.save_rule({"id": "", "trigger": {}}) is None
    assert controller.rules() == []
    assert storage.load_settings()["automations"]["rules"] == []


def test_deleting_a_rule_removes_it_from_both(monkeypatch) -> None:
    controller = _controller(monkeypatch, storage.load_settings())
    controller.save_rule(APP_RULE)

    assert controller.delete_rule("app-chrome") is True
    assert controller.rules() == []
    assert storage.load_settings()["automations"]["rules"] == []
    assert controller.delete_rule("app-chrome") is False, "deleting nothing reported success"


def test_switching_one_rule_off_leaves_the_rest_alone(monkeypatch) -> None:
    controller = _controller(monkeypatch, storage.load_settings())
    controller.save_rule(APP_RULE)
    controller.save_rule(APP_RULE | {"id": "app-vlc", "trigger": {"kind": "app_foreground", "app": "vlc"}})

    assert controller.set_rule_enabled("app-chrome", False) is True

    states = {rule.id: rule.enabled for rule in controller.rules()}
    assert states == {"app-chrome": False, "app-vlc": True}


def test_an_edit_keeps_the_provenance_the_migration_recorded(monkeypatch) -> None:
    """It is what keeps a bridged rule out of the task compiler, so an edit that
    quietly dropped it would give the schedule a second scheduler."""
    controller = _controller(monkeypatch, storage.load_settings())
    controller.save_rule(APP_RULE | {"origin": ORIGIN_APP_TRIGGER, "origin_ref": "chrome"})

    controller.set_rule_enabled("app-chrome", False)

    assert controller.rule("app-chrome").origin == ORIGIN_APP_TRIGGER


def test_the_master_switch_is_stored(monkeypatch) -> None:
    controller = _controller(monkeypatch, storage.load_settings())

    assert controller.set_enabled(True) is True

    assert controller.is_enabled() is True
    assert storage.load_settings()["automations"]["enabled"] is True


def test_every_edit_says_so_and_reconciles_the_tasks(monkeypatch) -> None:
    controller = _controller(monkeypatch, storage.load_settings())
    told: list = []
    synced: list = []
    controller.changed.connect(lambda: told.append(True))
    monkeypatch.setattr(controller, "sync_tasks", lambda: synced.append(True))

    controller.save_rule(APP_RULE)

    assert told == [True], "the screen was not told to redraw"
    assert synced == [True], "a rule changed without the Windows tasks following"


# ── what the strip now shows ──────────────────────────────────────────
def test_the_applied_state_is_passed_on(monkeypatch) -> None:
    controller, runtime = _started(monkeypatch)
    seen: list = []
    controller.applied.connect(seen.append)

    state = AppliedState(rule_id="evening", power=False)
    runtime.applied.emit(state)

    assert seen == [state]


# ── the pause ─────────────────────────────────────────────────────────
def test_the_pause_reports_what_the_engine_reports(monkeypatch) -> None:
    controller, runtime = _started(monkeypatch)

    assert controller.pause(1800) is True
    assert runtime.paused == [1800]

    runtime.pause_result = False
    assert controller.pause(1800) is False, "a pause the machine never heard read as success"
    assert controller.resume() is False


def test_the_pause_state_is_the_engine_s_four_states(monkeypatch) -> None:
    controller, runtime = _started(monkeypatch)
    runtime.status = PAUSE_ACTIVE

    assert controller.pause_status() == PAUSE_ACTIVE
    assert controller.paused_until() == datetime(2026, 7, 27, 0, 0)


def test_without_an_engine_nothing_claims_to_be_paused(monkeypatch) -> None:
    """A controller whose engine failed to start must not report a pause it is in no
    position to keep."""
    controller = _controller(monkeypatch)

    assert controller.pause_status() == PAUSE_OFF
    assert controller.pause(60) is False
    assert controller.paused_until() is None


def test_a_pause_from_an_earlier_session_can_still_be_lifted(monkeypatch) -> None:
    """A pause outlives the window it was set in — that is the point of writing it
    where every process can see it. So a controller whose engine never came up must
    still report the pause and still be able to end it: without that the user is left
    with a pause they cannot lift except by switching automations off and on, only to
    find the old pause waiting for them."""
    from app.automation import headless

    controller = _controller(monkeypatch)
    assert headless.pause_automations(datetime.now(), 3600) is True

    assert controller.pause_status() == PAUSE_ACTIVE
    assert controller.paused_until() is not None

    assert controller.resume() is True
    assert controller.pause_status() == PAUSE_OFF


def test_a_reconciliation_still_owed_is_reported_as_such(monkeypatch) -> None:
    """``last_task_result`` is what the screen shows, so the facade has to say when
    that result no longer describes the rules. The answer belongs to the task
    controller; keeping a second copy here would let the two disagree."""
    controller = _controller(monkeypatch)
    started: list[int] = []
    controller.tasks_sync_started.connect(lambda: started.append(1))

    controller.sync_tasks()

    assert started == [1], "a screen was never told the reconciliation had begun"
    assert controller.tasks_syncing() is False
    monkeypatch.setattr(type(controller._tasks), "busy", property(lambda _self: True))
    assert controller.tasks_syncing() is True


# ── lifecycle ─────────────────────────────────────────────────────────
def test_starting_brings_the_engine_up_and_stopping_takes_it_down(monkeypatch) -> None:
    controller, runtime = _started(monkeypatch)

    assert runtime.started is True
    assert controller.is_running() is True

    controller.stop()

    assert runtime.stopped is True
    assert controller.is_running() is False
    controller.stop()  # a second close must not fail


def test_a_connection_edge_reaches_the_engine(monkeypatch) -> None:
    controller, runtime = _started(monkeypatch)

    controller.note_connected(True)
    controller.note_connected(False)

    assert runtime.connected == [True, False]


def test_an_engine_that_cannot_start_does_not_migrate(monkeypatch) -> None:
    """The migration stands the old App Trigger watcher down. With no engine to take
    over, that would leave the user with no triggers at all."""
    from app.automation import controller as controller_module

    def explode(*args: Any, **kwargs: Any):
        raise RuntimeError("no engine today")

    migrated: list = []
    monkeypatch.setattr(controller_module, "AutomationRuntime", explode)
    monkeypatch.setattr(controller_module, "migrate", lambda: migrated.append(True))
    # Caught here so the run does not write a crash log into the real user data
    # directory — and so the test can prove the fault was reported at all.
    reported: list[str] = []
    monkeypatch.setattr(
        controller_module, "write_current_exception", lambda context="": reported.append(context)
    )
    controller = _controller(monkeypatch)

    controller.start()

    assert migrated == [], "the migration ran with nothing to take over"
    assert controller.is_running() is False
    assert reported == ["automation_runtime"], "a broken engine was not reported"


# ── the tasks and the bridge ──────────────────────────────────────────
def test_the_last_task_result_is_kept_for_a_screen_opened_later(monkeypatch) -> None:
    controller = _controller(monkeypatch)
    reported: list = []
    controller.tasks_synced.connect(reported.append)
    result = TaskSyncResult(created=("evening-off",))

    controller._on_tasks_synced(result)

    assert controller.last_task_result() is result
    assert reported == [result]


def test_the_bridge_is_reported_from_the_stored_state(monkeypatch) -> None:
    settings = storage.load_settings()
    settings["automations"]["legacy_bridge"] = True
    controller = _controller(monkeypatch, settings)

    assert controller.bridge_active() is True


def test_a_handoff_that_worked_is_taken_into_memory(monkeypatch) -> None:
    """It clears the bridge on disk; the window's copy has to follow or closing would
    put it back."""
    from app.automation import controller as controller_module
    from app.automation.migration import HandoffResult

    settings = storage.load_settings()
    settings["automations"]["legacy_bridge"] = True
    controller = _controller(monkeypatch, settings)
    stored = storage.load_settings()
    stored["automations"]["legacy_bridge"] = False
    storage.save_settings(stored)
    monkeypatch.setattr(
        controller_module, "complete_legacy_handoff", lambda: HandoffResult(done=True)
    )
    finished: list = []
    controller.handoff_finished.connect(finished.append)

    assert controller.complete_handoff() is True
    _wait_for(finished)

    assert finished[0].done is True
    assert controller.bridge_active() is False


def test_the_handoff_does_not_block_the_window(monkeypatch) -> None:
    """It is several schtasks processes deep. Run on the thread that draws the
    window, the button behind it would look broken at the moment it was working
    hardest — so the call returns at once and answers by signal."""
    import threading

    from app.automation import controller as controller_module
    from app.automation.migration import HandoffResult

    release = threading.Event()
    calls: list[int] = []

    def slow_handoff() -> HandoffResult:
        calls.append(1)
        release.wait(timeout=5.0)
        return HandoffResult(done=True)

    monkeypatch.setattr(controller_module, "complete_legacy_handoff", slow_handoff)
    controller = _controller(monkeypatch)
    started: list = []
    finished: list = []
    controller.handoff_started.connect(lambda: started.append(True))
    controller.handoff_finished.connect(finished.append)

    assert controller.complete_handoff() is True, "the handoff never started"
    assert started == [True], "the button was told nothing while the work ran"
    assert controller.handoff_in_progress() is True
    assert finished == [], "the call waited for the work to finish"

    # Pressed again while it is running: one machine, one handoff.
    assert controller.complete_handoff() is False, "a second handoff was started"

    release.set()
    _wait_for(finished)

    assert calls == [1], "the work ran more than once"
    assert finished[0].done is True
    assert controller.handoff_in_progress() is False


def test_what_follows_a_handoff_happens_on_the_qt_thread(monkeypatch) -> None:
    """Adoption, the redraw and the final reconciliation are the window's business,
    so they wait for the result to arrive back on its thread."""
    import threading

    from app.automation import controller as controller_module
    from app.automation.migration import HandoffResult

    settings = storage.load_settings()
    settings["automations"]["legacy_bridge"] = True
    controller = _controller(monkeypatch, settings)
    stored = storage.load_settings()
    stored["automations"]["legacy_bridge"] = False
    storage.save_settings(stored)
    monkeypatch.setattr(
        controller_module, "complete_legacy_handoff", lambda: HandoffResult(done=True)
    )
    main_thread = threading.get_ident()
    seen: list[tuple[str, int]] = []
    controller.changed.connect(lambda: seen.append(("changed", threading.get_ident())))
    monkeypatch.setattr(
        controller, "sync_tasks", lambda: seen.append(("synced", threading.get_ident()))
    )
    finished: list = []
    controller.handoff_finished.connect(finished.append)

    controller.complete_handoff()
    _wait_for(finished)

    assert [name for name, _thread in seen] == ["changed", "synced"]
    assert {thread for _name, thread in seen} == {main_thread}
    assert controller.bridge_active() is False


def test_a_handoff_that_failed_changes_nothing_here(monkeypatch) -> None:
    from app.automation import controller as controller_module
    from app.automation.migration import HandoffResult

    settings = storage.load_settings()
    settings["automations"]["legacy_bridge"] = True
    controller = _controller(monkeypatch, settings)
    monkeypatch.setattr(
        controller_module,
        "complete_legacy_handoff",
        lambda: HandoffResult(errors=(("tasks", "access is denied"),)),
    )
    told: list = []
    controller.changed.connect(lambda: told.append(True))
    finished: list = []
    controller.handoff_finished.connect(finished.append)

    controller.complete_handoff()
    _wait_for(finished)

    assert finished[0].ok is False
    assert told == [], "a failed handoff told the screen the bridge was gone"
    assert controller.bridge_active() is True


def _wait_for(reported: list, timeout: float = 5.0) -> None:
    """Spin the Qt loop: the handoff answers from a worker thread."""
    from time import monotonic, sleep

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + timeout
    while not reported and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    app.processEvents()
    assert reported, "the handoff never reported back"


# ── the journal ───────────────────────────────────────────────────────
def test_the_journal_comes_back_newest_first(monkeypatch) -> None:
    from app.automation.journal import AutomationJournal

    book = AutomationJournal(storage.automation_journal_path())
    base = datetime(2026, 7, 27, 20, 0)
    for index in range(3):
        book.record_success(f"rule-{index}", message_code="power_set", now=base + timedelta(minutes=index))
    book.flush(0.0, force=True)
    controller = _controller(monkeypatch)

    entries = controller.journal(limit=2)

    assert [entry.rule_id for entry in entries] == ["rule-2", "rule-1"]


# ── the boundary itself ───────────────────────────────────────────────
ALLOWED_AUTOMATION_IMPORT = "app.automation.controller"


def _automation_imports(source: str) -> list[str]:
    """Every ``app.automation.*`` module a file imports, however it spells it.

    Parsed rather than searched for. A list of forbidden names only bans what
    somebody thought of: reading the imports asks the opposite question — what is
    allowed — so a module added to the package later is covered without anyone
    remembering to add it here.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module == "app.automation":
                # ``from app.automation import runtime``: the module is in the alias.
                found.extend(f"app.automation.{alias.name}" for alias in node.names)
            else:
                # ``from app.automation.runtime import X``: the aliases are symbols.
                found.append(node.module)
    return [name for name in found if name.startswith("app.automation")]


def test_the_interface_reaches_automations_only_through_the_controller() -> None:
    """The screens may know about one object. Everything behind it has its own locks,
    its own files and its own ordering rules, and a panel that reached past the
    facade would end up re-deciding what the rest of the system has already decided.
    """
    root = Path(__file__).resolve().parent.parent / "app"
    ui_files = [
        path
        for path in (
            list(root.glob("panels/*.py"))
            + list(root.glob("widgets/*.py"))
            # The panel builders are only half of a screen; the controller that fills
            # them in is where the temptation to reach past the facade actually is.
            + list(root.glob("*_ui_controller.py"))
            + [root / "main_layout.py"]
        )
        if path.name != "__init__.py"
    ]
    assert any(path.name == "automation_ui_controller.py" for path in ui_files)
    offenders = [
        f"{path.name} -> {module}"
        for path in ui_files
        for module in _automation_imports(path.read_text(encoding="utf-8"))
        if module != ALLOWED_AUTOMATION_IMPORT
    ]

    assert offenders == [], "the interface reached past the automation controller"


def test_the_boundary_test_would_notice_a_screen_reaching_past_it() -> None:
    """The guard above passes trivially while there is no screen, so this is what
    says it will still mean something once there is one."""
    assert _automation_imports("from app.automation.runtime import AutomationRuntime") == [
        "app.automation.runtime"
    ]
    assert _automation_imports("from app.automation import headless") == [
        "app.automation.headless"
    ]
    assert _automation_imports("import app.automation.windows_tasks") == [
        "app.automation.windows_tasks"
    ]
    # And the one that is allowed reads as exactly that, not as a symbol beneath it.
    assert _automation_imports("from app.automation.controller import AutomationController") == [
        ALLOWED_AUTOMATION_IMPORT
    ]
