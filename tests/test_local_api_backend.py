"""QtApiBackend maps API actions onto the same host operations the tray uses.

Runs the invoker on the test's own (main) thread, where it executes directly —
no event loop needed."""

from __future__ import annotations

import contextlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject

from app.app_info import APP_VERSION
from app.local_api.backend import QtApiBackend


class _Slider:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = int(value)


class _Power:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        self._checked = bool(value)


class _Combo:
    def __init__(self, codes: dict[int, int], current_code: int = 0) -> None:
        self._codes = codes  # code -> index
        self.current = -1
        self.current_code = current_code  # 0 = solid / no firmware effect

    def findData(self, code: int) -> int:
        return self._codes.get(int(code), -1)

    def setCurrentIndex(self, index: int) -> None:
        self.current = index

    def currentData(self):
        return self.current_code


class _Ble:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def mirror_addresses(self):
        return ["CC:DD"]

    def set_effect(self, code):
        self.calls.append(("effect", code))

    def set_effect_with_speed(self, code, speed):
        self.calls.append(("effect_speed", code, speed))

    def set_effect_speed(self, value):
        self.calls.append(("speed", value))


class _Host(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.power_button = _Power(True)
        self.red_slider = _Slider(10)
        self.green_slider = _Slider(20)
        self.blue_slider = _Slider(30)
        self.brightness_slider = _Slider(80)
        self.speed_slider = _Slider(60)
        self.effect_combo = _Combo({7: 3, 12: 5})
        self._ble = _Ble()
        self._is_connected = True
        self._active_mode_key = "gaming"
        self._custom_quick_modes: list[dict] = []
        self._settings = {"last_device_address": "AA:BB", "last_device_name": "Strip", "device_names": {"AA:BB": "Desk"}}
        self.toggled = 0
        self.applied = 0
        self.stops = 0
        self.activated: list[str] = []

    def stop_streams(self, **_):
        self.stops += 1

    @contextlib.contextmanager
    def _suppress_signals(self):
        yield

    def _toggle_power(self):
        self.toggled += 1

    def _apply_current_color(self):
        self.applied += 1

    def _activate_quick_mode(self, key):
        self.activated.append(key)


def _backend():
    return QtApiBackend(_Host())


def test_app_version_is_reported() -> None:
    assert _backend().app_version() == APP_VERSION


def test_status_snapshot() -> None:
    status = _backend().status()
    assert status["connected"] is True
    assert status["power"] is True
    assert status["brightness"] == 80
    assert status["color"] == {"r": 10, "g": 20, "b": 30}
    assert status["mode"] == "gaming"
    assert status["name"] == "Desk"  # active strip name for the phone header
    assert status["pc_mode"] is None  # no PC stream controllers on the bare host
    assert status["pc_mode_detail"] == ""


class _FakeMode:
    def __init__(self, running: bool = False, starts: bool = True) -> None:
        self._running = running
        self._starts = starts  # whether activate() actually turns it on
        self.activated = 0

    def is_running(self) -> bool:
        return self._running

    def activate(self) -> bool:
        self.activated += 1
        self._running = self._starts
        return self._running


def test_set_pc_mode_activates_matching_controller() -> None:
    host = _Host()
    host._music_ui = _FakeMode()
    backend = QtApiBackend(host)
    assert backend.set_pc_mode("music") is True
    assert host._music_ui.activated == 1
    assert backend.status()["pc_mode"] == "music"


def test_set_pc_mode_off_stops_all_streams() -> None:
    host = _Host()
    stops = {"count": 0}
    host.stop_streams = lambda **_: stops.__setitem__("count", stops["count"] + 1)
    assert QtApiBackend(host).set_pc_mode("off") is True
    assert stops["count"] == 1


def test_set_pc_mode_unknown_is_rejected() -> None:
    assert _backend().set_pc_mode("laser") is False


# ── scenes (integration with the real QtApiBackend) ───────────────────────
def test_save_scene_snapshots_current_state(monkeypatch) -> None:
    import app.local_api.backend as backend_mod

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    host = _Host()
    host.effect_combo.current_code = 12  # a firmware effect is active
    backend = QtApiBackend(host)

    scene = backend.save_scene("Look")
    assert scene is not None
    assert scene["state"]["power"] is True
    assert scene["state"]["rgb"] == [10, 20, 30]
    assert scene["state"]["brightness"] == 80
    assert scene["state"]["effect"] == {"kind": "firmware", "ref": 12, "speed": 60}
    assert [s["name"] for s in backend.list_scenes()] == ["Look"]


def test_apply_scene_stops_streams_then_applies_to_the_connected_set(monkeypatch) -> None:
    # 0.3.2 applies to all connected strips (no per-strip BLE addressing yet);
    # this proves the stop-first ordering and that the light is actually pushed.
    import app.local_api.backend as backend_mod

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    host = _Host()
    backend = QtApiBackend(host)
    scene = backend.save_scene("Look")
    host.toggled = host.applied = host.stops = 0

    report = backend.apply_scene(scene["scene_id"])
    assert report is not None
    assert host.stops >= 1               # a live stream is stopped before applying
    assert "color" in report["applied"]
    assert host.applied >= 1             # colour was actually pushed to the strip


def test_apply_unknown_scene_returns_none(monkeypatch) -> None:
    import app.local_api.backend as backend_mod

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    assert QtApiBackend(_Host()).apply_scene("nope") is None


def test_pc_mode_detail_names_the_active_software_effect() -> None:
    host = _Host()
    host._tr = lambda key, **_: {"software_fx.effect_rainbow": "Rainbow"}.get(key, key)
    host._settings["software_fx"] = {"effect": "rainbow"}
    host._software_fx_ui = _FakeMode(running=True)
    status = QtApiBackend(host).status()
    assert status["pc_mode"] == "effect"
    assert status["pc_mode_detail"] == "Rainbow"


def test_set_pc_mode_reports_failure_when_gate_blocks_start() -> None:
    host = _Host()
    host._ambient_ui = _FakeMode(starts=False)  # e.g. Free licence / not connected
    backend = QtApiBackend(host)
    assert backend.set_pc_mode("screen") is False
    assert host._ambient_ui.activated == 1
    assert backend.status()["pc_mode"] is None


def test_devices_lists_primary_and_mirror_with_names() -> None:
    devices = _backend().devices()
    primary = next(d for d in devices if d["role"] == "primary")
    mirror = next(d for d in devices if d["role"] == "mirror")
    assert primary["name"] == "Desk"  # custom name wins
    assert mirror["address"] == "CC:DD"


def test_set_power_toggles_via_host() -> None:
    backend = QtApiBackend(_Host())
    host = backend._host
    backend.set_power(False, None)
    assert host.power_button.isChecked() is False
    assert host.toggled == 1


def test_set_color_sets_sliders_and_applies() -> None:
    backend = QtApiBackend(_Host())
    host = backend._host
    backend.set_color(1, 2, 3, None)
    assert (host.red_slider.value(), host.green_slider.value(), host.blue_slider.value()) == (1, 2, 3)
    assert host.applied == 1


def test_set_brightness_clamps() -> None:
    backend = QtApiBackend(_Host())
    backend.set_brightness(500, None)
    assert backend._host.brightness_slider.value() == 100


def test_effect_uses_combo_when_present_else_ble() -> None:
    backend = QtApiBackend(_Host())
    host = backend._host
    backend.set_effect(7, None, None)  # code 7 is in the combo
    assert host.effect_combo.current == 3
    backend.set_effect(99, None, None)  # not in combo -> ble fallback
    assert ("effect", 99) in host._ble.calls


def test_quick_mode_validates_key() -> None:
    backend = QtApiBackend(_Host())
    assert backend.apply_quick_mode("gaming") is True
    assert backend.apply_quick_mode("does-not-exist") is False
    assert "gaming" in backend._host.activated
