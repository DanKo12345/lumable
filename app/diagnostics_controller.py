from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication, QFileDialog

from app.app_info import APP_VERSION
from app.diagnostics import build_diagnostics_report


class DiagnosticsController:
    """Builds the diagnostics report and handles its copy/export actions.

    Extracted from MainWindow to keep the window a thin orchestrator. Reads the
    live BLE snapshot, session log and ambient stats off the host on demand.
    """

    def __init__(self, host: Any) -> None:
        self._host = host

    def text(self, *, include_crashes: bool = False) -> str:
        host = self._host
        return build_diagnostics_report(
            host._ble.diagnostics_snapshot(),
            host._ui_feedback.raw_log_messages(),
            include_crashes=include_crashes,
            ambient=host._ambient_ui.stats(),
        )

    def refresh_view(self) -> None:
        host = self._host
        if host.diagnostics_output is not None and host._ui_feedback is not None:
            host.diagnostics_output.setPlainText(self.text())

    def copy_report(self) -> None:
        host = self._host
        QApplication.clipboard().setText(self.text())
        host._log(host._tr("diagnostics.copied"))

    def export_report(self) -> None:
        host = self._host
        default_name = f"lumable-diagnostics-{APP_VERSION}.txt"
        path, _selected_filter = QFileDialog.getSaveFileName(
            host,
            host._tr("diagnostics.export_title"),
            str(Path.home() / "Desktop" / default_name),
            host._tr("diagnostics.file_filter"),
        )
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        report = self.text(include_crashes=True)
        try:
            Path(path).write_text(report, encoding="utf-8")
        except OSError as exc:
            host._show_error(host._tr("diagnostics.export_error", error=str(exc)))
            return
        host._log(host._tr("diagnostics.exported", path=Path(path).name))
