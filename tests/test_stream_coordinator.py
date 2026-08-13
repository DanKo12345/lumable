"""Tests for the single stream-owner coordinator on MainWindow.

Exactly one controller may drive the strip's colour path at a time. Starting a
stream stops the others, a power toggle stops all, and a BLE disconnect stops
everything so nothing keeps writing to a dead connection (or auto-resumes on
reconnect).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow

# Screen Sync no longer owns the strip itself: in both of its modes the colour
# is composed and written by the Fusion coordinator, so that is the owner the
# others have to yield to. The music card is still here because its standalone
# mode is unchanged and still takes the strip on its own.
_OWNER_ATTRS = ("_fusion_ui", "_music_ui", "_software_fx_ui", "_diy_ui", "_timer_ctrl")


class _Recorder:
    def __init__(self) -> None:
        self.stopped = 0

    def stop_if_running(self) -> None:
        self.stopped += 1

    def shutdown(self) -> None:
        # MainWindow.close() calls shutdown() on its stream owners; the recorder
        # stands in for one, so it must accept the teardown call.
        pass


def _install_recorders(window: MainWindow) -> dict[str, _Recorder]:
    recs: dict[str, _Recorder] = {}
    for name in _OWNER_ATTRS:
        rec = _Recorder()
        setattr(window, name, rec)
        recs[name] = rec
    return recs


def _fresh_window() -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication([])
    return app, MainWindow()


def test_stop_streams_excludes_the_new_owner() -> None:
    app, window = _fresh_window()
    try:
        recs = _install_recorders(window)
        window.stop_streams(exclude=recs["_music_ui"])
        assert recs["_music_ui"].stopped == 0
        for name, rec in recs.items():
            if name != "_music_ui":
                assert rec.stopped == 1, name
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_stop_all_streams_stops_every_owner() -> None:
    app, window = _fresh_window()
    try:
        recs = _install_recorders(window)
        window.stop_all_streams()
        assert all(rec.stopped == 1 for rec in recs.values())
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_disconnect_stops_all_streams() -> None:
    app, window = _fresh_window()
    try:
        recs = _install_recorders(window)
        window._is_connected = True
        window._ble_events.on_connected_changed(False, "")
        assert window._is_connected is False
        assert all(rec.stopped == 1 for rec in recs.values())
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_connect_does_not_stop_streams() -> None:
    app, window = _fresh_window()
    try:
        recs = _install_recorders(window)
        window._is_connected = False
        window._ble_events.on_connected_changed(True, "AA:BB:CC:DD:EE:FF")
        assert all(rec.stopped == 0 for rec in recs.values())
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
