from __future__ import annotations

import json
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidget

from app.profile_controller import ProfileController


@dataclass
class ProfileStateStub:
    preset_key: str
    name: str
    power: bool
    brightness: int
    speed: int
    effect_code: int
    color: dict


def _profile(name: str, red: int = 1, *, preset_key: str = "") -> dict:
    return {
        "preset_key": preset_key,
        "name": name,
        "power": True,
        "brightness": 80,
        "speed": 40,
        "effect_code": 0,
        "color": {"r": red, "g": 2, "b": 3},
    }


def _state(name: str, red: int = 1, *, preset_key: str = "") -> ProfileStateStub:
    profile = _profile(name, red=red, preset_key=preset_key)
    return ProfileStateStub(**profile)


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_profile_controller_exports_profiles_with_metadata(tmp_path) -> None:
    controller = ProfileController([_profile("Desk")])
    path = tmp_path / "profiles.json"

    count = controller.export_profiles(path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert count == 1
    assert payload["app"] == "LumaBLE"
    assert payload["version"] == "0.2.0"
    assert payload["profiles"][0]["name"] == "Desk"


def test_profile_controller_imports_and_merges_profiles(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _profiles: None)
    controller = ProfileController([_profile("Desk", red=1)])
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    _profile("Desk", red=90),
                    _profile("TV", red=40),
                    {"name": ""},
                ]
            }
        ),
        encoding="utf-8",
    )

    count, skipped = controller.import_profiles(path)

    assert count == 2
    assert skipped == 1
    assert [profile["name"] for profile in controller.profiles] == ["Desk", "TV"]
    assert controller.profiles[0]["color"]["r"] == 90


def test_profile_list_items_keep_color_for_thumbnail() -> None:
    _ensure_app()
    profile = _profile("Desk", red=123)
    controller = ProfileController([profile])
    profile_list = QListWidget()

    controller.refresh_list(profile_list)

    item_profile = profile_list.item(0).data(Qt.UserRole)
    assert item_profile["color"] == {"r": 123, "g": 2, "b": 3}


def test_profile_controller_blocks_fourth_custom_profile_in_free(monkeypatch) -> None:
    _ensure_app()
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _profiles: None)
    controller = ProfileController([_profile("One"), _profile("Two"), _profile("Three")])
    errors = []
    logs = []

    controller.save_profile(
        "Four",
        lambda name: _state(name),
        errors.append,
        logs.append,
        lambda key: key,
        QListWidget(),
    )

    assert errors == ["error.profile_limit_free"]
    assert logs == []
    assert [profile["name"] for profile in controller.profiles] == ["One", "Two", "Three"]


def test_profile_controller_allows_replacing_existing_profile_at_free_limit(monkeypatch) -> None:
    _ensure_app()
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _profiles: None)
    controller = ProfileController([_profile("One"), _profile("Two"), _profile("Three")])

    controller.save_profile(
        "Two",
        lambda name: _state(name, red=90),
        lambda message: (_ for _ in ()).throw(AssertionError(message)),
        lambda _message: None,
        lambda key: key,
        QListWidget(),
    )

    assert len(controller.profiles) == 3
    assert controller.profiles[1]["color"]["r"] == 90


def test_profile_controller_does_not_count_builtin_presets_toward_free_limit(monkeypatch) -> None:
    _ensure_app()
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _profiles: None)
    controller = ProfileController(
        [
            _profile("Built in 1", preset_key="one"),
            _profile("Built in 2", preset_key="two"),
            _profile("Built in 3", preset_key="three"),
            _profile("Built in 4", preset_key="four"),
            _profile("Built in 5", preset_key="five"),
        ]
    )

    controller.save_profile(
        "Custom",
        lambda name: _state(name),
        lambda message: (_ for _ in ()).throw(AssertionError(message)),
        lambda _message: None,
        lambda key: key,
        QListWidget(),
    )

    assert controller.user_profile_count() == 1
    assert controller.profiles[-1]["name"] == "Custom"


def test_profile_controller_allows_more_than_three_custom_profiles_in_pro(monkeypatch) -> None:
    _ensure_app()
    monkeypatch.setattr("app.profile_controller.save_profiles", lambda _profiles: None)
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    controller = ProfileController([_profile("One"), _profile("Two"), _profile("Three")])

    controller.save_profile(
        "Four",
        lambda name: _state(name),
        lambda message: (_ for _ in ()).throw(AssertionError(message)),
        lambda _message: None,
        lambda key: key,
        QListWidget(),
    )

    assert [profile["name"] for profile in controller.profiles] == ["One", "Two", "Three", "Four"]

