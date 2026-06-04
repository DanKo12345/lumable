from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QDate, Qt, QTime, QTimer

from app.constants import SCHEDULE_MISSED_WINDOW_MINUTES
from app.feature_gate import can_use
from app.schedule import should_fire_schedule_time
from app.storage import save_settings, validate_schedule


class ScheduleHost(Protocol):
    _ble: Any
    _initializing: bool
    _is_connected: bool
    _settings: dict

    schedule_toggle_button: Any
    schedule_on_time: Any
    schedule_off_time: Any
    power_button: Any

    def _log(self, message: str) -> None: ...

    def _show_license_overlay(self) -> None: ...

    def _suppress_signals(self): ...

    def _sync_power_button(self) -> None: ...

    def _sync_quick_mode_from_state(self, preferred: str | None = None) -> None: ...

    def _tr(self, key: str, **kwargs: object) -> str: ...


class ScheduleController:
    def __init__(self, host: ScheduleHost) -> None:
        self._host = host
        self._last_fire: set[str] = set()
        self._timer = QTimer(host)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self._check_schedule)

    def start(self) -> None:
        self._timer.start()

    def wire(self) -> None:
        host = self._host
        host.schedule_toggle_button.clicked.connect(self.toggle_schedule)
        host.schedule_on_time.timeChanged.connect(self.save_settings)
        host.schedule_off_time.timeChanged.connect(self.save_settings)

    def load_state(self) -> None:
        self.apply_settings(self._host._settings.get("schedule", {}), save=False, run_check=False)

    def apply_settings(self, schedule: dict, *, save: bool = True, run_check: bool = True) -> None:
        host = self._host
        normalized = validate_schedule(schedule)
        if bool(normalized.get("enabled", False)) and not can_use("schedule"):
            normalized["enabled"] = False
        with host._suppress_signals():
            host.schedule_toggle_button.setChecked(bool(normalized.get("enabled", False)))
            host.schedule_on_time.setTime(self.time_from_text(str(normalized.get("on_time", "19:00")), QTime(19, 0)))
            host.schedule_off_time.setTime(self.time_from_text(str(normalized.get("off_time", "23:00")), QTime(23, 0)))
        self.sync_controls()
        if save and not host._initializing:
            host._settings["schedule"] = self.settings()
            self._last_fire.clear()
            save_settings(host._settings)
            if run_check:
                QTimer.singleShot(0, self._check_schedule)

    def time_from_text(self, text: str, fallback: QTime) -> QTime:
        parsed = QTime.fromString(text, "HH:mm")
        return parsed if parsed.isValid() else fallback

    def settings(self) -> dict:
        host = self._host
        return {
            "enabled": host.schedule_toggle_button.isChecked() and can_use("schedule"),
            "on_time": host.schedule_on_time.time().toString("HH:mm"),
            "off_time": host.schedule_off_time.time().toString("HH:mm"),
        }

    def save_settings(self, *_args: object) -> None:
        host = self._host
        if host._initializing:
            return
        host._settings["schedule"] = self.settings()
        self._last_fire.clear()
        save_settings(host._settings)
        self.sync_controls()
        QTimer.singleShot(0, self._check_schedule)

    def toggle_schedule(self, _checked: bool = False) -> None:
        host = self._host
        if host.schedule_toggle_button.isChecked() and not can_use("schedule"):
            with host._suppress_signals():
                host.schedule_toggle_button.setChecked(False)
            self.sync_controls()
            host._settings["schedule"] = self.settings()
            save_settings(host._settings)
            host._show_license_overlay()
            return
        self.save_settings()
        host._log(host._tr("schedule.enabled_log") if host.schedule_toggle_button.isChecked() else host._tr("schedule.disabled_log"))

    def sync_controls(self) -> None:
        host = self._host
        enabled = host.schedule_toggle_button.isChecked()
        host.schedule_toggle_button.setText(host._tr("schedule.toggle_on") if enabled else host._tr("schedule.toggle_off"))
        host.schedule_toggle_button.set_role("accent_soft" if enabled else "ghost")
        host.schedule_on_time.setEnabled(enabled)
        host.schedule_off_time.setEnabled(enabled)

    def _check_schedule(self) -> None:
        host = self._host
        if host._initializing or not hasattr(host, "schedule_toggle_button") or not host.schedule_toggle_button.isChecked():
            return
        now_time = QTime.currentTime()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        on_time = host.schedule_on_time.time()
        off_time = host.schedule_off_time.time()
        on_text = on_time.toString("HH:mm")
        off_text = off_time.toString("HH:mm")
        if should_fire_schedule_time(now_time, on_time, missed_window_minutes=SCHEDULE_MISSED_WINDOW_MINUTES):
            self.trigger_scheduled_power(True, f"{today}:on:{on_text}")
        if should_fire_schedule_time(now_time, off_time, missed_window_minutes=SCHEDULE_MISSED_WINDOW_MINUTES):
            self.trigger_scheduled_power(False, f"{today}:off:{off_text}")

    def trigger_scheduled_power(self, enabled: bool, fire_key: str) -> None:
        host = self._host
        if fire_key in self._last_fire:
            return
        self._last_fire.add(fire_key)
        if not host._is_connected:
            host._log(host._tr("schedule.skipped_not_connected"))
            return
        if host.power_button.isChecked() == enabled:
            host._log(host._tr("schedule.already_on" if enabled else "schedule.already_off"))
            return
        host.power_button.setChecked(enabled)
        host._sync_power_button()
        host._ble.set_power(enabled)
        host._sync_quick_mode_from_state()
        host._log(host._tr("schedule.power_on" if enabled else "schedule.power_off"))
