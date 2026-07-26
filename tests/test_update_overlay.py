from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from app.widgets.update_overlay import UpdateOverlay

_LABELS = {
    "title": "Update available",
    "release": "LumaBLE 0.3.5",
    "versions": "Installed 0.3.4 → available 0.3.5-beta",
    "installed": "Installed",
    "available": "Available",
    "current_version": "0.3.4",
    "latest_version": "0.3.5-beta",
    "whats_new": "What's new",
    "notes": "x" * 2000,  # a deliberately huge changelog
    "open": "Open download page",
    "later": "Remind later",
    "skip": "Skip this version",
    "close": "Close",
}


def _overlay(parent: QWidget) -> UpdateOverlay:
    return UpdateOverlay(dict(_LABELS), "0.3.5-beta", parent)


def test_skip_requested_carries_the_exact_version_from_the_window() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    overlay = _overlay(parent)
    captured: list[str] = []
    overlay.skip_requested.connect(captured.append)

    overlay._on_skip()

    # The version comes from the window, not from a mutable controller field.
    assert captured == ["0.3.5-beta"]
    parent.deleteLater()


def test_release_notes_are_plain_text_and_length_capped() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    overlay = _overlay(parent)

    notes = overlay.findChild(QLabel, "updateBody")
    assert notes is not None
    # GitHub body is external text: never interpreted as HTML, never unbounded.
    assert notes.textFormat() == Qt.PlainText
    assert len(notes.text()) <= UpdateOverlay.NOTES_LIMIT + 1  # +1 for the ellipsis
    # Long notes get a bounded, scrollable area.
    assert overlay.findChild(QScrollArea, "updateNotesScroll") is not None
    parent.deleteLater()


def test_release_title_is_length_capped() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    labels = dict(_LABELS)
    labels["release"] = "L" * 400
    overlay = UpdateOverlay(labels, "0.3.5-beta", parent)

    release = overlay.findChild(QLabel, "updateRelease")
    assert release is not None
    assert len(release.text()) <= UpdateOverlay.TITLE_LIMIT + 1
    parent.deleteLater()


def test_short_notes_use_no_scroll_area() -> None:
    QApplication.instance() or QApplication([])
    parent = QWidget()
    labels = dict(_LABELS)
    labels["notes"] = "One short line."
    overlay = UpdateOverlay(labels, "0.3.5-beta", parent)

    # Short notes render inline — no empty 140px scroll area.
    assert overlay.findChild(QLabel, "updateBody") is not None
    assert overlay.findChild(QScrollArea, "updateNotesScroll") is None
    parent.deleteLater()


def test_short_window_keeps_header_and_actions_inside_panel() -> None:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(860, 420)
    parent.show()
    overlay = _overlay(parent)
    overlay.open()
    QTest.qWait(240)

    panel = overlay._panel
    assert panel.height() <= parent.height() - 24
    assert panel.geometry().top() >= 0
    assert panel.geometry().bottom() < overlay.height()
    for name in ("updateClose", "updateLaterButton", "updateOpenButton", "updateSkipLink"):
        widget = overlay.findChild(QWidget, name)
        assert widget is not None
        top_left = widget.mapTo(panel, widget.rect().topLeft())
        bottom_right = widget.mapTo(panel, widget.rect().bottomRight())
        assert top_left.y() >= 0
        assert bottom_right.y() < panel.height()

    parent.resize(1000, 700)
    app.processEvents()
    assert panel.height() == overlay._preferred_height
    overlay.close_overlay()
    parent.deleteLater()
    app.processEvents()
