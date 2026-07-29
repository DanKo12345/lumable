from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QObject, QTimer

from app.ble import BleController
from app.feature_gate import can_use
from app.storage import load_settings, update_power_setting, validate_schedule

ACTION_TIMEOUT_MS = 30_000
WRITE_SETTLE_MS = 2_800


class _ScheduledActionRunner(QObject):
    def __init__(self, action: str, address: str) -> None:
        super().__init__()
        self._action = action
        self._address = address
        self._ble = BleController()
        self._finished = False
        self.exit_code = 1
        self._ble.connected_changed.connect(self._on_connected_changed)
        self._ble.error_occurred.connect(self._on_error)
        self._ble.status_changed.connect(self._on_status)

    def start(self) -> None:
        print(f"LumaBLE scheduled action: {self._action} -> {self._address}")
        QTimer.singleShot(ACTION_TIMEOUT_MS, self._on_timeout)
        self._ble.connect_to_address(self._address)

    def _on_connected_changed(self, connected: bool, _address: str) -> None:
        if self._finished or not connected:
            return
        self._ble.set_power(self._action == "on", restore_state=False)
        QTimer.singleShot(WRITE_SETTLE_MS, self._finish_success)

    def _on_error(self, message: str) -> None:
        if self._finished:
            return
        print(f"LumaBLE scheduled action error: {message}", file=sys.stderr)
        self._finish(1)

    def _on_status(self, message: str) -> None:
        if message:
            print(message)

    def _on_timeout(self) -> None:
        if self._finished:
            return
        print("LumaBLE scheduled action timed out.", file=sys.stderr)
        self._finish(1)

    def _finish_success(self) -> None:
        if self._finished:
            return
        update_power_setting(self._action == "on")
        self._finish(0)

    def _finish(self, exit_code: int) -> None:
        if self._finished:
            return
        self._finished = True
        self.exit_code = exit_code
        try:
            self._ble.shutdown()
        finally:
            QCoreApplication.quit()


def bridge_rule_id(settings: dict, action: str) -> str:
    """The migrated rule this legacy task now stands for, or "" if there is none.

    Every condition has to hold — automations on, the bridge up, the rule present
    and enabled — because the fallback is the 0.3.5 executor below, and that is the
    thing keeping the user's schedule working. A migration that never happened, a
    rule the user deleted, or a handoff already completed all mean: do it the old
    way, exactly as this build did before.
    """
    from app.automation.migration import LEGACY_OFF_ID, LEGACY_ON_ID
    from app.automation.rules import validate_rules
    from app.storage import validate_automations

    automations = validate_automations(settings.get("automations", {}))
    if not automations.get("enabled") or not automations.get("legacy_bridge"):
        return ""
    wanted = LEGACY_ON_ID if action == "on" else LEGACY_OFF_ID
    for rule in validate_rules(automations.get("rules", [])):
        if rule.id == wanted and rule.enabled:
            return rule.id
    return ""


def run_scheduled_action(action: str) -> int:
    action = str(action).strip().lower()
    if action not in {"on", "off"}:
        print("Usage: LumaBLE.exe --scheduled-action on|off", file=sys.stderr)
        return 2

    settings = load_settings()

    bridged = bridge_rule_id(settings, action)
    if bridged:
        # The 0.3.5 tasks are still what wakes the machine, but the rule they stand
        # for has been migrated: hand the wake-up to the engine that now owns it.
        # It decides against the rules and the clock as they are now, so a pair of
        # times missed during a sleep produces one winner instead of two writes in
        # whatever order the processes happen to finish.
        from app.automation.headless import run_automations

        return run_automations(woken_by=bridged)

    schedule = validate_schedule(settings.get("schedule", {}))
    if not schedule.get("enabled"):
        print("LumaBLE schedule is disabled; nothing to do.")
        return 0
    if not can_use("schedule"):
        print("LumaBLE schedule requires Pro; nothing to do.", file=sys.stderr)
        return 3

    address = str(settings.get("last_device_address", "")).strip()
    if not address:
        print("LumaBLE scheduled action has no saved controller address.", file=sys.stderr)
        return 4

    app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    runner = _ScheduledActionRunner(action, address)
    QTimer.singleShot(0, runner.start)
    app.exec()
    return runner.exit_code
