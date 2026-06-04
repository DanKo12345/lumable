from __future__ import annotations

from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from app.update_checker import UpdateChecker, UpdateResult


class UpdateController:
    def __init__(self, host: Any, current_version: str, update_url: str, releases_url: str) -> None:
        self._host = host
        self._checker = UpdateChecker(current_version, update_url, releases_url)
        self.result: UpdateResult | None = None

    @property
    def checker(self) -> UpdateChecker:
        return self._checker

    def wire(self) -> None:
        self._host.check_update_button.clicked.connect(self.check)
        self._checker.finished.connect(self.handle_result)

    def check_silent(self) -> None:
        if self._checker.is_configured:
            self._checker.check()

    def check(self) -> None:
        if self.result is not None and self.result.state == "available":
            self.open_update_page()
            return
        self._host.check_update_button.setEnabled(False)
        self._host.check_update_button.setText(self._host._tr("updates.checking"))
        self._host._log(self._host._tr("updates.checking"))
        self._checker.check()

    def handle_result(self, result: UpdateResult) -> None:
        self.result = result
        self._host._update_result = result
        self._host.check_update_button.setEnabled(True)
        self._host.check_update_button.setText(self._host._tr("updates.check"))
        if result.state == "disabled":
            self._host._log(self._host._tr("updates.disabled"))
            return
        if result.state == "error":
            self._host._log(self._host._tr("updates.error", error=result.message or "unknown"))
            return
        if result.info is None:
            self._host._log(self._host._tr("updates.error", error="invalid response"))
            return
        if result.state == "available":
            self._host.check_update_button.setText(self._host._tr("updates.open"))
            self._host._log(
                self._host._tr(
                    "updates.available",
                    current=result.info.current_version,
                    latest=result.info.latest_version,
                )
            )
            return
        self._host._log(self._host._tr("updates.current", version=result.info.current_version))

    def open_update_page(self) -> None:
        if self.result is None or self.result.info is None or not self.result.info.url:
            self._host._show_error(self._host._tr("updates.no_download_url"))
            return
        QDesktopServices.openUrl(QUrl(self.result.info.url))
