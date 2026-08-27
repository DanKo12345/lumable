from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.diagnostics_controller import DiagnosticsController
from app.main_layout import select_section
from app.main_window import MainWindow
from app.scan_choices import address_of
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
        monkeypatch.setattr(
            window._ble_events,
            "start_scan",
            lambda **kwargs: started.append(kwargs) or True,
        )
        monkeypatch.setattr(
            "app.diagnostics_controller.QFileDialog.getSaveFileName",
            lambda *_args: (str(destination), ""),
        )
        monkeypatch.setattr(DiagnosticsController, "_reveal_in_explorer", staticmethod(lambda _path: None))

        window._diagnostics_ctrl.export_scan_snapshot()
        assert window._diagnostics_ctrl._save_after_scan
        assert started == [{"auto_connect": False}]
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
        monkeypatch.setattr(window._ble_events, "start_scan", lambda **_kwargs: False)

        window._diagnostics_ctrl.export_scan_snapshot()

        assert not window._diagnostics_ctrl._save_after_scan
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_the_device_cards_report_button_saves_the_scan_it_already_has(monkeypatch, tmp_path) -> None:
    """One exporter, reached from the place the question comes up.

    The button sits beside the scan result rather than inside Diagnostics,
    because that is where somebody learns their controller is not supported.
    What it must not do is start the search again: the snapshot describing the
    device they are asking about is the one that has just been taken.
    """
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    destination = tmp_path / "scan.json"
    started: list = []
    try:
        window.show()
        app.processEvents()
        monkeypatch.setattr(
            window._ble,
            "scan_snapshot",
            lambda: ScanSnapshot(
                records=(AdvertisementRecord(name="SP630E", address="AA:BB:CC:DD:EE:FF"),),
                captured_at="2026-08-22T12:00:00",
                app_version="0.4.2",
            ),
        )
        monkeypatch.setattr(
            window._ble_events, "start_scan", lambda **kwargs: started.append(kwargs) or True
        )
        monkeypatch.setattr(
            "app.diagnostics_controller.QFileDialog.getSaveFileName",
            lambda *_args: (str(destination), ""),
        )
        monkeypatch.setattr(
            DiagnosticsController, "_reveal_in_explorer", staticmethod(lambda _path: None)
        )

        window.save_report_button.click()
        app.processEvents()

        assert started == [], "the button searched again instead of saving what it had"
        assert destination.exists()
        assert "SP630E" in destination.read_text(encoding="utf-8")
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_the_report_button_appears_where_the_question_comes_up(monkeypatch) -> None:
    """Hidden while a strip is in hand, offered when a scan found nothing that
    can be driven and after a compatibility check has run."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        # The device card lives on the settings screen; a widget on a screen
        # nobody is looking at reports itself hidden whatever it was told.
        select_section(window, "settings")
        app.processEvents()
        assert window.save_report_button.isVisible() is False

        window._ble_events.populate_devices([])
        app.processEvents()
        assert window.save_report_button.isVisible() is True, (
            "a scan that found nothing left the person with no next step"
        )

        window._ble_events.start_scan()
        app.processEvents()
        assert window.save_report_button.isVisible() is False, (
            "the offer outlived the question it was about"
        )
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def _strip(address: str, name: str, *, supported: bool = True, samples=(-60, -61, -59)) -> dict:
    return {
        "name": name,
        "address": address,
        "supported": supported,
        "rssi": str(samples[-1]) if samples else "-",
        "rssi_samples": tuple(samples),
        "services": "-",
    }


def _index_of_kind(window, wanted: str) -> int:
    from app.scan_choices import kind_of

    for index in range(window.device_combo.count()):
        if kind_of(window.device_combo.itemData(index)) == wanted:
            return index
    raise AssertionError(f"no {wanted} row in the picker")


def _kinds(window) -> list[str]:
    from app.scan_choices import kind_of

    return [kind_of(window.device_combo.itemData(i)) for i in range(window.device_combo.count())]


def test_opening_the_other_devices_through_the_real_signal_keeps_them_open() -> None:
    """Driven the way a person drives it, which is the only way this failed.

    ``currentIndexChanged`` is connected straight through, and the first row
    added to an emptied box becomes the current one — so adding "Back" as the
    first row of the unrecognised list announced that Back had been chosen while
    the list was still being built. Calling the method directly, as the earlier
    tests did, never went near that.
    """
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        select_section(window, "settings")
        app.processEvents()
        window._settings["trusted_device_addresses"] = ["AA:BB:CC:DD:EE:01"]
        window._ble_events.populate_devices(
            [
                _strip("AA:BB:CC:DD:EE:01", "Desk strip"),
                _strip("AA:BB:CC:DD:EE:03", "Unknown", supported=False, samples=(-88, -89, -87)),
            ]
        )
        app.processEvents()

        window.device_combo.setCurrentIndex(_index_of_kind(window, "show_unknown"))
        app.processEvents()

        assert _kinds(window) == ["back", "device"], (
            "the list closed itself while it was being built"
        )

        window.device_combo.setCurrentIndex(_index_of_kind(window, "back"))
        app.processEvents()

        assert "show_unknown" in _kinds(window), "there was no way back out"
        assert address_of(window.device_combo.currentData()) == "AA:BB:CC:DD:EE:01"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_the_report_carries_the_readings_for_recognised_strips_too(monkeypatch) -> None:
    """The unrecognised list answers "why is my device missing". Only the whole
    scan can answer why the list came out in that order, because the strips
    being compared are exactly the ones that list leaves out."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        monkeypatch.setattr(
            window._ble,
            "diagnostics_snapshot",
            lambda: {
                "nearby_scan": [
                    _strip("AA:BB:CC:DD:EE:01", "Desk strip", samples=(-52, -53, -51, -52)),
                    _strip("AA:BB:CC:DD:EE:02", "Hall strip", samples=(-89, -90, -88)),
                ],
                "nearby_unknown": [],
            },
        )

        report = window._diagnostics_ctrl.text()

        assert "Desk strip" in report and "Hall strip" in report
        assert "RSSI median: -52.0 dBm" in report
        assert "RSSI median: -89.0 dBm" in report
        assert "RSSI samples: 4" in report and "RSSI samples: 3" in report
        assert "Signal level: strong" in report and "Signal level: weak" in report
        assert "Supported: yes" in report
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_filling_the_picker_announces_nothing_by_itself() -> None:
    """Rebuilding a list is not somebody choosing from it.

    Every row added to an emptied box can become the current one, and some rows
    mean something when chosen. A scan that finds only unrecognised devices puts
    one of those first, so filling the list announced a choice nobody had made,
    halfway through filling it — the list expanded and collapsed again, and came
    out right only by the accident of toggling twice.

    Driven through a real window on purpose. The stand-in combo the other tests
    use is not a QObject, has no signals to emit, and could never have shown
    this.
    """
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    activations: list[str] = []
    try:
        window.show()
        select_section(window, "settings")
        app.processEvents()
        from app.scan_choices import kind_of

        original = window._ble_events.on_choice_activated

        def spy() -> None:
            activations.append(kind_of(window.device_combo.currentData()))
            original()

        window._ble_events.on_choice_activated = spy

        for devices in (
            [_strip("AA:BB:CC:DD:EE:11", "Headphones", supported=False)],
            [],
            [
                _strip("AA:BB:CC:DD:EE:21", "ELK-BLEDOM"),
                _strip("AA:BB:CC:DD:EE:22", "Watch", supported=False),
            ],
        ):
            activations.clear()
            window._ble_events.populate_devices(devices)
            app.processEvents()
            assert activations == [], f"the rebuild chose rows on its own: {activations}"
            assert window._ble_events._showing_unknown is False

        assert _kinds(window)[-1] == "show_unknown"
    finally:
        window._ble_events.on_choice_activated = original
        window._ble.shutdown()
        window.close()
        app.processEvents()
