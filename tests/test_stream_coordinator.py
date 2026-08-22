"""Tests for the single stream-owner coordinator on MainWindow.

Exactly one controller may drive the strip's colour path at a time. Starting a
stream stops the others and a power toggle stops all. A BLE disconnect stops
everything that exists only to feed a strip — with one exception, made on
purpose: Screen Sync keeps reading the screen and shows the result instead of
sending it, because none of that depends on the radio. It is told the link went,
and told again when it comes back.
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
        self.link_lost = 0
        self.link_back = 0

    def stop_if_running(self) -> None:
        self.stopped += 1

    def note_link_lost(self) -> None:
        self.link_lost += 1

    def note_link_back(self) -> None:
        self.link_back += 1

    # The card repaints itself after either of those, and asks the owner what to
    # say. Answered with real keys so a missing translation would still fail.
    def status_key(self) -> str:
        return "ambient.status_off"

    def toggle_label_key(self) -> str:
        return "ambient.toggle_off"

    def preview_hint_key(self) -> str:
        return "ambient.preview_hint"

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


def test_a_lost_link_stops_every_owner_except_the_screen() -> None:
    """The others have nothing to do without a strip and must not come back by
    themselves. Screen Sync has plenty to do — it is reading a screen — and is
    told what happened rather than taken apart."""
    app, window = _fresh_window()
    try:
        recs = _install_recorders(window)
        window.note_link_lost()
        assert recs["_fusion_ui"].stopped == 0, "the screen was torn down over a radio"
        assert recs["_fusion_ui"].link_lost == 1, "the screen was never told"
        for name, rec in recs.items():
            if name != "_fusion_ui":
                assert rec.stopped == 1, name
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_disconnect_goes_through_the_same_door() -> None:
    """The BLE event does not have its own idea of what a lost strip means."""
    app, window = _fresh_window()
    try:
        recs = _install_recorders(window)
        window._is_connected = True
        window._ble_events.on_connected_changed(False, "")
        assert window._is_connected is False
        assert recs["_fusion_ui"].stopped == 0
        assert recs["_fusion_ui"].link_lost == 1
        for name, rec in recs.items():
            if name != "_fusion_ui":
                assert rec.stopped == 1, name
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
        assert recs["_fusion_ui"].link_back == 1, "a run waiting for the strip was not told"
        assert recs["_music_ui"].link_back == 0, "something that was stopped was woken up"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
