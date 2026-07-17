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

from app import scene_store
from app.app_info import APP_VERSION
from app.device_names import device_display_name
from app.quick_modes import QUICK_MODE_MAP
from app.scene_apply import SceneApplyService, scene_from_status
from app.storage import save_settings

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

    def set_pc_mode(self, mode: str) -> bool:
        return self._invoker.call(lambda: self._set_pc_mode(mode))

    # ── scenes ────────────────────────────────────────────────────────
    def list_scenes(self) -> list[dict[str, Any]]:
        return self._invoker.call(self._list_scenes)

    def save_scene(self, name: str) -> dict[str, Any] | None:
        return self._invoker.call(lambda: self._save_scene(name))

    def apply_scene(self, scene_id: str) -> dict[str, Any] | None:
        return self._invoker.call(lambda: self._apply_scene(scene_id))

    def delete_scene(self, scene_id: str) -> bool:
        return self._invoker.call(lambda: self._delete_scene(scene_id))

    # ── main-thread implementations ───────────────────────────────────
    def _build_status(self) -> dict[str, Any]:
        host = self._host
        primary = str(host._settings.get("last_device_address", "")).strip() if isinstance(host._settings, dict) else ""
        name = (
            device_display_name(primary, str(host._settings.get("last_device_name", "")), self._device_names())
            if primary
            else ""
        )
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
            "name": name,
            "effect": self._active_firmware_effect(),
            "pc_mode": (pc := self._active_pc_mode()),
            "pc_mode_detail": self._pc_mode_detail(pc),
        }

    def _active_firmware_effect(self) -> dict[str, Any] | None:
        # The controller's built-in effect currently selected (code 0 = solid, so
        # "no effect"). Speed comes from the effect-speed slider. Kept defensive
        # so a fake host without these widgets simply reports no effect.
        host = self._host
        combo = getattr(host, "effect_combo", None)
        code = combo.currentData() if combo is not None and hasattr(combo, "currentData") else 0
        if not isinstance(code, int) or code == 0:
            return None
        slider = getattr(host, "speed_slider", None)
        speed = int(slider.value()) if slider is not None and hasattr(slider, "value") else None
        return {"kind": "firmware", "ref": int(code), "speed": speed}

    def _pc_mode_detail(self, mode: str | None) -> str:
        # For "effect", the phone can't see which software effect is running, so
        # surface its localised name (e.g. "Rainbow"). Other modes have none.
        if mode != "effect":
            return ""
        host = self._host
        saved = host._settings.get("software_fx", {}) if isinstance(host._settings, dict) else {}
        key = str(saved.get("effect", "")).strip() if isinstance(saved, dict) else ""
        translate = getattr(host, "_tr", None)
        if not key or not callable(translate):
            return ""
        try:
            return str(translate(f"software_fx.effect_{key}"))
        except Exception:
            return ""

    # PC "hub" modes exposed to the phone: which live stream (if any) the desktop
    # is currently running. The name is the stable API key; the label is localised
    # on the phone side.
    _PC_MODES = (("_ambient_ui", "screen"), ("_music_ui", "music"), ("_software_fx_ui", "effect"), ("_diy_ui", "diy"))

    def _active_pc_mode(self) -> str | None:
        for attr, key in self._PC_MODES:
            controller = getattr(self._host, attr, None)
            if controller is not None and controller.is_running():
                return key
        return None

    def _set_pc_mode(self, mode: str) -> bool:
        host = self._host
        wanted = str(mode or "").strip().lower()
        if wanted in ("", "off", "none", "stop"):
            host.stop_streams()  # back to plain manual colour
            return True
        for attr, key in self._PC_MODES:
            if key != wanted:
                continue
            controller = getattr(host, attr, None)
            if controller is None:
                return False
            if controller.is_running():
                return True
            # activate() reports the real outcome — a Free licence or a missing
            # BLE connection can silently refuse to start the stream.
            return bool(controller.activate())
        return False

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

    # ── scene main-thread implementations ─────────────────────────────
    def _settings(self) -> dict[str, Any]:
        settings = self._host._settings
        return settings if isinstance(settings, dict) else {}

    def _list_scenes(self) -> list[dict[str, Any]]:
        return scene_store.list_scenes(self._settings())

    def _save_scene(self, name: str) -> dict[str, Any] | None:
        scene = scene_from_status(self._build_status(), str(name or ""))
        saved = scene_store.save_scene(self._settings(), scene)
        if saved is not None:
            save_settings(self._host._settings)
        return saved

    def _apply_scene(self, scene_id: str) -> dict[str, Any] | None:
        scene = scene_store.get_scene(self._settings(), str(scene_id or ""))
        if scene is None:
            return None
        # HONEST LIMITATION (0.3.2): the BLE layer has no per-strip addressing yet,
        # so every command mirrors to all connected strips regardless of device_id.
        # We therefore apply to the whole set (device_ids=None) rather than pretend
        # a scene's target is honoured. The scene model already carries a target and
        # SceneApplyService can route per-device; wiring the BLE addressed path and
        # exposing target/group in the UI lands in 0.3.3.
        return SceneApplyService(self).apply(scene)

    def _delete_scene(self, scene_id: str) -> bool:
        removed = scene_store.delete_scene(self._settings(), str(scene_id or ""))
        if removed:
            save_settings(self._host._settings)
        return removed
