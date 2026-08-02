from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QObject, QPropertyAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.widgets.animation_helpers import play_or_complete
from app.widgets.update_overlay import UpdateOverlay

_LABELS = {
    "title": "Update available",
    "release": "LumaBLE 0.3.5",
    "versions": "Installed 0.3.4 → available 0.3.5-beta",
    "notes": "Some notes",
    "open": "Open download page",
    "later": "Remind later",
    "skip": "Skip this version",
}


def test_overlay_open_lands_in_final_state_when_motion_is_reduced(preserve_motion_policy) -> None:
    """A reduced-motion overlay must open straight into its resting state: full
    opacity and the panel at its final position, with no animation left running."""
    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    overlay = UpdateOverlay(dict(_LABELS), "0.3.5-beta", parent)
    try:
        overlay.open()
        app.processEvents()

        assert overlay._opacity_effect.opacity() == 1.0
        assert overlay._panel.pos() == overlay._panel_anim.endValue()
        assert overlay._fade_anim.state() == QPropertyAnimation.State.Stopped
        assert overlay._panel_anim.state() == QPropertyAnimation.State.Stopped
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_theme_crossfade_runs_cleanup_when_motion_is_reduced(preserve_motion_policy) -> None:
    """The theme crossfade's cleanup (delete the snapshot overlay + clear the
    host references) hangs off finished, so reduced motion must still run it —
    otherwise a frozen snapshot would stay on top of the app."""
    from app.main_window import MainWindow

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        snapshot = window.grab()
        assert not snapshot.isNull()

        window._theme_controller.animate_overlay_fade(snapshot, duration=200)
        app.processEvents()

        assert window._theme_transition is None
        assert window._theme_transition_overlay is None
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_combo_popup_restores_scrollbar_policy_when_reduced(preserve_motion_policy) -> None:
    """The combo's open animation hides the list scrollbar during the grow and
    restores the as-needed policy on the slide's finished. Reduced motion must
    still land in the restored (as-needed) state, not stuck on always-off."""
    from app.theme import theme_manager
    from app.widgets.static_popup_combo_box import StaticPopupComboBox

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    tokens = theme_manager.set_dark(True)
    parent = QWidget()
    parent.resize(400, 300)
    parent.show()
    combo = StaticPopupComboBox(lambda: tokens, lambda: True, parent)
    combo.addItem("Russian", "ru")
    combo.addItem("English", "en")
    app.processEvents()
    try:
        combo.showPopup()
        app.processEvents()
        assert combo._list.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    finally:
        combo.hidePopup()
        parent.deleteLater()
        app.processEvents()


def test_onboarding_open_and_tour_transition_land_final_state_when_reduced(preserve_motion_policy) -> None:
    """Reduced motion completes the welcome opening and moves the spotlight
    without leaving a position or scroll animation running."""
    from app.widgets.onboarding_overlay import OnboardingOverlay

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    labels = {
        "skip": "Skip",
        "tour": "Tour",
        "back": "Back",
        "next": "Next",
        "finish": "Finish",
        "tour_steps": [
            {"section": "color", "target": "missing", "title": "One", "body": "First"},
            {"section": "settings", "target": "missing", "title": "Two", "body": "Second"},
        ],
    }
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    overlay = OnboardingOverlay(labels, parent)
    try:
        overlay.open()
        app.processEvents()
        # Open finished: the fade's cleanup dropped the overlay opacity effect,
        # and the panel settled at its resting position.
        assert overlay._opacity_effect is None
        assert overlay._panel.pos() == overlay._panel_anim.endValue()

        # Starting the tour lands on its first step without a moving spotlight.
        overlay._next()
        app.processEvents()
        assert overlay._tour_index == 0
        assert overlay._spot_anim.state() == QAbstractAnimation.Stopped
    finally:
        overlay.hide()
        parent.deleteLater()
        app.processEvents()


def test_aurora_phase_timer_freezes_and_resumes_with_motion_policy(preserve_motion_policy) -> None:
    from app.widgets.aurora_background import AuroraBackground

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    aurora = AuroraBackground()
    aurora.resize(120, 120)
    aurora.show()
    app.processEvents()
    try:
        assert aurora._timer.isActive()  # phase drifts under full motion

        policy.set_mode("reduced")
        assert not aurora._timer.isActive()  # phase frozen

        # A real colour change still repaints the static background and must not
        # wake the phase timer.
        aurora.set_accent_color(10, 20, 30)
        assert not aurora._timer.isActive()

        policy.set_mode("full")
        assert aurora._timer.isActive()  # resumed for the visible owner
    finally:
        aurora.deleteLater()
        app.processEvents()


def test_aurora_starts_frozen_when_already_reduced(preserve_motion_policy) -> None:
    from app.widgets.aurora_background import AuroraBackground

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    aurora = AuroraBackground()
    aurora.resize(120, 120)
    aurora.show()
    app.processEvents()
    try:
        assert not aurora._timer.isActive()
    finally:
        aurora.deleteLater()
        app.processEvents()


def test_aurora_hidden_flip_to_full_resumes_only_after_show(preserve_motion_policy) -> None:
    """The lifecycle edge: reduced + hidden, flipped back to full while hidden,
    stays off until shown; show() starts it, hide() stops it again."""
    from app.widgets.aurora_background import AuroraBackground

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    aurora = AuroraBackground()
    aurora.resize(120, 120)
    try:
        # Hidden + reduced → off.
        assert not aurora._timer.isActive()

        # Flip to full while still hidden → must stay off (no visible owner).
        policy.set_mode("full")
        assert not aurora._timer.isActive()

        # Shown → resumes; hidden again → stops.
        aurora.show()
        app.processEvents()
        assert aurora._timer.isActive()
        aurora.hide()
        app.processEvents()
        assert not aurora._timer.isActive()
    finally:
        aurora.deleteLater()
        app.processEvents()


def test_celebration_reduced_is_static_and_closes_via_its_own_timer(preserve_motion_policy, monkeypatch) -> None:
    from app.widgets.celebration_overlay import CelebrationOverlay

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    # Prove the REAL single-shot finish timer fires (not just that _finish works):
    # shorten the duration and wait for the actual signal.
    monkeypatch.setattr(CelebrationOverlay, "DURATION_MS", 1)

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(400, 300)
    parent.show()
    cel = CelebrationOverlay(parent, message="Done")
    emitted: list[bool] = []
    cel.finished.connect(lambda: emitted.append(True))
    try:
        cel.start()
        # Static from the start: no confetti, and the frame timer never runs...
        assert cel._static is True
        assert cel._particles == []
        assert not cel._frame_timer.isActive()
        assert cel._finish_timer.isActive()

        # ...yet the functional close timer really fires finished on its own.
        for _ in range(50):
            if emitted:
                break
            QTest.qWait(5)
        assert emitted == [True]
    finally:
        parent.deleteLater()
        app.processEvents()


def test_celebration_freezes_on_reduced_and_does_not_resume_on_full(preserve_motion_policy) -> None:
    from app.widgets.celebration_overlay import CelebrationOverlay

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(400, 300)
    parent.show()
    cel = CelebrationOverlay(parent, message="Done")
    try:
        cel.start()
        assert not cel._static
        assert cel._frame_timer.isActive()

        policy.set_mode("reduced")  # freeze in place; close deadline preserved
        assert cel._static is True
        assert not cel._frame_timer.isActive()
        assert cel._finish_timer.isActive()

        policy.set_mode("full")  # must NOT resume confetti (no jump backwards)
        assert cel._static is True
        assert not cel._frame_timer.isActive()
    finally:
        cel._finish()
        parent.deleteLater()
        app.processEvents()


def test_slider_reduced_snaps_readout_and_keeps_feedback_neutral(preserve_motion_policy) -> None:
    from app.widgets.liquid_slider import LiquidSlider

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    slider = LiquidSlider("blue")
    slider.setRange(0, 100)
    try:
        slider.setValue(50)  # readout must snap, not ease
        assert slider._display_value == 50.0

        slider._press_in()  # decorative press glow is disabled
        assert slider._press == 0.0
        assert slider._press_anim.state() == QPropertyAnimation.State.Stopped
    finally:
        slider.deleteLater()
        app.processEvents()


def test_slider_switch_to_reduced_resets_feedback_then_full_reanimates(preserve_motion_policy) -> None:
    from app.widgets.liquid_slider import LiquidSlider

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    slider = LiquidSlider("blue")
    slider.setRange(0, 100)
    slider.setValue(0)
    try:
        slider._press_in()  # press glow running under full
        assert slider._press_anim.state() == QPropertyAnimation.State.Running
        slider.setValue(80)  # readout easing toward 80 under full

        policy.set_mode("reduced")  # reset feedback + snap the readout
        assert slider._press == 0.0
        assert slider._impact == 0.0
        assert slider._display_value == 80.0
        assert slider._press_anim.state() == QPropertyAnimation.State.Stopped

        policy.set_mode("full")  # a new press animates again — no permanent freeze
        slider._press_in()
        assert slider._press_anim.state() == QPropertyAnimation.State.Running
    finally:
        slider.deleteLater()
        app.processEvents()


def test_effect_preview_freezes_on_reduced_and_resumes_on_full(preserve_motion_policy) -> None:
    from app.widgets.effect_preview_strip import EffectPreviewStrip

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    preview = EffectPreviewStrip()
    preview.resize(200, 54)
    preview.show()
    app.processEvents()
    try:
        assert preview._timer.isActive()
        assert preview._pulse_anim.state() == QPropertyAnimation.State.Running

        policy.set_mode("reduced")  # freeze on a clear static frame
        assert not preview._timer.isActive()
        assert preview._pulse_anim.state() == QPropertyAnimation.State.Stopped
        assert preview._active_pulse_anim.state() == QPropertyAnimation.State.Stopped
        assert preview._intensity == 1.0

        policy.set_mode("full")  # resume the visible preview
        assert preview._timer.isActive()
        assert preview._pulse_anim.state() == QPropertyAnimation.State.Running
    finally:
        preview.deleteLater()
        app.processEvents()


def test_effect_preview_starts_frozen_when_already_reduced(preserve_motion_policy) -> None:
    from app.widgets.effect_preview_strip import EffectPreviewStrip

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    preview = EffectPreviewStrip()
    preview.resize(200, 54)
    preview.show()
    app.processEvents()
    try:
        assert not preview._timer.isActive()
        assert preview._pulse_anim.state() == QPropertyAnimation.State.Stopped
        assert preview._intensity == 1.0

        # Switching effect under reduced motion must snap — no cross-dissolve.
        preview.set_effect("smooth_rainbow", 0x8A)
        assert preview._effect_key == "smooth_rainbow"
        assert preview._switch_anim.state() == QPropertyAnimation.State.Stopped
        assert preview._switch_value == 0.0
        assert preview._prev_pixmap is None
    finally:
        preview.deleteLater()
        app.processEvents()


def test_smooth_scroll_lands_exact_value_and_clears_target_when_reduced(preserve_motion_policy) -> None:
    """Reduced motion snaps the scroll animation to its exact target and the
    finished handler clears the pending _target_value."""
    from PySide6.QtWidgets import QScrollArea

    from app.widgets.smooth_scroll_filter import SmoothScrollFilter

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scrollbar = scroll.verticalScrollBar()
    scrollbar.setRange(0, 1000)
    scrollbar.setValue(0)
    scroll_filter = SmoothScrollFilter(scroll)

    # Mimic what eventFilter sets up for a pending wheel scroll, then complete it.
    scroll_filter._target_value = 420
    scroll_filter._animation.setStartValue(0)
    scroll_filter._animation.setEndValue(420)
    play_or_complete(scroll_filter._animation)

    assert scrollbar.value() == 420
    assert scroll_filter._target_value is None
    scroll.deleteLater()
    app.processEvents()


def test_license_open_lands_final_state_when_reduced(preserve_motion_policy) -> None:
    """The License overlay's initial open (fade + panel rise) must land at full
    opacity and the panel's resting geometry under reduced motion. The success /
    Celebration animation is a separate scenario, not touched here."""
    from app.widgets.license_overlay import LicenseOverlay

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    labels = {
        "title": "LumaBLE Pro", "subtitle": "Unlock everything",
        "active_title": "Pro active", "active_license": "License active", "active_dev": "Dev active",
        "key_label": "Key", "placeholder": "Paste key", "activate": "Activate", "activating": "Checking",
        "buy": "Buy Pro", "have_key": "I have a key", "back": "Back", "ok": "OK", "close": "Close",
        "invalid": "Invalid", "activated": "Activated", "buy_unavailable": "No page",
        "deactivate": "Deactivate", "deactivate_confirm": "Sure?", "deactivated": "Deactivated",
    }
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    overlay = LicenseOverlay(labels, lambda _k: (False, "Invalid"), parent, buy_callback=lambda: False)
    try:
        overlay.open()
        app.processEvents()  # runs the deferred _start_open_animation

        assert overlay._opacity_effect.opacity() == 1.0
        assert overlay._panel.geometry() == overlay._panel_anim.endValue()
        assert overlay._fade_anim.state() == QPropertyAnimation.State.Stopped
        assert overlay._panel_anim.state() == QPropertyAnimation.State.Stopped
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_button_reduced_skips_ripple_and_keeps_scale_neutral(preserve_motion_policy) -> None:
    from app.widgets.liquid_button import LiquidButton

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    button = LiquidButton("X", "accent")
    try:
        button._handle_button_enter()  # would hover-scale in full motion
        button._handle_button_press(5.0, 5.0)  # would spawn a ripple in full motion

        assert button._scale == 1.0
        assert button._ripple_opacity == 0.0
        assert button._scale_anim.state() == QPropertyAnimation.State.Stopped
        assert button._ripple_anim.state() == QPropertyAnimation.State.Stopped
    finally:
        button.deleteLater()
        app.processEvents()


def test_button_switching_to_reduced_resets_running_scale_and_ripple(preserve_motion_policy) -> None:
    from app.widgets.liquid_button import LiquidButton

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    button = LiquidButton("X", "accent")
    try:
        button._handle_button_press(5.0, 5.0)  # ripple + press-scale running under full
        assert button._ripple_anim.state() == QPropertyAnimation.State.Running

        policy.set_mode("reduced")  # changed → reset to the neutral resting state

        assert button._scale == 1.0
        assert button._ripple_opacity == 0.0
        assert button._scale_anim.state() == QPropertyAnimation.State.Stopped
        assert button._ripple_anim.state() == QPropertyAnimation.State.Stopped

        # Back to full: a new press must animate a ripple again — no permanent freeze.
        policy.set_mode("full")
        button._handle_button_press(6.0, 6.0)
        assert button._ripple_anim.state() == QPropertyAnimation.State.Running
        assert button._ripple_opacity > 0.0
    finally:
        button.deleteLater()
        app.processEvents()


_LICENSE_LABELS = {
    "title": "LumaBLE Pro", "subtitle": "Unlock everything",
    "active_title": "Pro active", "active_license": "License active", "active_dev": "Dev active",
    # "activating" is stored without a suffix in every language ("Checking",
    # "Проверяем", ...) — the reduced-motion label has to add the ellipsis itself.
    "key_label": "Key", "placeholder": "Paste key", "activate": "Activate", "activating": "Checking",
    "buy": "Buy Pro", "have_key": "I have a key", "back": "Back", "ok": "OK", "close": "Close",
    "invalid": "Invalid", "activated": "Activated", "buy_unavailable": "No page",
    "deactivate": "Deactivate", "deactivate_confirm": "Sure?", "deactivated": "Deactivated",
}


def test_license_spinner_freezes_to_static_label_and_resumes(preserve_motion_policy) -> None:
    """Reduced motion must not cancel the activation worker — only the trailing
    dots stop, leaving a static 'Activating…' on the button."""
    from app.widgets.license_overlay import LicenseOverlay

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    overlay = LicenseOverlay(_LICENSE_LABELS, lambda _k: (False, "Invalid"), parent, buy_callback=lambda: False)
    try:
        overlay._set_activating(True)
        assert overlay._spinner_timer.isActive()
        overlay._tick_spinner()
        assert overlay._activate_button.text() == "Checking."  # animated frame

        policy.set_mode("reduced")
        assert not overlay._spinner_timer.isActive()
        assert overlay._activate_button.text() == "Checking…"  # static, single ellipsis
        assert overlay._activating is True  # the worker is still considered busy

        policy.set_mode("full")
        assert overlay._spinner_timer.isActive()
        assert overlay._activate_button.text() == "Checking"  # back to frame 0

        # Finishing the activation stops the spinner regardless of motion mode.
        overlay._set_activating(False)
        assert not overlay._spinner_timer.isActive()
        assert overlay._activating is False
    finally:
        parent.deleteLater()
        app.processEvents()


def test_license_spinner_stays_static_when_activation_starts_reduced(preserve_motion_policy) -> None:
    from app.widgets.license_overlay import LicenseOverlay

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(900, 700)
    overlay = LicenseOverlay(_LICENSE_LABELS, lambda _k: (False, "Invalid"), parent, buy_callback=lambda: False)
    try:
        overlay._set_activating(True)

        assert not overlay._spinner_timer.isActive()
        assert overlay._activate_button.text() == "Checking…"
    finally:
        parent.deleteLater()
        app.processEvents()


class _QtUpdateHost(QObject):
    """UpdateController only builds its dots timer when the host is a QObject."""

    def __init__(self) -> None:
        super().__init__()
        self.check_update_button = _FakeCheckButton()
        self._settings: dict = {}
        self._update_result = None
        self.update_overlays: list[object] = []

    def _tr(self, key: str, **_kwargs: object) -> str:
        return "Checking for updates..." if key == "updates.checking" else key


class _FakeCheckButton:
    def __init__(self) -> None:
        self.text = ""
        self.enabled = True

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


def test_update_check_dots_freeze_to_static_text_and_resume(preserve_motion_policy) -> None:
    """The update check keeps running under reduced motion — only the animated
    dots stop, leaving the plain 'Checking for updates...' label."""
    from app.update_controller import UpdateController

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    QApplication.instance() or QApplication([])
    host = _QtUpdateHost()
    controller = UpdateController(host, "0.1.1", "", "")

    controller._start_check_animation()
    assert controller._checking_timer.isActive()
    controller._tick_check_animation()
    assert host.check_update_button.text == "Checking for updates."

    policy.set_mode("reduced")
    assert not controller._checking_timer.isActive()
    assert host.check_update_button.text == "Checking for updates..."  # static label
    assert controller._checking_active is True  # the check itself is still running

    policy.set_mode("full")
    assert controller._checking_timer.isActive()

    controller._stop_check_animation()
    assert not controller._checking_timer.isActive()
    assert controller._checking_active is False


def test_update_check_starts_static_when_already_reduced(preserve_motion_policy) -> None:
    from app.update_controller import UpdateController

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")

    QApplication.instance() or QApplication([])
    host = _QtUpdateHost()
    controller = UpdateController(host, "0.1.1", "", "")

    controller._start_check_animation()

    assert not controller._checking_timer.isActive()
    assert host.check_update_button.text == "Checking for updates..."
