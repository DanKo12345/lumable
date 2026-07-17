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

    def set_pc_mode(self, mode):
        self.calls.append(("pc_mode", mode))
        return mode == "off" or self.pc_mode_starts


def test_apply_stops_streams_first_then_sets_light() -> None:
    backend = FakeBackend()
    scene = make_scene("Movie", {"power": True, "rgb": [10, 20, 30], "brightness": 40})
    report = SceneApplyService(backend).apply(scene)

    # First call must be the stream-stop, so nothing fights over the strip.
    assert backend.calls[0] == ("pc_mode", "off")
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
    assert backend.calls[-1] == ("pc_mode", "screen")             # start last


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


def test_snapshot_captures_light_and_active_mode() -> None:
    status = {"power": True, "color": {"r": 5, "g": 6, "b": 7}, "brightness": 55, "pc_mode": "music"}
    scene = scene_from_status(status, "Now")
    assert scene["name"] == "Now"
    assert scene["state"]["power"] is True
    assert scene["state"]["rgb"] == [5, 6, 7]
    assert scene["state"]["brightness"] == 55
    assert scene["state"]["pc_mode"] == "music"


def test_snapshot_captures_firmware_effect() -> None:
    status = {"power": True, "effect": {"kind": "firmware", "ref": 12, "speed": 60}}
    scene = scene_from_status(status, "FX")
    assert scene["state"]["effect"] == {"kind": "firmware", "ref": 12, "speed": 60}


def test_snapshot_derives_a_colour_chip() -> None:
    scene = scene_from_status({"color": {"r": 5, "g": 6, "b": 7}}, "Now")
    assert scene["color"] == "#050607"
