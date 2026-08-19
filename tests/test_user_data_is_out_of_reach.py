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
import os
from pathlib import Path

import pytest

from tests.conftest import production_data_dir

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def child_data_dir_before_any_test():
    """Where a subprocess lands when it is spawned from a module-scoped fixture.

    This is the exact shape of the original mistake: higher-scoped fixtures run
    before the per-test isolation, so whatever protects this moment has to come
    from the session, not from the test. Captured here and asserted below.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "from app import storage; print(storage.DATA_DIR)"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip()).resolve()


def test_a_child_spawned_before_the_per_test_isolation_is_still_safe(
    child_data_dir_before_any_test,
) -> None:
    production = production_data_dir()
    child = child_data_dir_before_any_test

    assert child != production and production not in child.parents, (
        f"a subprocess started from a module fixture reached the real data: {child}"
    )


def test_the_storage_paths_point_somewhere_temporary() -> None:
    from app import storage

    production = production_data_dir()
    for name in ("DATA_DIR", "SETTINGS_PATH", "PROFILES_PATH"):
        path = getattr(storage, name).resolve()
        assert production not in path.parents and path != production, (
            f"storage.{name} still points at the real data: {path}"
        )


def test_the_paths_copied_at_import_are_temporary_too() -> None:
    """The window a fixture cannot close.

    These are computed once, when the module is first imported — and a test
    module imports the app during collection, before any fixture runs. A value
    copied from the real installation at that moment is held for the life of the
    process, and repointing storage.DATA_DIR afterwards never reaches it. Which
    is why the directory is chosen when conftest is loaded, not in a fixture.
    """
    from app import crash_logging, localization

    production = production_data_dir()
    captured = {
        "crash_logging.CRASH_LOG_DIR": crash_logging.CRASH_LOG_DIR,
        "crash_logging.FATAL_LOG_PATH": crash_logging.FATAL_LOG_PATH,
        "localization.USER_I18N_DIR": localization.USER_I18N_DIR,
    }
    for name, value in captured.items():
        path = Path(value).resolve()
        assert production not in path.parents and path != production, (
            f"{name} was captured from the real installation: {path}"
        )


def test_reading_the_real_settings_is_refused() -> None:
    """Deliberately reaching for it, the way a wrongly scoped fixture would."""
    target = production_data_dir() / "settings.json"

    with pytest.raises(AssertionError, match="real LumaBLE data"):
        target.open("r", encoding="utf-8")


def test_the_guard_recognises_a_path_in_the_real_directory() -> None:
    """Checked against a made-up name, never by writing.

    An earlier version of this test proved the guard by calling write_text on
    the real settings and expecting the refusal. It got the refusal — and an
    emptied settings file, because the audit event is raised after the file has
    been truncated. A test for a safety net must not be the thing that tears it.
    """
    from tests.conftest import is_production_path

    assert is_production_path(production_data_dir() / "settings.json")
    assert is_production_path(str(production_data_dir() / "nothing-here.json"))
    assert not is_production_path(Path.cwd() / "settings.json")
    assert not is_production_path(None)


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


def test_even_reading_the_real_settings_trips_the_guard() -> None:
    """Reading is safe to attempt — it cannot damage anything — so this one is
    allowed to reach for the real file and be refused."""
    target = production_data_dir() / "settings.json"

    with pytest.raises(AssertionError, match="real LumaBLE data"):
        target.read_bytes()


def test_a_child_process_lands_in_the_temporary_directory_too() -> None:
    """The gap the audit hook does not cover: hooks are not inherited, so a
    subprocess starts with a clean interpreter and a fresh import of the storage
    module. An environment variable is inherited, which is why the redirect
    lives there as well as on the module."""
    import subprocess
    import sys

    from app import storage

    result = subprocess.run(
        [sys.executable, "-c", "from app import storage; print(storage.DATA_DIR)"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    child_dir = Path(result.stdout.strip()).resolve()
    assert child_dir == storage.DATA_DIR.resolve(), (
        f"the child went to {child_dir}, the parent is using {storage.DATA_DIR}"
    )
    assert production_data_dir() != child_dir
    assert production_data_dir() not in child_dir.parents


def test_a_child_process_without_the_variable_would_use_the_real_directory() -> None:
    """The other half of the claim: the variable is doing the work, not luck.

    Without it a child resolves the installed location — which is correct for a
    person running the app, and is exactly what must never happen under test.
    """
    import subprocess
    import sys

    env = dict(os.environ)
    env.pop("LUMABLE_DATA_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", "from app import storage; print(storage.DATA_DIR)"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=env,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == production_data_dir()
