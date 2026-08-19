"""A test process must not be able to touch the real LumaBLE data.

This exists because it happened. A module-scoped fixture built a MainWindow,
higher-scoped fixtures are set up before function-scoped ones, and the suite's
isolation is function-scoped — so that window read and wrote the developer's own
``settings.json``. The symptom was three tests failing because of what had last
been chosen in the running app, which points nowhere near the cause.

Fixing the one fixture was not enough: the next module-scoped fixture would do
it again. These check the two guarantees that make the mistake impossible rather
than merely absent — the paths are redirected before anything runs, and the real
directory refuses to open at all.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import production_data_dir


def test_the_storage_paths_point_somewhere_temporary() -> None:
    from app import storage

    production = production_data_dir()
    for name in ("DATA_DIR", "SETTINGS_PATH", "PROFILES_PATH"):
        path = getattr(storage, name).resolve()
        assert production not in path.parents and path != production, (
            f"storage.{name} still points at the real data: {path}"
        )


def test_reading_the_real_settings_is_refused() -> None:
    """Deliberately reaching for it, the way a wrongly scoped fixture would."""
    target = production_data_dir() / "settings.json"

    with pytest.raises(AssertionError, match="real LumaBLE data"):
        target.open("r", encoding="utf-8")


def test_writing_into_the_real_directory_is_refused() -> None:
    target = production_data_dir() / "settings.json"

    with pytest.raises(AssertionError, match="real LumaBLE data"):
        target.write_text("{}", encoding="utf-8")


def test_saving_settings_never_reaches_the_real_file() -> None:
    """The whole path a window takes, end to end: if this wrote to the real
    file the guard would raise, and if it silently wrote nowhere the temporary
    file would not exist."""
    from app.storage import SETTINGS_PATH, load_settings, save_settings

    settings = load_settings()
    settings["fusion"] = {"mode": "screen_music"}
    save_settings(settings)

    assert SETTINGS_PATH.exists()
    assert json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))["fusion"]["mode"] == (
        "screen_music"
    )
    assert production_data_dir() not in SETTINGS_PATH.resolve().parents


def test_the_real_settings_file_is_never_modified_by_a_run() -> None:
    """Stated as a property rather than a hope. Nothing here can even measure
    the real file without tripping the guard — which is the point."""
    target = production_data_dir() / "settings.json"

    with pytest.raises(AssertionError, match="real LumaBLE data"):
        target.read_bytes()
