from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
