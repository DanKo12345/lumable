from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LUMABLE_DISABLE_SCHTASKS", "1")
# Startup services (autoconnect, license refresh, app triggers, hotkeys, silent
# update check, local API) are tested directly against their controllers, so a
# widget test should not schedule them as background work.
os.environ.setdefault("LUMABLE_NO_STARTUP_SERVICES", "1")


def production_data_dir() -> Path:
    """Where the installed app keeps its data on this machine."""
    from platformdirs import user_data_dir

    return Path(user_data_dir("LumaBLE", False, roaming=True)).resolve()


def is_production_path(candidate: object) -> bool:
    """Whether a path being opened belongs to the installed app's data.

    Separate from the hook so it can be checked against a made-up path. Proving
    the guard by actually writing to the real settings is not a proof, it is the
    accident: the audit event is raised after the operating system has already
    truncated the file, so the call fails *and* the data is gone. That is not a
    hypothetical either — it is how this file was emptied while testing the
    guard meant to protect it.
    """
    if not isinstance(candidate, (str, bytes, os.PathLike)):
        return False
    text = os.fspath(candidate)
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    try:
        production = str(production_data_dir()).lower()
    except Exception:
        return False
    return text.lower().startswith(production)


def _guard_production_data() -> None:
    """Refuse, loudly, any attempt to open a file in the real data directory.

    The per-test isolation below is function-scoped, and pytest builds
    higher-scoped fixtures first — so a module- or session-scoped fixture that
    builds a MainWindow runs *before* it and reads and writes the developer's
    own settings. That is not hypothetical: it happened, and the only symptom
    was a test failing because of what the developer had last chosen in the app.

    Redirecting at session scope fixes the ordering, but a wrongly scoped
    fixture could reach the path some other way — through a saved constant or a
    module that captured it at import. This closes the door at the file itself:
    nothing in *this* process may open it, whatever route it took. An audit hook
    cannot be removed once installed, which is exactly the property wanted here.

    It stops the call, not the damage: the event is raised after the file has
    already been opened for writing, so a truncating mode has already emptied
    it. The guard is a tripwire that names the culprit, and the redirects above
    are what actually keep the data safe.

    It does not reach a child process: audit hooks are not inherited. That gap
    is covered separately, by ``LUMABLE_DATA_DIR`` in the environment, which is.
    """
    import sys as _sys

    def _hook(event: str, args) -> None:
        if event != "open" or not args:
            return
        if is_production_path(args[0]):
            text = os.fspath(args[0])
            raise AssertionError(
                "a test tried to open the real LumaBLE data: "
                f"{text}. Isolate the storage paths in the fixture that reached "
                "it — see _isolate_user_data, and note that a module- or "
                "session-scoped fixture runs before the function-scoped one."
            )

    _sys.addaudithook(_hook)


_guard_production_data()


@pytest.fixture(scope="session", autouse=True)
def _isolate_user_data_for_the_whole_session(tmp_path_factory):
    """Point the storage paths away from the real data before anything runs.

    Session scope on purpose: this has to be in place before a module-scoped
    fixture builds its window, and those are set up before any function-scoped
    fixture. The per-test isolation still gives each test a fresh directory.

    Set in the environment as well as on the module, because a subprocess starts
    with a fresh import of ``app.storage`` and inherits nothing else.
    """
    try:
        from app import storage
    except Exception:
        yield
        return

    data_dir = tmp_path_factory.mktemp("lumable-session")
    storage.DATA_DIR = data_dir
    storage.SETTINGS_PATH = data_dir / "settings.json"
    storage.PROFILES_PATH = data_dir / "profiles.json"
    # And in the environment, which a child process inherits and a patched
    # module attribute does not. Every helper the suite runs as a subprocess
    # resolves its data directory from here.
    os.environ["LUMABLE_DATA_DIR"] = str(data_dir)
    yield


@pytest.fixture(autouse=True)
def _isolate_user_data(tmp_path, monkeypatch):
    """Isolate every test from the developer's real LumaBLE data.

    Without this, ``load_settings()`` (reached via ``feature_gate.is_pro``) reads
    the actual ``settings.json`` on the machine running the suite, so results
    differ between a developer with an activated Pro license and a clean CI box.
    Each test gets a fresh, empty data directory; tests that need their own
    storage paths simply monkeypatch them again afterwards (their setattr wins).
    """
    try:
        from app import feature_gate, storage
    except Exception:
        yield
        return

    data_dir = tmp_path / "lumable-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(storage, "DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr(storage, "SETTINGS_PATH", data_dir / "settings.json", raising=False)
    monkeypatch.setattr(storage, "PROFILES_PATH", data_dir / "profiles.json", raising=False)
    monkeypatch.setattr(storage, "_legacy_migration_pairs", lambda: [], raising=False)
    monkeypatch.setattr(storage, "_migration_done", True, raising=False)
    # In the environment too, so a helper this test runs as a subprocess reads
    # and writes the same directory the test does. Without it the child would
    # land in the session directory — safe, but describing different data than
    # the test that spawned it.
    monkeypatch.setenv("LUMABLE_DATA_DIR", str(data_dir))

    feature_gate.invalidate_pro_cache()
    yield
    feature_gate.invalidate_pro_cache()


@pytest.fixture
def preserve_motion_policy():
    """Opt-in (NOT autouse): snapshot and restore the global motion_policy so a
    step-2 integration test that flips reduced motion can't leak into others."""
    from app.motion_policy import motion_policy

    saved_mode = motion_policy._mode
    saved_provider = motion_policy._provider
    saved_reduced = motion_policy._reduced
    try:
        yield motion_policy
    finally:
        motion_policy._mode = saved_mode
        motion_policy._provider = saved_provider
        # If the resolved flag changed during the test, notify subscribers so an
        # already-open window reverts its visual state instead of being stranded.
        if motion_policy._reduced != saved_reduced:
            motion_policy._reduced = saved_reduced
            motion_policy.changed.emit(saved_reduced)


def _qt_widgets_available() -> bool:
    """QtWidgets is available if it can import and create an offscreen app."""
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        app.processEvents()
    except Exception:
        return False
    return True


if not _qt_widgets_available():
    # When libEGL is missing we cannot import QtWidgets at all.
    # Provide a stub module whose *class* attributes are real Python classes
    # so that `class Foo(QPushButton)` doesn't cause metaclass conflicts.

    class _QtWidgetStub:
        """Minimal stand-in for any Qt widget or object class."""
        def __init__(self, *args, **kwargs):
            pass
        def update(self): pass
        def isEnabled(self): return True

    class _QtModule:
        """Pretends to be a PySide6 module by returning stub classes."""
        Qt = MagicMock()
        Qt.UserRole = 256

        def __getattr__(self, name: str):
            # Return a fresh subclass so each name is a distinct class
            stub_cls = type(name, (_QtWidgetStub,), {})
            setattr(self, name, stub_cls)
            return stub_cls

    _widget_stub = _QtModule()

    for _mod in ("PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtSvg"):
        sys.modules[_mod] = _widget_stub


@pytest.fixture
def screen(request):
    """A built and wired automations screen, and the host it lives on.

    Shared by the screen's tests and the rule editor's. It lives here rather than in
    either of them because a fixture imported from another test module reads to every
    linter as a redefinition — and because both files must be looking at the same
    screen. See tests/automation_screen.py for the fake facade behind it.
    """
    from automation_screen import Host
    from PySide6.QtWidgets import QApplication

    from app.automation_ui_controller import AutomationUiController
    from app.panels.automations_panel import (
        build_automation_bridge_section,
        build_automation_journal_section,
        build_automation_rules_section,
        build_automations_section,
    )

    QApplication.instance() or QApplication([])
    host = Host()
    # The same builders, in the same order, as the automations page itself.
    for builder in (
        build_automations_section,
        build_automation_rules_section,
        build_automation_journal_section,
        build_automation_bridge_section,
    ):
        host._column.addWidget(builder(host))
    controller = AutomationUiController(host)
    host._automation_ui = controller
    controller.wire()

    def teardown() -> None:
        # The refresh poll outlives the fixture otherwise, and would go on ticking
        # against a torn-down host for the rest of the suite.
        controller.stop()
        host.close()
        # RuleEditorOverlay closes with deleteLater(), as it should in the running
        # app. Tests do not naturally return to exec(), so drain deferred deletes
        # here instead of leaving dozens of SVG renderers and animations for
        # QApplication's process-exit teardown.
        from PySide6.QtCore import QCoreApplication, QEvent

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()

    request.addfinalizer(teardown)
    return host, controller
