from __future__ import annotations

from time import monotonic
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from app.update_checker import UpdateChecker, UpdateResult


class UpdateController:
    RATE_LIMIT_COOLDOWN_SECONDS = 600

    def __init__(self, host: Any, current_version: str, update_url: str, releases_url: str) -> None:
        self._host = host
        self._releases_url = releases_url.strip()
        self._checker = UpdateChecker(current_version, update_url, releases_url)
        self.result: UpdateResult | None = None
        self._silent_check = False
        self._rate_limited_until = 0.0
        self._checking_phase = 0
        self._checking_timer = QTimer(host) if isinstance(host, QObject) else None
        if self._checking_timer is not None:
            self._checking_timer.setInterval(450)
            self._checking_timer.timeout.connect(self._tick_check_animation)

    @property
    def checker(self) -> UpdateChecker:
        return self._checker

    def wire(self) -> None:
        self._host.check_update_button.clicked.connect(self.check)
        self._checker.finished.connect(self.handle_result)

    def check_silent(self) -> None:
        if self._checker.is_configured and not self._checker.is_running:
            self._silent_check = True
            self._checker.check()

    def check(self) -> None:
        if self.result is not None and self.result.state == "available":
            self.open_update_page()
            return
        if self._is_rate_limit_active():
            self.open_releases_page()
            return
        self._host.check_update_button.setEnabled(False)
        self._start_check_animation()
        self._host._log(self._host._tr("updates.checking"))
        self._silent_check = False
        if self._checker.is_running:
            return
        if not self._checker.check():
            self._stop_check_animation()
            self._host.check_update_button.setEnabled(True)
            self._host.check_update_button.setText(self._host._tr("updates.check"))

    def handle_result(self, result: UpdateResult) -> None:
        was_silent = self._silent_check
        self._silent_check = False
        self._stop_check_animation()
        self.result = result
        self._host._update_result = result
        self._host.check_update_button.setEnabled(True)
        self._host.check_update_button.setText(self._host._tr("updates.check"))
        if was_silent and result.state in {"disabled", "error", "rate_limited", "current"}:
            return
        if result.state == "disabled":
            self._host._log(self._host._tr("updates.disabled"))
            return
        if result.state == "rate_limited":
            self._rate_limited_until = monotonic() + self.RATE_LIMIT_COOLDOWN_SECONDS
            self._host.check_update_button.setText(self._host._tr("updates.open_releases"))
            self._host._log(self._host._tr("updates.rate_limited"))
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

    def open_releases_page(self) -> None:
        if not self._releases_url:
            self._host._show_error(self._host._tr("updates.no_download_url"))
            return
        QDesktopServices.openUrl(QUrl(self._releases_url))

    def _is_rate_limit_active(self) -> bool:
        return monotonic() < self._rate_limited_until

    def _start_check_animation(self) -> None:
        self._checking_phase = 0
        self._host.check_update_button.setText(self._checking_text())
        if self._checking_timer is not None and not self._checking_timer.isActive():
            self._checking_timer.start()

    def _stop_check_animation(self) -> None:
        if self._checking_timer is not None and self._checking_timer.isActive():
            self._checking_timer.stop()

    def _tick_check_animation(self) -> None:
        self._checking_phase = (self._checking_phase + 1) % 4
        self._host.check_update_button.setText(self._checking_text())

    def _checking_text(self) -> str:
        return f"{self._host._tr('updates.checking').rstrip('.')}{'.' * self._checking_phase}"
