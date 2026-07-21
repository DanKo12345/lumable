from __future__ import annotations

from app.scene_apply import SceneApplyService, scene_from_status
from app.scenes import make_scene


class FakeBackend:
    def __init__(self, *, pc_mode_starts: bool = True) -> None:
        self.calls: list[tuple] = []
        self.pc_mode_starts = pc_mode_starts

    def set_power(self, on, device_id):
        self.calls.append(("power", on, device_id))

    def set_color(self, red, green, blue, device_id):
        self.calls.append(("color", red, green, blue, device_id))

    def set_brightness(self, value, device_id):
        self.calls.append(("brightness", value, device_id))

    def set_effect(self, code, speed, device_id):
        self.calls.append(("effect", code, speed, device_id))

    def set_pc_mode(self, mode, preset=None):
        self.calls.append(("pc_mode", mode, preset))
        return mode == "off" or self.pc_mode_starts


def test_apply_stops_streams_first_then_sets_light() -> None:
    backend = FakeBackend()
    scene = make_scene("Movie", {"power": True, "rgb": [10, 20, 30], "brightness": 40})
    report = SceneApplyService(backend).apply(scene)

    # First call must be the stream-stop, so nothing fights over the strip.
    assert backend.calls[0] == ("pc_mode", "off", None)
    assert ("power", True, None) in backend.calls
    assert ("color", 10, 20, 30, None) in backend.calls
    assert ("brightness", 40, None) in backend.calls
    assert report["applied"] == ["power", "color", "brightness"]
    assert report["skipped"] == []


def test_apply_starts_pc_mode_last() -> None:
    backend = FakeBackend()
    scene = make_scene("Immersive", {"rgb": [1, 2, 3], "pc_mode": "screen"})
    SceneApplyService(backend).apply(scene)
    ops = [c[0] for c in backend.calls]
    assert ops[0] == "pc_mode" and backend.calls[0][1] == "off"   # stop first
    assert backend.calls[-1] == ("pc_mode", "screen", None)       # start last


def test_apply_reports_refused_pc_mode() -> None:
    backend = FakeBackend(pc_mode_starts=False)
    scene = make_scene("Music", {"pc_mode": "music"})
    report = SceneApplyService(backend).apply(scene)
    assert "pc_mode" not in report["applied"]
    assert {"field": "pc_mode", "reason": "refused"} in report["skipped"]


def test_firmware_effect_is_applied_but_software_is_deferred() -> None:
    backend = FakeBackend()
    firmware = make_scene("F", {"effect": {"kind": "firmware", "ref": 12, "speed": 50}})
    assert SceneApplyService(backend).apply(firmware)["applied"] == ["effect"]
    assert ("effect", 12, 50, None) in backend.calls

    backend2 = FakeBackend()
    software = make_scene("S", {"effect": {"kind": "software", "ref": "rainbow"}})
    report = SceneApplyService(backend2).apply(software)
    assert report["applied"] == []
    assert {"field": "effect", "reason": "pc_effect_pending"} in report["skipped"]


def test_unsupported_cct_is_reported_not_emulated() -> None:
    backend = FakeBackend()
    scene = make_scene("Warm", {"cct": 2700})
    report = SceneApplyService(backend).apply(scene, capabilities={"cct": True})
    # Planner allows it (cap true) but the service won't fake a white channel yet.
    assert {"field": "cct", "reason": "not_wired"} in report["skipped"]
    assert all(c[0] != "cct" for c in backend.calls)


def test_apply_targets_resolved_devices() -> None:
    backend = FakeBackend()
    scene = make_scene("Group", {"power": True, "rgb": [1, 2, 3]})
    SceneApplyService(backend).apply(scene, device_ids=["AA", "BB"])
    assert ("color", 1, 2, 3, "AA") in backend.calls
    assert ("color", 1, 2, 3, "BB") in backend.calls
    assert ("power", True, "AA") in backend.calls
    assert ("power", True, "BB") in backend.calls


def test_apply_reports_no_target_when_resolved_empty() -> None:
    backend = FakeBackend()
    scene = make_scene("x", {"rgb": [1, 2, 3]})
    report = SceneApplyService(backend).apply(scene, device_ids=[])
    assert {"field": "color", "reason": "no_target"} in report["skipped"]
    assert "color" not in report["applied"]
    assert all(c[0] != "color" for c in backend.calls)


def test_empty_target_never_stops_a_running_stream() -> None:
    # Applying a scene whose group has no connected strips must not kill the
    # screen sync / music / DIY the user is running on another strip.
    backend = FakeBackend()
    scene = make_scene("Ghost", {"rgb": [1, 2, 3], "brightness": 40, "pc_mode": "screen"})

    report = SceneApplyService(backend).apply(scene, device_ids=[])

    assert backend.calls == []  # no BLE writes and, crucially, no set_pc_mode("off")
    assert report["applied"] == []
    reasons = {(entry["field"], entry["reason"]) for entry in report["skipped"]}
    assert ("color", "no_target") in reasons
    assert ("brightness", "no_target") in reasons
    assert ("pc_mode", "no_target") in reasons  # the mode isn't started either
    assert not any(call[0] == "pc_mode" for call in backend.calls)  # set_pc_mode never called


def test_mixed_driver_group_reports_per_strip_skips() -> None:
    # A group can mix controllers: the effect works on one strip and not on the
    # other. The report must say which strip couldn't take it, not claim success.
    backend = FakeBackend()
    scene = make_scene("Group", {"rgb": [1, 2, 3], "effect": {"kind": "firmware", "ref": 12, "speed": 40}})

    def caps_for(device_id):
        if device_id == "NO-FX":
            return {"rgb": True, "firmware_effects": False}
        return {"rgb": True, "firmware_effects": True, "effect_speed": True}

    report = SceneApplyService(backend).apply(
        scene, device_ids=["OK-FX", "NO-FX"], capabilities_for=caps_for
    )

    # Colour reached both strips; the effect only the one that supports it.
    assert ("color", 1, 2, 3, "OK-FX") in backend.calls
    assert ("color", 1, 2, 3, "NO-FX") in backend.calls
    assert ("effect", 12, 40, "OK-FX") in backend.calls
    assert all(call[0] != "effect" or call[3] != "NO-FX" for call in backend.calls)
    assert {"field": "effect", "reason": "unsupported", "target": "NO-FX"} in report["skipped"]
    assert "effect" in report["applied"]  # it did land somewhere


def test_per_strip_effect_speed_is_resolved_per_target() -> None:
    backend = FakeBackend()
    scene = make_scene("Group", {"effect": {"kind": "firmware", "ref": 7, "speed": 80}})

    def caps_for(device_id):
        supports_speed = device_id == "FAST"
        return {"firmware_effects": True, "effect_speed": supports_speed}

    report = SceneApplyService(backend).apply(scene, device_ids=["FAST", "SLOW"], capabilities_for=caps_for)

    assert ("effect", 7, 80, "FAST") in backend.calls
    assert ("effect", 7, None, "SLOW") in backend.calls  # speed dropped, effect kept
    assert {"field": "effect_speed", "reason": "unsupported", "target": "SLOW"} in report["skipped"]


def test_snapshot_captures_light_and_active_mode() -> None:
    status = {"power": True, "color": {"r": 5, "g": 6, "b": 7}, "brightness": 55, "pc_mode": "music"}
    scene = scene_from_status(status, "Now")
    assert scene["name"] == "Now"
    assert scene["state"]["power"] is True
    assert scene["state"]["rgb"] == [5, 6, 7]
    assert scene["state"]["brightness"] == 55
    assert scene["state"]["pc_mode"] == {"kind": "music", "preset": None}


def test_snapshot_captures_firmware_effect() -> None:
    status = {"power": True, "effect": {"kind": "firmware", "ref": 12, "speed": 60}}
    scene = scene_from_status(status, "FX")
    assert scene["state"]["effect"] == {"kind": "firmware", "ref": 12, "speed": 60}


def test_snapshot_derives_a_colour_chip() -> None:
    scene = scene_from_status({"color": {"r": 5, "g": 6, "b": 7}}, "Now")
    assert scene["color"] == "#050607"
