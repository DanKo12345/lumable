from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from PySide6.QtCore import QTime

from app.schedule_controller import ScheduleController

# ── fake host ─────────────────────────────────────────────────────────

def _make_host(*, enabled: bool = False, on_time: str = "19:00", off_time: str = "23:00",
               is_connected: bool = False, power_on: bool = False) -> MagicMock:
    host = MagicMock()
    host._initializing = False
    host._is_connected = is_connected
    host._settings = {}
    host._ble = MagicMock()

    toggle = MagicMock()
    toggle.isChecked.return_value = enabled
    host.schedule_toggle_button = toggle

    on = MagicMock()
    on.time.return_value = QTime.fromString(on_time, "HH:mm")
    host.schedule_on_time = on

    off = MagicMock()
    off.time.return_value = QTime.fromString(off_time, "HH:mm")
    host.schedule_off_time = off

    power = MagicMock()
    power.isChecked.return_value = power_on
    host.power_button = power

    @contextmanager
    def suppress():
        yield
    host._suppress_signals = suppress
    host._tr.side_effect = lambda key, **_: key

    return host


def _make_ctrl(host: MagicMock) -> ScheduleController:
    ctrl = ScheduleController.__new__(ScheduleController)
    ctrl._host = host
    ctrl._last_fire = set()
    return ctrl


# ── settings() ────────────────────────────────────────────────────────

def test_settings_returns_enabled_state(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.can_use", lambda _: True)
    host = _make_host(enabled=True, on_time="20:00", off_time="22:30")
    ctrl = _make_ctrl(host)

    result = ctrl.settings()

    assert result["enabled"] is True
    assert result["on_time"] == "20:00"
    assert result["off_time"] == "22:30"


def test_settings_returns_disabled_when_toggle_off(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.can_use", lambda _: True)
    host = _make_host(enabled=False)
    ctrl = _make_ctrl(host)

    assert ctrl.settings()["enabled"] is False


def test_settings_returns_disabled_when_not_pro(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.can_use", lambda _: False)
    host = _make_host(enabled=True)
    ctrl = _make_ctrl(host)

    assert ctrl.settings()["enabled"] is False


# ── time_from_text() ──────────────────────────────────────────────────

def test_time_from_text_parses_valid_time() -> None:
    ctrl = _make_ctrl(_make_host())
    fallback = QTime(9, 0)

    result = ctrl.time_from_text("14:30", fallback)

    assert result == QTime(14, 30)


def test_time_from_text_returns_fallback_for_invalid() -> None:
    ctrl = _make_ctrl(_make_host())
    fallback = QTime(9, 0)

    result = ctrl.time_from_text("not-a-time", fallback)

    assert result == fallback


# ── trigger_scheduled_power() ─────────────────────────────────────────

def test_trigger_scheduled_power_on_calls_ble(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.save_settings", lambda _: None)
    host = _make_host(is_connected=True, power_on=False)
    ctrl = _make_ctrl(host)

    ctrl.trigger_scheduled_power(True, "2026-01-01:on:19:00")

    host._ble.set_power.assert_called_once_with(True)
    host.power_button.setChecked.assert_called_once_with(True)


def test_trigger_scheduled_power_skips_when_not_connected() -> None:
    host = _make_host(is_connected=False)
    ctrl = _make_ctrl(host)

    ctrl.trigger_scheduled_power(True, "2026-01-01:on:19:00")

    host._ble.set_power.assert_not_called()
    host._log.assert_called_once()


def test_trigger_scheduled_power_skips_duplicate_fire_key() -> None:
    host = _make_host(is_connected=True, power_on=False)
    ctrl = _make_ctrl(host)
    fire_key = "2026-01-01:on:19:00"
    ctrl._last_fire.add(fire_key)

    ctrl.trigger_scheduled_power(True, fire_key)

    host._ble.set_power.assert_not_called()


def test_trigger_scheduled_power_skips_when_already_in_desired_state(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.save_settings", lambda _: None)
    host = _make_host(is_connected=True, power_on=True)
    ctrl = _make_ctrl(host)

    ctrl.trigger_scheduled_power(True, "2026-01-01:on:19:00")

    host._ble.set_power.assert_not_called()
    host._log.assert_called_once()


def test_trigger_scheduled_power_records_fire_key(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.save_settings", lambda _: None)
    host = _make_host(is_connected=True, power_on=False)
    ctrl = _make_ctrl(host)
    fire_key = "2026-06-01:on:19:00"

    ctrl.trigger_scheduled_power(True, fire_key)

    assert fire_key in ctrl._last_fire


# ── _check_schedule() ─────────────────────────────────────────────────

def test_check_schedule_does_not_fire_when_disabled() -> None:
    host = _make_host(enabled=False)
    ctrl = _make_ctrl(host)

    ctrl._check_schedule()

    host._ble.set_power.assert_not_called()


def test_check_schedule_does_not_fire_during_initializing() -> None:
    host = _make_host(enabled=True)
    host._initializing = True
    ctrl = _make_ctrl(host)

    ctrl._check_schedule()

    host._ble.set_power.assert_not_called()


def test_check_schedule_fires_power_on_at_scheduled_time(monkeypatch) -> None:
    monkeypatch.setattr("app.schedule_controller.save_settings", lambda _: None)
    now = QTime.currentTime()
    on_str = now.toString("HH:mm")

    host = _make_host(enabled=True, on_time=on_str, off_time="03:00",
                      is_connected=True, power_on=False)
    ctrl = _make_ctrl(host)

    ctrl._check_schedule()

    host._ble.set_power.assert_called_once_with(True)
