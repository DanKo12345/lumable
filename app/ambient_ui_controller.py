from __future__ import annotations

import time
from typing import Any

from app.ambient_controller import AmbientController
from app.feature_gate import can_use
from app.screen_profiles import normalize_profile_id
from app.storage import save_settings

_DEFAULTS = {"region": "full", "saturation": 55, "smoothing": 65, "monitor": 0, "profile": "desktop"}


class AmbientUiController:
    """Wires the ambient screen-sync card to the capture/stream backend.

    Pro-gated. While ambient is running it owns the strip colour, so the manual
    colour and effect controls are disabled to avoid two writers fighting.
    """

    def __init__(self, host: Any) -> None:
        self._host = host
        self._ambient = AmbientController(host)
        self._frame_times: list[float] = []

    def wire(self) -> None:
        host = self._host
        host.ambient_toggle_button.clicked.connect(self._toggle)
        host.ambient_profile_segment.selected.connect(lambda _key: self._on_options_changed())
        host.ambient_area_selector.selected.connect(lambda _region: self._on_options_changed())
        host.ambient_saturation_slider.valueChanged.connect(self._on_options_changed)
        host.ambient_smoothing_slider.valueChanged.connect(self._on_options_changed)
        if host.ambient_monitor_combo is not None:
            host.ambient_monitor_combo.currentIndexChanged.connect(self._on_options_changed)
        # The preview shows raw → final; only the final colour drives BLE (wired
        # to the engine inside the controller).
        self._ambient.preview_sampled.connect(self._update_preview)
        self._ambient.failed.connect(self._on_failed)
        # A reconnect is only Screen Sync's business while Screen Sync is the
        # one driving the strip; the signal itself belongs to the whole app.
        host._ble.reconnect_succeeded.connect(self._on_reconnected)
        self.sync_controls()
        self.refresh_lock()

    def _on_reconnected(self, _address: str) -> None:
        # The session token is what actually keeps another mode's reconnect out
        # of the Screen Sync report; this check only says so at the layer where
        # the signal arrives. Removing it changes no observable behaviour.
        if self._ambient.is_running():
            self._ambient.note_reconnect()

    def refresh_lock(self) -> None:
        """Show the Pro badge and disable the controls until screen sync is unlocked.

        The toggle stays enabled so a click still opens the Pro upsell.
        """
        host = self._host
        unlocked = can_use("ambient_sync")
        lock_label = getattr(host, "ambient_lock_label", None)
        if lock_label is not None:
            lock_label.setVisible(not unlocked)
        for widget in (
            host.ambient_profile_segment,
            host.ambient_area_selector,
            host.ambient_saturation_slider,
            host.ambient_smoothing_slider,
            host.ambient_preview,
            host.ambient_monitor_combo,
        ):
            if widget is not None:
                widget.setEnabled(unlocked)

    def sync_controls(self) -> None:
        host = self._host
        saved = host._settings.get("ambient", {}) if isinstance(host._settings, dict) else {}
        region = str(saved.get("region", _DEFAULTS["region"]))
        saturation = int(saved.get("saturation", _DEFAULTS["saturation"]))
        smoothing = int(saved.get("smoothing", _DEFAULTS["smoothing"]))
        profile = normalize_profile_id(saved.get("profile", _DEFAULTS["profile"]))

        host.ambient_saturation_slider.jump_to(saturation)
        host.ambient_smoothing_slider.jump_to(smoothing)
        host.ambient_profile_segment.set_current(profile, animate=False)

        host.ambient_area_selector.blockSignals(True)
        host.ambient_area_selector.set_current_region(region, animate=False)
        host.ambient_area_selector.blockSignals(False)

        if host.ambient_monitor_combo is not None:
            monitor = int(saved.get("monitor", _DEFAULTS["monitor"]))
            monitor_index = host.ambient_monitor_combo.findData(monitor)
            host.ambient_monitor_combo.blockSignals(True)
            host.ambient_monitor_combo.setCurrentIndex(monitor_index if monitor_index >= 0 else 0)
            host.ambient_monitor_combo.blockSignals(False)
        self._refresh_value_labels()
        self._refresh_profile_description()

    def is_running(self) -> bool:
        return self._ambient.is_running()

    def stats(self) -> dict:
        return {
            "running": self._ambient.is_running(),
            "errors": self._ambient.stream_error_count(),
            "last_error": self._ambient.last_stream_error(),
            # The last run's numbers survive its stop, so a report exported
            # after switching sync off still describes the run being asked about.
            "live_sync": self._ambient.live_sync_report(),
            "live_sync_settings": self._ambient.live_sync_settings(),
        }

    def stop_if_running(self) -> None:
        if self._ambient.is_running():
            self._stop()

    def activate(self, profile_id: str | None = None) -> bool:
        """Start screen sync as if the card's toggle was pressed (keeps the
        licence/connection gates and stops any other active stream). A scene can
        pin ``profile_id`` (desktop/game/movie) — it is selected first, so
        applying the scene restores the exact look, and it applies live if screen
        sync is already running. Returns whether it is running — a gate may have
        silently blocked it."""
        host = self._host
        # Gate before touching the saved profile: if a Free licence or a missing
        # connection will refuse the start, the user's profile must not be
        # silently changed as a side effect. When already running, the gates
        # already passed, so switching the profile live is fine.
        if not self.is_running() and (not can_use("ambient_sync") or not host._is_connected):
            host.ambient_toggle_button.setChecked(True)
            self._toggle()  # surfaces the upsell / not-connected error
            return self.is_running()
        if profile_id:
            host.ambient_profile_segment.set_current(normalize_profile_id(profile_id), animate=False)
            self._on_options_changed()  # persist + reconfigure the live capture
        if self.is_running():
            return True
        host.ambient_toggle_button.setChecked(True)
        self._toggle()
        return self.is_running()

    def toggle(self) -> bool:
        """Start if stopped, stop if running. Returns whether it now runs.

        The one place that decision lives, so the tray menu and a global hotkey
        cannot drift apart from each other or from the card's own button — and
        neither of them has to know about the licence gate, the connection or
        the other modes, all of which ``activate`` already handles.
        """
        if self.is_running():
            self.stop_if_running()
            return False
        return self.activate()

    def shutdown(self) -> None:
        self._ambient.stop()

    def _toggle(self) -> None:
        host = self._host
        if not host.ambient_toggle_button.isChecked():
            self._stop()
            return
        if not can_use("ambient_sync"):
            host.ambient_toggle_button.setChecked(False)
            host._show_license_overlay()
            return
        if not host._is_connected:
            host.ambient_toggle_button.setChecked(False)
            host._show_error(host._tr("ambient.not_connected"))
            return
        self._start()

    def _start(self) -> None:
        host = self._host
        # Only one owner drives the strip at a time — stop the others (music,
        # software FX, DIY, sleep/sunrise timers).
        host.stop_streams(exclude=self)
        # If the strip is powered off the colour stream wouldn't show — turn it
        # on first so enabling screen sync "just works".
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()
        self._apply_options()

        def sink(red: int, green: int, blue: int, token: int, frame_id: int) -> bool:
            # Colour-only quiet stream: never resends brightness, drops frames
            # while a BLE write is in flight, and stays out of the session log.
            # The frame's identity rides along so the write's outcome can be
            # attributed to the run that produced it, even if that run has ended
            # by the time the strip answers.
            return host._ble.set_color_stream(
                red,
                green,
                blue,
                observer=lambda ok: self._ambient.command_finished(token, frame_id, ok),
            )

        # Seed from the strip's current colour so nothing flashes black before
        # the first captured frame (both the filter and the stream engine).
        # _current_color() is a QColor — read the channels, don't index it.
        seed = host._current_color()
        self._ambient.start(sink, initial=(seed.red(), seed.green(), seed.blue()))
        self._set_manual_controls_enabled(False)
        host.ambient_toggle_button.setText(host._tr("ambient.toggle_on"))
        self._frame_times.clear()
        status = getattr(host, "ambient_status_label", None)
        if status is not None:
            status.setText(host._tr("ambient.capture_status", fps=0))
            status.setVisible(True)
        host._log(host._tr("ambient.started_log"))

    def _stop(self) -> None:
        host = self._host
        was_running = self._ambient.is_running()
        self._ambient.stop()
        host.ambient_preview.clear()
        self._set_manual_controls_enabled(True)
        host.ambient_toggle_button.setChecked(False)
        host.ambient_toggle_button.setText(host._tr("ambient.toggle_off"))
        status = getattr(host, "ambient_status_label", None)
        if status is not None:
            status.setText(host._tr("ambient.status_off"))
        if was_running:
            host._log(host._tr("ambient.stopped_log"))

    def _apply_options(self) -> None:
        host = self._host
        # The sliders are user nudges on top of the profile; the profile carries
        # the actual recipe. All resolution happens on the capture thread.
        self._ambient.configure(
            profile_id=host.ambient_profile_segment.current_key(),
            intensity=int(host.ambient_saturation_slider.value()),
            smoothness=int(host.ambient_smoothing_slider.value()),
            region=host.ambient_area_selector.current_region(),
            monitor_index=self._selected_monitor(),
        )

    def _selected_monitor(self) -> int:
        combo = self._host.ambient_monitor_combo
        if combo is None:
            return 0
        return int(combo.currentData() or 0)

    def _on_options_changed(self) -> None:
        self._refresh_value_labels()
        self._refresh_profile_description()
        self._persist()
        if self._ambient.is_running():
            self._apply_options()

    def _refresh_value_labels(self) -> None:
        host = self._host
        host.ambient_saturation_value.setText(f"{host.ambient_saturation_slider.value()}%")
        host.ambient_smoothing_value.setText(f"{host.ambient_smoothing_slider.value()}%")

    def _refresh_profile_description(self) -> None:
        label = getattr(self._host, "ambient_profile_description", None)
        if label is not None:
            profile_id = self._host.ambient_profile_segment.current_key()
            label.setText(self._host._tr(f"ambient.profile.{profile_id}_desc"))

    def refresh_texts(self) -> None:
        """Refresh dynamic copy after a language change."""
        host = self._host
        host.ambient_mode_title_label.setText(host._tr("ambient.mode_title"))
        host.ambient_profile_title_label.setText(host._tr("ambient.profile_title"))
        self._refresh_profile_description()
        if not self.is_running():
            host.ambient_status_label.setText(host._tr("ambient.status_off"))

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["ambient"] = {
            "region": host.ambient_area_selector.current_region(),
            "saturation": int(host.ambient_saturation_slider.value()),
            "smoothing": int(host.ambient_smoothing_slider.value()),
            "monitor": self._selected_monitor(),
            "profile": host.ambient_profile_segment.current_key(),
        }
        save_settings(host._settings)

    def _update_preview(self, raw_r: int, raw_g: int, raw_b: int, r: int, g: int, b: int) -> None:
        host = self._host
        host.ambient_preview.set_colors((raw_r, raw_g, raw_b), (r, g, b))
        # Live capture rate: count frames sampled in the last second.
        now = time.monotonic()
        self._frame_times.append(now)
        cutoff = now - 1.0
        while self._frame_times and self._frame_times[0] < cutoff:
            self._frame_times.pop(0)
        status = getattr(host, "ambient_status_label", None)
        if status is not None:
            status.setText(host._tr("ambient.capture_status", fps=len(self._frame_times)))

    def _on_failed(self, reason: str) -> None:
        host = self._host
        self._stop()
        # Log the raw reason (incl. the underlying import/capture error) so a
        # failure is diagnosable, but show the user a friendly message.
        host._log(host._tr("ambient.error", error=reason))
        if reason.startswith("screen_capture_unavailable"):
            host._show_error(host._tr("ambient.capture_failed"))
        else:
            host._show_error(host._tr("ambient.error", error=reason))

    def _set_manual_controls_enabled(self, enabled: bool) -> None:
        host = self._host
        # Note: power_button stays enabled so the user can always switch the
        # strip off — pressing it stops ambient first (see MainWindow._toggle_power).
        for widget in (
            host.red_slider,
            host.green_slider,
            host.blue_slider,
            host.brightness_slider,
            host.pick_color_button,
            host.effect_combo,
            host.speed_slider,
        ):
            widget.setEnabled(enabled)
