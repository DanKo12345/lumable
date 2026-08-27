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

    def activate(self, profile_id: str | None = None, mode: str | None = None) -> bool:
        if profile_id:
            self._segment.set_current(profile_id)
        self._running = True
        self.activated_with = profile_id
        self.activated_mode = mode
        return True

    def sync_mode_segment(self) -> None:
        pass


class _FusionUi:
    """The controller that actually runs both screen modes now."""

    def __init__(self, *, lights_the_strip: bool = True) -> None:
        self._mode = "screen"
        self._running = False
        # A scene applied on a machine with a licence and a strip. The refusal
        # case has its own test in the Local API suite.
        self.lights_the_strip = lights_the_strip

    def would_light_the_strip(self, _mode=None) -> bool:
        return self.lights_the_strip

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, **_kwargs) -> None:
        self._mode = mode

    def is_running(self) -> bool:
        return self._running

    def activate(self) -> bool:
        self._running = True
        return True

    def stop_if_running(self) -> None:
        self._running = False


class _Host:
    def __init__(self, segment: _Segment, ambient: _AmbientUi) -> None:
        self.ambient_profile_segment = segment
        self._ambient_ui = ambient
        self._fusion_ui = _FusionUi()
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


class _FusionStub:
    """Stands in for the coordinator-owning controller the card delegates to."""

    def __init__(self) -> None:
        self.activated = 0
        self.running = False
        self.reason = ""
        self.target = None

    def is_running(self) -> bool:
        return self.running

    def mode(self) -> str:
        return "screen"

    def unavailable_reason(self, _mode=None) -> str:
        return self.reason

    def last_reason(self) -> str:
        return self.reason

    def activate(self, *, target=None) -> bool:
        self.target = target
        if self.reason:
            return False
        self.activated += 1
        self.running = True
        return True

    def stop_if_running(self) -> None:
        self.running = False

    def status_key(self) -> str:
        return self.reason or "ambient.status_off"

    def toggle_label_key(self) -> str:
        return "ambient.toggle_on" if self.running else "ambient.toggle_off"

    def preview_hint_key(self) -> str:
        return "ambient.preview_hint"


class _MusicStub:
    def refresh_shared_state(self) -> None:
        pass


class _StartHost:
    def __init__(self) -> None:
        from PySide6.QtGui import QColor

        self._qcolor = QColor(10, 20, 30)
        self._fusion_ui = _FusionStub()
        self._music_ui = _MusicStub()
        self.fusion_mode_segment = None
        self.fusion_mode_hint_label = None
        self._is_connected = True
        self.license_overlays = 0
        self.errors: list[str] = []
        self.power_button = _Btn(True)  # already on → skip the power toggle
        self.ambient_profile_segment = _Segment("desktop")
        self.ambient_saturation_slider = _Slider(55)
        self.ambient_smoothing_slider = _Slider(65)
        self.ambient_area_selector = type("A", (), {"current_region": lambda self: "full"})()
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


def test_the_seed_handed_to_the_stream_is_a_real_rgb_triple(monkeypatch) -> None:
    """Regression for the P1 crash: ``_current_color()`` is a QColor and is not
    subscriptable. The seed now leaves from the Fusion controller, which is
    where the conversion has to happen — a future ``seed[0]`` fails here instead
    of only at runtime.
    """
    import app.fusion_ui_controller as fusion_mod

    started: dict = {}

    class _FakeCoordinator:
        def __init__(self, _host) -> None:
            pass

        def is_running(self) -> bool:
            return False

        def attach_sources(self, **_kwargs) -> None:
            pass

        def start(self, _sink, *, mode, initial=(0, 0, 0), measures_a_link=True) -> None:
            started["initial"] = initial
            started["mode"] = mode
            started["measures_a_link"] = measures_a_link

        def frame_composed_connect(self, _slot) -> None:
            pass

        def set_beat_gain(self, _gain) -> None:
            pass

        def set_powered(self, _on) -> None:
            pass

    host = _StartHost()
    host._music_ui = type(
        "M", (), {"has_audio_source": lambda self: True, "beat_strength": lambda self: 0.4}
    )()
    monkeypatch.setattr(fusion_mod, "FusionCoordinator", _FakeCoordinator)
    monkeypatch.setattr(fusion_mod, "can_use", lambda _feature: True)

    controller = fusion_mod.FusionUiController(host)
    assert controller.activate() is True

    assert started["initial"] == (10, 20, 30)
    assert started["mode"] == "screen"


def test_activate_does_not_change_profile_when_start_is_blocked(monkeypatch) -> None:
    """A start that is going to refuse must leave nothing behind it.

    The profile is the user's, and a scene that asks for one and then fails to
    run would otherwise have quietly rewritten it. A licence and a missing strip
    no longer refuse anything — they choose where the colours go — so what is
    left to refuse is Screen + music with nothing to listen to.
    """
    import app.ambient_ui_controller as mod

    class _FakeAmbient:
        def __init__(self, _host) -> None:
            pass

        def is_running(self) -> bool:
            return False

    host = _StartHost()
    host._is_connected = True
    host._fusion_ui.reason = "fusion.needs_audio"
    monkeypatch.setattr(mod, "AmbientController", _FakeAmbient)
    monkeypatch.setattr(mod, "can_use", lambda _feature: True)

    ui = mod.AmbientUiController(host)

    assert ui.activate("movie") is False
    assert host.ambient_profile_segment.current_key() == "desktop"
    assert host.errors == ["fusion.needs_audio"]
