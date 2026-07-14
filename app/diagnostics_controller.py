from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from app.app_info import APP_VERSION
from app.diagnostics import build_diagnostics_report
from app.support import build_unsupported_report_url


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
        # Include crash logs in the copy too: pasting into a support chat is the
        # most common path, and it should carry the same detail as the export.
        QApplication.clipboard().setText(self.text(include_crashes=True))
        host._log(host._tr("diagnostics.copied"))

    def _device_identity(self) -> tuple[str, str]:
        """Best-effort (device name, detected-protocol hint) for a report."""
        host = self._host
        snapshot = host._ble.diagnostics_snapshot()
        device = snapshot.get("device", {}) if isinstance(snapshot, dict) else {}
        driver = snapshot.get("driver", {}) if isinstance(snapshot, dict) else {}
        name = str(device.get("name", "")).strip()
        if not name and isinstance(host._settings, dict):
            name = str(host._settings.get("last_device_name", "")).strip()
        return name, str(driver.get("name", "")).strip()

    def report_unsupported(self) -> None:
        """One-click report: copy the diagnostics to the clipboard and open a
        prefilled GitHub issue so adding support for a controller is easy."""
        host = self._host
        QApplication.clipboard().setText(self.text(include_crashes=True))
        name, hint = self._device_identity()
        url = build_unsupported_report_url(device_name=name, driver_hint=hint)
        QDesktopServices.openUrl(QUrl(url))
        host._log(host._tr("diagnostics.report_opened"))

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
        # Reveal the saved file so it's ready to drag into an email or chat.
        self._reveal_in_explorer(Path(path))

    @staticmethod
    def _reveal_in_explorer(path: Path) -> None:
        """Open the file manager with the report selected (best-effort)."""
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["explorer", f"/select,{path}"], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path.parent)], check=False)
        except OSError:
            pass
