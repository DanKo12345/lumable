from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.feature_gate import can_use
from app.music_controller import MusicController, list_audio_outputs
from app.storage import save_settings
from app.widgets import ColorPickerOverlay

_DEFAULTS = {"saturation": 60, "smoothing": 50, "speed": 30, "beat": 40}
_BANDS = ("bass", "mid", "treble")
_DEFAULT_BAND_RGB = {"bass": (255, 80, 70), "mid": (180, 90, 255), "treble": (60, 190, 255)}


class MusicUiController:
    """Wires the music-reactive card to the audio-capture/stream backend.

    Pro-gated. While music is running it owns the strip colour, so the manual
    colour and effect controls are disabled, and screen sync (which also owns the
    strip) is stopped first to avoid two writers fighting.
    """

    def __init__(self, host: Any) -> None:
        self._host = host
        self._music = MusicController(host)
        self._sink = None

    def wire(self) -> None:
        host = self._host
        host.music_toggle_button.clicked.connect(self._toggle)
        self._populate_sources()
        host.music_source_combo.currentIndexChanged.connect(self._on_source_changed)
        host.music_speed_slider.valueChanged.connect(self._on_options_changed)
        host.music_beat_slider.valueChanged.connect(self._on_options_changed)
        host.music_saturation_slider.valueChanged.connect(self._on_options_changed)
        host.music_smoothing_slider.valueChanged.connect(self._on_options_changed)
        for band in _BANDS:
            swatch = getattr(host, f"music_{band}_swatch", None)
            if swatch is not None:
                swatch.clicked.connect(lambda b=band: self._pick_band_color(b))
        self._band_picker = None
        self._music.color_sampled.connect(self._update_preview)
        self._music.failed.connect(self._on_failed)
        self._setup_preview_fade()
        self.sync_controls()
        self.refresh_lock()

    def _setup_preview_fade(self) -> None:
        """Reveal the live preview bar by growing its height + fading it in,
        instead of popping it on/off (which jumps the sliders below it).
        """
        host = self._host
        preview = getattr(host, "music_preview", None)
        if preview is None:
            return
        self._preview_height = host._sz(52)
        # Start fully collapsed and transparent. Driving both min and max height
        # (plus opacity) makes the reveal exact regardless of size policy.
        preview.setMinimumHeight(0)
        preview.setMaximumHeight(0)
        self._preview_effect = QGraphicsOpacityEffect(preview)
        self._preview_effect.setOpacity(0.0)
        preview.setGraphicsEffect(self._preview_effect)

        self._preview_anim = QParallelAnimationGroup(host)
        self._preview_opacity = QPropertyAnimation(self._preview_effect, b"opacity")
        self._preview_min = QPropertyAnimation(preview, b"minimumHeight")
        self._preview_max = QPropertyAnimation(preview, b"maximumHeight")
        for anim in (self._preview_opacity, self._preview_min, self._preview_max):
            anim.setDuration(260)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._preview_anim.addAnimation(anim)
        self._preview_hiding = False
        self._preview_anim.finished.connect(self._on_preview_anim_finished)

    def _animate_preview(self, *, opening: bool) -> None:
        preview = getattr(self._host, "music_preview", None)
        if preview is None or getattr(self, "_preview_anim", None) is None:
            return
        self._preview_anim.stop()
        self._preview_hiding = not opening
        target_h = self._preview_height if opening else 0
        self._preview_opacity.setStartValue(self._preview_effect.opacity())
        self._preview_opacity.setEndValue(1.0 if opening else 0.0)
        self._preview_min.setStartValue(preview.minimumHeight())
        self._preview_min.setEndValue(target_h)
        self._preview_max.setStartValue(preview.maximumHeight())
        self._preview_max.setEndValue(target_h)
        self._preview_anim.start()

    def _show_preview(self) -> None:
        preview = getattr(self._host, "music_preview", None)
        if preview is None or getattr(self, "_preview_anim", None) is None:
            return
        preview.clear()
        preview.setVisible(True)
        self._animate_preview(opening=True)

    def _hide_preview(self) -> None:
        preview = getattr(self._host, "music_preview", None)
        if preview is None or getattr(self, "_preview_anim", None) is None:
            return
        if not preview.isVisible():
            return
        self._animate_preview(opening=False)

    def _on_preview_anim_finished(self) -> None:
        if not self._preview_hiding:
            return
        preview = getattr(self._host, "music_preview", None)
        if preview is not None:
            preview.setVisible(False)
            preview.clear()
        self._preview_hiding = False

    def _update_preview(self, red: int, green: int, blue: int) -> None:
        preview = getattr(self._host, "music_preview", None)
        if preview is not None:
            preview.set_color(red, green, blue)

    def refresh_lock(self) -> None:
        """Show the Pro badge and disable the controls until music sync is unlocked.

        The toggle stays enabled so a click still opens the Pro upsell.
        """
        host = self._host
        unlocked = can_use("music_sync")
        lock_label = getattr(host, "music_lock_label", None)
        if lock_label is not None:
            lock_label.setVisible(not unlocked)
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        # The controls are live only when unlocked AND music is running, so the
        # whole group reads as greyed-out/"off" until you turn music on (the same
        # cue the Schedule card uses). The custom slider/swatch widgets don't dim
        # themselves when disabled, so we also fade the container's opacity.
        host = self._host
        active = can_use("music_sync") and self._music.is_running()
        controls = getattr(host, "music_controls", None)
        if controls is None:
            return
        controls.setEnabled(active)
        if getattr(self, "_controls_effect", None) is None:
            self._controls_effect = QGraphicsOpacityEffect(controls)
            controls.setGraphicsEffect(self._controls_effect)
        self._controls_effect.setOpacity(1.0 if active else 0.4)

    def sync_controls(self) -> None:
        host = self._host
        saved = host._settings.get("music", {}) if isinstance(host._settings, dict) else {}
        saturation = int(saved.get("saturation", _DEFAULTS["saturation"]))
        smoothing = int(saved.get("smoothing", _DEFAULTS["smoothing"]))
        speed = int(saved.get("speed", _DEFAULTS["speed"]))
        beat = int(saved.get("beat", _DEFAULTS["beat"]))
        host.music_speed_slider.jump_to(speed)
        host.music_beat_slider.jump_to(beat)
        host.music_saturation_slider.jump_to(saturation)
        host.music_smoothing_slider.jump_to(smoothing)
        combo = getattr(host, "music_source_combo", None)
        if combo is not None:
            device = str(saved.get("device", ""))
            index = combo.findData(device)
            combo.blockSignals(True)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        colors = saved.get("colors", {}) if isinstance(saved.get("colors"), dict) else {}
        for band in _BANDS:
            swatch = getattr(host, f"music_{band}_swatch", None)
            if swatch is None:
                continue
            default_r, default_g, default_b = _DEFAULT_BAND_RGB[band]
            saved_color = colors.get(band, {}) if isinstance(colors.get(band), dict) else {}
            swatch.set_color(
                QColor(
                    int(saved_color.get("r", default_r)),
                    int(saved_color.get("g", default_g)),
                    int(saved_color.get("b", default_b)),
                )
            )
        self._refresh_value_labels()

    def _populate_sources(self) -> None:
        host = self._host
        combo = getattr(host, "music_source_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("music.source_default"), "")
        for name in list_audio_outputs():
            combo.addItem(name, name)
        combo.blockSignals(False)

    def _on_source_changed(self) -> None:
        self._persist()
        # Switching output device means re-opening the loopback recorder, so
        # restart the capture in place if music is currently running.
        if self._music.is_running():
            self._restart_capture()

    def _restart_capture(self) -> None:
        if self._sink is None:
            return
        self._music.stop()
        self._apply_options()
        self._music.start(self._sink)

    def _colors_dict(self) -> dict:
        host = self._host
        result = {}
        for band in _BANDS:
            swatch = getattr(host, f"music_{band}_swatch", None)
            color = swatch.color() if swatch is not None else QColor(*_DEFAULT_BAND_RGB[band])
            result[band] = {"r": color.red(), "g": color.green(), "b": color.blue()}
        return result

    def _band_colors_tuple(self) -> tuple:
        colors = self._colors_dict()
        return tuple((colors[band]["r"], colors[band]["g"], colors[band]["b"]) for band in _BANDS)

    def _pick_band_color(self, band: str) -> None:
        host = self._host
        if not can_use("music_sync"):
            host._show_license_overlay()
            return
        swatch = getattr(host, f"music_{band}_swatch", None)
        if swatch is None:
            return
        if getattr(self, "_band_picker", None) is not None:
            self._band_picker.raise_()
            return
        picker = ColorPickerOverlay(
            host._tr("music.pick_band_color"),
            swatch.color(),
            {
                "red": host._tr("slider.red"),
                "green": host._tr("slider.green"),
                "blue": host._tr("slider.blue"),
                "hex": host._tr("color.hex"),
                "recent": host._tr("color.recent"),
                "cancel": host._tr("dialog.cancel"),
                "ok": host._tr("dialog.ok"),
            },
            host._color_history(),
            host,
        )
        self._band_picker = picker
        picker.colorSelected.connect(lambda color, b=band: self._apply_band_color(b, color))
        picker.closed.connect(lambda: setattr(self, "_band_picker", None))
        picker.open()

    def _apply_band_color(self, band: str, color: QColor) -> None:
        swatch = getattr(self._host, f"music_{band}_swatch", None)
        if swatch is not None:
            swatch.set_color(color)
        self._persist()
        if self._music.is_running():
            self._apply_options()

    def is_running(self) -> bool:
        return self._music.is_running()

    def stats(self) -> dict:
        return {
            "running": self._music.is_running(),
            "errors": self._music.stream_error_count(),
            "last_error": self._music.last_stream_error(),
        }

    def stop_if_running(self) -> None:
        if self._music.is_running():
            self._stop()

    def shutdown(self) -> None:
        self._music.stop()

    def _toggle(self) -> None:
        host = self._host
        if not host.music_toggle_button.isChecked():
            self._stop()
            return
        if not can_use("music_sync"):
            host.music_toggle_button.setChecked(False)
            host._show_license_overlay()
            return
        if not host._is_connected:
            host.music_toggle_button.setChecked(False)
            host._show_error(host._tr("music.not_connected"))
            return
        self._start()

    def _start(self) -> None:
        host = self._host
        # Screen sync / app animations also own the strip — only one can drive it.
        host._ambient_ui.stop_if_running()
        if getattr(host, "_software_fx_ui", None) is not None:
            host._software_fx_ui.stop_if_running()
        if getattr(host, "_diy_ui", None) is not None:
            host._diy_ui.stop_if_running()
        # If the strip is powered off the colour stream wouldn't show — turn it
        # on first so enabling music "just works".
        if not host.power_button.isChecked():
            host.power_button.setChecked(True)
            host._toggle_power()
        self._apply_options()

        def sink(red: int, green: int, blue: int) -> None:
            # Colour-only quiet stream: never resends brightness, drops frames
            # while a BLE write is in flight, and stays out of the session log.
            host._ble.set_color_stream(red, green, blue)

        self._sink = sink
        self._music.start(sink)
        self._set_manual_controls_enabled(False)
        self._apply_enabled_state()
        self._show_preview()
        host.music_toggle_button.setText(host._tr("music.toggle_on"))
        status = getattr(host, "music_status_label", None)
        if status is not None:
            status.setText(host._tr("music.listening"))
            status.setVisible(True)
        host._log(host._tr("music.started_log"))

    def _stop(self) -> None:
        host = self._host
        was_running = self._music.is_running()
        self._music.stop()
        self._apply_enabled_state()
        self._hide_preview()
        self._set_manual_controls_enabled(True)
        host.music_toggle_button.setChecked(False)
        host.music_toggle_button.setText(host._tr("music.toggle_off"))
        status = getattr(host, "music_status_label", None)
        if status is not None:
            status.setVisible(False)
        if was_running:
            host._log(host._tr("music.stopped_log"))

    def _apply_options(self) -> None:
        host = self._host
        # Saturation slider is an intuitive 0..100% deepening of the dominant hue:
        # 0 = gentle (1.0x), 100 = vivid (2.5x).
        saturation = 1.0 + (host.music_saturation_slider.value() / 100.0) * 1.5
        # "Плавность" reads naturally: 100% = very smooth (small easing step),
        # 0% = instant. The engine wants the easing factor, so invert.
        smoothing = max(0.05, 1.0 - host.music_smoothing_slider.value() / 100.0)
        # Speed slider -> EMA reactivity: 0 = very calm/slow, 100 = instant.
        reactivity = 0.05 + (host.music_speed_slider.value() / 100.0) * 0.95
        # Beat slider -> brightness pop strength (0 disables the beat punch).
        beat_strength = host.music_beat_slider.value() / 100.0
        device_name = host.music_source_combo.currentData() or ""
        self._music.configure(
            saturation=saturation,
            smoothing=smoothing,
            reactivity=reactivity,
            beat_strength=beat_strength,
            device_name=device_name,
            band_colors=self._band_colors_tuple(),
        )

    def _on_options_changed(self) -> None:
        self._refresh_value_labels()
        self._persist()
        if self._music.is_running():
            self._apply_options()

    def _refresh_value_labels(self) -> None:
        host = self._host
        host.music_speed_value.setText(f"{host.music_speed_slider.value()}%")
        host.music_beat_value.setText(f"{host.music_beat_slider.value()}%")
        host.music_saturation_value.setText(f"{host.music_saturation_slider.value()}%")
        host.music_smoothing_value.setText(f"{host.music_smoothing_slider.value()}%")

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        host._settings["music"] = {
            "saturation": int(host.music_saturation_slider.value()),
            "smoothing": int(host.music_smoothing_slider.value()),
            "speed": int(host.music_speed_slider.value()),
            "beat": int(host.music_beat_slider.value()),
            "device": str(host.music_source_combo.currentData() or ""),
            "colors": self._colors_dict(),
        }
        save_settings(host._settings)

    def _on_failed(self, reason: str) -> None:
        host = self._host
        self._stop()
        # Log the raw reason (incl. the underlying import/capture error) so a
        # failure is diagnosable, but show the user a friendly message.
        host._log(host._tr("music.error", error=reason))
        if reason.startswith("audio_capture_unavailable"):
            host._show_error(host._tr("music.capture_failed"))
        else:
            host._show_error(host._tr("music.error", error=reason))

    def _set_manual_controls_enabled(self, enabled: bool) -> None:
        host = self._host
        # Note: power_button stays enabled so the user can always switch the
        # strip off — pressing it stops music first (see MainWindow._toggle_power).
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
