from __future__ import annotations

from app.scene_store import (
    delete_group,
    delete_scene,
    get_scene,
    group_members,
    list_groups,
    list_scenes,
    normalize_group,
    resolve_target,
    save_group,
    save_scene,
)
from app.scenes import SCENE_VERSION, make_scene, wrap_scene


def test_save_lists_and_gets_a_scene() -> None:
    settings: dict = {}
    scene = make_scene("Movie", {"brightness": 40})
    saved = save_scene(settings, scene)
    assert saved is not None
    assert [s["name"] for s in list_scenes(settings)] == ["Movie"]
    assert get_scene(settings, scene["scene_id"])["name"] == "Movie"


def test_save_is_upsert_by_id() -> None:
    settings: dict = {}
    scene = make_scene("Movie", {"brightness": 40})
    save_scene(settings, scene)
    updated = {**scene, "name": "Cinema"}
    save_scene(settings, updated)
    scenes = list_scenes(settings)
    assert len(scenes) == 1  # replaced, not appended
    assert scenes[0]["name"] == "Cinema"


def test_nameless_scene_is_not_saved() -> None:
    settings: dict = {}
    assert save_scene(settings, make_scene("", {"brightness": 10})) is None
    assert list_scenes(settings) == []


def test_save_overwrites_by_name_case_insensitively() -> None:
    settings: dict = {}
    first = save_scene(settings, make_scene("Movie", {"brightness": 40}))
    # A fresh scene (different id) with the same name overwrites, keeping the id.
    save_scene(settings, make_scene("movie", {"brightness": 10}))
    scenes = list_scenes(settings)
    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == first["scene_id"]
    assert scenes[0]["state"]["brightness"] == 10


def test_save_respects_capacity(monkeypatch) -> None:
    import app.scene_store as store

    monkeypatch.setattr(store, "MAX_SCENES", 2)
    settings: dict = {}
    assert save_scene(settings, make_scene("A", {"brightness": 1})) is not None
    assert save_scene(settings, make_scene("B", {"brightness": 2})) is not None
    assert save_scene(settings, make_scene("C", {"brightness": 3})) is None  # full
    assert save_scene(settings, make_scene("A", {"brightness": 9})) is not None  # update still ok


def test_delete_scene() -> None:
    settings: dict = {}
    scene = make_scene("Movie", {"brightness": 40})
    save_scene(settings, scene)
    assert delete_scene(settings, scene["scene_id"]) is True
    assert delete_scene(settings, scene["scene_id"]) is False
    assert list_scenes(settings) == []


def test_corrupt_entries_are_dropped_from_listing() -> None:
    settings = {"scenes": ["garbage", {"no": "envelope"}, None]}
    assert list_scenes(settings) == []


def test_group_normalization_dedupes_members() -> None:
    group = normalize_group({"name": "Desk", "members": ["AA", "BB", "AA", " ", "BB"]})
    assert group["members"] == ["AA", "BB"]
    assert group["group_id"]


def test_group_save_list_delete_and_members() -> None:
    settings: dict = {}
    group = save_group(settings, "Desk", ["AA:BB", "CC:DD"])
    assert group is not None
    assert [g["name"] for g in list_groups(settings)] == ["Desk"]
    assert group_members(settings, group["group_id"]) == ["AA:BB", "CC:DD"]
    assert delete_group(settings, group["group_id"]) is True
    assert list_groups(settings) == []


def test_group_id_is_stable_across_rename() -> None:
    settings: dict = {}
    group = save_group(settings, "Desk", ["AA"])
    renamed = save_group(settings, "Work desk", ["AA"], group_id=group["group_id"])
    assert renamed["group_id"] == group["group_id"]
    assert len(list_groups(settings)) == 1  # rename updates in place, no duplicate


def test_scenes_survive_settings_validation() -> None:
    # Regression: scenes must round-trip through validate_settings (app restart).
    from app.storage import validate_settings

    settings: dict = {}
    save_scene(settings, make_scene("Movie", {"brightness": 40, "rgb": [1, 2, 3]}))
    assert len(list_scenes(settings)) == 1

    validated = validate_settings(settings)
    survived = list_scenes(validated)
    assert len(survived) == 1
    assert survived[0]["name"] == "Movie"
    assert survived[0]["state"]["rgb"] == [1, 2, 3]


def test_future_scene_survives_validation_but_stays_unavailable() -> None:
    from app.storage import validate_settings

    future = wrap_scene(make_scene("From tomorrow", {"brightness": 40}))
    future["version"] = SCENE_VERSION + 1
    settings = validate_settings({"scenes": [future]})

    assert settings["scenes"] == [future]
    assert list_scenes(settings) == []


def test_corrupt_future_scene_is_not_preserved() -> None:
    from app.storage import validate_settings

    future = wrap_scene(make_scene("Broken tomorrow", {"brightness": 40}))
    future["version"] = SCENE_VERSION + 1
    future["payload"]["name"] = "changed after checksum"

    assert validate_settings({"scenes": [future]})["scenes"] == []


def test_editing_known_scenes_keeps_an_opaque_future_scene() -> None:
    from app.storage import validate_settings

    future = wrap_scene(make_scene("From tomorrow", {"brightness": 40}))
    future["version"] = SCENE_VERSION + 1
    settings = validate_settings({"scenes": [future]})

    known = save_scene(settings, make_scene("Today", {"brightness": 20}))
    assert known is not None
    assert settings["scenes"][0] == future
    assert [scene["name"] for scene in list_scenes(settings)] == ["Today"]

    assert delete_scene(settings, known["scene_id"]) is True
    assert settings["scenes"] == [future]


def test_groups_survive_settings_validation() -> None:
    from app.storage import validate_settings

    settings: dict = {}
    save_group(settings, "Desk", ["AA", "BB"])
    validated = validate_settings(settings)
    assert [g["name"] for g in list_groups(validated)] == ["Desk"]
    assert group_members(validated, list_groups(validated)[0]["group_id"]) == ["AA", "BB"]


def test_resolve_target_maps_to_addresses() -> None:
    settings: dict = {}
    group = save_group(settings, "Desk", ["AA", "BB"])
    assert resolve_target(settings, {"kind": "primary"}, primary="P1") == ["P1"]
    assert resolve_target(settings, {"kind": "all"}, all_addresses=["P1", "X2"]) == ["P1", "X2"]
    assert resolve_target(settings, {"kind": "group", "group_id": group["group_id"]}) == ["AA", "BB"]
    # A group that no longer exists resolves to nothing, not a crash.
    assert resolve_target(settings, {"kind": "group", "group_id": "gone"}) == []
