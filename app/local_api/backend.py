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
from app.driver_capabilities import capabilities_for
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
        self._invoker.call(lambda: self._apply_power(on, device_id))

    def set_color(self, red: int, green: int, blue: int, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_color(red, green, blue, device_id))

    def set_brightness(self, value: int, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_brightness(value, device_id))

    def set_effect(self, code: int, speed: int | None, device_id: str | None) -> None:
        self._invoker.call(lambda: self._apply_effect(code, speed, device_id))

    def apply_quick_mode(self, key: str) -> bool:
        return self._invoker.call(lambda: self._apply_quick_mode(key))

    def set_pc_mode(self, mode: str, preset: str | None = None) -> bool:
        return self._invoker.call(lambda: self._set_pc_mode(mode, preset))

    # ── scenes ────────────────────────────────────────────────────────
    def list_scenes(self) -> list[dict[str, Any]]:
        return self._invoker.call(self._list_scenes)

    def save_scene(self, name: str) -> dict[str, Any] | None:
        return self._invoker.call(lambda: self._save_scene(name))

    def apply_scene(self, scene_id: str) -> dict[str, Any] | None:
        return self._invoker.call(lambda: self._apply_scene(scene_id))

    def delete_scene(self, scene_id: str) -> bool:
        return self._invoker.call(lambda: self._delete_scene(scene_id))

    # ── shared with the automation executor ───────────────────────────
    # It writes to the strips itself, through tracked BLE commands, but the
    # questions of *which* strips a scene means and what each of them can do are
    # already answered here — and answering them twice is how the phone and an
    # automation would start applying the same scene differently.
    def resolve_scene_targets(self, target: Any) -> list[str] | None:
        return self._invoker.call(lambda: self._resolve_scene_targets(target))

    def capabilities_for_device(self, device_id: str | None) -> dict[str, Any]:
        return self._invoker.call(lambda: self._capabilities_for(device_id))

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
            # The stable id of the active mode's variant (currently the screen
            # profile). The phone still reads the bare "pc_mode" string; this is
            # extra, so scenes can restore the exact look.
            "pc_mode_preset": self._active_pc_mode_preset(pc),
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
    # "screen" and "screen_music" are both run by the Fusion controller and are
    # asked for by name, never inferred from whatever the card happens to be set
    # to. A scene saved as "screen + music" must light the same way on a machine
    # whose local chooser says "screen", and a command that says "screen" must
    # not quietly start the combined mode.
    _PC_MODES = (("_software_fx_ui", "effect"), ("_diy_ui", "diy"))
    _FUSION_MODES = ("screen", "screen_music")

    def _active_pc_mode(self) -> str | None:
        fusion = getattr(self._host, "_fusion_ui", None)
        if fusion is not None and fusion.is_running():
            return str(fusion.mode())
        music = getattr(self._host, "_music_ui", None)
        standalone = getattr(music, "is_standalone_running", None) if music else None
        if callable(standalone) and standalone():
            return "music"
        for attr, key in self._PC_MODES:
            controller = getattr(self._host, attr, None)
            if controller is not None and controller.is_running():
                return key
        return None

    def _active_pc_mode_preset(self, mode: str | None) -> str | None:
        # The screen profile, in both of the modes that capture the screen.
        if mode not in self._FUSION_MODES:
            return None
        segment = getattr(self._host, "ambient_profile_segment", None)
        if segment is not None:
            return str(segment.current_key())
        return None

    def _set_pc_mode(self, mode: str, preset: str | None = None) -> bool:
        host = self._host
        wanted = str(mode or "").strip().lower()
        if wanted in ("", "off", "none", "stop"):
            host.stop_streams()  # back to plain manual colour
            return True
        if wanted in self._FUSION_MODES:
            ambient = getattr(host, "_ambient_ui", None)
            if ambient is None:
                return False
            # Named, not read off the card: the mode goes in with the command so
            # the result does not depend on what this machine was last left
            # showing. The card's own controller owns the gate and the chooser.
            return bool(ambient.activate(preset, mode=wanted))
        if wanted == "music":
            music = getattr(host, "_music_ui", None)
            if music is None:
                return False
            # Explicitly the standalone reaction: "music" as an API mode is the
            # one that owns the strip by itself, whatever the card is set to.
            return bool(music.activate_standalone())
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

    # ── addressed vs whole-set commands ───────────────────────────────
    # No device_id -> the familiar whole-set path through the host (sliders move,
    # every strip follows, /status updates). A device_id -> an addressed BLE write
    # that touches only that strip; the desktop UI is synced (without re-sending)
    # only when the address is the primary, so a mirror-only write never drags the
    # global sliders around.
    def _primary_address(self) -> str:
        settings = self._settings()
        return str(settings.get("last_device_address", "")).strip()

    def _is_primary(self, device_id: str | None) -> bool:
        address = str(device_id or "").strip()
        return bool(address) and address == self._primary_address()

    def _apply_power(self, on: bool, device_id: str | None = None) -> None:
        host = self._host
        if device_id:
            host._ble.set_power_for_addresses(bool(on), [str(device_id).strip()])
            if self._is_primary(device_id):
                host.power_button.setChecked(bool(on))  # reflect, don't re-send
                # The streams belong to the primary strip, so an address-targeted
                # command still has to reach them. Without this the capture keeps
                # running and the colour keeps going out to a strip that was just
                # switched off.
                apply_to_streams = getattr(host, "apply_power_to_streams", None)
                if callable(apply_to_streams):
                    apply_to_streams(bool(on))
                remember_power = getattr(host, "_remember_power_setting", None)
                if callable(remember_power):
                    remember_power(bool(on))
                else:
                    # Lightweight protocol fakes and embedders may not own the
                    # MainWindow persistence helper. Keep their in-memory status
                    # truthful without assuming a concrete host class.
                    self._settings().setdefault("last_state", {})["power"] = bool(on)
            return
        host.power_button.setChecked(bool(on))
        host._toggle_power()

    def _apply_color(self, red: int, green: int, blue: int, device_id: str | None = None) -> None:
        host = self._host
        if device_id:
            host._ble.set_color_for_addresses(int(red), int(green), int(blue), [str(device_id).strip()])
            if self._is_primary(device_id):
                self._sync_primary_color(int(red), int(green), int(blue))
            return
        self._sync_primary_color(int(red), int(green), int(blue))
        host._apply_current_color()

    def _sync_primary_color(self, red: int, green: int, blue: int) -> None:
        host = self._host
        with host._suppress_signals():
            host.red_slider.setValue(red)
            host.green_slider.setValue(green)
            host.blue_slider.setValue(blue)

    def _apply_brightness(self, value: int, device_id: str | None = None) -> None:
        host = self._host
        value = max(0, min(100, int(value)))
        if device_id:
            host._ble.set_brightness_for_addresses(value, [str(device_id).strip()])
            if self._is_primary(device_id):
                with host._suppress_signals():
                    host.brightness_slider.setValue(value)
            return
        host.brightness_slider.setValue(value)
        host._apply_current_color()

    def _apply_effect(self, code: int, speed: int | None, device_id: str | None = None) -> None:
        host = self._host
        if device_id:
            host._ble.set_effect_for_addresses(int(code), speed, [str(device_id).strip()])
            if self._is_primary(device_id):
                # Reflect both the effect *and* its speed, or /status and the next
                # scene snapshot would keep reporting the old speed.
                index = host.effect_combo.findData(int(code))
                slider = getattr(host, "speed_slider", None)
                with host._suppress_signals():
                    if index >= 0:
                        host.effect_combo.setCurrentIndex(index)
                    if speed is not None and slider is not None:
                        slider.setValue(int(speed))
            return
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
        device_ids = self._resolve_scene_targets(scene.get("target"))
        report = SceneApplyService(self).apply(
            scene,
            capabilities=self._strip_capabilities(),
            device_ids=device_ids,
            capabilities_for=self._capabilities_for,
        )
        # Which strips this actually reached, named, so the UI can say so.
        report["targets"] = self._target_names(device_ids)
        return report

    def _resolve_scene_targets(self, target: Any) -> list[str] | None:
        """``None`` for a whole-set scene — the familiar path that also moves the
        desktop sliders. An explicit address list when the scene targets the
        primary strip or a group, which routes as addressed BLE writes."""
        target = target if isinstance(target, dict) else {}
        if target.get("kind", "all") == "all":
            return None
        primary = self._primary_address() or None
        try:
            mirror = list(self._host._ble.mirror_addresses())
        except Exception:
            mirror = []
        all_addresses = ([primary] if primary else []) + [str(m).strip() for m in mirror if str(m).strip()]
        resolved = scene_store.resolve_target(
            self._settings(), target, primary=primary, all_addresses=all_addresses
        )
        # Keep only strips that are connected right now. A saved group can still
        # name a strip that is offline or has been removed; sending to it would be
        # dropped silently by the BLE layer while the report claimed the scene
        # reached it.
        connected = set(all_addresses)
        return [address for address in resolved if address in connected]

    def _target_names(self, device_ids: list[str] | None) -> list[str]:
        settings = self._settings()
        names = self._device_names()
        primary = self._primary_address()
        if device_ids is None:
            addresses = [device["address"] for device in self._build_devices()]
        else:
            addresses = [str(address).strip() for address in device_ids if str(address).strip()]
        labels = []
        for address in addresses:
            fallback = str(settings.get("last_device_name", "")) if address == primary else ""
            labels.append(device_display_name(address, fallback, names))
        return labels

    def _capabilities_for(self, device_id: str | None) -> dict[str, Any]:
        """Capabilities of one specific strip. A group can mix controllers, so an
        effect supported on the primary may be missing on a mirror — resolving per
        target keeps the apply report honest."""
        if not device_id:
            return self._strip_capabilities()
        ble = self._host._ble
        try:
            caps = capabilities_for(ble.driver_id_for_address(device_id))
        except Exception:
            caps = capabilities_for("")
        try:
            caps["effect_speed"] = bool(ble.supports_effect_speed_for_address(device_id))
        except Exception:
            pass
        return caps

    def _strip_capabilities(self) -> dict[str, Any]:
        """Real capabilities of the connected controller so a scene skips fields
        the hardware can't do (e.g. CCT) instead of assuming defaults."""
        driver_id = ""
        try:
            driver_id = self._host._ble.active_driver_id()
        except Exception:
            driver_id = ""
        caps = capabilities_for(driver_id)
        try:
            caps["effect_speed"] = bool(self._host._ble.supports_effect_speed())
        except Exception:
            pass
        return caps

    def _delete_scene(self, scene_id: str) -> bool:
        removed = scene_store.delete_scene(self._settings(), str(scene_id or ""))
        if removed:
            save_settings(self._host._settings)
        return removed
