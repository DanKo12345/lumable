from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QObject, QTimer

from app.ble import BleController
from app.feature_gate import can_use
from app.storage import load_settings, save_settings, validate_schedule

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
        settings = load_settings()
        settings.setdefault("last_state", {})["power"] = self._action == "on"
        save_settings(settings)
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


def run_scheduled_action(action: str) -> int:
    action = str(action).strip().lower()
    if action not in {"on", "off"}:
        print("Usage: LumaBLE.exe --scheduled-action on|off", file=sys.stderr)
        return 2

    settings = load_settings()
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
