"""Recently applied scenes: what the tray menu offers first.

Kept beside the scenes rather than inside them — a scene record is a versioned,
checksummed envelope, and "when was this last used" is not part of what a scene
is. Adding a field there would mean a schema change and a migration.
"""

from __future__ import annotations

from app import scene_store
from app.scenes import make_scene


def _settings_with(*names: str) -> dict:
    settings: dict = {}
    for name in names:
        scene_store.save_scene(settings, make_scene(name, {"power": True}))
    return settings


def _ids(settings: dict) -> dict[str, str]:
    return {scene["name"]: scene["scene_id"] for scene in scene_store.list_scenes(settings)}


def test_the_newest_use_comes_first() -> None:
    settings = _settings_with("Read", "Film", "Party")
    ids = _ids(settings)

    scene_store.note_scene_applied(settings, ids["Film"])
    scene_store.note_scene_applied(settings, ids["Party"])

    assert [s["name"] for s in scene_store.recent_scenes(settings, limit=3)] == [
        "Party",
        "Film",
        "Read",
    ]


def test_applying_the_same_scene_again_does_not_crowd_the_others_out() -> None:
    """A menu that shows a handful would otherwise fill with one repeated name."""
    settings = _settings_with("Read", "Film")
    ids = _ids(settings)

    for _ in range(5):
        scene_store.note_scene_applied(settings, ids["Read"])

    assert settings[scene_store.RECENT_SCENES_KEY] == [ids["Read"]]
    assert [s["name"] for s in scene_store.recent_scenes(settings, limit=2)] == ["Read", "Film"]


def test_a_fresh_install_still_offers_something() -> None:
    """Nothing has been applied yet, so the saved order is the best guess. An
    empty menu would read as "no scenes" to someone who has several."""
    settings = _settings_with("Read", "Film")

    assert [s["name"] for s in scene_store.recent_scenes(settings, limit=5)] == ["Read", "Film"]


def test_a_deleted_scene_leaves_the_recent_list() -> None:
    """A menu offering a scene that no longer exists is worse than a short menu."""
    settings = _settings_with("Read", "Film")
    ids = _ids(settings)
    scene_store.note_scene_applied(settings, ids["Film"])

    scene_store.delete_scene(settings, ids["Film"])

    assert ids["Film"] not in settings[scene_store.RECENT_SCENES_KEY]
    assert [s["name"] for s in scene_store.recent_scenes(settings, limit=5)] == ["Read"]


def test_the_recent_list_is_bounded() -> None:
    settings = _settings_with(*[f"Scene {index}" for index in range(12)])
    for scene in scene_store.list_scenes(settings):
        scene_store.note_scene_applied(settings, scene["scene_id"])

    assert len(settings[scene_store.RECENT_SCENES_KEY]) == scene_store.MAX_RECENT_SCENES


def test_junk_in_the_stored_list_is_ignored() -> None:
    settings = _settings_with("Read")
    settings[scene_store.RECENT_SCENES_KEY] = ["", "  ", "no-such-scene"]

    scene_store.note_scene_applied(settings, _ids(settings)["Read"])

    assert [s["name"] for s in scene_store.recent_scenes(settings, limit=5)] == ["Read"]


def test_only_a_scene_that_reached_a_strip_becomes_recent(monkeypatch) -> None:
    """A list of "recent" scenes that includes the ones which failed is a list
    of disappointments. Recording happens on the app's single apply path, so
    the tray, the tiles and an automation cannot disagree about it."""
    import pytest

    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        settings = window._settings
        for name in ("Read", "Film"):
            scene_store.save_scene(settings, make_scene(name, {"power": True}))
        ids = {s["name"]: s["scene_id"] for s in scene_store.list_scenes(settings)}

        class _Backend:
            def __init__(self, targets):
                self._targets = targets

            def apply_scene(self, _scene_id):
                return {"targets": list(self._targets)}

        window._scene_ui._get_backend = lambda: _Backend(["Strip"])
        window._scene_ui.apply_scene(ids["Read"])
        assert settings[scene_store.RECENT_SCENES_KEY][:1] == [ids["Read"]]

        # The scene points at strips that are gone: nothing lit up.
        window._scene_ui._get_backend = lambda: _Backend([])
        window._scene_ui.apply_scene(ids["Film"])
        assert ids["Film"] not in settings[scene_store.RECENT_SCENES_KEY]
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
