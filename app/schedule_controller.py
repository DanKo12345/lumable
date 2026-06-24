from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QDate, Qt, QTime, QTimer

from app.constants import SCHEDULE_MISSED_WINDOW_MINUTES
from app.feature_gate import can_use
from app.schedule import is_scheduled_day, should_fire_schedule_time
from app.startup_controller import (
    are_schedule_tasks_enabled,
    is_startup_enabled,
    set_schedule_tasks_enabled,
    set_startup_enabled,
)
from app.storage import save_settings, validate_schedule


class ScheduleHost(Protocol):
    _ble: Any
    _initializing: bool
    _is_connected: bool
    _settings: dict

    schedule_toggle_button: Any
    schedule_startup_button: Any
    schedule_on_time: Any
    schedule_off_time: Any
    schedule_day_buttons: Any
    power_button: Any

    def _log(self, message: str) -> None: ...

    def _show_license_overlay(self) -> None: ...

    def _show_error(self, message: str) -> None: ...

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
        host.schedule_startup_button.clicked.connect(self.toggle_startup)
        host.schedule_on_time.timeChanged.connect(self.save_settings)
        host.schedule_off_time.timeChanged.connect(self.save_settings)
        for chip in host.schedule_day_buttons:
            chip.clicked.connect(self.save_settings)

    def load_state(self) -> None:
        self.apply_settings(self._host._settings.get("schedule", {}), save=False, run_check=False)

    def apply_settings(self, schedule: dict, *, save: bool = True, run_check: bool = True) -> None:
        host = self._host
        normalized = validate_schedule(schedule)
        if bool(normalized.get("enabled", False)) and not can_use("schedule"):
            normalized["enabled"] = False
        if bool(normalized.get("startup_enabled", False)) and not can_use("schedule"):
            normalized["startup_enabled"] = False
        with host._suppress_signals():
            host.schedule_toggle_button.setChecked(bool(normalized.get("enabled", False)))
            host.schedule_startup_button.setChecked(
                bool(normalized.get("startup_enabled", False)) and (is_startup_enabled() or are_schedule_tasks_enabled())
            )
            host.schedule_on_time.setTime(self.time_from_text(str(normalized.get("on_time", "19:00")), QTime(19, 0)))
            host.schedule_off_time.setTime(self.time_from_text(str(normalized.get("off_time", "23:00")), QTime(23, 0)))
            days = set(normalized.get("days", []))
            for index, chip in enumerate(host.schedule_day_buttons):
                chip.setChecked(index in days)
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
            "startup_enabled": host.schedule_startup_button.isChecked() and can_use("schedule"),
            "days": self._selected_days(),
        }

    def _selected_days(self) -> list[int]:
        return [index for index, chip in enumerate(self._host.schedule_day_buttons) if chip.isChecked()]

    def save_settings(self, *_args: object) -> None:
        host = self._host
        if host._initializing:
            return
        host._settings["schedule"] = self.settings()
        self._last_fire.clear()
        save_settings(host._settings)
        if host.schedule_startup_button.isChecked() or are_schedule_tasks_enabled():
            self._sync_background_schedule_tasks()
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

    def toggle_startup(self, _checked: bool = False) -> None:
        host = self._host
        requested = host.schedule_startup_button.isChecked()
        if requested and not can_use("schedule"):
            with host._suppress_signals():
                host.schedule_startup_button.setChecked(False)
            self.sync_controls()
            host._settings["schedule"] = self.settings()
            save_settings(host._settings)
            host._show_license_overlay()
            return
        try:
            set_startup_enabled(requested)
            self._sync_background_schedule_tasks(force_enabled=requested)
        except OSError as exc:
            with host._suppress_signals():
                host.schedule_startup_button.setChecked(is_startup_enabled())
            self.sync_controls()
            host._show_error(host._tr("schedule.startup_error", error=str(exc)))
            return
        self.save_settings()
        host._log(host._tr("schedule.startup_enabled_log") if requested else host._tr("schedule.startup_disabled_log"))

    def sync_controls(self) -> None:
        host = self._host
        lock_label = getattr(host, "schedule_lock_label", None)
        if lock_label is not None:
            lock_label.setVisible(not can_use("schedule"))
        enabled = host.schedule_toggle_button.isChecked()
        startup_enabled = host.schedule_startup_button.isChecked() and enabled
        host.schedule_toggle_button.setText(host._tr("schedule.toggle_on") if enabled else host._tr("schedule.toggle_off"))
        host.schedule_toggle_button.set_role("accent_soft" if enabled else "ghost")
        host.schedule_startup_button.setText(
            host._tr("schedule.startup_on") if startup_enabled else host._tr("schedule.startup_off")
        )
        host.schedule_startup_button.set_role("accent_soft" if startup_enabled else "ghost")
        host.schedule_startup_button.setEnabled(enabled)
        host.schedule_on_time.setEnabled(enabled)
        host.schedule_off_time.setEnabled(enabled)
        for chip in host.schedule_day_buttons:
            chip.setEnabled(enabled)

    def _sync_background_schedule_tasks(self, *, force_enabled: bool | None = None) -> None:
        host = self._host
        if host._initializing:
            return
        enabled = (
            host.schedule_toggle_button.isChecked() and host.schedule_startup_button.isChecked()
            if force_enabled is None
            else bool(force_enabled and host.schedule_toggle_button.isChecked())
        )
        try:
            set_schedule_tasks_enabled(
                enabled and can_use("schedule"),
                on_time=host.schedule_on_time.time().toString("HH:mm"),
                off_time=host.schedule_off_time.time().toString("HH:mm"),
                days=self._selected_days(),
            )
        except OSError as exc:
            if enabled:
                host._show_error(host._tr("schedule.startup_error", error=str(exc)))

    def _check_schedule(self) -> None:
        host = self._host
        if host._initializing or not hasattr(host, "schedule_toggle_button") or not host.schedule_toggle_button.isChecked():
            return
        # Qt: dayOfWeek() is 1=Mon..7=Sun; our days are 0=Mon..6=Sun.
        if not is_scheduled_day(QDate.currentDate().dayOfWeek() - 1, self._selected_days()):
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
