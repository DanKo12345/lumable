"""Qt adapter that lets the (background-thread) API talk to the app safely.

The HTTP server runs on a worker thread, but Qt widgets and the BLE controller
must only be touched from the main thread. ``_MainThreadInvoker`` marshals a
callable onto the main thread and waits for the result; ``QtApiBackend`` uses it
to map API actions onto the same host operations the tray quick-controls use.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal

from app.app_info import APP_VERSION
from app.device_names import device_display_name
from app.quick_modes import QUICK_MODE_MAP

_CALL_TIMEOUT_SECONDS = 3.0


class _MainThreadInvoker(QObject):
    """Runs a callable on the thread this object lives on (the main thread)."""

    _invoke = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._invoke.connect(self._run, Qt.QueuedConnection)

    def _run(self, fn: Callable[[], None]) -> None:
        fn()

    def call(self, fn: Callable[[], Any], timeout: float = _CALL_TIMEOUT_SECONDS) -> Any:
        # Already on the main thread? Just run it — avoids a self-deadlock.
        if QThread.currentThread() is self.thread():
            return fn()
        done = threading.Event()
        box: dict[str, Any] = {}

        def wrapper() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # surfaced to the caller
                box["error"] = exc
            finally:
                done.set()

        self._invoke.emit(wrapper)
        if not done.wait(timeout):
            raise TimeoutError("main thread did not respond in time")
        if "error" in box:
            raise box["error"]
        return box.get("result")


class QtApiBackend:
    """Implements the ApiBackend protocol against a live MainWindow host."""

    def __init__(self, host: Any, invoker: _MainThreadInvoker | None = None) -> None:
        self._host = host
        self._invoker = invoker or _MainThreadInvoker()

    # ── reads ─────────────────────────────────────────────────────────
    def app_version(self) -> str:
        return APP_VERSION

    def status(self) -> dict[str, Any]:
        return self._invoker.call(self._build_status)

    def devices(self) -> list[dict[str, Any]]:
        return self._invoker.call(self._build_devices)

    # ── commands ──────────────────────────────────────────────────────
    def set_power(self, on: bool, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_power(on))

    def set_color(self, red: int, green: int, blue: int, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_color(red, green, blue))

    def set_brightness(self, value: int, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_brightness(value))

    def set_effect(self, code: int, speed: int | None, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_effect(code, speed))

    def apply_quick_mode(self, key: str) -> bool:
        return self._invoker.call(lambda: self._apply_quick_mode(key))

    # ── main-thread implementations ───────────────────────────────────
    def _build_status(self) -> dict[str, Any]:
        host = self._host
        return {
            "connected": bool(host._is_connected),
            "power": bool(host.power_button.isChecked()),
            "brightness": int(host.brightness_slider.value()),
            "color": {
                "r": int(host.red_slider.value()),
                "g": int(host.green_slider.value()),
                "b": int(host.blue_slider.value()),
            },
            "mode": getattr(host, "_active_mode_key", None) or None,
        }

    def _device_names(self) -> dict[str, str]:
        names = self._host._settings.get("device_names") if isinstance(self._host._settings, dict) else {}
        return names if isinstance(names, dict) else {}

    def _build_devices(self) -> list[dict[str, Any]]:
        host = self._host
        names = self._device_names()
        devices: list[dict[str, Any]] = []
        primary = str(host._settings.get("last_device_address", "")).strip()
        if primary:
            devices.append(
                {
                    "address": primary,
                    "name": device_display_name(primary, str(host._settings.get("last_device_name", "")), names),
                    "role": "primary",
                    "connected": bool(host._is_connected),
                }
            )
        for address in host._ble.mirror_addresses():
            devices.append(
                {
                    "address": address,
                    "name": device_display_name(address, "", names),
                    "role": "mirror",
                    "connected": bool(host._is_connected),
                }
            )
        return devices

    def _apply_power(self, on: bool) -> None:
        host = self._host
        host.power_button.setChecked(bool(on))
        host._toggle_power()

    def _apply_color(self, red: int, green: int, blue: int) -> None:
        host = self._host
        with host._suppress_signals():
            host.red_slider.setValue(int(red))
            host.green_slider.setValue(int(green))
            host.blue_slider.setValue(int(blue))
        host._apply_current_color()

    def _apply_brightness(self, value: int) -> None:
        host = self._host
        host.brightness_slider.setValue(max(0, min(100, int(value))))
        host._apply_current_color()

    def _apply_effect(self, code: int, speed: int | None) -> None:
        host = self._host
        index = host.effect_combo.findData(int(code))
        if index >= 0:
            host.effect_combo.setCurrentIndex(index)
            if speed is not None:
                host._ble.set_effect_speed(int(speed))
        elif speed is not None:
            host._ble.set_effect_with_speed(int(code), int(speed))
        else:
            host._ble.set_effect(int(code))

    def _apply_quick_mode(self, key: str) -> bool:
        host = self._host
        valid = set(QUICK_MODE_MAP.keys())
        for mode in getattr(host, "_custom_quick_modes", None) or []:
            custom_key = str(mode.get("key", "")).strip()
            if custom_key:
                valid.add(custom_key)
        if key not in valid:
            return False
        host._activate_quick_mode(key)
        return True
