"""Restoring a backup over the settings file, and shutting the door behind it.

The dangerous moment is not the write. It is everything the app does *after*:
the shutdown path alone saves settings from several controllers, and any one of
them holds a snapshot of the world that existed before the restore. Writing
that back would undo the restore silently, minutes after telling the user it
worked.
"""

from __future__ import annotations

import json

import pytest

from app import storage


@pytest.fixture()
def store(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(storage, "PROFILES_PATH", tmp_path / "profiles.json")
    monkeypatch.setattr(storage, "_legacy_migration_pairs", lambda: [])
    monkeypatch.setattr(storage, "_migration_done", False)
    # The freeze is process-wide by design; each test starts with the door open.
    monkeypatch.setattr(storage, "_writes_frozen", False)
    settings_path.write_text(json.dumps({"theme_mode": "dark"}), encoding="utf-8")
    return settings_path


def _stored(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_restore_replaces_the_file_and_keeps_the_old_one(store) -> None:
    kept = storage.restore_settings_file({"theme_mode": "light"})

    assert _stored(store)["theme_mode"] == "light"
    assert kept is not None and kept.exists()
    assert _stored(kept)["theme_mode"] == "dark", "the safety copy is the old world"


def test_nothing_ordinary_can_write_after_a_restore(store) -> None:
    """The failure this prevents is silent and late: the app closes, a
    controller saves the settings it has been holding since start-up, and the
    restored scenes are gone by the next launch."""
    storage.restore_settings_file({"theme_mode": "light"})

    storage.save_settings({"theme_mode": "dark", "scenes": ["stale"]})

    assert _stored(store)["theme_mode"] == "light"
    assert "scenes" not in _stored(store)


def test_a_targeted_update_cannot_slip_through_either(store) -> None:
    """update_settings takes the same lock but a different path — a guard on
    save_settings alone would let a power command rewrite the file."""
    storage.restore_settings_file({"theme_mode": "light"})

    storage.update_settings(lambda settings: settings.update({"theme_mode": "dark"}))

    assert _stored(store)["theme_mode"] == "light"


def test_a_power_command_during_shutdown_cannot_undo_it(store) -> None:
    storage.restore_settings_file({"theme_mode": "light"})

    storage.update_power_setting(True)

    assert _stored(store)["theme_mode"] == "light"


def test_a_failed_write_leaves_the_old_settings_and_the_door_open(store) -> None:
    """If the replacement cannot be written, the app has to carry on with what
    it had. Freezing there would leave it unable to save anything at all for the
    rest of the session, having restored nothing."""

    def explode(_path, _payload):
        raise OSError("disk full")

    original = storage._write_json
    storage._write_json = explode
    try:
        with pytest.raises(OSError):
            storage.restore_settings_file({"theme_mode": "light"})
    finally:
        storage._write_json = original

    assert _stored(store)["theme_mode"] == "dark"
    assert not storage.settings_writes_frozen()
    storage.save_settings({"theme_mode": "auto"})
    assert _stored(store)["theme_mode"] == "auto", "ordinary saving still works"


def test_restoring_onto_nothing_reports_no_safety_copy(store, tmp_path) -> None:
    store.unlink()

    kept = storage.restore_settings_file({"theme_mode": "light"})

    assert kept is None
    assert _stored(store)["theme_mode"] == "light"


def test_the_freeze_is_visible_to_whoever_asks(store) -> None:
    assert not storage.settings_writes_frozen()

    storage.restore_settings_file({"theme_mode": "light"})

    assert storage.settings_writes_frozen()


def test_reading_still_works_after_a_restore(store) -> None:
    """The app has to be able to show what it just restored."""
    storage.restore_settings_file({"theme_mode": "light", "scenes": []})

    assert storage.load_settings()["theme_mode"] == "light"
