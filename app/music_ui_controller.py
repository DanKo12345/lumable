from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.feature_gate import can_use
from app.music_controller import MusicController, list_audio_inputs, list_audio_outputs
from app.storage import save_settings
from app.widgets import ColorPickerOverlay
from app.widgets.animation_helpers import play_or_complete

_DEFAULTS = {"saturation": 60, "smoothing": 50, "speed": 30, "beat": 40, "gate": 16}
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
        self._source = "system"

    def wire(self) -> None:
        host = self._host
        host.music_toggle_button.clicked.connect(self._toggle)
        self._populate_sources()
        host.music_source_segment.selected.connect(self._on_source_type_changed)
        host.music_source_combo.currentIndexChanged.connect(self._on_source_changed)
        host.music_speed_slider.valueChanged.connect(self._on_options_changed)
        host.music_beat_slider.valueChanged.connect(self._on_options_changed)
        host.music_gate_slider.valueChanged.connect(self._on_options_changed)
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
        self._setup_gate_reveal()
        self.sync_controls()
        self.refresh_lock()

    # ── noise-gate reveal (mic only) ──────────────────────────────────
    # Height-only accordion (no opacity effect): the row lives inside
    # music_controls, which already carries its own opacity effect for the
    # dim-when-off state, and nesting two QGraphicsEffects renders glitchy.
    def _setup_gate_reveal(self) -> None:
        host = self._host
        row = getattr(host, "music_gate_row", None)
        if row is None:
            return
        self._gate_height = max(row.sizeHint().height(), host._sz(40))
        self._gate_anim = QParallelAnimationGroup(host)
        self._gate_min = QPropertyAnimation(row, b"minimumHeight")
        self._gate_max = QPropertyAnimation(row, b"maximumHeight")
        for anim in (self._gate_min, self._gate_max):
            anim.setDuration(240)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._gate_anim.addAnimation(anim)
        self._gate_hiding = False
        self._gate_anim.finished.connect(self._on_gate_anim_finished)

    def _set_gate_visible_instant(self, visible: bool) -> None:
        row = getattr(self._host, "music_gate_row", None)
        if row is None or getattr(self, "_gate_anim", None) is None:
            return
        self._gate_anim.stop()
        height = self._gate_height if visible else 0
        row.setMinimumHeight(height)
        row.setMaximumHeight(height)
        row.setVisible(visible)

    def _animate_gate(self, *, opening: bool) -> None:
        row = getattr(self._host, "music_gate_row", None)
        if row is None or getattr(self, "_gate_anim", None) is None:
            return
        self._gate_anim.stop()
        self._gate_hiding = not opening
        if opening:
            row.setVisible(True)
        target = self._gate_height if opening else 0
        self._gate_min.setStartValue(row.minimumHeight())
        self._gate_min.setEndValue(target)
        self._gate_max.setStartValue(row.maximumHeight())
        self._gate_max.setEndValue(target)
        play_or_complete(self._gate_anim)

    def _on_gate_anim_finished(self) -> None:
        if not self._gate_hiding:
            return
        row = getattr(self._host, "music_gate_row", None)
        if row is not None:
            row.setVisible(False)
        self._gate_hiding = False

    def _setup_preview_fade(self) -> None:
        """Reveal the live preview bar by growing its height + fading it in,
        instead of popping it on/off (which jumps the sliders below it).
        """
        host = self._host
        preview = getattr(host, "music_preview", None)
        if preview is None:
            return
        self._preview_height = host._sz(40)
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
        play_or_complete(self._preview_anim)

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
        gate = int(saved.get("gate", _DEFAULTS["gate"]))
        host.music_speed_slider.jump_to(speed)
        host.music_beat_slider.jump_to(beat)
        host.music_gate_slider.jump_to(gate)
        host.music_saturation_slider.jump_to(saturation)
        host.music_smoothing_slider.jump_to(smoothing)
        self._source = "mic" if str(saved.get("source", "system")) == "mic" else "system"
        segment = getattr(host, "music_source_segment", None)
        if segment is not None:
            segment.set_current(self._source, animate=False)
        self._set_gate_visible_instant(self._source == "mic")
        self._refresh_source_description()
        self._populate_sources()
        combo = getattr(host, "music_source_combo", None)
        if combo is not None:
            device = str(saved.get("mic_device" if self._source == "mic" else "device", ""))
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
        is_mic = self._source == "mic"
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(host._tr("music.source_default_mic" if is_mic else "music.source_default"), "")
        names = list_audio_inputs() if is_mic else list_audio_outputs()
        for name in names:
            combo.addItem(name, name)
        combo.blockSignals(False)

    def _on_source_type_changed(self, key: str) -> None:
        self._source = "mic" if key == "mic" else "system"
        self._refresh_source_description()
        self._animate_gate(opening=self._source == "mic")
        self._populate_sources()
        # Re-select the device previously chosen for this source, if any.
        host = self._host
        saved = host._settings.get("music", {}) if isinstance(host._settings, dict) else {}
        device = str(saved.get("mic_device" if self._source == "mic" else "device", ""))
        combo = host.music_source_combo
        index = combo.findData(device)
        combo.blockSignals(True)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)
        self._persist()
        if self._music.is_running():
            self._restart_capture()

    def _refresh_source_description(self) -> None:
        label = getattr(self._host, "music_source_description", None)
        if label is not None:
            key = "music.source_mic_desc" if self._source == "mic" else "music.source_system_desc"
            label.setText(self._host._tr(key))

    def _on_source_changed(self) -> None:
        self._persist()
        # Switching device means re-opening the recorder, so restart the capture
        # in place if music is currently running.
        if self._music.is_running():
            self._restart_capture()

    def _restart_capture(self) -> None:
        host = self._host
        if host._fusion_ui.is_running():
            # Only the audio device is reopened. The screen keeps arriving and
            # the composed colour keeps going out, so changing the microphone
            # does not blink the light.
            host._fusion_ui.restart_audio()
            return
        if self._sink is None:
            return
        self._music.stop()
        self._apply_options()
        self._music.start_output(self._sink)

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

    def _shared_with_screen(self) -> bool:
        return self._host._fusion_ui.mode() == "screen_music"

    def _audio_lost(self) -> bool:
        return self._host._fusion_ui.audio_lost()

    def is_standalone_running(self) -> bool:
        """Whether the old mode — music owning the strip by itself — is on.

        Distinct from :meth:`is_running`, which answers what a person means by
        "is music on" and includes the combined mode. The API and a saved scene
        need the narrower question, because "music" is a mode name there.
        """
        return self._music.is_running() and not self._shared_with_screen()

    def is_running(self) -> bool:
        """Whether "music" is on, as a person means it.

        In the combined mode that is the combined mode: the tray tick and the
        hotkey both read this, and answering with the standalone capture would
        show music as off while the strip is plainly reacting to it.
        """
        if self._shared_with_screen() and not self._audio_lost():
            return self._host._fusion_ui.is_running()
        return self._music.is_running()

    def stats(self) -> dict:
        return {
            "running": self._music.is_running(),
            "errors": self._music.stream_error_count(),
            "last_error": self._music.last_stream_error(),
            # Survives the stop, so a report exported after switching music off
            # still describes the run being asked about.
            "music_sync": self._music.music_report(),
        }

    # ── lending the analysis to Fusion ────────────────────────────────
    def connect_samples(self, slot) -> None:
        """Send every analysed block to ``slot`` as well as to the card."""
        self._music.modulation_sampled.connect(slot, Qt.QueuedConnection)

    def start_listening(self) -> int:
        """Analyse the sound for someone else to compose with.

        No colour is produced and nothing is written to the strip; the card's
        source, gate and reaction settings all still apply. Returns the session
        token every block of this run will carry.
        """
        self._apply_options()
        return self._music.start_listening()

    def stop_listening(self) -> None:
        if self._music.is_running():
            self._music.stop()

    def refresh_shared_state(self) -> None:
        """Show whether music is currently working as part of the screen mode.

        One button stops the combined mode, and it is the screen card's. A second
        one here would be two buttons for one thing, so this explains where the
        stop lives instead of offering a different one.
        """
        host = self._host
        shared = host._fusion_ui.mode() == "screen_music"
        lost = host._fusion_ui.audio_lost()
        button = getattr(host, "music_toggle_button", None)
        status = getattr(host, "music_status_label", None)
        if button is not None:
            # With the device gone there is nothing shared to point at, so the
            # card's own button comes back rather than staying disabled with an
            # explanation that is no longer true.
            button.setEnabled(not shared or lost)
        if status is not None and shared:
            status.setText(host._tr("fusion.audio_lost" if lost else "fusion.music_shared"))
            status.setVisible(True)
        elif status is not None and not self._music.is_running():
            status.setText(host._tr("music.status_off"))

    def has_audio_source(self) -> bool:
        """Whether there is a device to listen to at all.

        Asked before the combined mode starts so the reason can be shown next to
        the choice, instead of the mode appearing to start and then dying with
        an error a moment later.
        """
        combo = getattr(self._host, "music_source_combo", None)
        if combo is None:
            return True
        return combo.count() > 0

    def beat_strength(self) -> float:
        return float(self._music.options().beat_strength)

    def stop_if_running(self) -> None:
        """Stop whatever "music" currently means.

        In the combined mode that is the whole mode. Stopping only the listener
        would leave the screen still driving the strip with a modulation that
        has silently gone stale — a half-stop nobody asked for and nothing
        reports.
        """
        if self._shared_with_screen() and self._host._fusion_ui.is_running():
            self._host._fusion_ui.stop_if_running()
            return
        if self._music.is_running():
            self._stop()

    def activate(self) -> bool:
        # Music is part of the screen mode right now. Starting it on its own
        # from a tray entry or a hotkey would tear it back out into the old
        # standalone mode and take the strip off the screen — the opposite of
        # what someone pressing "music" while that mode is chosen wants.
        if self._shared_with_screen():
            fusion = self._host._fusion_ui
            return True if fusion.is_running() else fusion.activate()
        return self._activate_standalone()

    def activate_standalone(self) -> bool:
        """Start music reaction on its own, whatever the screen card is set to.

        What "music" means as an API mode or in a saved scene: the reaction that
        owns the strip by itself. The tray entry and the hotkey deliberately do
        something else — there, "music" means whatever the person has chosen.
        """
        if self._shared_with_screen():
            self._host._fusion_ui.stop_if_running()
            self._host._fusion_ui.set_mode("screen")
            self._host._ambient_ui.sync_mode_segment()
        return self._activate_standalone()

    def _activate_standalone(self) -> bool:
        """Start music reaction as if its toggle was pressed. Returns whether it
        actually started (a licence/connection gate may have blocked it)."""
        self._host.music_toggle_button.setChecked(True)
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
        # Only one owner drives the strip at a time — stop the others (screen
        # sync, software FX, DIY, sleep/sunrise timers).
        host.stop_streams(exclude=self)
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
        self._music.start_output(sink)
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
            status.setText(host._tr("music.status_off"))
            status.setVisible(True)
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
        # Gate slider 0..100% -> noise-gate fraction 0..0.5 of full loudness.
        # Only applied for the microphone (system audio doesn't need it).
        noise_gate = (host.music_gate_slider.value() / 100.0) * 0.5 if self._source == "mic" else 0.0
        device_name = host.music_source_combo.currentData() or ""
        self._music.configure(
            saturation=saturation,
            smoothing=smoothing,
            reactivity=reactivity,
            beat_strength=beat_strength,
            noise_gate=noise_gate,
            source=self._source,
            device_name=device_name,
            band_colors=self._band_colors_tuple(),
        )

    def _on_options_changed(self) -> None:
        self._refresh_value_labels()
        self._persist()
        if self._music.is_running():
            # True in the combined mode too: the analysis is running as a
            # listener there, so every slider on this card lands on the live
            # capture without anything being restarted.
            self._apply_options()
        # The beat slider is the exception, because the impulse is applied by
        # whoever composes the frame rather than inside the analysis. Without
        # this it would only take effect the next time the mode was started —
        # a slider that silently does nothing while you drag it.
        self._host._fusion_ui.set_beat_gain(self.beat_strength())

    def _refresh_value_labels(self) -> None:
        host = self._host
        host.music_speed_value.setText(f"{host.music_speed_slider.value()}%")
        host.music_beat_value.setText(f"{host.music_beat_slider.value()}%")
        host.music_gate_value.setText(f"{host.music_gate_slider.value()}%")
        host.music_saturation_value.setText(f"{host.music_saturation_slider.value()}%")
        host.music_smoothing_value.setText(f"{host.music_smoothing_slider.value()}%")

    def _persist(self) -> None:
        host = self._host
        if not isinstance(host._settings, dict):
            return
        prev = host._settings.get("music", {}) if isinstance(host._settings.get("music"), dict) else {}
        active_device = str(host.music_source_combo.currentData() or "")
        music = {
            "saturation": int(host.music_saturation_slider.value()),
            "smoothing": int(host.music_smoothing_slider.value()),
            "speed": int(host.music_speed_slider.value()),
            "beat": int(host.music_beat_slider.value()),
            "gate": int(host.music_gate_slider.value()),
            "source": self._source,
            # Remember the chosen device per source so switching back restores it.
            "device": str(prev.get("device", "")),
            "mic_device": str(prev.get("mic_device", "")),
            "colors": self._colors_dict(),
        }
        music["mic_device" if self._source == "mic" else "device"] = active_device
        host._settings["music"] = music
        save_settings(host._settings)

    def _on_failed(self, reason: str) -> None:
        host = self._host
        if host._fusion_ui.is_running():
            # The screen half is still working and should keep working. What
            # stops is the claim that music is part of it.
            host._fusion_ui.note_audio_lost()
            self.refresh_shared_state()
            host._ambient_ui.refresh_status()
            host._log(host._tr("music.error", error=reason))
            host._show_error(host._tr("fusion.audio_lost"))
            return
        self._stop()
        # Log the raw reason (incl. the underlying import/capture error) so a
        # failure is diagnosable, but show the user a friendly message.
        host._log(host._tr("music.error", error=reason))
        if reason.startswith("audio_capture_unavailable"):
            host._show_error(host._tr("music.capture_failed"))
        elif reason.startswith("mic_backend_missing"):
            host._show_error(host._tr("music.mic_backend_missing"))
        elif reason.startswith("mic_capture_failed"):
            host._show_error(host._tr("music.mic_failed"))
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
