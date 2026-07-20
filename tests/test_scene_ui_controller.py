"""The desktop scenes card path: the target picked in the combo must end up in
the saved scene. Core and backend routing are covered elsewhere; this closes the
UI gap between "what the user chose" and "what was stored"."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from app.scene_store import list_scenes
from app.scene_ui_controller import SceneUiController


class _Combo:
    def __init__(self, data) -> None:
        self._data = data

    def currentData(self):
        return self._data


class _Field:
    def __init__(self, text: str = "") -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def clear(self) -> None:
        self._text = ""


class _Host:
    def __init__(self, target_data) -> None:
        self._settings: dict = {}
        self.scenes_target_combo = _Combo(target_data)
        self.scenes_name_field = _Field("My scene")
        self.logs: list[str] = []
        self.errors: list[str] = []

    def _tr(self, key: str, **_kwargs) -> str:
        return key

    def _log(self, message: str) -> None:
        self.logs.append(message)

    def _show_error(self, message: str) -> None:
        self.errors.append(message)


class _Backend:
    def __init__(self, report: dict | None = None) -> None:
        self._report = report or {"applied": ["color"], "skipped": [], "targets": ["Desk"]}

    def status(self) -> dict:
        return {"power": True, "color": {"r": 1, "g": 2, "b": 3}, "brightness": 50}

    def apply_scene(self, scene_id: str) -> dict:
        return self._report


@pytest.mark.parametrize(
    ("combo_data", "expected"),
    [
        ("all", {"kind": "all", "group_id": None}),
        ("primary", {"kind": "primary", "group_id": None}),
        ("group:grp-1", {"kind": "group", "group_id": "grp-1"}),
        (None, {"kind": "all", "group_id": None}),  # nothing selected -> safe default
    ],
)
def test_selected_target_is_stored_in_the_saved_scene(monkeypatch, combo_data, expected) -> None:
    import app.scene_ui_controller as module

    monkeypatch.setattr(module, "save_settings", lambda *_a, **_k: None)
    host = _Host(combo_data)
    controller = SceneUiController(host)
    monkeypatch.setattr(controller, "refresh", lambda: None)
    monkeypatch.setattr(controller, "_get_backend", lambda: _Backend())

    controller._save_current()

    scenes = list_scenes(host._settings)
    assert len(scenes) == 1
    assert scenes[0]["name"] == "My scene"
    assert scenes[0]["target"] == expected
    assert scenes[0]["state"]["rgb"] == [1, 2, 3]  # the snapshot still works


class _Chip:
    def __init__(self, checked: bool) -> None:
        self._checked = checked

    def isChecked(self) -> bool:
        return self._checked


def test_create_group_stores_only_the_ticked_strips(monkeypatch) -> None:
    import app.scene_ui_controller as module
    from app.scene_store import list_groups

    monkeypatch.setattr(module, "save_settings", lambda *_a, **_k: None)
    host = _Host("all")
    host.groups_name_field = _Field("Desk")
    controller = SceneUiController(host)
    controller._member_chips = [("AA:BB", _Chip(True)), ("CC:DD", _Chip(False)), ("EE:FF", _Chip(True))]
    monkeypatch.setattr(controller, "refresh", lambda: None)

    controller._create_group()

    groups = list_groups(host._settings)
    assert len(groups) == 1
    assert groups[0]["name"] == "Desk"
    assert groups[0]["members"] == ["AA:BB", "EE:FF"]  # the unticked strip stays out


def test_create_group_needs_a_name_and_a_member(monkeypatch) -> None:
    import app.scene_ui_controller as module
    from app.scene_store import list_groups

    monkeypatch.setattr(module, "save_settings", lambda *_a, **_k: None)

    nameless = _Host("all")
    nameless.groups_name_field = _Field("  ")
    controller = SceneUiController(nameless)
    controller._member_chips = [("AA:BB", _Chip(True))]
    monkeypatch.setattr(controller, "refresh", lambda: None)
    controller._create_group()
    assert list_groups(nameless._settings) == []

    unticked = _Host("all")
    unticked.groups_name_field = _Field("Desk")
    controller = SceneUiController(unticked)
    controller._member_chips = [("AA:BB", _Chip(False))]
    monkeypatch.setattr(controller, "refresh", lambda: None)
    controller._create_group()
    assert list_groups(unticked._settings) == []


def _saved_scene(host, target: dict) -> str:
    from app.scene_store import save_scene
    from app.scenes import make_scene

    scene = save_scene(host._settings, make_scene("Group look", {"brightness": 40}, target=target))
    return scene["scene_id"]


def test_apply_reports_when_the_target_group_is_gone(monkeypatch) -> None:
    host = _Host("all")
    scene_id = _saved_scene(host, {"kind": "group", "group_id": "grp-gone"})
    controller = SceneUiController(host)
    # Backend reached nothing: the group's strips aren't connected.
    monkeypatch.setattr(
        controller, "_get_backend", lambda: _Backend({"applied": [], "skipped": [], "targets": []})
    )

    controller._apply_scene(scene_id)

    assert host.errors == ["scenes.target_gone"]  # explained, not a false success
    assert host.logs == []
    assert controller._active_scene_id == ""  # a failed apply never marks a tile


def test_apply_logs_the_strips_it_reached(monkeypatch) -> None:
    host = _Host("all")
    scene_id = _saved_scene(host, {"kind": "all"})
    controller = SceneUiController(host)
    monkeypatch.setattr(
        controller, "_get_backend", lambda: _Backend({"applied": ["color"], "skipped": [], "targets": ["Desk", "TV"]})
    )

    controller._apply_scene(scene_id)

    assert host.logs == ["scenes.applied_to_log"]
    assert host.errors == []


def test_group_target_mapping_splits_the_id() -> None:
    assert SceneUiController(_Host("group:abc-123"))._selected_target() == {
        "kind": "group",
        "group_id": "abc-123",
    }


class _GridStub:
    def __init__(self) -> None:
        self.entries: list = []
        self.active = None
        self.visible = True

    def set_scenes(self, entries, active_id="") -> None:
        self.entries = list(entries)
        self.active = active_id

    def set_active(self, scene_id) -> None:
        self.active = scene_id

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _VisibleStub:
    def __init__(self) -> None:
        self.visible = True

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


def _grid_host(target="all") -> _Host:
    host = _Host(target)
    host.scenes_grid = _GridStub()
    host.scenes_empty_state = _VisibleStub()
    return host


def test_apply_scene_marks_the_tile_active(monkeypatch) -> None:
    host = _grid_host()
    scene_id = _saved_scene(host, {"kind": "all"})
    controller = SceneUiController(host)
    monkeypatch.setattr(controller, "_get_backend", lambda: _Backend())

    controller._apply_scene(scene_id)

    assert controller._active_scene_id == scene_id
    assert host.scenes_grid.active == scene_id


def test_manual_change_clears_the_active_tile(monkeypatch) -> None:
    host = _grid_host()
    scene_id = _saved_scene(host, {"kind": "all"})
    controller = SceneUiController(host)
    monkeypatch.setattr(controller, "_get_backend", lambda: _Backend())
    controller._apply_scene(scene_id)

    controller.note_manual_light_change()  # a real user action after the apply

    assert controller._active_scene_id == ""
    assert host.scenes_grid.active is None


def test_echoes_during_the_apply_itself_are_ignored(monkeypatch) -> None:
    """Applying moves the sliders; their synchronous signal echoes arrive while
    backend.apply_scene() runs and must not clear the tile they just lit."""
    host = _grid_host()
    scene_id = _saved_scene(host, {"kind": "all"})
    controller = SceneUiController(host)

    class _EchoBackend(_Backend):
        def apply_scene(self, scene_id: str) -> dict:
            controller.note_manual_light_change()  # programmatic slider echo
            return self._report

    monkeypatch.setattr(controller, "_get_backend", lambda: _EchoBackend())
    controller._active_scene_id = "previous-scene"

    controller._apply_scene(scene_id)

    assert controller._active_scene_id == scene_id  # the echo changed nothing


def test_delete_scene_removes_it_and_clears_active(monkeypatch) -> None:
    import app.scene_ui_controller as module

    monkeypatch.setattr(module, "save_settings", lambda *_a, **_k: None)
    host = _grid_host()
    scene_id = _saved_scene(host, {"kind": "all"})
    controller = SceneUiController(host)
    refreshed: list[bool] = []
    monkeypatch.setattr(controller, "refresh", lambda: refreshed.append(True))
    controller._active_scene_id = scene_id

    controller._delete_scene(scene_id)

    assert list_scenes(host._settings) == []
    assert controller._active_scene_id == ""
    assert refreshed == [True]


def test_refresh_scenes_grid_populates_tiles_and_toggles_empty_state() -> None:
    from app.scene_store import save_group

    host = _grid_host()
    controller = SceneUiController(host)

    # No scenes: grid hidden, empty state shown.
    controller._refresh_scenes_grid()
    assert host.scenes_grid.visible is False
    assert host.scenes_empty_state.visible is True

    group = save_group(host._settings, "Desk", ["AA:BB"])
    _saved_scene(host, {"kind": "group", "group_id": group["group_id"]})
    _saved_scene_named(host, "Gone look", {"kind": "group", "group_id": "grp-missing"})
    controller._refresh_scenes_grid()

    assert host.scenes_grid.visible is True
    assert host.scenes_empty_state.visible is False
    labels = [entry.target_label for entry in host.scenes_grid.entries]
    assert labels == ["Desk", "scenes.target_missing"]


def test_refresh_scenes_grid_after_overwrite_keeps_one_tile() -> None:
    """Re-saving under the same name overwrites — the grid must show one tile."""
    host = _grid_host()
    controller = SceneUiController(host)
    _saved_scene(host, {"kind": "all"})
    _saved_scene(host, {"kind": "primary"})  # same name "Group look" → overwrite
    controller._refresh_scenes_grid()

    assert len(host.scenes_grid.entries) == 1
    assert host.scenes_grid.entries[0].target_label == "scenes.target_primary"


def _saved_scene_named(host, name: str, target: dict) -> str:
    from app.scene_store import save_scene
    from app.scenes import make_scene

    scene = save_scene(host._settings, make_scene(name, {"brightness": 40}, target=target))
    return scene["scene_id"]


def test_nameless_scene_is_not_saved(monkeypatch) -> None:
    import app.scene_ui_controller as module

    monkeypatch.setattr(module, "save_settings", lambda *_a, **_k: None)
    host = _Host("all")
    host.scenes_name_field = _Field("   ")
    controller = SceneUiController(host)
    monkeypatch.setattr(controller, "refresh", lambda: None)
    monkeypatch.setattr(controller, "_get_backend", lambda: _Backend())

    controller._save_current()
    assert list_scenes(host._settings) == []
