from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LUMABLE_DISABLE_SCHTASKS", "1")
# Startup services (autoconnect, license refresh, app triggers, hotkeys, silent
# update check, local API) are tested directly against their controllers, so a
# widget test should not schedule them as background work.
os.environ.setdefault("LUMABLE_NO_STARTUP_SERVICES", "1")




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
