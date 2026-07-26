from __future__ import annotations

from time import monotonic, time
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices

from app.motion_policy import motion_policy
from app.storage import save_settings
from app.update_checker import UpdateChecker, UpdateResult, canonical_version


class UpdateController(QObject):
    """QObject so the controller can be parented to its host window: the global
    motion_policy.changed subscription is then torn down by Qt when the window
    dies, instead of outliving it and reaching into a deleted widget."""

    AUTO_CHECK_INTERVAL_SECONDS = 6 * 60 * 60
    UPDATE_REMINDER_INTERVAL_SECONDS = 24 * 60 * 60
    RATE_LIMIT_COOLDOWN_SECONDS = 600

    def __init__(self, host: Any, current_version: str, update_url: str, releases_url: str) -> None:
        super().__init__(host if isinstance(host, QObject) else None)
        self._host = host
        self._current_version = current_version.strip()
        self._releases_url = releases_url.strip()
        self._checker = UpdateChecker(current_version, update_url, releases_url)
        self.result: UpdateResult | None = None
        self._silent_check = False
        self._rate_limited_until = 0.0
        self._checking_phase = 0
        self._checking_active = False
        self._checking_timer = QTimer(host) if isinstance(host, QObject) else None
        if self._checking_timer is not None:
            self._checking_timer.setInterval(450)
            self._checking_timer.timeout.connect(self._tick_check_animation)
        motion_policy.changed.connect(self._on_motion_changed)

    @property
    def checker(self) -> UpdateChecker:
        return self._checker

    def wire(self) -> None:
        self._host.check_update_button.clicked.connect(self.check)
        self._checker.finished.connect(self.handle_result)

    def check_silent(self) -> None:
        if not self._checker.is_configured or self._checker.is_running:
            return
        if not self._should_run_silent_check():
            return
        self._silent_check = True
        if self._checker.check():
            self._mark_silent_check_attempted()
        else:
            self._silent_check = False

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
            self._notify_update(result.info, was_silent)
            return
        self._host._log(self._host._tr("updates.current", version=result.info.current_version))

    def _notify_update(self, info, was_silent: bool) -> None:
        # Manual checks already surface the result on the button. For background
        # checks, repeat the reminder at a humane interval while the app is old.
        if not was_silent:
            return
        settings = getattr(self._host, "_settings", None)
        if isinstance(settings, dict):
            skipped = str(settings.get("updates_skipped_version", ""))
            if skipped and skipped == canonical_version(info.latest_version):
                # The user explicitly skipped exactly this version. A different
                # build (newer beta or the final release) has a different
                # canonical id and will still notify.
                return
            now = int(time())
            notified_version = str(settings.get("updates_notified_version", ""))
            try:
                notified_at = int(settings.get("updates_notified_at", 0) or 0)
            except (TypeError, ValueError):
                notified_at = 0
            if (
                notified_version == info.latest_version
                and 0 <= now - notified_at < self.UPDATE_REMINDER_INTERVAL_SECONDS
            ):
                return
            settings["updates_notified_version"] = info.latest_version
            settings["updates_notified_at"] = now
            save_settings(settings)
        show = getattr(self._host, "_show_update_overlay", None)
        if callable(show):
            show(info)

    def skip_version(self, version: str) -> None:
        """Remember that the user chose to skip this exact version, so future
        background checks stay quiet about it. Manual checks still report it."""
        settings = getattr(self._host, "_settings", None)
        if not isinstance(settings, dict):
            return
        settings["updates_skipped_version"] = canonical_version(version)
        save_settings(settings)

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

    def _should_run_silent_check(self) -> bool:
        settings = getattr(self._host, "_settings", {})
        if not isinstance(settings, dict):
            return True
        if str(settings.get("updates_last_auto_check_version", "")) != self._current_version:
            return True
        try:
            last_check_at = float(settings.get("updates_last_auto_check_at", 0) or 0)
        except (TypeError, ValueError):
            last_check_at = 0.0
        elapsed = time() - last_check_at
        return elapsed < 0 or elapsed >= self.AUTO_CHECK_INTERVAL_SECONDS

    def _mark_silent_check_attempted(self) -> None:
        settings = getattr(self._host, "_settings", None)
        if not isinstance(settings, dict):
            return
        settings["updates_last_auto_check_at"] = int(time())
        settings["updates_last_auto_check_version"] = self._current_version
        save_settings(settings)

    def _start_check_animation(self) -> None:
        self._checking_phase = 0
        self._checking_active = True
        self._host.check_update_button.setText(self._checking_text())
        self._sync_check_animation()

    def _stop_check_animation(self) -> None:
        self._checking_active = False
        if self._checking_timer is not None and self._checking_timer.isActive():
            self._checking_timer.stop()

    def _sync_check_animation(self) -> None:
        """The check itself keeps running under reduced motion — only the trailing
        dots stop, leaving a static "Checking for updates..." label."""
        timer = self._checking_timer
        if timer is None:
            return
        if self._checking_active and not motion_policy.reduced:
            if not timer.isActive():
                timer.start()
            return
        timer.stop()

    @Slot(bool)
    def _on_motion_changed(self, _reduced: bool) -> None:
        if not self._checking_active:
            return
        self._checking_phase = 0
        try:
            self._host.check_update_button.setText(self._checking_text())
        except RuntimeError:
            # Host window already torn down (its C++ side is gone) — nothing to update.
            self._checking_active = False
            return
        self._sync_check_animation()

    def _tick_check_animation(self) -> None:
        self._checking_phase = (self._checking_phase + 1) % 4
        self._host.check_update_button.setText(self._checking_text())

    def _checking_text(self) -> str:
        raw = self._host._tr("updates.checking")
        if motion_policy.reduced:
            return raw
        return f"{raw.rstrip('.')}{'.' * self._checking_phase}"
