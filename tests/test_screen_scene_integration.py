"""A saved scene must restore the exact screen-sync look, not just "screen on".

0.3.4 contract: pc_mode carries a stable ``preset`` (the profile). Saving a scene
while Movie is running, then switching the UI to Desktop, then applying the scene
must bring Movie back — profile and all.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.local_api.backend import QtApiBackend
from app.scene_apply import scene_from_status
from app.scenes import plan_apply


class _Segment:
    def __init__(self, current: str) -> None:
        self._current = current

    def current_key(self) -> str:
        return self._current

    def set_current(self, key: str, *, animate: bool = True) -> None:
        self._current = key


class _AmbientUi:
    """A stand-in for AmbientUiController: activate(profile_id) picks the profile
    then reports running, exactly like the real one (minus the screen capture)."""

    def __init__(self, segment: _Segment) -> None:
        self._segment = segment
        self._running = False
        self.activated_with: str | None = "<never>"

    def is_running(self) -> bool:
        return self._running

    def activate(self, profile_id: str | None = None) -> bool:
        if profile_id:
            self._segment.set_current(profile_id)
        self._running = True
        self.activated_with = profile_id
        return True


class _Host:
    def __init__(self, segment: _Segment, ambient: _AmbientUi) -> None:
        self.ambient_profile_segment = segment
        self._ambient_ui = ambient
        self._music_ui = None
        self._software_fx_ui = None
        self._diy_ui = None

    def stop_streams(self, **_kwargs) -> None:
        pass


def _backend(host: _Host) -> QtApiBackend:
    backend = QtApiBackend.__new__(QtApiBackend)  # bypass the Qt invoker wiring
    backend._host = host
    return backend


def test_saved_scene_restores_the_screen_profile() -> None:
    segment = _Segment("game")
    ambient = _AmbientUi(segment)
    backend = _backend(_Host(segment, ambient))

    # 1–2. Movie is running; save the scene from a status snapshot.
    status = {"power": True, "pc_mode": "screen", "pc_mode_preset": "movie"}
    scene = scene_from_status(status, "Film night")
    assert scene["state"]["pc_mode"] == {"kind": "screen", "preset": "movie"}

    # 3. User switches the UI to Desktop.
    segment.set_current("desktop")

    # 4. Apply the scene — the pc_mode action carries the preset.
    plan = plan_apply(scene["state"], {})
    action = next(a for a in plan["actions"] if a["op"] == "pc_mode")
    assert backend._set_pc_mode(action["mode"], action.get("preset")) is True

    # 5. Movie is selected again and screen sync is running.
    assert segment.current_key() == "movie"
    assert ambient.is_running() is True
    assert ambient.activated_with == "movie"


def test_legacy_string_scene_applies_without_a_preset() -> None:
    segment = _Segment("desktop")
    ambient = _AmbientUi(segment)
    backend = _backend(_Host(segment, ambient))

    # A scene saved before 0.3.4 stored a bare "screen" string.
    scene = scene_from_status({"pc_mode": "screen"}, "Old")
    assert scene["state"]["pc_mode"] == {"kind": "screen", "preset": None}
    action = next(a for a in plan_apply(scene["state"], {})["actions"] if a["op"] == "pc_mode")
    backend._set_pc_mode(action["mode"], action.get("preset"))
    assert ambient.is_running() is True
    assert ambient.activated_with is None       # no preset → whatever profile was set
    assert segment.current_key() == "desktop"   # unchanged


class _Slider:
    def __init__(self, value: int = 0) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def setEnabled(self, _enabled: bool) -> None:
        pass


class _Btn:
    def __init__(self, checked: bool = True) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        self._checked = checked

    def setText(self, _text: str) -> None:
        pass


class _StartHost:
    def __init__(self) -> None:
        from PySide6.QtGui import QColor

        self._qcolor = QColor(10, 20, 30)
        self._is_connected = True
        self.license_overlays = 0
        self.errors: list[str] = []
        self.power_button = _Btn(True)  # already on → skip the power toggle
        self.ambient_profile_segment = _Segment("desktop")
        self.ambient_saturation_slider = _Slider(55)
        self.ambient_smoothing_slider = _Slider(65)
        self.ambient_region_combo = type("C", (), {"currentData": lambda self: "full"})()
        self.ambient_monitor_combo = None
        self.ambient_toggle_button = _Btn(True)
        self.ambient_status_label = None
        self._ble = type("B", (), {"set_color_stream": lambda self, r, g, b: None})()
        for name in (
            "red_slider", "green_slider", "blue_slider", "brightness_slider",
            "pick_color_button", "effect_combo", "speed_slider",
        ):
            setattr(self, name, _Slider())

    def stop_streams(self, exclude=None) -> None:
        pass

    def _current_color(self):
        return self._qcolor

    def _toggle_power(self) -> None:
        pass

    def _tr(self, key: str, **_kwargs) -> str:
        return key

    def _log(self, _message: str) -> None:
        pass

    def _show_license_overlay(self) -> None:
        self.license_overlays += 1

    def _show_error(self, message: str) -> None:
        self.errors.append(message)


def test_start_seeds_the_stream_with_the_current_qcolor(monkeypatch) -> None:
    # Regression for the P1 crash: _current_color() is a QColor (not
    # subscriptable). _start() must convert it and pass a real (r,g,b) seed, so a
    # future `seed[0]` would fail this test instead of only crashing at runtime.
    import app.ambient_ui_controller as mod

    started: dict = {}

    class _FakeAmbient:
        def __init__(self, _host) -> None:
            pass

        def configure(self, **_kwargs) -> None:
            pass

        def is_running(self) -> bool:
            return False

        def start(self, _sink, initial=(0, 0, 0)) -> None:
            started["initial"] = initial

    monkeypatch.setattr(mod, "AmbientController", _FakeAmbient)
    ui = mod.AmbientUiController(_StartHost())
    ui._start()
    assert started["initial"] == (10, 20, 30)


@pytest.mark.parametrize("licensed, connected", [(False, True), (True, False)])
def test_activate_does_not_change_profile_when_start_is_blocked(
    monkeypatch, licensed: bool, connected: bool,
) -> None:
    import app.ambient_ui_controller as mod

    class _FakeAmbient:
        def __init__(self, _host) -> None:
            pass

        def is_running(self) -> bool:
            return False

    host = _StartHost()
    host._is_connected = connected
    monkeypatch.setattr(mod, "AmbientController", _FakeAmbient)
    monkeypatch.setattr(mod, "can_use", lambda _feature: licensed)

    ui = mod.AmbientUiController(host)

    assert ui.activate("movie") is False
    assert host.ambient_profile_segment.current_key() == "desktop"
    assert host.license_overlays == (0 if licensed else 1)
    assert host.errors == (["ambient.not_connected"] if licensed else [])
