"""The engine running inside the open app — and the handover to it.

The migration switches the old App Trigger watcher off, so the question these tests
answer is the one that matters to a user: after migrating, does walking into an app
still change the light, and does it do it once rather than twice?
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from itertools import count
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from app import storage
from app.automation import headless as headless_module
from app.automation import migration as migration_module
from app.automation.file_lock import ProcessLock, file_lock
from app.automation.migration import LEGACY_OFF_ID, LEGACY_ON_ID, migrate, plan_migration
from app.automation.runtime import AutomationRuntime
from app.scene_presets import get_scene_preset
from app.scenes import wrap_scene

PRIMARY = "AA:BB:CC:DD:EE:01"


class FakeBle(QObject):
    operation_finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[tuple[str, Any, str]] = []
        self._ids = count(1)
        self._answered: set[int] = set()

    def primary_address(self) -> str:
        return PRIMARY

    def mirror_addresses(self) -> list[str]:
        return []

    def cancel_operation(self, operation_id: int) -> bool:
        return True

    def _submit(self, kind: str, payload: Any, address: str) -> int:
        operation_id = next(self._ids)
        self.writes.append((kind, payload, address))
        return operation_id

    def set_power_for_address_tracked(self, enabled: bool, address: str) -> int:
        return self._submit("power", bool(enabled), address)

    def set_color_for_address_tracked(self, red: int, green: int, blue: int, address: str) -> int:
        return self._submit("color", (red, green, blue), address)

    def set_brightness_for_address_tracked(self, value: int, address: str) -> int:
        return self._submit("brightness", value, address)

    def set_effect_for_address_tracked(self, code: int, speed: Any, address: str) -> int:
        return self._submit("effect", (code, speed), address)

    def confirm_all(self) -> None:
        """Answer every outstanding write, the way the controller would."""
        self._answer_all(True, "success")

    def fail_all(self) -> None:
        self._answer_all(False, "ble_error")

    def _answer_all(self, ok: bool, code: str) -> None:
        for index in range(1, next(self._ids)):
            if index in self._answered:
                continue
            self._answered.add(index)
            self.operation_finished.emit(_Result(index, ok, code))


class _Result:
    def __init__(self, operation_id: int, ok: bool, code: str) -> None:
        self.operation_id = operation_id
        self.ok = ok
        self.code = code


class FakeBackend:
    """The parts of QtApiBackend the executor asks for."""

    def __init__(self) -> None:
        self.pc_modes: list[tuple[str, Any]] = []

    def resolve_scene_targets(self, target: Any) -> list[str] | None:
        return None  # "every connected strip"; the executor expands it

    def capabilities_for_device(self, device_id: str | None) -> dict[str, Any]:
        return {}

    def set_pc_mode(self, mode: str, preset: Any = None) -> bool:
        self.pc_modes.append((mode, preset))
        return True


class FakeHost:
    """A stand-in for MainWindow: settings, a strip, and the streaming controllers."""

    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = settings
        self._ble = FakeBle()
        self._is_connected = True
        self.power_calls: list[bool] = []

    def _remember_power_setting(self, enabled: bool) -> None:
        self.power_calls.append(bool(enabled))

    def _sync_power_button(self) -> None:
        pass


def _settings(**overrides: Any) -> dict[str, Any]:
    settings = {
        "schedule": {
            "enabled": False,
            "on_time": "19:00",
            "off_time": "23:00",
            "startup_enabled": False,
            "days": [0, 1, 2, 3, 4, 5, 6],
        },
        "app_triggers": {
            "enabled": True,
            "default": "",
            "rules": [{"app": "chrome", "scene": "cool_white"}],
        },
    }
    settings.update(overrides)
    return settings


def _runtime(host: FakeHost, foreground: str = "") -> AutomationRuntime:
    runtime = AutomationRuntime(host, FakeBackend(), interval_ms=10_000)
    runtime._foreground = staticmethod(lambda: foreground)  # type: ignore[method-assign]
    return runtime


# ── the handover ──────────────────────────────────────────────────────
def test_a_migrated_app_trigger_still_applies_its_scene(monkeypatch) -> None:
    """The migration stands the old watcher down, so this is the whole question:
    does walking into the app still change the light afterwards?"""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    assert migrate().ok

    host = FakeHost(storage.load_settings())
    assert host._settings["app_triggers"]["enabled"] is False, "the old watcher still runs"
    runtime = _runtime(host, foreground="chrome.exe")

    runtime._tick()
    host._ble.confirm_all()

    preset = get_scene_preset("cool_white")
    assert ("color", preset.rgb, PRIMARY) in host._ble.writes, "the scene never reached the strip"
    assert ("brightness", preset.brightness, PRIMARY) in host._ble.writes


def test_the_scene_is_applied_once_not_once_per_tick(monkeypatch) -> None:
    """The old watcher only acted when the foreground app changed. The engine has to
    be just as quiet: a rule that is still the winner has already had its way."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    migrate()
    host = FakeHost(storage.load_settings())
    runtime = _runtime(host, foreground="chrome.exe")

    runtime._tick()
    host._ble.confirm_all()
    writes_after_first = len(host._ble.writes)
    for _ in range(3):
        runtime._tick()
        host._ble.confirm_all()

    assert len(host._ble.writes) == writes_after_first, "the scene was re-applied on every tick"


def test_nothing_is_applied_for_an_app_no_rule_names(monkeypatch) -> None:
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    migrate()
    host = FakeHost(storage.load_settings())

    _runtime(host, foreground="notepad.exe")._tick()

    assert host._ble.writes == []


# ── what the runtime owns ─────────────────────────────────────────────
def test_background_rules_are_left_to_the_windows_tasks() -> None:
    """Two schedulers for one schedule would switch the light twice. The runtime and
    the tasks own disjoint sets of rules rather than coordinating over one."""
    settings = plan_migration(
        _settings(schedule={**_settings()["schedule"], "enabled": True}),
        legacy_tasks_present=True,
    ).settings
    host = FakeHost(settings)
    runtime = _runtime(host)

    rules = runtime._runtime_rules(settings["automations"])

    assert LEGACY_ON_ID not in {rule.id for rule in rules}
    assert LEGACY_OFF_ID not in {rule.id for rule in rules}


def test_a_streaming_mode_keeps_its_hold_on_the_strip(monkeypatch) -> None:
    """Walking into an app must not interrupt screen sync — but a time of day is
    still honoured, exactly as the old schedule was."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings(schedule={**_settings()["schedule"], "enabled": True}))
    migrate()
    host = FakeHost(storage.load_settings())
    host._ambient_ui = type("Stream", (), {"is_running": lambda self: True})()
    runtime = _runtime(host, foreground="chrome.exe")

    rules = runtime._runtime_rules(
        storage.validate_automations(host._settings.get("automations", {}))
    )

    kinds = {rule.trigger.kind for rule in rules}
    assert "app_foreground" not in kinds, "an app trigger interrupted a running stream"
    assert "time" in kinds, "a scheduled time was dropped because a stream was running"


def test_automations_switched_off_do_nothing(monkeypatch) -> None:
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    migrate()
    settings = storage.load_settings()
    settings["automations"]["enabled"] = False
    host = FakeHost(settings)

    _runtime(host, foreground="chrome.exe")._tick()

    assert host._ble.writes == []


def test_a_power_rule_tells_the_app_what_it_did(monkeypatch) -> None:
    """Otherwise the window still shows the light on, and the next reconnect restores
    the state the app believes in — undoing the automation."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(
        _settings(
            schedule={
                "enabled": True,
                "on_time": "19:00",
                "off_time": "23:00",
                "startup_enabled": False,
                "days": [0, 1, 2, 3, 4, 5, 6],
            }
        )
    )
    migrate()
    host = FakeHost(storage.load_settings())
    runtime = _runtime(host)

    decision = type(
        "Decision",
        (),
        {"action": type("Action", (), {"type": "set_power", "power": False})()},
    )()
    runtime._reflect(decision)

    assert host.power_calls == [False]


# ── the schedule and its migrated rules stay in step ──────────────────
def test_loading_a_profile_moves_the_migrated_schedule_rules_with_it(monkeypatch) -> None:
    """Loading a profile copies its schedule over the global one. The rules derived
    from that schedule have to follow, or the light ends up on whichever of the two
    the user is not looking at."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: True)
    storage.save_settings(
        _settings(
            schedule={
                "enabled": True,
                "on_time": "19:00",
                "off_time": "23:00",
                "startup_enabled": True,
                "days": [0, 1, 2, 3, 4, 5, 6],
            }
        )
    )
    migrate()
    settings = storage.load_settings()

    # What loading a profile does: the profile's schedule becomes the global one.
    settings["schedule"] = {
        "enabled": True,
        "on_time": "07:30",
        "off_time": "21:15",
        "startup_enabled": True,
        "days": [5, 6],
    }
    changed = migration_module.resync_legacy_schedule_rules(settings)

    assert changed is True
    rules = {
        rule.id: rule
        for rule in migration_module.validate_rules(settings["automations"]["rules"])
    }
    assert rules[LEGACY_ON_ID].trigger.time_at == "07:30"
    assert rules[LEGACY_OFF_ID].trigger.time_at == "21:15"
    assert rules[LEGACY_ON_ID].trigger.days == (5, 6)
    assert rules[LEGACY_ON_ID].runs_in_background, "the rule stopped being a background one"


def test_resyncing_before_a_migration_does_nothing() -> None:
    settings = _settings()

    assert migration_module.resync_legacy_schedule_rules(settings) is False
    assert "automations" not in settings or not settings["automations"].get("rules")


def test_resyncing_an_unchanged_schedule_reports_no_change(monkeypatch) -> None:
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: True)
    storage.save_settings(
        _settings(
            schedule={
                "enabled": True,
                "on_time": "19:00",
                "off_time": "23:00",
                "startup_enabled": True,
                "days": [0, 1, 2, 3, 4, 5, 6],
            }
        )
    )
    migrate()
    settings = storage.load_settings()

    assert migration_module.resync_legacy_schedule_rules(settings) is False


def test_the_window_moves_onto_the_migrated_engine(monkeypatch) -> None:
    """The real sequence, in one window: settings loaded at startup, migrated on
    disk, and then everything that reads them.

    The window keeps its own copy of the settings from before the migration. Left
    alone it would run the engine against the state from before, leave the old
    watcher switched on, hand the task compiler the wrong rule list — and save that
    stale copy straight over the migration on the way out.
    """
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_start_deferred", lambda self, delay_ms, callback: None)

    window = MainWindow()
    try:
        assert window._settings["app_triggers"]["enabled"] is True, "the test starts pre-migration"

        window._start_automations()

        automations = window._settings["automations"]
        assert automations["migrated_version"] == 1, "the window is still pre-migration"
        assert [rule["id"] for rule in automations["rules"]], "no rules reached the window"
        assert window._settings["app_triggers"]["enabled"] is False, "the old watcher still runs"
        # What the engine and the task compiler will each be handed.
        assert window._automation_runtime._settings() is window._settings
        assert window._automation_tasks._rules() is not None

        # And the copy the window saves on the way out keeps the migration.
        window._save_window_settings()
        assert storage.load_settings()["automations"]["rules"], "closing wiped the migration"
    finally:
        window._ble.shutdown()
        window.close()
        for _ in range(5):
            app.processEvents()


def test_a_noop_migration_marker_survives_the_window_closing(monkeypatch) -> None:
    """A clean install still commits migrated_version even though changed is false."""
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    monkeypatch.setattr(migration_module, "load_profiles", lambda: [])
    storage.save_settings(
        _settings(
            schedule={
                "enabled": False,
                "on_time": "19:00",
                "off_time": "23:00",
                "startup_enabled": False,
                "days": [],
            },
            app_triggers={"enabled": False, "default": "", "rules": []},
        )
    )
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_start_deferred", lambda self, delay_ms, callback: None)

    window = MainWindow()
    try:
        assert window._settings["automations"]["migrated_version"] == 0
        window._start_automations()
        assert window._settings["automations"]["migrated_version"] == 1

        window._save_window_settings()
        assert storage.load_settings()["automations"]["migrated_version"] == 1
    finally:
        window._ble.shutdown()
        window.close()
        for _ in range(5):
            app.processEvents()


def test_finished_legacy_cleanup_is_not_resurrected_on_close(monkeypatch) -> None:
    """Cleanup commits after startup; the window must adopt its cleared marker."""
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    settings = storage.validate_settings(_settings())
    settings["automations"].update(
        {"migrated_version": 1, "legacy_cleanup_pending": True}
    )
    storage.save_settings(settings)
    monkeypatch.setattr(migration_module, "_remove_legacy_tasks", lambda *_args, **_kwargs: None)
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_start_deferred", lambda self, delay_ms, callback: None)

    window = MainWindow()
    try:
        assert window._settings["automations"]["legacy_cleanup_pending"] is True
        window._start_automations()
        assert window._settings["automations"]["legacy_cleanup_pending"] is False

        window._save_window_settings()
        assert storage.load_settings()["automations"]["legacy_cleanup_pending"] is False
    finally:
        window._ble.shutdown()
        window.close()
        for _ in range(5):
            app.processEvents()


def test_the_runtime_starts_from_the_app(monkeypatch) -> None:
    """Without this call site the migration would switch off a working feature and
    put nothing in its place."""
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    scheduled: list = []
    monkeypatch.setattr(
        MainWindow,
        "_start_deferred",
        lambda self, delay_ms, callback: scheduled.append((delay_ms, callback)),
    )

    window = MainWindow()
    try:
        names = [callback.__name__ for _delay, callback in scheduled]
        assert "_start_automations" in names, "the engine is never started"
        # And before the tasks are reconciled, which is planned against its rules.
        engine_at = names.index("_start_automations")
        assert engine_at < names.index("sync")
    finally:
        window._ble.shutdown()
        window.close()
        for _ in range(5):
            app.processEvents()


# ── the engine keeps up with the rules ────────────────────────────────
def _edit_scene_behind(settings: dict[str, Any], scene_id: str) -> None:
    for rule in settings["automations"]["rules"]:
        if rule.get("trigger", {}).get("kind") == "app_foreground":
            rule["action"]["scene_id"] = scene_id


def test_editing_the_winning_rule_applies_the_new_scene(monkeypatch) -> None:
    """A stateful rule only acts when it takes over, so the engine remembers the one
    in force. Change what that rule *does* and the memory is about a rule that no
    longer exists — the light would stay on the old scene for ever."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    migrate()
    host = FakeHost(storage.load_settings())
    runtime = _runtime(host, foreground="chrome.exe")
    runtime._tick()
    host._ble.confirm_all()
    first = list(host._ble.writes)

    # The user points the same rule at a different look.
    red = get_scene_preset("red")
    host._settings["scenes"].append(
        wrap_scene(
            {
                "scene_id": "edited-scene",
                "name": "Edited",
                "state": {"power": True, "rgb": list(red.rgb), "brightness": red.brightness},
            }
        )
    )
    _edit_scene_behind(host._settings, "edited-scene")

    runtime._tick()
    host._ble.confirm_all()

    applied = [write for write in host._ble.writes[len(first):] if write[0] == "color"]
    assert applied, "the edited rule never applied its new scene"
    assert applied[0][1] == red.rgb

    # And exactly once: the rule is the winner again, not a new one every tick.
    before = len(host._ble.writes)
    runtime._tick()
    host._ble.confirm_all()
    assert len(host._ble.writes) == before, "the edited rule re-applied on every tick"


def test_switching_automations_off_and_on_applies_the_winner_again(monkeypatch) -> None:
    """While off, the user may have moved the light by hand. Coming back, the winning
    rule has to assert itself rather than be remembered as already applied."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    migrate()
    host = FakeHost(storage.load_settings())
    runtime = _runtime(host, foreground="chrome.exe")
    runtime._tick()
    host._ble.confirm_all()
    first = len(host._ble.writes)

    host._settings["automations"]["enabled"] = False
    runtime._tick()
    host._settings["automations"]["enabled"] = True
    runtime._tick()
    host._ble.confirm_all()

    assert len(host._ble.writes) > first, "the rule was still thought to be applied"


def test_reordering_rules_does_not_reapply_the_same_winner(monkeypatch) -> None:
    """List order is presentation only, so moving a row must not reset the engine."""
    monkeypatch.setattr(migration_module, "legacy_tasks_present", lambda: False)
    storage.save_settings(_settings())
    migrate()
    host = FakeHost(storage.load_settings())
    runtime = _runtime(host, foreground="chrome.exe")
    runtime._tick()
    host._ble.confirm_all()
    writes = len(host._ble.writes)

    host._settings["automations"]["rules"].reverse()
    runtime._tick()
    host._ble.confirm_all()

    assert len(host._ble.writes) == writes, "reordering rows replayed the winning rule"


# ── the triggers the app has to feed it ───────────────────────────────
def test_a_strip_that_connected_before_the_engine_started_still_counts() -> None:
    host = FakeHost(_settings())
    host._is_connected = True
    runtime = _runtime(host)

    runtime.start()
    try:
        assert "strip_connected" in runtime._pending, "the connection edge was lost"
    finally:
        runtime.stop()


def test_only_the_rising_edge_of_the_connection_is_an_event() -> None:
    host = FakeHost(_settings())
    runtime = _runtime(host)

    runtime.note_connected(False)
    assert runtime._pending == []

    runtime.note_connected(True)
    assert runtime._pending == ["strip_connected"]


def test_idle_time_reaches_the_snapshot() -> None:
    """Without a provider ``no_input`` rules could never come round at all."""
    host = FakeHost(_settings())
    runtime = AutomationRuntime(host, FakeBackend(), idle_provider=lambda: 754.0)

    assert runtime._snapshot(host._settings).idle_seconds == 754.0


def test_a_provider_that_fails_reads_as_no_idle_time() -> None:
    host = FakeHost(_settings())

    def broken() -> float:
        raise OSError("no such call")

    runtime = AutomationRuntime(host, FakeBackend(), idle_provider=broken)

    assert runtime._snapshot(host._settings).idle_seconds == 0.0


def _trigger_settings(trigger: dict[str, Any]) -> dict[str, Any]:
    scene_id = "trigger-scene"
    return {
        "automations": {
            "enabled": True,
            "migrated_version": 1,
            "rules": [
                {
                    "id": "trigger-rule",
                    "name": "Trigger rule",
                    "trigger": trigger,
                    "action": {"type": "apply_scene", "scene_id": scene_id},
                    "execution": "runtime",
                    "enabled": True,
                }
            ],
        },
        "scenes": [
            wrap_scene(
                {
                    "scene_id": scene_id,
                    "name": "Trigger scene",
                    "state": {
                        "power": True,
                        "rgb": [12, 34, 56],
                        "brightness": 78,
                    },
                }
            )
        ],
        "app_triggers": {"enabled": False, "default": "", "rules": []},
    }


def test_strip_connected_rule_executes_once_end_to_end() -> None:
    host = FakeHost(_trigger_settings({"kind": "strip_connected"}))
    runtime = _runtime(host)

    runtime.note_connected(True)
    runtime._tick()
    host._ble.confirm_all()
    writes = len(host._ble.writes)
    assert writes > 0, "the connection event was queued but its rule never executed"

    runtime._tick()
    host._ble.confirm_all()
    assert len(host._ble.writes) == writes


def test_idle_rule_executes_once_after_the_threshold() -> None:
    host = FakeHost(_trigger_settings({"kind": "no_input", "minutes": 1}))
    runtime = AutomationRuntime(
        host,
        FakeBackend(),
        interval_ms=10_000,
        idle_provider=lambda: 61.0,
    )

    runtime._tick()
    host._ble.confirm_all()
    writes = len(host._ble.writes)
    assert writes > 0, "idle time reached the snapshot but its rule never executed"

    runtime._tick()
    host._ble.confirm_all()
    assert len(host._ble.writes) == writes


def test_the_power_button_moves_with_the_automation() -> None:
    """Syncing without moving the button only re-describes the state it was already
    in, so the window would go on showing the light as it was."""

    class Button:
        def __init__(self) -> None:
            self.checked = True

        def setChecked(self, value: bool) -> None:
            self.checked = bool(value)

        def isChecked(self) -> bool:
            return self.checked

    host = FakeHost(_settings())
    host.power_button = Button()
    host.synced: list[bool] = []
    host._sync_power_button = lambda: host.synced.append(host.power_button.isChecked())
    runtime = _runtime(host)
    decision = type(
        "Decision", (), {"action": type("Action", (), {"type": "set_power", "power": False})()}
    )()

    runtime._reflect(decision)

    assert host.power_button.isChecked() is False, "the button kept its old state"
    assert host.synced == [False], "the window was synced before the button moved"
    assert host.power_calls == [False]


# ── background rules while the app is open ────────────────────────────
BACKGROUND_RULE = {
    "id": "evening-off",
    "name": "Evening off",
    "trigger": {"kind": "time", "time_at": "23:00", "days": [0, 1, 2, 3, 4, 5, 6]},
    "action": {"type": "set_power", "power": False, "target": "primary"},
    "execution": "background",
    "enabled": True,
}
EVENING = datetime(2026, 7, 26, 18, 0)
JUST_AFTER = datetime(2026, 7, 26, 23, 0, 30)


def _background_settings(**rule_overrides: Any) -> dict[str, Any]:
    rule = {**BACKGROUND_RULE, **rule_overrides}
    return {
        "automations": {"enabled": True, "rules": [rule], "migrated_version": 1},
        "last_device_address": PRIMARY,
    }


def _paused_at(when: datetime) -> bool:
    """Whether the shared intent holds automations off at that moment.

    A resume is recorded as "the pause ends now", not as an empty field: one field
    with one meaning, so the run path never has to tell two shapes apart.
    """
    ends_at = headless_module.load_control()["paused_until"]
    return ends_at is not None and ends_at > when


def _watching(rule_id: str = "evening-off", when: datetime = EVENING) -> None:
    headless_module.save_state({"seen_since": {rule_id: when}})


@contextmanager
def _clock(when: datetime):
    """Hold the clock the runtime reads still, so "overdue" is a fact not a race."""
    import app.automation.runtime as runtime_module

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return when

    original = runtime_module.datetime
    runtime_module.datetime = _Clock
    try:
        yield
    finally:
        runtime_module.datetime = original


def _tick_at(runtime: AutomationRuntime, host: FakeHost, when: datetime) -> None:
    with _clock(when):
        runtime._tick()
    host._ble.confirm_all()


def test_the_open_app_runs_a_background_rule_that_came_due() -> None:
    """A task starts a second process, and that process cannot take the strip while
    this one holds it — so leaving background rules to the tasks alone means the
    schedule fails exactly when the app is open."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == [("power", False, PRIMARY)]
    assert headless_module.load_state()["handled"]["evening-off"] == datetime(2026, 7, 26, 23, 0)
    assert host.power_calls == [False], "the app did not take on what it just did"


def test_it_runs_once_however_many_ticks_pass() -> None:
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    for _ in range(3):
        _tick_at(runtime, host, JUST_AFTER)

    assert len(host._ble.writes) == 1, "the occurrence was carried out more than once"


def test_an_occurrence_a_task_already_handled_is_left_alone() -> None:
    """The record is the arbitration: whoever got there first did it."""
    host = FakeHost(_background_settings())
    headless_module.save_state(
        {
            "seen_since": {"evening-off": EVENING},
            "handled": {"evening-off": datetime(2026, 7, 26, 23, 0)},
        }
    )
    runtime = _runtime(host)

    _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == []

    # And the record is the only reason: forget it and the same tick acts.
    headless_module.save_state({"seen_since": {"evening-off": EVENING}})
    _tick_at(runtime, host, JUST_AFTER)
    assert host._ble.writes == [("power", False, PRIMARY)]


def test_a_run_in_another_process_keeps_this_one_out() -> None:
    """Holding the execution lock stands in for a task's process mid-run: the app
    must not write alongside it, and must not sit waiting on the UI thread either."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    with file_lock(headless_module.execution_lock_path(), timeout=1.0) as locked:
        assert locked, "the test could not take the lock itself"
        _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == []
    assert headless_module.load_state()["handled"] == {}

    # Once that process is done, this one takes its turn.
    _tick_at(runtime, host, JUST_AFTER)
    assert host._ble.writes == [("power", False, PRIMARY)]


def test_the_lock_is_held_until_the_write_answers_and_then_let_go() -> None:
    """Released earlier, a task's process could start the same rule in the gap
    between deciding and finishing."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    _tick_at_without_answer(runtime, JUST_AFTER)
    with file_lock(headless_module.execution_lock_path(), timeout=0.0) as locked:
        assert locked is False, "the lock was let go while the write was in flight"

    host._ble.confirm_all()
    with file_lock(headless_module.execution_lock_path(), timeout=0.0) as locked:
        assert locked is True, "the lock was never released"


def _tick_at_without_answer(runtime: AutomationRuntime, when: datetime) -> None:
    with _clock(when):
        runtime._tick()


def test_a_write_that_failed_leaves_the_occurrence_for_the_next_attempt() -> None:
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    _tick_at_without_answer(runtime, JUST_AFTER)
    host._ble.fail_all()

    assert headless_module.load_state()["handled"] == {}, "a failed run was recorded as handled"
    with file_lock(headless_module.execution_lock_path(), timeout=0.0) as locked:
        assert locked is True, "the lock was not released after a failure"


def test_a_bridged_rule_is_left_to_the_old_in_app_schedule() -> None:
    """While the bridge is up the old schedule controller is still running and still
    switching the light at these times. Doing it here as well would do it twice."""
    settings = _background_settings(origin="legacy_schedule")
    settings["automations"]["legacy_bridge"] = True
    host = FakeHost(settings)
    _watching()
    runtime = _runtime(host)

    _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == []

    # Retire the bridge and the same rule becomes this engine's to run.
    host._settings["automations"]["legacy_bridge"] = False
    _tick_at(runtime, host, JUST_AFTER)
    assert host._ble.writes == [("power", False, PRIMARY)]


def test_a_disconnected_strip_leaves_it_to_the_task() -> None:
    """A task's process connects on demand, so this is one of the cases where
    standing aside is the better answer."""
    host = FakeHost(_background_settings())
    host._is_connected = False
    _watching()
    runtime = _runtime(host)

    _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == []

    host._is_connected = True
    _tick_at(runtime, host, JUST_AFTER)
    assert host._ble.writes == [("power", False, PRIMARY)]


def test_a_write_that_never_answers_does_not_keep_the_lock_for_ever() -> None:
    """The lock is machine-wide: holding it after we have stopped waiting would block
    every task's process too, and none of them would find out why."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    _tick_at_without_answer(runtime, JUST_AFTER)
    runtime._background_timed_out(runtime._background)

    with file_lock(headless_module.execution_lock_path(), timeout=0.0) as locked:
        assert locked is True, "a timed-out run kept the lock"
    assert headless_module.load_state()["handled"] == {}


# ── the losers of an overdue pile-up ──────────────────────────────────
def _two_overdue() -> dict[str, Any]:
    """An "on" and an "off" the machine slept through, both still owed."""
    return {
        "automations": {
            "enabled": True,
            "migrated_version": 1,
            "rules": [
                {**BACKGROUND_RULE, "id": "evening-on",
                 "trigger": {"kind": "time", "time_at": "19:00", "days": [0, 1, 2, 3, 4, 5, 6]},
                 "action": {"type": "set_power", "power": True, "target": "primary"}},
                {**BACKGROUND_RULE, "id": "evening-off"},
            ],
        },
        "last_device_address": PRIMARY,
    }


def test_the_loser_of_an_overdue_pile_up_does_not_run_next_tick() -> None:
    """The later crossing wins. Left owed, the earlier one would be found due on the
    very next tick and put the light straight back — the exact thing choosing one
    winner exists to prevent."""
    host = FakeHost(_two_overdue())
    headless_module.save_state(
        {"seen_since": {"evening-on": EVENING, "evening-off": EVENING}}
    )
    runtime = _runtime(host)

    for _ in range(3):
        _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == [("power", False, PRIMARY)], "the outranked rule ran too"
    handled = headless_module.load_state()["handled"]
    assert set(handled) == {"evening-on", "evening-off"}, "the loser was left owed"
    assert handled["evening-on"] == datetime(2026, 7, 26, 19, 0)


# ── the lifecycle of a run in flight ──────────────────────────────────
def test_stopping_mid_run_releases_the_lock_and_ignores_the_late_answer() -> None:
    """A window that closed holding the machine-wide lock would keep every Windows
    task from running an automation until the next restart."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    _tick_at_without_answer(runtime, JUST_AFTER)

    runtime.stop()

    with file_lock(headless_module.execution_lock_path(), timeout=0.0) as locked:
        assert locked is True, "closing left the lock held"

    host._ble.confirm_all()  # the write answers after we stopped waiting
    assert headless_module.load_state()["handled"] == {}, "a late answer was still counted"


def test_a_start_that_raised_does_not_wedge_the_engine(monkeypatch) -> None:
    """Leaving the run in place would stop the tick for good: every tick after it
    would see a background run that never ends."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    def explode(decision, done):
        runtime._background.handle = None
        raise RuntimeError("the executor is broken")

    monkeypatch.setattr(runtime._executor, "execute", explode)

    with pytest.raises(RuntimeError):
        _tick_at_without_answer(runtime, JUST_AFTER)

    assert runtime._background is None, "the engine was left with a run that never ends"
    with file_lock(headless_module.execution_lock_path(), timeout=0.0) as locked:
        assert locked is True, "the lock was not released"


def test_closing_the_window_releases_a_held_lock(monkeypatch) -> None:
    """The real close path, not just runtime.stop()."""
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "_start_deferred", lambda self, delay_ms, callback: None)
    window = MainWindow()
    try:
        lock = ProcessLock(headless_module.execution_lock_path())
        assert lock.acquire()
        window._automation_runtime = _StubRuntime(lock)

        stub = window._automation_runtime
        window.close()
        for _ in range(5):
            app.processEvents()

        assert stub.stopped is True, "closing never stopped the engine"
        assert window._automation_runtime is None
        # Not released by hand: the only thing that can have freed it is the stop()
        # the close triggered.
        with file_lock(headless_module.execution_lock_path(), timeout=0.0) as free:
            assert free is True, "the lock survived the window that was holding it"
    finally:
        window._ble.shutdown()
        window.close()
        for _ in range(5):
            app.processEvents()


class _StubRuntime:
    def __init__(self, lock) -> None:
        self._lock = lock
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True
        self._lock.release()


# ── the pause both sides honour ───────────────────────────────────────
def test_pausing_holds_the_background_off() -> None:
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    with _clock(JUST_AFTER):
        runtime.pause(seconds=3600)
    _tick_at(runtime, host, JUST_AFTER)

    assert host._ble.writes == [], "a paused automation still ran"
    assert runtime.paused_until() is not None


def test_a_pause_set_in_the_app_stops_a_task_process_too(monkeypatch) -> None:
    """A Windows task starts its own process, which would otherwise walk straight
    through a pause it never heard about."""
    from app.automation import headless
    from app.automation.headless import EXIT_OK, run_automations

    host = FakeHost(_background_settings())
    _watching()
    with _clock(JUST_AFTER):
        _runtime(host).pause(seconds=3600)

    storage.save_settings(
        {
            **storage.load_settings(),
            "automations": host._settings["automations"],
            "last_device_address": PRIMARY,
        }
    )
    monkeypatch.setattr(headless, "can_use", lambda feature: True)
    started: list[str] = []
    monkeypatch.setattr(
        headless, "BleController", lambda: started.append("connected") or _UnusedController()
    )

    assert run_automations(now=JUST_AFTER) == EXIT_OK
    assert started == [], "a task's process ran an automation during a pause"


class _UnusedController:
    def __getattr__(self, name):  # pragma: no cover - nothing should be called
        raise AssertionError(f"the controller was used during a pause: {name}")


def test_the_pause_lets_go_of_what_it_covered_when_it_runs_out() -> None:
    """Coming back to a light that switches itself twenty minutes later because an
    occurrence was waiting out the pause is a surprise, not a resumption."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=60)

    # The pause runs out, and only then does anything look at the rules again.
    later = JUST_AFTER + timedelta(minutes=30)
    _tick_at(runtime, host, later)

    assert host._ble.writes == [], "an occurrence from during the pause was replayed"
    assert _paused_at(later) is False, "the pause outlived its own deadline"
    assert "evening-off" in headless_module.load_state()["handled"]


def test_a_rule_that_comes_due_after_the_pause_still_runs() -> None:
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=60)

    # Long enough for the pause to end and for the next day's occurrence to come.
    tomorrow = JUST_AFTER + timedelta(days=1)
    _tick_at(runtime, host, tomorrow)

    assert host._ble.writes == [("power", False, PRIMARY)]


def test_resuming_by_hand_clears_the_pause() -> None:
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=3600)
        runtime.resume()

    assert _paused_at(JUST_AFTER) is False


def test_a_pause_survives_a_restart() -> None:
    """The shared state goes on holding background rules off, so the runtime rules —
    the app triggers the user paused in the first place — must not start again just
    because the window did."""
    host = FakeHost(_settings(automations={"enabled": True, "rules": [_APP_RULE]}))
    _add_scene(host._settings)
    first = _runtime(host, foreground="chrome.exe")
    with _clock(JUST_AFTER):
        assert first.pause(seconds=3600) is True

    second = _runtime(host, foreground="chrome.exe")
    with _clock(JUST_AFTER):
        second.start()
        second._tick()
    host._ble.confirm_all()

    assert host._ble.writes == [], "a paused automation ran after a restart"
    second.stop()


def test_a_pause_that_has_run_out_does_not_survive_a_restart() -> None:
    host = FakeHost(_settings(automations={"enabled": True, "rules": [_APP_RULE]}))
    _add_scene(host._settings)
    with _clock(JUST_AFTER):
        _runtime(host).pause(seconds=60)

    later = JUST_AFTER + timedelta(hours=2)
    second = _runtime(host, foreground="chrome.exe")
    with _clock(later):
        second.start()
        second._tick()
    host._ble.confirm_all()

    assert host._ble.writes, "the rule stayed paused after the pause had ended"
    second.stop()


_APP_RULE = {
    "id": "app-chrome",
    "name": "Chrome",
    "trigger": {"kind": "app_foreground", "app": "chrome"},
    "action": {"type": "apply_scene", "scene_id": "scene-chrome"},
    "execution": "runtime",
    "enabled": True,
}


def _add_scene(settings: dict[str, Any]) -> None:
    settings.setdefault("scenes", []).append(
        wrap_scene(
            {
                "scene_id": "scene-chrome",
                "name": "Chrome",
                "state": {"power": True, "rgb": [1, 2, 3], "brightness": 50},
            }
        )
    )


# ── the shared pause has to be written to mean anything ───────────────
def test_a_busy_lock_is_reported_and_the_pause_is_retried() -> None:
    """This process obeys either way — refusing to pause anything because a lock was
    busy would be worse — but the caller is told the machine has not heard, and the
    write is tried again until it lands."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    with file_lock(headless_module.control_lock_path(), timeout=1.0) as locked:
        assert locked
        with _clock(JUST_AFTER):
            assert runtime.pause(seconds=3600) is False, "a busy lock was reported as success"
        assert headless_module.load_control()["paused_until"] is None

    with _clock(JUST_AFTER):
        runtime._tick()

    assert headless_module.load_control()["paused_until"] is not None, "the pause was never retried"
    assert host._ble.writes == [], "the run went ahead during a pause this process knows about"


def test_a_pause_that_could_not_be_written_is_reported(monkeypatch) -> None:
    """The file write can fail even with the lock in hand, and claiming success would
    leave a task free to switch the light while the user believes it is paused."""
    host = FakeHost(_background_settings())
    runtime = _runtime(host)
    monkeypatch.setattr(headless_module, "_save_control", lambda control: False)

    with _clock(JUST_AFTER):
        assert runtime.pause(seconds=3600) is False


def test_a_busy_lock_is_reported_when_resuming() -> None:
    host = FakeHost(_background_settings())
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=3600)

    with file_lock(headless_module.control_lock_path(), timeout=1.0) as locked:
        assert locked
        assert runtime.resume() is False

    assert _paused_at(JUST_AFTER) is True, "the pause went away without being written"
    with _clock(JUST_AFTER):
        runtime._tick()
    assert _paused_at(JUST_AFTER) is False, "the resume was never retried"


def test_pausing_again_does_not_let_an_undelivered_resume_undo_it() -> None:
    """The user's older instruction must not undo their newer one: a resume that
    never reached the machine is no longer what they want."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=3600)

    with file_lock(headless_module.control_lock_path(), timeout=1.0) as locked:
        assert locked
        assert runtime.resume() is False  # the machine never hears about it

    with _clock(JUST_AFTER):
        assert runtime.pause(seconds=3600) is True
        runtime._tick()

    assert headless_module.load_control()["paused_until"] is not None, "the new pause was lifted"
    assert host._ble.writes == []


def test_closing_makes_a_last_attempt_at_an_undelivered_pause() -> None:
    """After this there are no more ticks to retry from, and the lock has just been
    let go by our own background run — so it is the likeliest moment to succeed."""
    host = FakeHost(_background_settings())
    runtime = _runtime(host)

    with file_lock(headless_module.control_lock_path(), timeout=1.0) as locked:
        assert locked
        with _clock(JUST_AFTER):
            assert runtime.pause(seconds=3600) is False
        assert headless_module.load_control()["paused_until"] is None

    runtime.stop()

    assert headless_module.load_control()["paused_until"] is not None, "the pause was dropped"


def test_the_pause_says_when_the_machine_has_not_been_told() -> None:
    """A UI that showed "paused" here would be promising something the app cannot
    deliver: a Windows task would still switch the light."""
    from app.automation.runtime import PAUSE_ACTIVE, PAUSE_ENDING, PAUSE_OFF, PAUSE_PENDING

    host = FakeHost(_background_settings())
    runtime = _runtime(host)
    assert runtime.pause_status() == PAUSE_OFF

    with file_lock(headless_module.control_lock_path(), timeout=1.0) as locked:
        assert locked
        with _clock(JUST_AFTER):
            runtime.pause(seconds=3600)
            assert runtime.pause_status() == PAUSE_PENDING

    with _clock(JUST_AFTER):
        runtime._tick()
        # Read on the same clock the pause was written on, or "an hour from now"
        # would be read against a date years later.
        assert runtime.pause_status() == PAUSE_ACTIVE

    with file_lock(headless_module.control_lock_path(), timeout=1.0) as locked:
        assert locked
        runtime.resume()
        assert runtime.pause_status() == PAUSE_ENDING

    with _clock(JUST_AFTER):
        runtime._tick()
        assert runtime.pause_status() == PAUSE_OFF


# ── an intent has to outlive the app that recorded it ─────────────────
def test_a_pause_survives_closing_while_a_run_holds_the_execution_lock() -> None:
    """The case a single retry cannot cover: a task's process is mid-run and keeps
    the execution lock for the whole close. The pause must still be there for it
    afterwards, so recording the intent never waits on that lock at all."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    with file_lock(headless_module.execution_lock_path(), timeout=1.0) as locked:
        assert locked, "the test could not take the execution lock"
        with _clock(JUST_AFTER):
            assert runtime.pause(seconds=3600) is True, "the pause waited on a run"
        runtime.stop()

    assert _paused_at(JUST_AFTER) is True, "closing lost the pause"


def test_a_resume_survives_closing_while_a_run_holds_the_execution_lock() -> None:
    """The mirror: automations are paused, the user lifts it, and the app closes
    while somebody else is running. The next process must see the resume, not go on
    holding everything off."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=3600)

    with file_lock(headless_module.execution_lock_path(), timeout=1.0) as locked:
        assert locked
        with _clock(JUST_AFTER):
            assert runtime.resume() is True, "the resume waited on a run"
        runtime.stop()

    assert _paused_at(JUST_AFTER) is False, "closing lost the resume"


def test_the_pause_that_ended_is_tidied_up_exactly_once() -> None:
    """The receipt is what makes that true: without it, every pass would treat the
    ended pause as fresh and go on marking whatever is due as handled."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)
    with _clock(JUST_AFTER):
        runtime.pause(seconds=60)

    after = JUST_AFTER + timedelta(minutes=5)
    _tick_at(runtime, host, after)
    generation = headless_module.load_state()["pause_generation"]
    handled = dict(headless_module.load_state()["handled"])

    # A second pass, and a third: the ended pause is not consumed again.
    _tick_at(runtime, host, after)
    _tick_at(runtime, host, after + timedelta(minutes=1))

    assert headless_module.load_state()["pause_generation"] == generation
    assert headless_module.load_state()["handled"] == handled


def test_a_task_process_honours_a_pause_it_never_saw_being_set(monkeypatch) -> None:
    """The whole point of the control file: the app that paused may be long gone."""
    from app.automation import headless
    from app.automation.headless import EXIT_OK, run_automations

    host = FakeHost(_background_settings())
    _watching()
    with _clock(JUST_AFTER):
        _runtime(host).pause(seconds=3600)

    storage.save_settings(
        {
            **storage.load_settings(),
            "automations": host._settings["automations"],
            "last_device_address": PRIMARY,
        }
    )
    monkeypatch.setattr(headless, "can_use", lambda feature: True)
    monkeypatch.setattr(headless, "BleController", _UnusedController)

    assert run_automations(now=JUST_AFTER) == EXIT_OK


def test_resuming_when_nothing_is_paused_does_not_swallow_what_is_owed() -> None:
    """A resume with nothing to resume must not look like a pause that began and
    ended in the same instant: the run path would let go of everything owed up to
    that moment, and the overdue rule would never run at all."""
    host = FakeHost(_background_settings())
    _watching()
    runtime = _runtime(host)

    with _clock(JUST_AFTER):
        assert runtime.resume() is True
        runtime._tick()
    host._ble.confirm_all()

    assert host._ble.writes == [("power", False, PRIMARY)], "the overdue rule was swallowed"


def test_a_resume_with_no_pause_leaves_the_control_state_alone() -> None:
    host = FakeHost(_background_settings())
    runtime = _runtime(host)
    before = headless_module.load_control()

    with _clock(JUST_AFTER):
        assert runtime.resume() is True

    assert headless_module.load_control() == before, "a resume invented a pause to end"


def test_a_lost_control_file_cannot_make_a_new_pause_look_already_settled() -> None:
    """Its generation reads as zero when the file is damaged. Numbering a fresh
    intent below the receipt already in the state would mark it dealt with, and the
    end of that pause would never be tidied up."""
    host = FakeHost(_background_settings())
    _watching()
    headless_module.save_state({"seen_since": {"evening-off": EVENING}, "pause_generation": 7})
    storage.automation_control_path().write_text("{ not json", encoding="utf-8")
    runtime = _runtime(host)

    with _clock(JUST_AFTER):
        assert runtime.pause(seconds=60) is True
    assert headless_module.load_control()["generation"] > 7, "the intent was numbered too low"

    # And once it ends, the run path does tidy it up rather than skip it as done.
    after = JUST_AFTER + timedelta(minutes=5)
    _tick_at(runtime, host, after)

    assert host._ble.writes == [], "the pause was ignored as already settled"
    assert headless_module.load_state()["pause_generation"] == 8
