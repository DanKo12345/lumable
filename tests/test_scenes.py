from __future__ import annotations

from app.scenes import (
    SCENE_VERSION,
    decode_scene,
    encode_scene,
    make_scene,
    normalize_scene,
    plan_apply,
    unwrap_scene,
    wrap_scene,
)


def test_optional_fields_absent_means_none() -> None:
    scene = make_scene("Dim", {"brightness": 20})
    state = scene["state"]
    assert state["brightness"] == 20
    # Everything else is "leave untouched", i.e. None — not a default value.
    assert state["power"] is None
    assert state["rgb"] is None
    assert state["cct"] is None
    assert state["effect"] is None
    assert state["pc_mode"] is None


def test_generates_id_and_clamps_ranges() -> None:
    scene = make_scene("X", {"rgb": [300, -5, 128], "brightness": 250, "cct": 50})
    assert scene["scene_id"]
    assert scene["state"]["rgb"] == [255, 0, 128]
    assert scene["state"]["brightness"] == 100
    assert scene["state"]["cct"] == 1000  # clamped up to the minimum


def test_effect_is_a_tagged_union() -> None:
    firmware = make_scene("f", {"effect": {"kind": "firmware", "ref": 12, "speed": 40}})
    assert firmware["state"]["effect"] == {"kind": "firmware", "ref": 12, "speed": 40}

    software = make_scene("s", {"effect": {"kind": "software", "ref": "rainbow"}})
    assert software["state"]["effect"] == {"kind": "software", "ref": "rainbow", "speed": None}

    # Unknown kind or a firmware effect without a numeric ref is rejected -> None.
    assert make_scene("bad", {"effect": {"kind": "laser", "ref": 1}})["state"]["effect"] is None
    assert make_scene("bad", {"effect": {"kind": "firmware", "ref": "nope"}})["state"]["effect"] is None


def test_group_target_needs_a_stable_id() -> None:
    grouped = make_scene("g", {}, target={"kind": "group", "group_id": "grp-1"})
    assert grouped["target"] == {"kind": "group", "group_id": "grp-1"}
    # A group target with no id falls back to primary (never a broken pointer).
    fallback = make_scene("g", {}, target={"kind": "group", "group_id": ""})
    assert fallback["target"]["kind"] == "primary"


def test_pc_mode_is_validated() -> None:
    assert make_scene("m", {"pc_mode": "music"})["state"]["pc_mode"] == "music"
    assert make_scene("m", {"pc_mode": "teleport"})["state"]["pc_mode"] is None


def test_normalize_rejects_non_dict() -> None:
    assert normalize_scene(None) is None
    assert normalize_scene("nope") is None


def test_storage_envelope_round_trip() -> None:
    scene = make_scene("Movie", {"rgb": [10, 20, 30], "brightness": 60})
    envelope = wrap_scene(scene)
    assert envelope["type"] == "scene"
    assert envelope["version"] == SCENE_VERSION
    assert unwrap_scene(envelope) == scene


def test_unwrap_rejects_wrong_type_version_and_corruption() -> None:
    scene = make_scene("Movie", {"brightness": 60})
    envelope = wrap_scene(scene)

    assert unwrap_scene({**envelope, "type": "diy"}) is None
    assert unwrap_scene({**envelope, "version": SCENE_VERSION + 1}) is None
    tampered = {**envelope, "payload": {**envelope["payload"], "name": "Hacked"}}
    assert unwrap_scene(tampered) is None  # checksum no longer matches
    # The checksum is mandatory for this format — a missing one is rejected.
    assert unwrap_scene({"type": "scene", "version": SCENE_VERSION, "payload": envelope["payload"]}) is None


def test_share_code_round_trip_and_rejects_junk() -> None:
    scene = make_scene("Chill", {"rgb": [0, 150, 255], "effect": {"kind": "software", "ref": "ocean"}})
    code = encode_scene(scene)
    assert code.startswith("LUMASCENE1-")
    decoded = decode_scene(code)
    assert decoded is not None
    assert decoded["state"]["rgb"] == [0, 150, 255]
    assert decoded["state"]["effect"]["ref"] == "ocean"

    assert decode_scene("not-a-code") is None
    assert decode_scene("LUMASCENE1-@@@@") is None


def test_plan_apply_orders_actions_and_ends_with_pc_mode() -> None:
    state = make_scene(
        "All",
        {"power": True, "rgb": [1, 2, 3], "brightness": 50, "effect": {"kind": "software", "ref": "rainbow"}, "pc_mode": "screen"},
    )["state"]
    plan = plan_apply(state, {"rgb": True, "firmware_effects": True})
    ops = [a["op"] for a in plan["actions"]]
    assert ops == ["power", "color", "brightness", "effect", "pc_mode"]
    assert plan["skipped"] == []


def test_plan_apply_skips_unsupported_fields_with_a_reason() -> None:
    state = make_scene("Warm", {"cct": 2700, "rgb": [255, 200, 120]})["state"]
    plan = plan_apply(state, {"rgb": False, "cct": False})  # a target that can't do either
    assert plan["actions"] == []
    reasons = {s["field"]: s["reason"] for s in plan["skipped"]}
    assert reasons == {"rgb": "unsupported", "cct": "unsupported"}


def test_plan_apply_allows_cct_when_supported() -> None:
    state = make_scene("Warm", {"cct": 2700})["state"]
    plan = plan_apply(state, {"cct": True})
    assert plan["actions"] == [{"op": "cct", "value": 2700}]
    assert plan["skipped"] == []
