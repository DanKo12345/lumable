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
    def __init__(self, driver_id: str = "bledom") -> None:
        self.calls: list[tuple] = []
        self._driver_id = driver_id

    def mirror_addresses(self):
        return ["CC:DD"]

    def active_driver_id(self):
        return self._driver_id

    def supports_effect_speed(self):
        return True

    def set_color_for_addresses(self, red, green, blue, addresses):
        self.calls.append(("color_addr", red, green, blue, tuple(addresses)))

    def set_power_for_addresses(self, enabled, addresses):
        self.calls.append(("power_addr", enabled, tuple(addresses)))

    def set_brightness_for_addresses(self, value, addresses):
        self.calls.append(("brightness_addr", value, tuple(addresses)))

    def set_effect_for_addresses(self, code, speed, addresses):
        self.calls.append(("effect_addr", code, speed, tuple(addresses)))

    def set_effect(self, code):
        self.calls.append(("effect", code))

    def set_effect_with_speed(self, code, speed):
        self.calls.append(("effect_speed", code, speed))

    def set_effect_speed(self, value):
        self.calls.append(("speed", value))


class _FakeFusion:
    """The controller that runs both screen modes."""

    def __init__(self, *, lights_the_strip: bool = True) -> None:
        self._mode = "screen"
        self._running = False
        # Whether a start would reach a strip. False stands for a Free licence
        # or no strip attached — the cases where the mode still runs, as a
        # preview on the desktop, and a phone would be told "on" for a room
        # that stays dark.
        self.lights_the_strip = lights_the_strip

    def would_light_the_strip(self, _mode=None) -> bool:
        return self.lights_the_strip

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode, **_kwargs) -> None:
        self._mode = mode

    def is_running(self) -> bool:
        return self._running

    def activate(self) -> bool:
        self._running = True
        return True

    def stop_if_running(self) -> None:
        self._running = False


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
        # Both screen modes run through here now; a host without one cannot
        # answer what mode it is in.
        self._fusion_ui = _FakeFusion()

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
    def __init__(self, running: bool = False, starts: bool = True, fusion=None) -> None:
        self._running = running
        self._starts = starts  # whether activate() actually turns it on
        self.activated = 0
        self.activated_standalone = 0
        self.activated_mode = None
        self._fusion = fusion or _FakeFusion()

    def is_running(self) -> bool:
        return self._running

    def activate(self, profile_id=None, mode=None) -> bool:
        # Screen sync's activate takes a profile id (scenes pin a preset) and,
        # since 0.4.0, the screen mode being asked for; the other modes ignore
        # both.
        self.activated += 1
        self.activated_with = profile_id
        self.activated_mode = mode
        if mode is not None:
            # The real controller sets the mode and then starts the coordinator,
            # which is what the status reads back.
            self._fusion.set_mode(mode)
            if self._starts:
                self._fusion.activate()
        self._running = self._starts
        return self._running

    def activate_standalone(self) -> bool:
        """What "music" means as an API mode: the reaction on its own."""
        self.activated_standalone += 1
        self.activated += 1
        self._running = self._starts
        return self._running

    def is_standalone_running(self) -> bool:
        return self._running


def test_set_pc_mode_activates_matching_controller() -> None:
    host = _Host()
    host._music_ui = _FakeMode()
    backend = QtApiBackend(host)
    assert backend.set_pc_mode("music") is True
    assert host._music_ui.activated == 1
    assert backend.status()["pc_mode"] == "music"


def test_the_two_screen_modes_are_asked_for_by_name() -> None:
    """A command must not depend on what the card was last left showing, and a
    scene saved as "screen + music" has to light the same way everywhere."""
    host = _Host()
    fusion = host._fusion_ui
    host._ambient_ui = _FakeMode(fusion=fusion)

    assert QtApiBackend(host).set_pc_mode("screen_music", "movie") is True

    assert fusion.mode() == "screen_music"
    assert host._ambient_ui.activated_with == "movie"
    assert QtApiBackend(host).status()["pc_mode"] == "screen_music"


def test_asking_for_the_plain_screen_mode_does_not_start_the_combined_one() -> None:
    host = _Host()
    fusion = host._fusion_ui
    fusion.set_mode("screen_music")  # what this machine was left on
    host._ambient_ui = _FakeMode(fusion=fusion)

    assert QtApiBackend(host).set_pc_mode("screen") is True

    assert fusion.mode() == "screen"


def test_asking_for_music_does_not_start_the_combined_mode() -> None:
    host = _Host()
    host._fusion_ui.set_mode("screen_music")
    host._music_ui = _FakeMode()

    assert QtApiBackend(host).set_pc_mode("music") is True

    assert host._music_ui.activated_standalone == 1, (
        "the shared-mode entry point was used, so the card's chooser decided this"
    )
    assert host._music_ui.activated == 1


def test_a_targeted_power_off_reaches_the_streams() -> None:
    """An address-targeted command still means the primary strip, and the
    streams belong to it. Writing only to the strip left the capture running
    and the colour going out to something that had just been switched off."""
    host = _Host()
    applied: list[bool] = []
    host.apply_power_to_streams = applied.append

    QtApiBackend(host).set_power(False, device_id="AA:BB")

    assert applied == [False], "the streams never heard about the power command"


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


# ── addressed routing (0.3.3) ─────────────────────────────────────────────
def test_addressed_mirror_write_leaves_the_desktop_ui_alone() -> None:
    host = _Host()
    QtApiBackend(host).set_color(1, 2, 3, "CC:DD")  # a mirror, not the primary
    assert ("color_addr", 1, 2, 3, ("CC:DD",)) in host._ble.calls
    assert host.applied == 0  # no whole-set re-send
    assert (host.red_slider.value(), host.green_slider.value(), host.blue_slider.value()) == (10, 20, 30)


def test_addressed_primary_write_syncs_sliders_without_resending() -> None:
    host = _Host()
    QtApiBackend(host).set_color(7, 8, 9, "AA:BB")  # the primary
    assert ("color_addr", 7, 8, 9, ("AA:BB",)) in host._ble.calls
    assert host.applied == 0  # reflected in the UI, not sent again
    assert (host.red_slider.value(), host.green_slider.value(), host.blue_slider.value()) == (7, 8, 9)


def test_addressed_primary_effect_syncs_combo_and_speed() -> None:
    host = _Host()
    QtApiBackend(host).set_effect(12, 70, "AA:BB")
    assert ("effect_addr", 12, 70, ("AA:BB",)) in host._ble.calls
    assert host.effect_combo.current == 5  # findData(12) -> index 5
    assert host.speed_slider.value() == 70  # /status + next snapshot stay truthful


def test_addressed_mirror_effect_leaves_primary_ui_alone() -> None:
    host = _Host()
    QtApiBackend(host).set_effect(12, 70, "CC:DD")
    assert ("effect_addr", 12, 70, ("CC:DD",)) in host._ble.calls
    assert host.speed_slider.value() == 60  # untouched
    assert host.effect_combo.current == -1


def test_whole_set_write_still_uses_the_host_path() -> None:
    host = _Host()
    QtApiBackend(host).set_color(4, 5, 6, None)
    assert host.applied == 1
    assert all(call[0] != "color_addr" for call in host._ble.calls)


def test_scene_targeting_all_uses_the_whole_set(monkeypatch) -> None:
    import app.local_api.backend as backend_mod

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    host = _Host()
    backend = QtApiBackend(host)
    scene = backend.save_scene("Look")  # new scenes default to target "all"
    host._ble.calls.clear()

    report = backend.apply_scene(scene["scene_id"])
    assert all(call[0] != "color_addr" for call in host._ble.calls)  # host path
    assert len(report["targets"]) == 2  # primary + mirror, named
    assert "Desk" in report["targets"]


def test_scene_targeting_primary_uses_addressed_writes(monkeypatch) -> None:
    import app.local_api.backend as backend_mod
    from app.scene_store import save_scene as store_save_scene

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    host = _Host()
    backend = QtApiBackend(host)
    scene = backend.save_scene("Desk look")
    store_save_scene(host._settings, {**scene, "target": {"kind": "primary", "group_id": None}})
    host._ble.calls.clear()
    host.applied = 0

    report = backend.apply_scene(scene["scene_id"])
    assert any(call[0] == "color_addr" and call[4] == ("AA:BB",) for call in host._ble.calls)
    assert report["targets"] == ["Desk"]


def test_group_target_ignores_strips_that_are_not_connected(monkeypatch) -> None:
    # A saved group may still name a strip that is offline or removed. Sending to
    # it would be dropped silently while the report claimed the scene reached it.
    import app.local_api.backend as backend_mod
    from app.scene_store import save_group
    from app.scene_store import save_scene as store_save_scene

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    host = _Host()
    backend = QtApiBackend(host)
    group = save_group(host._settings, "Desk", ["AA:BB", "GONE:99"])  # one is offline
    scene = backend.save_scene("Group look")
    store_save_scene(
        host._settings, {**scene, "target": {"kind": "group", "group_id": group["group_id"]}}
    )
    host._ble.calls.clear()

    report = backend.apply_scene(scene["scene_id"])
    written = {call[4] for call in host._ble.calls if call[0] == "color_addr"}
    assert written == {("AA:BB",)}  # nothing sent to the offline strip
    assert report["targets"] == ["Desk"]


def test_group_with_no_connected_strips_reports_nothing(monkeypatch) -> None:
    import app.local_api.backend as backend_mod
    from app.scene_store import save_group
    from app.scene_store import save_scene as store_save_scene

    monkeypatch.setattr(backend_mod, "save_settings", lambda *_a, **_k: None)
    host = _Host()
    backend = QtApiBackend(host)
    group = save_group(host._settings, "Ghosts", ["GONE:1", "GONE:2"])
    scene = backend.save_scene("Ghost look")
    store_save_scene(
        host._settings, {**scene, "target": {"kind": "group", "group_id": group["group_id"]}}
    )
    host._ble.calls.clear()

    report = backend.apply_scene(scene["scene_id"])
    assert report["targets"] == []
    assert all(call[0] != "color_addr" for call in host._ble.calls)
    assert any(entry.get("reason") == "no_target" for entry in report["skipped"])


def test_strip_capabilities_reflect_the_connected_driver() -> None:
    caps = QtApiBackend(_Host())._strip_capabilities()
    # bledom (fake default) is RGB with effects, no white channel.
    assert caps["rgb"] is True
    assert caps["firmware_effects"] is True
    assert caps["cct"] is False
    assert caps["effect_speed"] is True  # runtime query on the live driver


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


def test_a_phone_is_refused_when_the_mode_would_only_preview() -> None:
    """A phone asking for the light to come on has no screen of ours to show it.

    Without a licence or without a strip the mode still runs — as a preview
    beside the desktop card — and answering the phone "on" for a room that
    stays dark is the one reply this endpoint must not give. It already
    documents the refusal; what changed is that a preview started counting as a
    start.
    """
    host = _Host()
    host._fusion_ui = _FakeFusion(lights_the_strip=False)
    host._ambient_ui = _FakeMode()
    backend = QtApiBackend(host)

    assert backend.set_pc_mode("screen") is False
    assert host._ambient_ui.activated == 0, (
        "a capture nobody can see was left running after the refusal"
    )
    assert backend.status()["pc_mode"] is None


def test_the_same_command_is_allowed_when_it_really_lights_the_strip() -> None:
    """The other half: the refusal is about previewing, not about the phone."""
    host = _Host()
    host._fusion_ui = _FakeFusion(lights_the_strip=True)
    host._ambient_ui = _FakeMode()
    backend = QtApiBackend(host)

    assert backend.set_pc_mode("screen") is True
    assert host._ambient_ui.activated == 1
