"""Controller-level tests for TimerController.

These exercise the sleep countdown and the daily sunrise wake-light against a
lightweight fake host, so no real BLE hardware or Qt widgets are needed. They
require PySide6 (QObject/QTime/QColor) but never start an event loop — every
tick is driven manually.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QTime
from PySide6.QtGui import QColor

import app.timer_controller as tc
from app.timer_controller import TimerController
from app.timers import hm_to_seconds


# ── fakes ──────────────────────────────────────────────────────────────
class FakeButton:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked
        self.text = ""
        self.role = ""

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        self._checked = bool(value)

    def setText(self, text: str) -> None:
        self.text = text

    def set_role(self, role: str) -> None:
        self.role = role


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class FakeSlider:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class FakeTimeEdit:
    def __init__(self, qtime: QTime) -> None:
        self._time = qtime

    def time(self) -> QTime:
        return self._time

    def setTime(self, qtime: QTime) -> None:
        self._time = qtime


class FakeSwatch:
    def __init__(self, color: QColor) -> None:
        self._color = color

    def color(self) -> QColor:
        return self._color

    def set_color(self, color: QColor) -> None:
        self._color = color


class FakeBle:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def set_color_stream(self, r: int, g: int, b: int) -> None:
        self.calls.append(("stream", r, g, b))

    def set_color(self, r: int, g: int, b: int) -> None:
        self.calls.append(("color", r, g, b))

    def set_power(self, on: bool) -> None:
        self.calls.append(("power", on))

    def set_brightness(self, value: int) -> None:
        self.calls.append(("brightness", value))


class FakeHost(QObject):
    def __init__(self, *, connected: bool = True, powered: bool = True) -> None:
        super().__init__()
        self._settings = {}
        self._is_connected = connected
        self._ble = FakeBle()
        self.power_button = FakeButton(checked=powered)
        self.red_slider = FakeSlider(200)
        self.green_slider = FakeSlider(100)
        self.blue_slider = FakeSlider(50)
        self.timer_sleep_button = FakeButton()
        self.timer_sleep_pill = FakeLabel()
        self.timer_sleep_status = FakeLabel()
        self.timer_sunrise_button = FakeButton()
        self.timer_sunrise_pill = FakeLabel()
        self.timer_sunrise_status = FakeLabel()
        self.timer_sunrise_time = FakeTimeEdit(QTime(7, 0))
        self.timer_sunrise_swatch = FakeSwatch(QColor(255, 180, 120))
        self.logs: list[str] = []
        self.errors: list[str] = []
        self.power_toggled = 0
        self.synced = 0

    def _tr(self, key: str, **_kw: object) -> str:
        return key

    def _log(self, msg: str) -> None:
        self.logs.append(msg)

    def _show_error(self, msg: str) -> None:
        self.errors.append(msg)

    def _toggle_power(self) -> None:
        self.power_toggled += 1

    def _sync_power_button(self) -> None:
        self.synced += 1

    def _color_history(self) -> list:
        return []


@pytest.fixture(autouse=True)
def _no_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the real settings file from a controller test."""
    monkeypatch.setattr(tc, "save_settings", lambda *_a, **_k: None)


def _make(**kw) -> tuple[TimerController, FakeHost]:
    host = FakeHost(**kw)
    return TimerController(host), host


def _kinds(ble: FakeBle) -> list[str]:
    return [c[0] for c in ble.calls]


# ── sleep ──────────────────────────────────────────────────────────────
def test_sleep_start_activates_and_keeps_power_on() -> None:
    ctrl, host = _make(powered=True)
    host.timer_sleep_button.setChecked(True)  # click toggles state first
    ctrl._toggle_sleep()
    assert ctrl._sleep_active is True
    assert ctrl._sleep_was_off is False
    assert ctrl._sleep_base == (200, 100, 50)
    assert host.power_button.isChecked() is True


def test_sleep_start_when_disconnected_shows_error() -> None:
    ctrl, host = _make(connected=False)
    host.timer_sleep_button.setChecked(True)
    ctrl._toggle_sleep()
    assert ctrl._sleep_active is False
    assert host.timer_sleep_button.isChecked() is False
    assert host.errors == ["timers.not_connected"]


def test_sleep_cancel_restores_power_off_when_it_was_off() -> None:
    ctrl, host = _make(powered=False)  # strip is off before starting
    host.timer_sleep_button.setChecked(True)
    ctrl._toggle_sleep()
    assert ctrl._sleep_was_off is True
    # Cancel: button toggles off, then handler runs.
    host.timer_sleep_button.setChecked(False)
    ctrl._toggle_sleep()
    assert ctrl._sleep_active is False
    assert ("power", False) in host._ble.calls
    assert host.power_button.isChecked() is False


def test_sleep_tick_completes_and_powers_off() -> None:
    ctrl, host = _make(powered=True)
    host.timer_sleep_button.setChecked(True)
    ctrl._toggle_sleep()
    # Force the countdown past its end.
    ctrl._sleep_start = time.monotonic() - (ctrl._sleep_duration + 5)
    ctrl._tick_sleep()
    assert ctrl._sleep_active is False
    assert ("power", False) in host._ble.calls
    assert host.power_button.isChecked() is False


def test_sleep_tick_streams_dimmed_colour_midway() -> None:
    ctrl, host = _make(powered=True)
    host.timer_sleep_button.setChecked(True)
    ctrl._toggle_sleep()
    ctrl._sleep_start = time.monotonic() - (ctrl._sleep_duration / 2)
    ctrl._tick_sleep()
    assert "stream" in _kinds(host._ble)
    assert ctrl._sleep_active is True


# ── sunrise ────────────────────────────────────────────────────────────
def test_sunrise_fires_and_finalizes_at_target() -> None:
    ctrl, host = _make(powered=False)
    host.timer_sunrise_button.setChecked(True)
    ctrl._sunrise_minutes = 20
    # Now == target: elapsed equals the full duration -> ramp finishes.
    ctrl._now_seconds = lambda: hm_to_seconds(7, 0)
    ctrl._tick_sunrise()
    assert ("brightness", 100) in host._ble.calls
    assert ("color", 255, 180, 120) in host._ble.calls
    assert ctrl._sunrise_active is False
    assert ctrl._sunrise_last_fire != ""
    # Still armed for tomorrow.
    assert host.timer_sunrise_button.isChecked() is True


def test_sunrise_missed_window_does_nothing_and_stays_armed() -> None:
    ctrl, host = _make(powered=False)
    host.timer_sunrise_button.setChecked(True)
    ctrl._sunrise_minutes = 20
    # Well past the target -> outside the ramp window.
    ctrl._now_seconds = lambda: hm_to_seconds(9, 0)
    ctrl._tick_sunrise()
    assert host._ble.calls == []
    assert ctrl._sunrise_active is False
    assert ctrl._sunrise_last_fire == ""
    assert host.timer_sunrise_button.isChecked() is True


def test_sunrise_yields_to_active_sleep() -> None:
    ctrl, host = _make(powered=True)
    host.timer_sunrise_button.setChecked(True)
    ctrl._sunrise_minutes = 20
    ctrl._sleep_active = True  # sleep owns the strip
    ctrl._now_seconds = lambda: hm_to_seconds(7, 0)
    ctrl._tick_sunrise()
    assert host._ble.calls == []
    assert ctrl._sunrise_active is False


def test_sunrise_ramps_before_target() -> None:
    ctrl, host = _make(powered=False)
    host.timer_sunrise_button.setChecked(True)
    ctrl._sunrise_minutes = 20
    # Halfway into the window.
    ctrl._now_seconds = lambda: hm_to_seconds(6, 50)
    ctrl._tick_sunrise()
    assert ("brightness", 100) in host._ble.calls
    assert "stream" in _kinds(host._ble)
    assert ctrl._sunrise_active is True  # still ramping, not finished


def test_sunrise_disconnected_waits() -> None:
    ctrl, host = _make(connected=False, powered=False)
    host.timer_sunrise_button.setChecked(True)
    ctrl._sunrise_minutes = 20
    ctrl._now_seconds = lambda: hm_to_seconds(7, 0)
    ctrl._tick_sunrise()
    assert host._ble.calls == []
    assert ctrl._sunrise_active is False
