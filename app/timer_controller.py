from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QDate, Qt, QTime, QTimer
from PySide6.QtGui import QColor

from app.storage import save_settings
from app.timers import (
    MAX_MINUTES,
    MIN_MINUTES,
    SLEEP,
    SUNRISE,
    hm_to_seconds,
    ramp_level,
    scale_rgb,
    sunrise_elapsed,
)
from app.widgets import ColorPickerOverlay, ProfileRenameOverlay

_DEFAULT_SUNRISE_RGB = (255, 180, 120)


def _clamp_minutes(value: Any, default: int = 30) -> int:
    try:
        return max(MIN_MINUTES, min(MAX_MINUTES, int(value)))
    except (TypeError, ValueError):
        return default


class TimerController:
    """Sunrise / sleep light timers. Both are a smooth brightness ramp streamed
    over the BLE colour path (so they work on any controller):
      • sleep   — from now, fade the current colour to off over N minutes,
      • sunrise — a daily wake light: finish ramping the target colour up to full
        at HH:MM (starting N minutes before), once per day. Free feature."""

    def __init__(self, host: Any) -> None:
        self._host = host
        self._sleep_minutes = 30
        self._sunrise_minutes = 20
        self._sleep_active = False
        self._sleep_start = 0.0
        self._sleep_duration = 0
        self._sleep_base: tuple[int, int, int] = (255, 255, 255)
        self._sleep_was_off = False
        self._sunrise_active = False
        self._sunrise_last_fire = ""  # "YYYY-MM-DD:HH:mm" the ramp last completed for
        self._minutes_overlay: ProfileRenameOverlay | None = None
        self._color_picker: ColorPickerOverlay | None = None
        self._timer = QTimer(host)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        self._timer.start()

    def wire(self) -> None:
        host = self._host
        host.timer_sleep_button.clicked.connect(self._toggle_sleep)
        host.timer_sleep_pill.clicked.connect(lambda: self._edit_minutes(SLEEP))
        host.timer_sunrise_button.clicked.connect(self._toggle_sunrise)
        host.timer_sunrise_pill.clicked.connect(lambda: self._edit_minutes(SUNRISE))
        host.timer_sunrise_swatch.clicked.connect(self._pick_sunrise_color)
        host.timer_sunrise_time.timeChanged.connect(self._persist)
        self.load_state()

    def _config(self) -> dict:
        host = self._host
        cfg = host._settings.get("timers", {}) if isinstance(host._settings, dict) else {}
        return cfg if isinstance(cfg, dict) else {}

    def load_state(self) -> None:
        host = self._host
        cfg = self._config()
        self._sleep_minutes = _clamp_minutes(cfg.get("sleep_minutes", 30), 30)
        self._sunrise_minutes = _clamp_minutes(cfg.get("sunrise_minutes", 20), 20)
        parsed = QTime.fromString(str(cfg.get("sunrise_time", "07:00")), "HH:mm")
        host.timer_sunrise_time.setTime(parsed if parsed.isValid() else QTime(7, 0))
        color = cfg.get("sunrise_color", {}) if isinstance(cfg.get("sunrise_color"), dict) else {}
        host.timer_sunrise_swatch.set_color(QColor(
            int(color.get("r", _DEFAULT_SUNRISE_RGB[0])),
            int(color.get("g", _DEFAULT_SUNRISE_RGB[1])),
            int(color.get("b", _DEFAULT_SUNRISE_RGB[2])),
        ))
        host.timer_sunrise_button.setChecked(bool(cfg.get("sunrise_armed", False)))
        self._refresh_labels()

    def _persist(self, *_args: object) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        swatch = host.timer_sunrise_swatch.color()
        host._settings["timers"] = {
            "sleep_minutes": self._sleep_minutes,
            "sunrise_minutes": self._sunrise_minutes,
            "sunrise_time": host.timer_sunrise_time.time().toString("HH:mm"),
            "sunrise_color": {"r": swatch.red(), "g": swatch.green(), "b": swatch.blue()},
            "sunrise_armed": host.timer_sunrise_button.isChecked(),
        }
        save_settings(host._settings)

    # ── shared ────────────────────────────────────────────────────────
    def _current_rgb(self) -> tuple[int, int, int]:
        host = self._host
        try:
            rgb = (host.red_slider.value(), host.green_slider.value(), host.blue_slider.value())
        except Exception:
            rgb = (255, 255, 255)
        return rgb if any(rgb) else (255, 255, 255)

    def _stop_other_streams(self) -> None:
        self._host.stop_streams(exclude=self)

    def _mark_sunrise_handled_today(self) -> None:
        """Record today's window as done so a stopped ramp doesn't immediately
        re-fire and fight whatever took over. Stays armed for tomorrow."""
        host = self._host
        t = host.timer_sunrise_time.time()
        self._sunrise_last_fire = f"{QDate.currentDate().toString('yyyy-MM-dd')}:{t.toString('HH:mm')}"

    def stop_if_running(self) -> None:
        """Yield the strip to another owner (another stream started, power was
        toggled, or the controller disconnected). Cancels an active sleep
        countdown and stops an in-progress sunrise ramp for today; the sunrise
        stays armed for the next day."""
        if self._sleep_active:
            self._sleep_active = False
            self._host.timer_sleep_button.setChecked(False)
            self._refresh_labels()
        if self._sunrise_active:
            self._sunrise_active = False
            self._mark_sunrise_handled_today()
            self._refresh_labels()

    def _ensure_power_on(self) -> None:
        host = self._host
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()

    def _remember_power(self, enabled: bool) -> None:
        remember_power = getattr(self._host, "_remember_power_setting", None)
        if callable(remember_power):
            remember_power(bool(enabled))

    # ── sleep timer ───────────────────────────────────────────────────
    def _toggle_sleep(self) -> None:
        host = self._host
        if not host.timer_sleep_button.isChecked():
            self._end_sleep()
            return
        if not host._is_connected:
            host.timer_sleep_button.setChecked(False)
            host._show_error(host._tr("timers.not_connected"))
            return
        self._sleep_was_off = not host.power_button.isChecked()
        self._stop_other_streams()
        self._ensure_power_on()
        self._sleep_base = self._current_rgb()
        self._sleep_duration = self._sleep_minutes * 60
        self._sleep_start = time.monotonic()
        self._sleep_active = True
        self._refresh_labels()
        host._log(host._tr("timers.sleep_started", mins=self._sleep_minutes))

    def _end_sleep(self, *, powered_off: bool = False) -> None:
        host = self._host
        was_active = self._sleep_active
        self._sleep_active = False
        host.timer_sleep_button.setChecked(False)
        self._refresh_labels()
        if was_active and not powered_off:
            # Cancelled mid-fade: restore the state we started from — power back
            # off if the strip was off, otherwise bring the colour back to full.
            if self._sleep_was_off:
                host._ble.set_power(False)
                host.power_button.setChecked(False)
                host._sync_power_button()
                self._remember_power(False)
            else:
                host._ble.set_color(*self._sleep_base)
            host._log(host._tr("timers.sleep_cancelled"))

    def _tick_sleep(self) -> None:
        if not self._sleep_active:
            return
        host = self._host
        elapsed = time.monotonic() - self._sleep_start
        if elapsed >= self._sleep_duration:
            host._ble.set_power(False)
            host.power_button.setChecked(False)
            host._sync_power_button()
            self._remember_power(False)
            self._end_sleep(powered_off=True)
            host._log(host._tr("timers.sleep_done"))
            return
        level = ramp_level(elapsed, self._sleep_duration, kind=SLEEP)
        host._ble.set_color_stream(*scale_rgb(self._sleep_base, level))
        remaining = max(1, round((self._sleep_duration - elapsed) / 60))
        host.timer_sleep_status.setText(host._tr("timers.sleep_active", mins=remaining))

    # ── sunrise alarm ─────────────────────────────────────────────────
    def _toggle_sunrise(self) -> None:
        host = self._host
        armed = host.timer_sunrise_button.isChecked()
        if not armed and self._sunrise_active:
            self._sunrise_active = False
        # Re-arming clears the per-day guard so it can still fire today.
        self._sunrise_last_fire = ""
        self._persist()
        self._refresh_labels()
        host._log(host._tr("timers.sunrise_armed_log" if armed else "timers.sunrise_disarmed_log"))

    @staticmethod
    def _now_seconds() -> int:
        now = QTime.currentTime()
        return now.hour() * 3600 + now.minute() * 60 + now.second()

    def _tick_sunrise(self) -> None:
        host = self._host
        if not host.timer_sunrise_button.isChecked():
            self._sunrise_active = False
            return
        if self._sleep_active:
            return  # sleep owns the strip
        t = host.timer_sunrise_time.time()
        duration_s = self._sunrise_minutes * 60
        elapsed = sunrise_elapsed(self._now_seconds(), hm_to_seconds(t.hour(), t.minute()), duration_s)
        if elapsed is None:
            return  # outside today's ramp window
        # Daily wake light: run once per day. If the window was missed (app off /
        # disconnected the whole time), nothing gets stuck — it simply fires the
        # next day.
        fire_key = f"{QDate.currentDate().toString('yyyy-MM-dd')}:{t.toString('HH:mm')}"
        if not self._sunrise_active and self._sunrise_last_fire == fire_key:
            return
        if not host._is_connected:
            return  # can't run without a controller; try again next tick
        target = host.timer_sunrise_swatch.color()
        rgb = (target.red(), target.green(), target.blue())
        if not self._sunrise_active:
            self._stop_other_streams()
            self._ensure_power_on()
            host._ble.set_brightness(100)
            self._sunrise_active = True
            host._log(host._tr("timers.sunrise_started"))
        host._ble.set_color_stream(*scale_rgb(rgb, ramp_level(elapsed, duration_s, kind=SUNRISE)))
        if elapsed >= duration_s:
            host._ble.set_color(*rgb)
            self._sunrise_active = False
            self._sunrise_last_fire = fire_key  # stays armed for tomorrow
            self._refresh_labels()
            host._log(host._tr("timers.sunrise_done"))

    def _tick(self) -> None:
        self._tick_sleep()
        self._tick_sunrise()

    # ── editing ───────────────────────────────────────────────────────
    def _edit_minutes(self, kind: str) -> None:
        host = self._host
        if self._minutes_overlay is not None:
            self._minutes_overlay.raise_()
            return
        current = self._sleep_minutes if kind == SLEEP else self._sunrise_minutes
        overlay = ProfileRenameOverlay(
            {
                "title": host._tr("timers.sleep" if kind == SLEEP else "timers.sunrise"),
                "prompt": host._tr("timers.minutes_prompt"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            str(current),
            host,
        )
        self._minutes_overlay = overlay
        overlay.nameSelected.connect(lambda text, k=kind: self._apply_minutes(k, text))
        overlay.closed.connect(lambda: setattr(self, "_minutes_overlay", None))
        overlay.open()

    def _apply_minutes(self, kind: str, text: str) -> None:
        minutes = _clamp_minutes(text, self._sleep_minutes if kind == SLEEP else self._sunrise_minutes)
        if kind == SLEEP:
            self._sleep_minutes = minutes
        else:
            self._sunrise_minutes = minutes
        self._persist()
        self._refresh_labels()

    def _pick_sunrise_color(self) -> None:
        host = self._host
        if self._color_picker is not None:
            self._color_picker.raise_()
            return
        picker = ColorPickerOverlay(
            host._tr("timers.pick_color"),
            host.timer_sunrise_swatch.color(),
            {
                "red": host._tr("slider.red"),
                "green": host._tr("slider.green"),
                "blue": host._tr("slider.blue"),
                "hex": host._tr("color.hex"),
                "recent": host._tr("color.recent"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            host._color_history(),
            host,
        )
        self._color_picker = picker
        picker.colorSelected.connect(self._apply_sunrise_color)
        picker.closed.connect(lambda: setattr(self, "_color_picker", None))
        picker.open()

    def _apply_sunrise_color(self, color: QColor) -> None:
        self._host.timer_sunrise_swatch.set_color(color)
        self._persist()

    # ── presentation ──────────────────────────────────────────────────
    def _minutes_label(self, minutes: int) -> str:
        return f"{minutes} {self._host._tr('timers.minutes_short')}"

    @staticmethod
    def _set_active(widget: object, active: bool) -> None:
        """Flip the QSS `active` state on a row and repaint it."""
        if widget is None or widget.property("active") == active:
            return
        widget.setProperty("active", active)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)

    def _refresh_row_states(self, *, sleep_active: bool, sunrise_armed: bool) -> None:
        host = self._host
        self._set_active(getattr(host, "timer_sleep_row", None), sleep_active)
        self._set_active(getattr(host, "timer_sleep_status", None), sleep_active)
        self._set_active(getattr(host, "timer_sunrise_row", None), sunrise_armed)
        self._set_active(getattr(host, "timer_sunrise_status", None), sunrise_armed)

    def _refresh_labels(self) -> None:
        host = self._host
        host.timer_sleep_pill.setText(self._minutes_label(self._sleep_minutes))
        host.timer_sunrise_pill.setText(self._minutes_label(self._sunrise_minutes))
        host.timer_sleep_button.setText(host._tr("timers.cancel") if self._sleep_active else host._tr("timers.start"))
        host.timer_sleep_button.set_role("accent_soft" if self._sleep_active else "ghost")
        if not self._sleep_active:
            host.timer_sleep_status.setText(host._tr("timers.sleep_idle"))
        armed = host.timer_sunrise_button.isChecked()
        host.timer_sunrise_button.setText(host._tr("timers.disarm") if armed else host._tr("timers.arm"))
        host.timer_sunrise_button.set_role("accent_soft" if armed else "ghost")
        if armed:
            host.timer_sunrise_status.setText(
                host._tr("timers.sunrise_next", time=host.timer_sunrise_time.time().toString("HH:mm"))
            )
        else:
            host.timer_sunrise_status.setText(host._tr("timers.sunrise_idle"))
        self._refresh_row_states(sleep_active=self._sleep_active, sunrise_armed=armed)

    def relocalize(self) -> None:
        self._refresh_labels()
