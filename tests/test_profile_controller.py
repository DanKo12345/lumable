from __future__ import annotations

import json
from dataclasses import dataclass

from app.profile_controller import ProfileController

# ── mock helpers ──────────────────────────────────────────────────────

@dataclass
class _FakeState:
    name: str
    power: bool = True
    brightness: int = 80
    speed: int = 60
    effect_code: int = 0
    color: dict = None
    schedule: dict = None

    def __post_init__(self):
        if self.color is None:
            self.color = {"r": 100, "g": 150, "b": 200}
        if self.schedule is None:
            self.schedule = {}


def _collect_state(name: str) -> _FakeState:
    return _FakeState(name=name)


class _MockListWidgetItem:
    def __init__(self, text: str = "", *args) -> None:
        self._data: dict = {}

    def setData(self, role, value) -> None:
        self._data[role] = value

    def data(self, role):
        return self._data.get(role)


class _MockListWidget:
    def __init__(self) -> None:
        self._items: list = []
        self._current_row: int = -1

    def clear(self) -> None:
        self._items.clear()
        self._current_row = -1

    def addItem(self, item) -> None:
        self._items.append(item)

    def currentItem(self):
        if 0 <= self._current_row < len(self._items):
            return self._items[self._current_row]
        return None

    def setCurrentRow(self, row: int) -> None:
        self._current_row = row


def _list_widget() -> _MockListWidget:
    return _MockListWidget()


def _patch_qt(monkeypatch) -> None:
    monkeypatch.setattr("app.profile_controller.QListWidgetItem", _MockListWidgetItem)


def _make_controller(*profile_names: str) -> ProfileController:
    profiles = [{"name": n, "power": True, "brightness": 80, "speed": 60,
                 "effect_code": 0, "color": {"r": 10, "g": 20, "b": 30}} for n in profile_names]
    return ProfileController(profiles)


# ── save_profile ──────────────────────────────────────────────────────

def test_save_profile_adds_new_profile(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller()
    errors, logs = [], []

    ctrl.save_profile("Night", _collect_state, errors.append, logs.append, str, _list_widget())

    assert len(ctrl.profiles) == 1
    assert ctrl.profiles[0]["name"] == "Night"
    assert not errors
    assert logs


def test_save_profile_updates_existing_profile_by_name(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("Night")

    ctrl.save_profile("Night", _collect_state, [].append, [].append, str, _list_widget())

    assert len(ctrl.profiles) == 1


def test_save_profile_rejects_empty_name(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller()
    errors = []

    ctrl.save_profile("  ", _collect_state, errors.append, [].append, str, _list_widget())

    assert errors
    assert len(ctrl.profiles) == 0


def test_save_profile_is_case_insensitive_for_existing(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("Night")

    ctrl.save_profile("NIGHT", _collect_state, [].append, [].append, str, _list_widget())

    assert len(ctrl.profiles) == 1


def test_save_profile_rejects_at_free_limit(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    from app import feature_gate
    limit = feature_gate.FREE_PROFILE_MAX
    ctrl = _make_controller(*[f"p{i}" for i in range(limit)])
    errors = []

    ctrl.save_profile("overflow", _collect_state, errors.append, [].append, str, _list_widget())

    assert errors
    assert len(ctrl.profiles) == limit


# ── delete_selected_profile ───────────────────────────────────────────

def test_delete_selected_profile_removes_it(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("Alpha", "Beta")
    widget = _list_widget()
    ctrl.refresh_list(widget)
    widget.setCurrentRow(0)
    logs = []

    ctrl.delete_selected_profile(widget, [].append, logs.append, str)

    assert len(ctrl.profiles) == 1
    assert ctrl.profiles[0]["name"] == "Beta"
    assert logs


def test_delete_selected_profile_errors_when_nothing_selected(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    ctrl = _make_controller("Alpha")
    errors = []

    ctrl.delete_selected_profile(_list_widget(), errors.append, [].append, str)

    assert errors
    assert len(ctrl.profiles) == 1


# ── rename_selected_profile ───────────────────────────────────────────

def test_rename_selected_profile_changes_name(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("OldName")
    widget = _list_widget()
    ctrl.refresh_list(widget)
    widget.setCurrentRow(0)

    ctrl.rename_selected_profile(widget, "NewName", [].append, [].append, lambda k, **_: k)

    assert ctrl.profiles[0]["name"] == "NewName"


def test_rename_rejects_duplicate_name(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("Alpha", "Beta")
    widget = _list_widget()
    ctrl.refresh_list(widget)
    widget.setCurrentRow(0)
    errors = []

    ctrl.rename_selected_profile(widget, "Beta", errors.append, [].append, str)

    assert errors
    assert ctrl.profiles[0]["name"] == "Alpha"


def test_rename_rejects_empty_name(monkeypatch) -> None:
    _patch_qt(monkeypatch)
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("Alpha")
    widget = _list_widget()
    ctrl.refresh_list(widget)
    widget.setCurrentRow(0)
    errors = []

    ctrl.rename_selected_profile(widget, "  ", errors.append, [].append, str)

    assert errors


# ── export / import ───────────────────────────────────────────────────

def test_export_profiles_writes_valid_json(tmp_path) -> None:
    ctrl = _make_controller("Morning", "Evening")
    path = tmp_path / "export.json"

    count = ctrl.export_profiles(path)

    assert count == 2
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "profiles" in data
    assert len(data["profiles"]) == 2


def test_import_profiles_adds_new_profiles(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller()
    source = _make_controller("Morning", "Evening")
    export_path = tmp_path / "export.json"
    source.export_profiles(export_path)

    count, skipped = ctrl.import_profiles(export_path)

    assert count == 2
    assert skipped == 0
    assert len(ctrl.profiles) == 2


def test_import_profiles_updates_existing_by_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller("Morning")
    ctrl.profiles[0]["brightness"] = 50
    source = ProfileController([
        {"name": "Morning", "power": True, "brightness": 99,
         "speed": 60, "effect_code": 0, "color": {"r": 1, "g": 2, "b": 3}}
    ])
    export_path = tmp_path / "export.json"
    source.export_profiles(export_path)

    ctrl.import_profiles(export_path)

    assert ctrl.profiles[0]["brightness"] == 99
    assert len(ctrl.profiles) == 1


def test_import_profiles_skips_invalid_entries(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _: None)
    ctrl = _make_controller()
    payload = {"app": "LumaBLE", "version": "0.1.0", "profiles": [
        {},
        {"name": "Good", "power": True, "brightness": 80, "speed": 60,
         "effect_code": 0, "color": {"r": 1, "g": 2, "b": 3}},
    ]}
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    count, skipped = ctrl.import_profiles(path)

    assert count == 1
    assert skipped == 1


# ── user_profile_count ────────────────────────────────────────────────

def test_user_profile_count_excludes_preset_profiles() -> None:
    ctrl = ProfileController([
        {"name": "User profile", "preset_key": "", "power": True, "brightness": 80,
         "speed": 60, "effect_code": 0, "color": {"r": 0, "g": 0, "b": 0}},
        {"name": "Azure Drift", "preset_key": "azure_drift", "power": True, "brightness": 80,
         "speed": 60, "effect_code": 0, "color": {"r": 0, "g": 0, "b": 0}},
    ])

    assert ctrl.user_profile_count() == 1
