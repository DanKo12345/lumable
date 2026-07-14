from __future__ import annotations

import time
from typing import Any

from app.ambient_controller import AmbientController
from app.feature_gate import can_use
from app.storage import save_settings

_DEFAULTS = {"region": "full", "saturation": 55, "smoothing": 65, "monitor": 0}


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
        host.ambient_region_combo.currentIndexChanged.connect(self._on_options_changed)
        host.ambient_saturation_slider.valueChanged.connect(self._on_options_changed)
        host.ambient_smoothing_slider.valueChanged.connect(self._on_options_changed)
        if host.ambient_monitor_combo is not None:
            host.ambient_monitor_combo.currentIndexChanged.connect(self._on_options_changed)
        self._ambient.color_sampled.connect(self._update_preview)
        self._ambient.failed.connect(self._on_failed)
        self.sync_controls()
        self.refresh_lock()

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
            host.ambient_region_combo,
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

        host.ambient_saturation_slider.jump_to(saturation)
        host.ambient_smoothing_slider.jump_to(smoothing)

        index = host.ambient_region_combo.findData(region)
        host.ambient_region_combo.blockSignals(True)
        host.ambient_region_combo.setCurrentIndex(index if index >= 0 else 0)
        host.ambient_region_combo.blockSignals(False)

        if host.ambient_monitor_combo is not None:
            monitor = int(saved.get("monitor", _DEFAULTS["monitor"]))
            monitor_index = host.ambient_monitor_combo.findData(monitor)
            host.ambient_monitor_combo.blockSignals(True)
            host.ambient_monitor_combo.setCurrentIndex(monitor_index if monitor_index >= 0 else 0)
            host.ambient_monitor_combo.blockSignals(False)
        self._refresh_value_labels()

    def is_running(self) -> bool:
        return self._ambient.is_running()

    def stats(self) -> dict:
        return {
            "running": self._ambient.is_running(),
            "errors": self._ambient.stream_error_count(),
            "last_error": self._ambient.last_stream_error(),
        }

    def stop_if_running(self) -> None:
        if self._ambient.is_running():
            self._stop()

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

        def sink(red: int, green: int, blue: int) -> None:
            # Colour-only quiet stream: never resends brightness, drops frames
            # while a BLE write is in flight, and stays out of the session log.
            host._ble.set_color_stream(red, green, blue)

        self._ambient.start(sink)
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
            status.setVisible(False)
        if was_running:
            host._log(host._tr("ambient.stopped_log"))

    def _apply_options(self) -> None:
        host = self._host
        # Saturation slider is an intuitive 0..100% boost: 0 = screen colour as-is
        # (1.0x), 100 = punchy (2.2x).
        saturation = 1.0 + (host.ambient_saturation_slider.value() / 100.0) * 1.2
        # "Плавность" reads naturally: 100% = very smooth (small easing step),
        # 0% = instant. The engine wants the easing factor, so invert.
        smoothing = max(0.05, 1.0 - host.ambient_smoothing_slider.value() / 100.0)
        self._ambient.configure(
            region=str(host.ambient_region_combo.currentData() or "full"),
            saturation=saturation,
            smoothing=smoothing,
            monitor_index=self._selected_monitor(),
        )

    def _selected_monitor(self) -> int:
        combo = self._host.ambient_monitor_combo
        if combo is None:
            return 0
        return int(combo.currentData() or 0)

    def _on_options_changed(self) -> None:
        self._refresh_value_labels()
        self._persist()
        if self._ambient.is_running():
            self._apply_options()

    def _refresh_value_labels(self) -> None:
        host = self._host
        host.ambient_saturation_value.setText(f"{host.ambient_saturation_slider.value()}%")
        host.ambient_smoothing_value.setText(f"{host.ambient_smoothing_slider.value()}%")

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["ambient"] = {
            "region": str(host.ambient_region_combo.currentData() or "full"),
            "saturation": int(host.ambient_saturation_slider.value()),
            "smoothing": int(host.ambient_smoothing_slider.value()),
            "monitor": self._selected_monitor(),
        }
        save_settings(host._settings)

    def _update_preview(self, red: int, green: int, blue: int) -> None:
        host = self._host
        host.ambient_preview.set_color(red, green, blue)
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
