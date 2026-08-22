from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, Qt
from PySide6.QtWidgets import QGraphicsOpacityEffect

from app.ambient_controller import AmbientController
from app.feature_gate import can_use
from app.screen_profiles import normalize_profile_id
from app.storage import save_settings
from app.widgets.animation_helpers import play_or_complete

_DEFAULTS = {"region": "full", "saturation": 55, "smoothing": 65, "monitor": 0, "profile": "desktop"}


class AmbientUiController:
    """Wires the ambient screen-sync card to the capture/stream backend.

    Pro-gated. While ambient is running it owns the strip colour, so the manual
    colour and effect controls are disabled to avoid two writers fighting.
    """

    def __init__(self, host: Any) -> None:
        self._host = host
        self._ambient = AmbientController(host)

    def wire(self) -> None:
        host = self._host
        self._setup_tune_reveal()
        self._setup_tune_button_reveal()
        host.ambient_toggle_button.clicked.connect(self._toggle)
        host.ambient_profile_segment.selected.connect(lambda _key: self._on_options_changed())
        host.fusion_mode_segment.selected.connect(self._on_mode_changed)
        host.fusion_tune_button.toggled.connect(self._on_tune_toggled)
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
        """Whether the screen is driving the strip — in either mode.

        The capture on its own is not the answer: in the combined mode the
        coordinator is what owns the output, and the card's button has to
        describe that rather than the thread underneath it.
        """
        return self._host._fusion_ui.is_running()

    # ── the mode chooser ──────────────────────────────────────────────
    def sync_mode_segment(self) -> None:
        host = self._host
        segment = getattr(host, "fusion_mode_segment", None)
        if segment is None:
            return
        segment.blockSignals(True)
        segment.set_current(host._fusion_ui.mode(), animate=False)
        segment.blockSignals(False)
        self.refresh_status()
        self._refresh_tune_visibility(animate=False)

    def _on_mode_changed(self, key: str) -> None:
        self._host._fusion_ui.set_mode(key)
        self.refresh_status()
        self._refresh_tune_visibility(animate=True)
        self._host._music_ui.refresh_shared_state()

    def _on_tune_toggled(self, opened: bool) -> None:
        button = getattr(self._host, "fusion_tune_button", None)
        if button is not None:
            button.set_role("accent_soft" if opened else "ghost")
        self._animate_tune(opening=bool(opened))

    def _setup_tune_reveal(self) -> None:
        row = getattr(self._host, "fusion_tune_row", None)
        if row is None:
            return
        row.setMaximumHeight(0)
        self._tune_anim = QPropertyAnimation(row, b"maximumHeight", self._host)
        self._tune_anim.setDuration(210)
        self._tune_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._tune_hiding = False
        self._tune_anim.finished.connect(self._finish_tune_animation)

    def _setup_tune_button_reveal(self) -> None:
        button = getattr(self._host, "fusion_tune_button", None)
        if button is None:
            return
        self._tune_button_width_px = self._host._sz(32)
        effect = QGraphicsOpacityEffect(button)
        effect.setOpacity(0.0)
        button.setGraphicsEffect(effect)
        button.setMaximumWidth(0)

        width = QPropertyAnimation(button, b"maximumWidth", self._host)
        opacity = QPropertyAnimation(effect, b"opacity", self._host)
        for animation in (width, opacity):
            animation.setDuration(230)
            animation.setEasingCurve(QEasingCurve.OutCubic)
        group = QParallelAnimationGroup(self._host)
        group.addAnimation(width)
        group.addAnimation(opacity)
        group.finished.connect(self._finish_tune_button_animation)
        self._tune_button_effect = effect
        self._tune_button_width_anim = width
        self._tune_button_opacity_anim = opacity
        self._tune_button_anim = group
        self._tune_button_hiding = False

    def _set_tune_button_visible_instant(self, visible: bool) -> None:
        button = getattr(self._host, "fusion_tune_button", None)
        animation = getattr(self, "_tune_button_anim", None)
        effect = getattr(self, "_tune_button_effect", None)
        if button is None or animation is None or effect is None:
            if button is not None:
                button.setVisible(visible)
            return
        animation.stop()
        button.setMaximumWidth(self._tune_button_width_px if visible else 0)
        effect.setOpacity(1.0 if visible else 0.0)
        button.setVisible(visible)
        self._tune_button_hiding = False

    def _animate_tune_button(self, *, showing: bool) -> None:
        button = getattr(self._host, "fusion_tune_button", None)
        group = getattr(self, "_tune_button_anim", None)
        width = getattr(self, "_tune_button_width_anim", None)
        opacity = getattr(self, "_tune_button_opacity_anim", None)
        effect = getattr(self, "_tune_button_effect", None)
        if any(item is None for item in (button, group, width, opacity, effect)):
            self._set_tune_button_visible_instant(showing)
            return

        group.stop()
        self._tune_button_hiding = not showing
        if showing:
            button.setVisible(True)
        width.setStartValue(button.maximumWidth())
        width.setEndValue(self._tune_button_width_px if showing else 0)
        opacity.setStartValue(effect.opacity())
        opacity.setEndValue(1.0 if showing else 0.0)
        play_or_complete(group)

    def _finish_tune_button_animation(self) -> None:
        button = getattr(self._host, "fusion_tune_button", None)
        if button is None:
            return
        if self._tune_button_hiding:
            button.setMaximumWidth(0)
            button.setVisible(False)
            self._tune_button_hiding = False
            return
        button.setMaximumWidth(self._tune_button_width_px)

    def _set_tune_open_instant(self, opened: bool) -> None:
        row = getattr(self._host, "fusion_tune_row", None)
        animation = getattr(self, "_tune_anim", None)
        if row is None or animation is None:
            return
        animation.stop()
        if opened:
            row.setVisible(True)
            row.setMaximumHeight(16777215)
            row.setMaximumHeight(row.sizeHint().height())
        else:
            row.setMaximumHeight(0)
            row.setVisible(False)
        self._tune_hiding = False

    def _animate_tune(self, *, opening: bool) -> None:
        row = getattr(self._host, "fusion_tune_row", None)
        animation = getattr(self, "_tune_anim", None)
        if row is None or animation is None:
            if row is not None:
                row.setVisible(opening)
            return

        animation.stop()
        self._tune_hiding = not opening
        if opening:
            start = row.maximumHeight() if not row.isHidden() else 0
            row.setVisible(True)
            row.setMaximumHeight(16777215)
            target = row.sizeHint().height()
            row.setMaximumHeight(start)
        else:
            start = row.maximumHeight()
            target = 0
        animation.setStartValue(start)
        animation.setEndValue(target)
        play_or_complete(animation)

    def _finish_tune_animation(self) -> None:
        row = getattr(self._host, "fusion_tune_row", None)
        if row is None:
            return
        if self._tune_hiding:
            row.setMaximumHeight(0)
            row.setVisible(False)
            self._tune_hiding = False
            return
        row.setMaximumHeight(16777215)
        row.setMaximumHeight(row.sizeHint().height())

    def _refresh_tune_visibility(self, *, animate: bool = False) -> None:
        """The settings belong to the combined mode, so they appear with it.

        Collapsed again on the way out rather than merely hidden: coming back to
        the mode later should look the way it looked the first time, not the way
        it was left in a session someone has forgotten.
        """
        host = self._host
        button = getattr(host, "fusion_tune_button", None)
        row = getattr(host, "fusion_tune_row", None)
        if button is None or row is None:
            return
        combined = host._fusion_ui.mode() == "screen_music"
        if animate:
            self._animate_tune_button(showing=combined)
        else:
            self._set_tune_button_visible_instant(combined)
        if not combined:
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
            button.set_role("ghost")
            self._set_tune_open_instant(False)

    def refresh_status(self) -> None:
        """The one line under the row title, and the one place it is decided.

        Three things it can say, in order of what a person needs to know:
        something is stopping this mode, or it is running and which one, or it
        is simply off. A description of the chosen mode is not among them —
        while everything is fine the segments already say that, and while
        something is wrong the reason matters more than the description.
        """
        host = self._host
        label = getattr(host, "ambient_status_label", None)
        if label is None:
            return
        label.setText(host._tr(host._fusion_ui.status_key()))
        label.setVisible(True)
        self.sync_toggle_label()

    def sync_toggle_label(self) -> None:
        """What the button offers to do next: light the strip, or show it here."""
        host = self._host
        button = getattr(host, "ambient_toggle_button", None)
        if button is None:
            return
        button.setText(host._tr(host._fusion_ui.toggle_label_key()))
        caption = getattr(host, "ambient_preview_label", None)
        if caption is not None:
            caption.setText(host._tr(host._fusion_ui.preview_hint_key()))

    def stats(self) -> dict:
        return {
            "running": self._ambient.is_running(),
            # The frames are this controller's; the writes are not, once the
            # capture is feeding a composer. Said out loud so the report can
            # leave out numbers it is no longer measuring instead of printing
            # their zeros.
            #
            # Asked of the run, not of this instant: a report is usually
            # exported after stopping, and by then "is Fusion running" is False
            # while the numbers being described still belong to it.
            "link_owned_by_fusion": self._host._fusion_ui.has_run(),
            "errors": self._ambient.stream_error_count(),
            "last_error": self._ambient.last_stream_error(),
            # The last run's numbers survive its stop, so a report exported
            # after switching sync off still describes the run being asked about.
            "live_sync": self._ambient.live_sync_report(),
            "live_sync_settings": self._ambient.live_sync_settings(),
        }

    def stop_if_running(self) -> None:
        if self.is_running() or self._ambient.is_running():
            self._stop()

    # ── lending the capture to Fusion ─────────────────────────────────
    def connect_samples(self, slot) -> None:
        """Send every captured frame to ``slot`` as well as to the card.

        Queued on purpose: the frames are produced on the capture thread and the
        composer lives on the UI thread, which is also why a sample carries its
        own timestamp instead of being timed on arrival.
        """
        self._ambient.screen_sampled.connect(slot, Qt.QueuedConnection)

    def start_listening(self) -> int:
        """Capture the screen for someone else to compose with.

        The card's own options still apply and its preview still updates; what
        does not happen is this controller writing to the strip. Returns the
        session token every frame of this run will carry.
        """
        self._apply_options()
        return self._ambient.start_listening()

    def stop_listening(self) -> None:
        if self._ambient.is_running():
            self._ambient.stop()
            self._host.ambient_preview.clear()

    def activate(self, profile_id: str | None = None, mode: str | None = None) -> bool:
        """Start screen sync as if the card's toggle was pressed (keeps the
        licence/connection gates and stops any other active stream). A scene can
        pin ``profile_id`` (desktop/game/movie) — it is selected first, so
        applying the scene restores the exact look, and it applies live if screen
        sync is already running. Returns whether it is running — a gate may have
        silently blocked it."""
        host = self._host
        if mode is not None:
            # An explicit mode from a scene or the API. Set before the gate, so
            # the gate is asked about the mode being requested rather than the
            # one this machine happens to be showing.
            host._fusion_ui.set_mode(mode)
            self.sync_mode_segment()
        # Gate before touching the saved profile: if a Free licence or a missing
        # connection will refuse the start, the user's profile must not be
        # silently changed as a side effect. When already running, the gates
        # already passed, so switching the profile live is fine.
        # Asked before the saved profile is touched. A licence and a strip are
        # no longer among the answers — they decide where the colours go, not
        # whether the mode runs — but the principle is unchanged: a start that
        # is going to refuse must not leave a changed profile behind it as the
        # only trace. What can still refuse is a missing audio device.
        if not self.is_running() and host._fusion_ui.unavailable_reason():
            host.ambient_toggle_button.setChecked(True)
            self._toggle()  # surfaces the reason
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
        self._start()

    def _start(self) -> None:
        host = self._host
        if not host._fusion_ui.activate():
            host.ambient_toggle_button.setChecked(False)
            self.refresh_status()
            reason = host._fusion_ui.last_reason()
            if reason:
                host._show_error(host._tr(reason))
            return
        self._set_manual_controls_enabled(False)
        self.refresh_status()
        host._music_ui.refresh_shared_state()
        host._log(host._tr("ambient.started_log"))

    def _stop(self) -> None:
        host = self._host
        was_running = host._fusion_ui.is_running()
        host._fusion_ui.stop_if_running()
        self._ambient.stop()
        host.ambient_preview.clear()
        self._set_manual_controls_enabled(True)
        host.ambient_toggle_button.setChecked(False)
        self.refresh_status()
        host._music_ui.refresh_shared_state()
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
        self.refresh_status()

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

    def _update_preview(self, raw_r: int, raw_g: int, raw_b: int, *_shaped: int) -> None:
        """The left half only: the screen as the capture found it.

        The right half used to be this controller's own finished colour, which
        stopped being the answer the moment music could move it. It now comes
        from the delivery itself, so the two capsules read "the screen" and
        "what the strip was given" rather than two stages of the same sum with
        the interesting part left out.
        """
        self._host.ambient_preview.set_source((raw_r, raw_g, raw_b))

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
