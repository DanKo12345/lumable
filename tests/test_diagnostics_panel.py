from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.diagnostics_controller import DiagnosticsController
from app.main_layout import select_section
from app.main_window import MainWindow
from app.scan_snapshot import AdvertisementRecord, ScanSnapshot


def _inside(widget, ancestor) -> bool:
    top_left = widget.mapTo(ancestor, QPoint(0, 0))
    return (
        top_left.x() >= 0
        and top_left.y() >= 0
        and top_left.x() + widget.width() <= ancestor.width()
        and top_left.y() + widget.height() <= ancestor.height()
    )


@pytest.mark.parametrize("size", ((WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT), (1280, 860)))
def test_the_diagnostics_tools_keep_one_action_column(size) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(*size)
        window.show()
        select_section(window, "settings")
        app.processEvents()
        window.body_scroll.ensureWidgetVisible(window.diagnostics_card, 0, 16)
        app.processEvents()

        buttons = (
            window.show_logs_button,
            window.export_scan_button,
            window.check_update_button,
        )
        right_edges = {
            button.mapTo(window.diagnostics_tools_list, QPoint(0, 0)).x() + button.width()
            for button in buttons
        }
        assert len(right_edges) == 1, "diagnostic actions no longer share one right edge"
        assert len({button.width() for button in buttons}) == 1
        assert all(_inside(button, window.diagnostics_tools_list) for button in buttons)
        assert window.body_scroll.horizontalScrollBar().maximum() == 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_report_tools_have_one_primary_command_and_two_accessible_icons() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()

        assert window.report_device_button._role == "accent"
        for button in (window.copy_diagnostics_button, window.export_diagnostics_button):
            assert button.text() == ""
            assert button.accessibleName()
            assert button.toolTip()
            assert button.width() == button.height()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_saving_a_ble_report_runs_the_missing_scan_first(monkeypatch, tmp_path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    snapshots = [ScanSnapshot()]
    started = []
    destination = tmp_path / "scan.json"
    try:
        window.show()
        select_section(window, "settings")
        app.processEvents()
        monkeypatch.setattr(window._ble, "scan_snapshot", lambda: snapshots[0])
        monkeypatch.setattr(window._ble_events, "start_scan", lambda: started.append(True) or True)
        monkeypatch.setattr(
            "app.diagnostics_controller.QFileDialog.getSaveFileName",
            lambda *_args: (str(destination), ""),
        )
        monkeypatch.setattr(DiagnosticsController, "_reveal_in_explorer", staticmethod(lambda _path: None))

        window._diagnostics_ctrl.export_scan_snapshot()
        assert started == [True]
        assert window._diagnostics_ctrl._save_after_scan
        assert not destination.exists(), "the app tried to save before scanning"

        snapshots[0] = ScanSnapshot(
            records=(AdvertisementRecord(name="SP630E", address="AA:BB:CC:DD:EE:FF"),),
            captured_at="2026-08-01T20:00:00",
            app_version="0.3.7",
        )
        window._diagnostics_ctrl._on_scan_completed([])
        app.processEvents()

        assert not window._diagnostics_ctrl._save_after_scan
        assert destination.exists(), "the save dialog did not continue after the scan"
        assert "SP630E" in destination.read_text(encoding="utf-8")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_a_refused_scan_does_not_leave_a_future_export_armed(monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        monkeypatch.setattr(window._ble, "scan_snapshot", lambda: ScanSnapshot())
        monkeypatch.setattr(window._ble_events, "start_scan", lambda: False)

        window._diagnostics_ctrl.export_scan_snapshot()

        assert not window._diagnostics_ctrl._save_after_scan
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
