from __future__ import annotations

from math import ceil
from time import monotonic
from typing import Any

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from app import music_calibration
from app.feature_gate import can_use
from app.localization import localization_manager
from app.music_controller import (
    OWNER_CALIBRATION,
    OWNER_FUSION,
    OWNER_OUTPUT,
    OWNER_PREVIEW,
    MusicController,
    beat_ratio_for_sensitivity,
    list_audio_inputs,
    list_audio_outputs,
)
from app.music_gate import (
    db_for_slider,
    format_db,
    gate_db_from_saved,
    rms_for_slider,
    slider_for_db,
    slider_for_rms,
)
from app.storage import save_settings
from app.widgets import ColorPickerOverlay, ValueChip
from app.widgets.animation_helpers import motion_reduced, play_or_complete
from app.widgets.band_meter import FLASH_S, follow_level
from app.widgets.liquid_slider import LiquidSlider

_DEFAULTS = {
    "saturation": 60,
    "smoothing": 50,
    "speed": 30,
    "beat": 40,
    "sensitivity": 50,
}
_BANDS = ("bass", "mid", "treble")
_DEFAULT_BAND_RGB = {"bass": (255, 80, 70), "mid": (180, 90, 255), "treble": (60, 190, 255)}

# The sound check listens for this long and then stops by itself.
SOUND_CHECK_SECONDS = 30
# One interface tick drives the meters and the check's countdown.
METER_INTERVAL_MS = 50
# A reading older than this means the device has stopped handing sound over.
METER_STALE_S = 0.4
# A status must hold this long before the next may replace it, so a signal on
# the edge of the gate does not make the label flicker. Clipping is shown at
# once and then held longer, so a single loud hit is still readable.
METER_STATUS_DWELL_S = 0.4
METER_CLIPPED_HOLD_S = 1.0
# While the device is still opening there is no reading yet, which is not the
# same thing as a device that has gone quiet.
METER_STARTUP_GRACE_S = 1.0
# A calibration's result stays in the status this long before what was there
# before comes back.
CALIBRATION_RESULT_HOLD_S = 3.0
# A calibration started without a check ends with a short one, so the new gate
# can be seen against the room's own level.
CHECK_AFTER_CALIBRATION_S = 10.0


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
        # The sound check: when it ends, or None while none is running.
        self._check_deadline: float | None = None
        self._check_started_at = 0.0
        # The meters draw only while their page is the one on screen.
        self._on_music_page = False
        self._window_visible = True
        # Two flags, not one: a machine that sleeps without locking wakes with
        # no "unlocked" to follow, and one that locks on waking wakes locked.
        self._session_locked = False
        self._session_asleep = False
        # A calibration in progress: the sample being measured, or None.
        self._calibration: music_calibration.NoiseSample | None = None
        self._calibration_started_at = 0.0
        self._calibration_shown: tuple | None = None
        # The check to hand back to afterwards: seconds left, or None.
        self._resume_check_s: float | None = None
        # The status label belongs to a calibration while it runs and while its
        # result is shown; what the others said meanwhile waits here.
        self._status_to_restore: str | None = None
        # A result on show ends by this timer, not the meters': with nobody left
        # listening those stop, and the result would stay for good.
        self._hold_timer: QTimer | None = None
        self._tuning_widget_cache: list | None = None
        self._meter_timer: QTimer | None = None
        self._meter_tick_at = 0.0
        self._flash = 0.0
        # The room's level as shown on the noise-gate slider, in its units.
        self._gate_level = 0.0
        self._last_beat_id = 0
        self._meter_status = ""
        self._meter_status_since = 0.0

    def wire(self) -> None:
        host = self._host
        host.music_toggle_button.clicked.connect(self._toggle)
        self._populate_sources()
        host.music_source_segment.selected.connect(self._on_source_type_changed)
        host.music_source_combo.currentIndexChanged.connect(self._on_source_changed)
        host.music_speed_slider.valueChanged.connect(self._on_options_changed)
        host.music_beat_slider.valueChanged.connect(self._on_options_changed)
        host.music_sensitivity_slider.valueChanged.connect(self._on_options_changed)
        # The compact controls on the screen card. Views of the same values, not
        # a second set: they hand the change to the same handler and are written
        # back from the same refresh, so there is one saved number and one place
        # that decides what it means.
        host.fusion_beat_slider.valueChanged.connect(self._on_shared_beat_changed)
        host.fusion_source_segment.selected.connect(self._on_shared_source_changed)
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
        self._music.recovery_changed.connect(self._on_recovery_changed)
        check = getattr(host, "music_check_button", None)
        if check is not None:
            check.clicked.connect(self.toggle_sound_check)
        calibrate = getattr(host, "music_calibrate_button", None)
        if calibrate is not None:
            calibrate.clicked.connect(self.toggle_calibration)
        # The one timer behind the meters and the check's countdown. It runs
        # only while the music page is on screen and something is listening.
        self._meter_timer = QTimer(host)
        self._meter_timer.setInterval(METER_INTERVAL_MS)
        self._meter_timer.timeout.connect(self._refresh_meters)
        self._hold_timer = QTimer(host)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._restore_status)
        self._setup_preview_fade()
        self._setup_gate_reveal()
        self.sync_controls()
        self.refresh_lock()
        self.refresh_check_button()
        self.refresh_calibrate_button()

    # ── noise-gate reveal (mic only) ──────────────────────────────────
    # The slot fades cached pixels, avoiding a second QGraphicsEffect inside
    # the reaction section, which already has a dim-when-off effect.
    def _setup_gate_reveal(self) -> None:
        host = self._host
        row = getattr(host, "music_gate_row", None)
        slot = getattr(host, "music_gate_slot", None)
        if row is None or slot is None:
            return
        self._gate_height = max(row.sizeHint().height(), host._sz(40)) + host._sz(5)
        slot.set_content_height(self._gate_height - host._sz(5))
        self._gate_anim = QPropertyAnimation(slot, b"progress", host)
        self._gate_anim.setDuration(320)
        # The slot eases its height and opacity phases independently.
        self._gate_anim.setEasingCurve(QEasingCurve.Linear)
        self._gate_anim.finished.connect(slot.finish_transition)

    def _set_gate_visible_instant(self, visible: bool) -> None:
        row = getattr(self._host, "music_gate_row", None)
        slot = getattr(self._host, "music_gate_slot", None)
        if row is None or slot is None or getattr(self, "_gate_anim", None) is None:
            return
        self._gate_anim.stop()
        slot.set_progress(1.0 if visible else 0.0)
        slot.finish_transition()

    def _animate_gate(self, *, opening: bool) -> None:
        row = getattr(self._host, "music_gate_row", None)
        slot = getattr(self._host, "music_gate_slot", None)
        if row is None or slot is None or getattr(self, "_gate_anim", None) is None:
            return
        self._gate_anim.stop()
        slot.prepare_transition()
        self._gate_anim.setStartValue(slot.get_progress())
        self._gate_anim.setEndValue(1.0 if opening else 0.0)
        play_or_complete(self._gate_anim)

    def _setup_preview_fade(self) -> None:
        """Reveal the live preview bar by growing its height + fading it in,
        instead of popping it on/off (which jumps the sliders below it).
        """
        host = self._host
        preview = getattr(host, "music_preview", None)
        slot = getattr(host, "music_preview_slot", None)
        if preview is None or slot is None:
            return
        self._preview_height = max(preview.minimumHeight(), host._sz(40)) + host._sz(12)
        # Start fully collapsed and transparent. Driving both min and max height
        # (plus opacity) makes the reveal exact regardless of size policy.
        slot.setMinimumHeight(0)
        slot.setMaximumHeight(0)
        self._preview_effect = QGraphicsOpacityEffect(preview)
        self._preview_effect.setOpacity(0.0)
        preview.setGraphicsEffect(self._preview_effect)

        self._preview_anim = QParallelAnimationGroup(host)
        self._preview_opacity = QPropertyAnimation(self._preview_effect, b"opacity")
        self._preview_min = QPropertyAnimation(slot, b"minimumHeight")
        self._preview_max = QPropertyAnimation(slot, b"maximumHeight")
        for anim in (self._preview_opacity, self._preview_min, self._preview_max):
            anim.setDuration(260)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            self._preview_anim.addAnimation(anim)
        self._preview_hiding = False
        self._preview_anim.finished.connect(self._on_preview_anim_finished)

    def _animate_preview(self, *, opening: bool) -> None:
        preview = getattr(self._host, "music_preview", None)
        slot = getattr(self._host, "music_preview_slot", None)
        if preview is None or slot is None or getattr(self, "_preview_anim", None) is None:
            return
        self._preview_anim.stop()
        self._preview_hiding = not opening
        if opening:
            preview.setVisible(True)
        target_h = self._preview_height if opening else 0
        self._preview_opacity.setStartValue(self._preview_effect.opacity())
        self._preview_opacity.setEndValue(1.0 if opening else 0.0)
        self._preview_min.setStartValue(slot.minimumHeight())
        self._preview_min.setEndValue(target_h)
        self._preview_max.setStartValue(slot.maximumHeight())
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
        # The controls are live only when unlocked AND something is listening
        # for them to act on — the reaction, or a sound check — so the group
        # reads as greyed-out/"off" otherwise (the same cue the Schedule card
        # uses). The custom slider/swatch widgets don't dim themselves when
        # disabled, so each part also fades. "Check sound" in the colours
        # heading stays outside the fade: it is how you start listening while
        # everything else is off.
        host = self._host
        # A check or a calibration is listening for the controls, and both are
        # interactive for everyone, Pro or not: they are how the settings are
        # tried out before any light is involved.
        checking = self.is_checking_sound() or self.is_calibrating()
        active = self._feeding_a_light()
        tuning = checking or (can_use("music_sync") and active)
        showing_bands = checking or active
        for widget in self._tuning_widgets():
            self._fade(widget, enabled=tuning, shown=tuning)
        self._fade(getattr(host, "music_colors_label", None), enabled=True, shown=showing_bands)
        self._fade(getattr(host, "music_bands_row", None), enabled=tuning, shown=showing_bands)
        calibrate = getattr(host, "music_calibrate_button", None)
        if calibrate is not None:
            # Its own rule, apart from the tuning controls: a microphone to
            # measure. Not Pro, not the reaction and not a check.
            calibrate.setEnabled(self._source == "mic")
        check = getattr(host, "music_check_button", None)
        if check is not None:
            # One scenario at a time: a check does not start over a calibration.
            check.setEnabled(self._calibration is None)

    def _tuning_widgets(self) -> list:
        """The reaction section's own labels, sliders and readouts, one by one.

        Faded and locked individually rather than through the section, so the
        calibrate button inside it keeps a rule of its own. Leaves only: an
        effect on a container as well would nest one effect inside another.
        """
        if self._tuning_widget_cache is None:
            section = getattr(self._host, "music_reaction_section", None)
            if section is None:
                return []
            calibrate = getattr(self._host, "music_calibrate_button", None)
            self._tuning_widget_cache = [
                widget for widget in section.findChildren(QWidget)
                if isinstance(widget, (QLabel, LiquidSlider, ValueChip)) and widget is not calibrate
            ]
        return self._tuning_widget_cache

    @staticmethod
    def _fade(widget, *, enabled: bool, shown: bool) -> None:
        if widget is None:
            return
        widget.setEnabled(enabled)
        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
        effect.setOpacity(1.0 if shown else 0.4)
        # At full strength the effect only costs: every repaint beneath it — the
        # live meters twenty times a second — would first be drawn offscreen.
        effect.setEnabled(not shown)

    def sync_controls(self) -> None:
        host = self._host
        saved = host._settings.get("music", {}) if isinstance(host._settings, dict) else {}
        saturation = int(saved.get("saturation", _DEFAULTS["saturation"]))
        smoothing = int(saved.get("smoothing", _DEFAULTS["smoothing"]))
        speed = int(saved.get("speed", _DEFAULTS["speed"]))
        beat = int(saved.get("beat", _DEFAULTS["beat"]))
        sensitivity = int(saved.get("sensitivity", _DEFAULTS["sensitivity"]))
        # Either saved format; see gate_db_from_saved.
        gate = round(slider_for_db(gate_db_from_saved(saved)))
        host.music_speed_slider.jump_to(speed)
        host.music_beat_slider.jump_to(beat)
        host.music_sensitivity_slider.jump_to(sensitivity)
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
        self._refresh_band_meter_colors()
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
        # A measurement of one room says nothing about another input.
        self._cancel_calibration()
        self._source = "mic" if key == "mic" else "system"
        self._refresh_shared_views()
        self._refresh_source_description()
        self._animate_gate(opening=self._source == "mic")
        self._apply_enabled_state()
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
        # Nor of another microphone.
        self._cancel_calibration()
        self._persist()
        # Switching device means re-opening the recorder, so restart the capture
        # in place if music is currently running.
        if self._music.is_running():
            self._restart_capture()

    def _restart_capture(self) -> None:
        host = self._host
        if host._fusion_ui.is_running() and OWNER_FUSION in self._music.owners():
            # Only the audio device is reopened. The screen keeps arriving and
            # the composed colour keeps going out, so changing the microphone
            # does not blink the light.
            host._fusion_ui.restart_audio()
            # A restart that failed leaves the combined mode without its audio;
            # both cards have to say so.
            self.refresh_shared_state()
            host._ambient_ui.refresh_status()
            return
        # One capture reopened for whoever holds it — the reaction, a sound
        # check or both — while the stream to the strip keeps going.
        self._apply_options()
        if not self._music.restart_capture():
            # The old capture never let go of the device and has been dropped.
            # Said out loud, rather than leaving a card that looks listening.
            prefix = "mic_capture_failed" if self._source == "mic" else "audio_capture_unavailable"
            self._on_failed(f"{prefix}: the device did not let go")

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
        self._refresh_band_meter_colors()
        self._persist()
        if self._music.is_running():
            self._apply_options()

    def _shared_with_screen(self) -> bool:
        return self._host._fusion_ui.mode() == "screen_music"

    def _feeding_a_light(self) -> bool:
        """Whether the capture is feeding a light: this card's reaction or Fusion."""
        owners = self._music.owners()
        return OWNER_OUTPUT in owners or OWNER_FUSION in owners

    def _reacting(self) -> bool:
        """Whether this card's own reaction is the one writing the strip.

        Not the same as the capture running: a sound check or Fusion may be
        listening while nothing of this card's reaches the strip.
        """
        return OWNER_OUTPUT in self._music.owners()

    def _audio_lost(self) -> bool:
        return self._host._fusion_ui.audio_lost()

    def is_standalone_running(self) -> bool:
        """Whether the old mode — music owning the strip by itself — is on.

        Distinct from :meth:`is_running`, which answers what a person means by
        "is music on" and includes the combined mode. The API and a saved scene
        need the narrower question, because "music" is a mode name there.
        """
        return self._reacting() and not self._shared_with_screen()

    def is_running(self) -> bool:
        """Whether "music" is on, as a person means it.

        In the combined mode that is the combined mode: the tray tick and the
        hotkey both read this, and answering with the standalone capture would
        show music as off while the strip is plainly reacting to it.
        """
        if self._shared_with_screen() and not self._audio_lost():
            return self._host._fusion_ui.is_running()
        return self._reacting()

    def stats(self) -> dict:
        return {
            "running": self._reacting(),
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
        token = self._music.start_listening()
        # Taken over, not reopened: Fusion already holds the capture, so the
        # check lets go without the device closing in between.
        self._end_sound_check()
        self._apply_enabled_state()
        self._update_meter_timer()
        return token

    def restart_listening(self) -> int:
        """Reopen the device for Fusion: a new device, or the old one back.

        Stopping and starting again would reopen nothing while a sound check
        holds the capture, so this asks for a real restart when Fusion already
        holds it and a fresh hold when it does not.
        """
        self._apply_options()
        if OWNER_FUSION in self._music.owners():
            token = self._music.restart_capture()
        else:
            token = self._music.acquire(OWNER_FUSION)
            self._end_sound_check()
        self._apply_enabled_state()
        self._update_meter_timer()
        return token

    def stop_listening(self) -> None:
        self._music.release(OWNER_FUSION)
        self._apply_enabled_state()
        self._update_meter_timer()

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
            self._write_status(host._tr("fusion.audio_lost" if lost else "fusion.music_shared"))
        elif status is not None and not self._reacting() and not self.is_checking_sound():
            self._write_status(host._tr("music.status_off"))
        self._apply_enabled_state()
        self._update_meter_timer()

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
        """Yield the strip, if this controller is the one holding it.

        In the combined mode it is not: the audio is Fusion's source, and Fusion
        is its own entry in the owner list, so whoever is taking over has already
        dealt with it. Stopping the analysis from here would tear the audio half
        out of a mode that is meant to keep running — which is what power does,
        since power deliberately skips Fusion and would otherwise reach it
        sideways through this method.
        """
        if self._shared_with_screen() and self._host._fusion_ui.is_running():
            return
        if self._reacting():
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
        if self._shared_with_screen() and not self._audio_lost():
            # "Music" here means the mode the person chose, and stopping it means
            # stopping that mode. Routed through Fusion directly rather than
            # through stop_if_running, which is the narrower "yield the strip to
            # another owner" and deliberately leaves Fusion alone.
            return self._host._fusion_ui.toggle()
        if self.is_running():
            self.stop_if_running()
            return False
        return self.activate()

    def shutdown(self) -> None:
        if self._hold_timer is not None:
            self._hold_timer.stop()
        self._cancel_calibration()
        self._end_sound_check()
        self._music.stop()
        self._update_meter_timer()

    def _toggle(self) -> None:
        host = self._host
        if not host.music_toggle_button.isChecked():
            self._stop()
            return
        if self._audio_lost():
            # The button came back because the device went away, and what it
            # offers is that device again — not the old standalone mode, which
            # would stop Screen Sync to take the strip for itself. The person
            # pressing it wants their music back, not their screen gone.
            host.music_toggle_button.setChecked(False)
            host._fusion_ui.restart_audio()
            self.refresh_shared_state()
            host._ambient_ui.refresh_status()
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
        # The reaction takes the capture over; the check lets go afterwards, so
        # the device stays open and keeps the room it has learned.
        self._end_sound_check()
        self._set_manual_controls_enabled(False)
        self._apply_enabled_state()
        self._show_preview()
        host.music_toggle_button.setText(host._tr("music.toggle_on"))
        self._write_status(host._tr("music.listening"))
        self._meter_status = ""
        host._log(host._tr("music.started_log"))
        self._update_meter_timer()

    def _stop(self) -> None:
        host = self._host
        was_running = self._reacting()
        self._music.release(OWNER_OUTPUT)
        self._apply_enabled_state()
        self._hide_preview()
        self._set_manual_controls_enabled(True)
        host.music_toggle_button.setChecked(False)
        host.music_toggle_button.setText(host._tr("music.toggle_off"))
        self._write_status(host._tr("music.status_off"))
        # Written over by the next meter tick if a sound check is still going.
        self._meter_status = ""
        if was_running:
            host._log(host._tr("music.stopped_log"))
        self._update_meter_timer()

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
        beat_sensitivity = beat_ratio_for_sensitivity(
            host.music_sensitivity_slider.value()
        )
        # The gate slider is in decibels and the engine takes the RMS it stands
        # for. Only applied for the microphone (system audio doesn't need it).
        noise_gate_rms = rms_for_slider(host.music_gate_slider.value()) if self._source == "mic" else 0.0
        device_name = host.music_source_combo.currentData() or ""
        self._music.configure(
            saturation=saturation,
            smoothing=smoothing,
            reactivity=reactivity,
            beat_strength=beat_strength,
            beat_sensitivity=beat_sensitivity,
            noise_gate_rms=noise_gate_rms,
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

    def _on_shared_beat_changed(self, value: int) -> None:
        """The screen card's beat slider moved. Same value, same handler."""
        slider = self._host.music_beat_slider
        if slider.value() == int(value):
            return
        slider.blockSignals(True)
        slider.setValue(int(value))
        slider.blockSignals(False)
        self._on_options_changed()

    def _on_shared_source_changed(self, key: str) -> None:
        """The screen card's source segment moved. Same path as the card's own,
        including reopening the device — nothing about switching source is
        reimplemented here."""
        segment = self._host.music_source_segment
        if segment.current_key() == key:
            return
        segment.set_current(key, animate=False)
        self._on_source_type_changed(key)

    def _refresh_shared_views(self) -> None:
        """Write the current values back onto the screen card's copies.

        Called from the same refresh that updates this card's own labels, so the
        two can never show different numbers — whichever of them was moved.
        """
        host = self._host
        beat = int(host.music_beat_slider.value())
        mirror = getattr(host, "fusion_beat_slider", None)
        if mirror is not None and int(mirror.value()) != beat:
            mirror.blockSignals(True)
            mirror.jump_to(beat)
            mirror.blockSignals(False)
        pill = getattr(host, "fusion_beat_value", None)
        if pill is not None:
            pill.setText(f"{beat}%")
        segment = getattr(host, "fusion_source_segment", None)
        source = host.music_source_segment.current_key()
        if segment is not None and segment.current_key() != source:
            segment.blockSignals(True)
            segment.set_current(source, animate=False)
            segment.blockSignals(False)

    def _refresh_value_labels(self) -> None:
        host = self._host
        host.music_speed_value.setText(f"{host.music_speed_slider.value()}%")
        host.music_beat_value.setText(f"{host.music_beat_slider.value()}%")
        host.music_sensitivity_value.setText(
            f"{host.music_sensitivity_slider.value()}%"
        )
        self._refresh_shared_views()
        host.music_gate_value.setText(
            host._tr("music.gate_value", value=format_db(db_for_slider(host.music_gate_slider.value())))
        )
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
            "sensitivity": int(host.music_sensitivity_slider.value()),
            "gate_db": round(db_for_slider(host.music_gate_slider.value()), 1),
            "source": self._source,
            # Remember the chosen device per source so switching back restores it.
            "device": str(prev.get("device", "")),
            "mic_device": str(prev.get("mic_device", "")),
            "colors": self._colors_dict(),
        }
        music["mic_device" if self._source == "mic" else "device"] = active_device
        host._settings["music"] = music
        save_settings(host._settings)

    def _on_recovery_changed(self, token: int, recovering: bool) -> None:
        if token != self._music.session_token() or not self._music.is_running():
            return
        if not self._reacting() and not self._shared_with_screen():
            # A sound check on its own: its meters say what the device is doing.
            return
        if recovering:
            self._write_status(self._host._tr("music.recovering"))
        elif self._shared_with_screen():
            self.refresh_shared_state()
        else:
            self._write_status(self._host._tr("music.listening"))

    def _on_failed(self, reason: str) -> None:
        host = self._host
        # The controller has already let go of everyone; the check and any
        # calibration go too, and a calibration leaves the gate as it was.
        self._cancel_calibration()
        self._end_sound_check()
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

    # ── sound check and band meters ───────────────────────────────────
    def is_checking_sound(self) -> bool:
        return self._check_deadline is not None and OWNER_PREVIEW in self._music.owners()

    def toggle_sound_check(self) -> None:
        """The heading's button: start a check, or end the running one at once."""
        if self._check_deadline is not None:
            self._end_sound_check()
        else:
            self._start_sound_check()

    def stop_sound_check(self) -> None:
        """End a running check: the page, the window or the session went away."""
        self._end_sound_check()

    def _start_sound_check(self) -> None:
        # Listen only, and only because the button was pressed. Not behind Pro
        # and not behind a connection: nothing is ever sent to the strip.
        self._apply_options()
        self._music.acquire(OWNER_PREVIEW)
        now = monotonic()
        self._check_started_at = now
        self._check_deadline = now + SOUND_CHECK_SECONDS
        self._meter_status = ""
        self._show_meter_status("music.meter_listening", now)
        self.refresh_check_button()
        self._apply_enabled_state()
        self._update_meter_timer()

    def _end_sound_check(self) -> None:
        if self._check_deadline is None:
            return
        self._check_deadline = None
        self._music.release(OWNER_PREVIEW)
        self._meter_status = ""
        if not self._reacting() and not self._shared_with_screen():
            self._write_status(self._host._tr("music.status_off"))
        self.refresh_check_button()
        self._apply_enabled_state()
        self._update_meter_timer()

    def note_section_changed(self, key: str) -> None:
        """The page changed. A check stops; the reaction itself does not."""
        self._on_music_page = key == "music"
        if not self._on_music_page:
            self._cancel_calibration()
            self._end_sound_check()
        self._update_meter_timer()

    def note_session(self, *, locked: bool | None = None, asleep: bool | None = None) -> None:
        """Windows locked or unlocked the session, or slept or woke.

        Nobody can see the card on a locked or sleeping machine: a check ends
        and the meters stop drawing until the person is back. A reaction still
        writing the strip keeps doing so; only its display pauses.
        """
        if locked is not None:
            self._session_locked = bool(locked)
        if asleep is not None:
            self._session_asleep = bool(asleep)
        if self._session_locked or self._session_asleep:
            self._cancel_calibration()
            self._end_sound_check()
        self._update_meter_timer()

    def note_window_visible(self, visible: bool) -> None:
        """The window was hidden, minimised or brought back."""
        self._window_visible = bool(visible)
        if not self._window_visible:
            self._cancel_calibration()
            self._end_sound_check()
        self._update_meter_timer()

    def refresh_check_button(self) -> None:
        host = self._host
        button = getattr(host, "music_check_button", None)
        if button is None:
            return
        checking = self._check_deadline is not None
        if checking:
            remaining = max(1, ceil(self._check_deadline - monotonic()))
            button.setText(host._tr("music.check_sound_stop", seconds=remaining))
        else:
            button.setText(host._tr("music.check_sound"))
        button.setToolTip(host._tr("music.check_sound_hint", seconds=SOUND_CHECK_SECONDS))
        if bool(button.property("active")) != checking:
            button.setProperty("active", checking)
            button.style().unpolish(button)
            button.style().polish(button)

    def retranslate(self) -> None:
        """Language changed: the button, the gate's readout and a check's status follow it."""
        self.refresh_check_button()
        self.refresh_calibrate_button()
        self._calibration_shown = None
        self._refresh_value_labels()
        key = self._meter_status
        if self._check_deadline is not None and key:
            self._meter_status = ""
            self._show_meter_status(key, monotonic(), force=True)

    def _band_meters(self) -> list:
        meters = getattr(self._host, "music_band_meters", {})
        return [meters[band] for band in _BANDS if band in meters]

    def _refresh_band_meter_colors(self) -> None:
        meters = getattr(self._host, "music_band_meters", {})
        for band in _BANDS:
            swatch = getattr(self._host, f"music_{band}_swatch", None)
            meter = meters.get(band)
            if swatch is not None and meter is not None:
                meter.set_color(swatch.color())

    def _update_meter_timer(self) -> None:
        timer = self._meter_timer
        if timer is None:
            return
        wanted = (
            self._on_music_page
            and self._window_visible
            and not self._session_locked
            and not self._session_asleep
            and self._music.is_running()
        )
        if wanted and not timer.isActive():
            self._meter_tick_at = monotonic()
            # A beat heard before the meters were on screen is not news now.
            self._last_beat_id = self._music.meter_reading().beat_id
            timer.start()
        elif not wanted and timer.isActive():
            timer.stop()
            for meter in self._band_meters():
                meter.set_state(False, 0.0)
            self._flash = 0.0
            self._clear_gate_level()

    def _refresh_meters(self) -> None:
        now = monotonic()
        dt = min(0.2, max(0.0, now - self._meter_tick_at))
        self._meter_tick_at = now
        if self._calibration is not None:
            self._tick_calibration(now)
        if self._check_deadline is not None:
            if now >= self._check_deadline or OWNER_PREVIEW not in self._music.owners():
                self._end_sound_check()
                return
            self.refresh_check_button()
        if not self._music.is_running():
            self._update_meter_timer()
            return
        reading = self._music.meter_reading()
        fresh = (
            reading.session_token == self._music.session_token()
            and reading.captured_at > 0.0
            and now - reading.captured_at <= METER_STALE_S
        )
        sounding = fresh and not reading.silent
        targets = self._meter_targets(reading, sounding)
        new_beat = sounding and reading.beat_id and reading.beat_id != self._last_beat_id
        if new_beat and not motion_reduced():
            self._flash = 1.0
        else:
            self._flash = max(0.0, self._flash - dt / FLASH_S)
        self._last_beat_id = reading.beat_id
        for index, meter in enumerate(self._band_meters()):
            level = follow_level(meter.level(), targets[index], dt)
            meter.set_state(True, level, self._flash if index == 0 else 0.0)
        self._refresh_gate_level(reading, fresh, dt)
        if self._check_deadline is not None:
            self._show_meter_status(self._meter_status_for(reading, fresh, now), now)

    @staticmethod
    def _meter_targets(reading, sounding: bool) -> tuple[float, float, float]:
        """How long each band's line should be: its share of the colour times
        how bright the reaction made that colour.

        The balance between the bands survives, quiet music draws short lines
        and loud music long ones, and a beat visibly lifts them — which is what
        the beat slider changes. Silence shows as empty lines whatever the
        weights say: at the strip's floor brightness the balance means nothing.
        """
        if not sounding:
            return (0.0, 0.0, 0.0)
        brightness = max(0.0, min(1.0, reading.color_level))
        return (reading.bass * brightness, reading.mid * brightness, reading.treble * brightness)

    @staticmethod
    def _gate_value_for_rms(rms: float) -> float:
        """A block RMS in noise-gate slider units — the inverse of the gate.

        The same decibel mapping that turns the slider into the gate's RMS, so
        the room's level and the handle can never drift apart.
        """
        return slider_for_rms(rms)

    def _refresh_gate_level(self, reading, fresh: bool, dt: float) -> None:
        gate = getattr(self._host, "music_gate_slider", None)
        if gate is None:
            return
        if self._source != "mic":
            # System audio has no gate to set, and its row is folded away.
            self._clear_gate_level()
            return
        target = min(100.0, self._gate_value_for_rms(reading.rms)) if fresh else 0.0
        self._gate_level = follow_level(self._gate_level, target, dt)
        gate.set_live_level(self._gate_level, passing=fresh and not reading.silent)

    def _clear_gate_level(self) -> None:
        self._gate_level = 0.0
        gate = getattr(self._host, "music_gate_slider", None)
        if gate is not None:
            gate.set_live_level(None)

    def _meter_status_for(self, reading, fresh: bool, now: float) -> str:
        if not fresh:
            if now - self._check_started_at < METER_STARTUP_GRACE_S:
                return "music.meter_listening"
            return "music.meter_no_signal"
        if reading.clipped:
            return "music.meter_clipped"
        if reading.silent:
            return "music.meter_silence"
        return "music.meter_listening"

    def _show_meter_status(self, key: str, now: float, *, force: bool = False) -> None:
        if self._holding_result():
            return  # a calibration's result is still on show
        if key == self._meter_status and not force:
            return
        if self._meter_status and not force and key != "music.meter_clipped":
            hold = METER_CLIPPED_HOLD_S if self._meter_status == "music.meter_clipped" else METER_STATUS_DWELL_S
            if now - self._meter_status_since < hold:
                return
        self._meter_status = key
        self._meter_status_since = now
        # The reaction and the combined mode keep their own words in the label;
        # the check only speaks for itself.
        if not self._reacting() and not self._shared_with_screen():
            self._write_status(self._host._tr(key))

    # ── calibration ────────────────────────────────────────────────────
    def is_calibrating(self) -> bool:
        return self._calibration is not None and OWNER_CALIBRATION in self._music.owners()

    def toggle_calibration(self) -> None:
        """The gate row's button: calibrate, or cancel the calibration running."""
        if self._calibration is not None:
            self._cancel_calibration(announce=True, resume=True)
        else:
            self._start_calibration()

    def _start_calibration(self) -> None:
        if self._source != "mic":
            return
        now = monotonic()
        # A check running now comes back afterwards with the time it had left.
        self._resume_check_s = max(0.0, self._check_deadline - now) if self._check_deadline is not None else None
        if self._holding_result():
            # The label shows the last result; the words it covers are already
            # waiting, and they are what goes back afterwards.
            self._hold_timer.stop()
        else:
            status = getattr(self._host, "music_status_label", None)
            self._status_to_restore = status.text() if status is not None else None
        self._apply_options()
        # The calibration takes the capture first and the check lets go after,
        # so the device stays open and the two never speak at once.
        self._music.acquire(OWNER_CALIBRATION)
        self._calibration = self._music.begin_noise_sample()
        self._calibration_started_at = now
        self._calibration_shown = None
        self._end_sound_check()
        self._show_calibration_progress()
        self.refresh_calibrate_button()
        self._apply_enabled_state()
        self._update_meter_timer()

    def _cancel_calibration(self, *, announce: bool = False, resume: bool = False) -> None:
        """Stop without touching the gate: the slider and the saved value stay.

        Only the person pressing Cancel resumes an interrupted check; the page,
        the window, the session or the device going away does not.
        """
        if self._calibration is None:
            return
        self._finish_calibration(None, "music.calibration_cancelled" if announce else None, resume=resume)

    def _tick_calibration(self, now: float) -> None:
        sample = self._calibration
        if sample is None:
            return
        if sample.complete:
            result = music_calibration.judge(*sample.snapshot())
            # Everything but silence from the device ends back in the check:
            # a result worth a second try is best judged against the room.
            resume = result.outcome != music_calibration.NO_AUDIO
            self._finish_calibration(result, self._calibration_message(result), resume=resume)
        elif now - self._calibration_started_at > music_calibration.TIMEOUT_S:
            result = music_calibration.Calibration(music_calibration.NO_AUDIO)
            self._finish_calibration(result, self._calibration_message(result), resume=False)
        else:
            self._show_calibration_progress()

    def _finish_calibration(self, result, message_key: str | None, *, resume: bool) -> None:
        if self._calibration is None:
            return
        succeeded = result is not None and result.outcome == music_calibration.OK
        seconds = self._resume_check_s
        if succeeded and seconds is None and not self._feeding_a_light():
            # Started on its own: a short check, to see the new gate against the room.
            seconds = CHECK_AFTER_CALIBRATION_S
        if resume and seconds:
            # The check takes the capture first and the calibration lets go
            # after, so the device stays open across the hand-over.
            now = monotonic()
            self._music.acquire(OWNER_PREVIEW)
            self._check_deadline = now + seconds
            self._check_started_at = now - METER_STARTUP_GRACE_S
            self._meter_status = ""
        self._calibration = None
        self._resume_check_s = None
        self._music.end_noise_sample()
        self._music.release(OWNER_CALIBRATION)
        if succeeded:
            # The only moment the gate changes: the slider saves it the way a
            # hand on the slider would.
            self._host.music_gate_slider.setValue(int(result.position))
        if message_key is None:
            # Stopped from outside: nothing to report, the label gets its words back.
            self._restore_status()
        else:
            text = (self._host._tr(message_key, value=format_db(result.gate_db)) if succeeded
                    else self._host._tr(message_key))
            self._write_calibration_status(text)
            if self._hold_timer is not None:
                self._hold_timer.start(round(CALIBRATION_RESULT_HOLD_S * 1000))
        self.refresh_calibrate_button()
        self.refresh_check_button()
        self._apply_enabled_state()
        self._update_meter_timer()

    @staticmethod
    def _calibration_message(result) -> str:
        return {
            music_calibration.OK: "music.calibration_done",
            music_calibration.CLIPPED: "music.calibration_clipped",
            music_calibration.UNSTABLE: "music.calibration_unstable",
            music_calibration.TOO_NOISY: "music.calibration_too_noisy",
            music_calibration.NO_AUDIO: "music.calibration_no_audio",
        }[result.outcome]

    def _show_calibration_progress(self) -> None:
        sample = self._calibration
        measured = sample.measured_seconds if sample is not None else 0.0
        remaining = max(1, ceil(music_calibration.MEASURE_S - measured))
        if self._calibration_shown == ("hold", remaining):
            return
        self._calibration_shown = ("hold", remaining)
        self._write_calibration_status(self._host._tr("music.calibration_hold", seconds=remaining))

    # ── who speaks in the status label ─────────────────────────────────
    def _holding_result(self) -> bool:
        """A calibration's result is on show until its timer lets the label go."""
        return self._hold_timer is not None and self._hold_timer.isActive()

    def _write_calibration_status(self, text: str) -> None:
        """A calibration's words. Its own, whatever mode is running."""
        status = getattr(self._host, "music_status_label", None)
        if status is not None:
            status.setText(text)
            status.setVisible(True)

    def _write_status(self, text: str) -> None:
        """Everyone but a calibration writes the status through here.

        While a calibration runs, or its result is still on show, the label is
        the calibration's: what the others would have said is kept and comes
        back afterwards.
        """
        status = getattr(self._host, "music_status_label", None)
        if status is None:
            return
        if self._calibration is not None or self._holding_result():
            self._status_to_restore = text
            return
        status.setText(text)
        status.setVisible(True)

    def _restore_status(self) -> None:
        text = self._status_to_restore
        self._status_to_restore = None
        if self._hold_timer is not None:
            self._hold_timer.stop()
        if self.is_checking_sound():
            # A resumed check speaks for itself on its next tick.
            self._meter_status = ""
            return
        status = getattr(self._host, "music_status_label", None)
        if status is not None and text is not None:
            status.setText(text)
            status.setVisible(True)

    def refresh_calibrate_button(self) -> None:
        host = self._host
        button = getattr(host, "music_calibrate_button", None)
        if button is None:
            return
        calibrating = self._calibration is not None
        button.setText(host._tr("music.calibrate_cancel" if calibrating else "music.calibrate"))
        button.setToolTip(host._tr("music.calibrate_hint", seconds=round(music_calibration.MEASURE_S)))
        # One width for every language and both states, so the row never moves
        # when the language changes or the button turns into Cancel.
        button.ensurePolished()
        metrics = button.fontMetrics()
        widest = max(
            metrics.horizontalAdvance(text)
            for key in ("music.calibrate", "music.calibrate_cancel")
            for text in localization_manager.translation_variants(key) or [host._tr(key)]
        )
        button.setFixedWidth(widest + host._sz(6))
        if bool(button.property("active")) != calibrating:
            button.setProperty("active", calibrating)
            button.style().unpolish(button)
            button.style().polish(button)
