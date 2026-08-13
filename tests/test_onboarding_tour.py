"""The welcome tour moves the interface, never the user's light or settings."""

from __future__ import annotations

from copy import deepcopy

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRectF
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.main_layout import select_section
from app.main_window import MainWindow
from app.widgets.onboarding_overlay import OnboardingOverlay


@pytest.fixture()
def window():
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.resize(1280, 860)
    win.show()
    app.processEvents()
    try:
        yield win
    finally:
        overlay = getattr(win, "_onboarding_overlay", None)
        if overlay is not None:
            overlay.hide()
        win._ble.shutdown()
        win.close()
        app.processEvents()


@pytest.fixture()
def tour(window, preserve_motion_policy):
    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    QApplication.instance().processEvents()
    try:
        yield overlay
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_the_welcome_fits_the_minimum_window(window, tour) -> None:
    window.resize(860, 420)
    QApplication.instance().processEvents()

    panel = tour._panel.geometry()
    assert QRectF(tour.rect()).contains(QRectF(panel)), "the first dialog is clipped"
    assert panel.contains(tour._later_button.geometry().translated(tour._panel.pos()))
    assert panel.contains(tour._tour_button.geometry().translated(tour._panel.pos()))


def test_the_tour_reveals_real_sections_and_scrolls_to_diagnostics(window, tour) -> None:
    tour._begin_tour()
    QApplication.instance().processEvents()

    assert window._section_stack.currentWidget() is window._nav_pages["color"]
    assert tour._target is window.color_card
    assert not tour._spotlight_rect.isEmpty()

    tour._go_tour_step(6)
    QApplication.instance().processEvents()

    assert window._section_stack.currentWidget() is window._nav_pages["settings"]
    assert tour._target is window.diagnostics_card
    assert window.body_scroll.verticalScrollBar().value() > 0
    assert QRectF(tour.rect()).intersects(tour._spotlight_rect)


@pytest.mark.parametrize("size", ((1280, 860), (1600, 900)))
def test_the_diagnostics_step_remeasures_the_redesigned_card(window, tour, size) -> None:
    window.resize(*size)
    QApplication.instance().processEvents()
    tour._begin_tour()
    tour._go_tour_step(6)
    QApplication.instance().processEvents()

    target = window.diagnostics_card
    target_top = tour.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
    target_rect = QRectF(target_top.x(), target_top.y(), target.width(), target.height())
    viewport_top = tour.mapFromGlobal(window.body_scroll.viewport().mapToGlobal(QPoint(0, 0)))
    viewport = QRectF(
        viewport_top.x(),
        viewport_top.y(),
        window.body_scroll.viewport().width(),
        window.body_scroll.viewport().height(),
    )
    expected = (
        viewport.adjusted(10, 10, -10, -10)
        if target_rect.width() > viewport.width() or target_rect.height() > viewport.height()
        else target_rect
    )
    expected = expected.intersected(QRectF(tour.rect()).adjusted(6, 6, -6, -6))

    assert tour._spotlight_rect == expected, "the diagnostics redesign moved the blue frame off its target"


def test_the_spotlight_uses_the_real_card_coordinates_after_scrolling(window, tour) -> None:
    tour._begin_tour()
    tour._go_tour_step(2)
    QApplication.instance().processEvents()

    target = window.ambient_card
    top_left = tour.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
    expected = QRectF(top_left.x(), top_left.y(), target.width(), target.height())
    viewport_top = tour.mapFromGlobal(window.body_scroll.viewport().mapToGlobal(QPoint(0, 0)))
    viewport = QRectF(
        viewport_top.x(),
        viewport_top.y(),
        window.body_scroll.viewport().width(),
        window.body_scroll.viewport().height(),
    )
    expected = expected.intersected(viewport).intersected(QRectF(tour.rect()).adjusted(6, 6, -6, -6))

    assert tour._spotlight_rect == expected, "the blue outline drifted away from the real card"


@pytest.mark.parametrize(
    ("step", "target_name"),
    ((0, "color_card"), (1, "scenes_card"), (2, "ambient_card"), (3, "automations_rules_card")),
)
def test_the_first_four_steps_frame_the_whole_card(window, tour, step: int, target_name: str) -> None:
    tour._begin_tour()
    tour._go_tour_step(step)
    QApplication.instance().processEvents()

    target = getattr(window, target_name)
    top_left = tour.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
    assert tour._spotlight_rect == QRectF(top_left.x(), top_left.y(), target.width(), target.height())


def _expected_frame(tour, window, target) -> QRectF:
    """Where the frame belongs, by the widget's own documented rule.

    A card that fits is framed exactly. A card taller than the viewport cannot
    have its far edge shown, so the visible work area is framed instead — see
    ``_target_rect``. Which of the two applies depends on the window size and on
    how tall the card happens to be, so a test that always expects the card is a
    test about today's card rather than about remeasuring.
    """
    top_left = tour.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
    card = QRectF(top_left.x(), top_left.y(), target.width(), target.height())
    scroll = window.body_scroll
    view_top = tour.mapFromGlobal(scroll.viewport().mapToGlobal(QPoint(0, 0)))
    viewport = QRectF(
        view_top.x(), view_top.y(), scroll.viewport().width(), scroll.viewport().height()
    )
    if card.width() > viewport.width() or card.height() > viewport.height():
        return viewport.adjusted(10, 10, -10, -10)
    return card


@pytest.mark.parametrize(("step", "target_name"), ((0, "color_card"), (2, "ambient_card")))
def test_resizing_between_windowed_and_large_remeasures_the_card(
    window, tour, step: int, target_name: str
) -> None:
    tour._begin_tour()
    tour._go_tour_step(step)
    QApplication.instance().processEvents()

    seen = []
    for size in ((1600, 900), (1000, 700)):
        window.resize(*size)
        QTest.qWait(420)
        target = getattr(window, target_name)
        expected = _expected_frame(tour, window, target)
        assert tour._spotlight_rect == expected, "the frame kept geometry from the previous window size"
        seen.append(QRectF(tour._spotlight_rect))

    assert seen[0] != seen[1], "the frame never moved, so nothing was remeasured"


def test_reopened_guide_follows_the_card_while_the_live_preview_expands(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    select_section(window, "settings")
    window.body_scroll.verticalScrollBar().setValue(window.body_scroll.verticalScrollBar().maximum())
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()

    try:
        QTest.qWait(1500)
        target = window.color_card
        top_left = overlay.mapFromGlobal(target.mapToGlobal(QPoint(0, 0)))
        expected = QRectF(top_left.x(), top_left.y(), target.width(), target.height())
        assert overlay._spotlight_rect == expected, "the frame stayed above the card after leaving Settings"
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_a_tall_card_uses_one_closed_visible_frame_at_the_minimum_window(window, tour) -> None:
    window.resize(860, 420)
    QApplication.instance().processEvents()
    tour._begin_tour()
    QApplication.instance().processEvents()

    viewport_top = tour.mapFromGlobal(window.body_scroll.viewport().mapToGlobal(QPoint(0, 0)))
    viewport = QRectF(
        viewport_top.x(),
        viewport_top.y(),
        window.body_scroll.viewport().width(),
        window.body_scroll.viewport().height(),
    )
    assert viewport.contains(tour._spotlight_rect)
    assert tour._spotlight_rect == viewport.adjusted(10, 10, -10, -10)
    assert not hasattr(tour, "_spotlight_frame_rect"), "the frame and transparent hole diverged again"


def test_the_step_dots_do_not_run_under_the_next_button(window, tour) -> None:
    window.resize(860, 420)
    QApplication.instance().processEvents()
    tour._begin_tour()
    QApplication.instance().processEvents()

    dots_right = tour._dots.mapTo(tour._tip, QPoint(tour._dots.width(), 0)).x()
    next_left = tour._tip_next.mapTo(tour._tip, QPoint(0, 0)).x()
    assert next_left - dots_right >= 10


def test_programmatic_scrolling_moves_through_intermediate_frames(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()
    overlay._go_tour_step(6)
    QApplication.instance().processEvents()
    bar = window.body_scroll.verticalScrollBar()
    samples = [bar.value()]

    try:
        for _ in range(9):
            QTest.qWait(80)
            samples.append(bar.value())
        assert samples[-1] > samples[0]
        assert len(set(samples)) >= 5, "the page jumped to the target instead of scrolling smoothly"
        assert samples == sorted(samples), "the guided scroll moved backwards during the transition"
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_full_motion_fades_a_final_sized_frame_instead_of_cropping_the_target(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()

    try:
        QTest.qWait(700)
        assert overlay._spotlight_rect == overlay._raw_target_rect()
        assert overlay._spot_anim.propertyName() == b"spotlightAlpha"
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_autoplay_waits_until_the_visual_demo_finishes(window, preserve_motion_policy) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()
    QApplication.instance().processEvents()

    try:
        assert not overlay._autoplay_timer.isActive()
        QTest.qWait(2750)
        assert overlay._autoplay_timer.isActive()
        assert overlay._autoplay_timer.remainingTime() > 5000
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_the_colour_demo_emits_no_slider_signal_and_restores_every_value(window, tour) -> None:
    sliders = (
        window.red_slider,
        window.green_slider,
        window.blue_slider,
        window.brightness_slider,
    )
    original_values = tuple(slider.value() for slider in sliders)
    original_display_values = tuple(slider._display_value for slider in sliders)
    original_labels = tuple(
        widget.text()
        for widget in (window.red_value, window.green_value, window.blue_value, window.brightness_value)
    )
    original_preview = (QColor(window.preview._color), window.preview._brightness)
    emissions = [0]
    for slider in sliders:
        slider.valueChanged.connect(lambda _value: emissions.__setitem__(0, emissions[0] + 1))

    tour._begin_tour()
    QApplication.instance().processEvents()

    assert tuple(slider.value() for slider in sliders) != original_values
    assert tuple(slider._display_value for slider in sliders) != original_display_values
    assert emissions == [0], "the visual demo escaped QSignalBlocker and could reach BLE"

    tour._go_tour_step(1)
    QApplication.instance().processEvents()

    assert tuple(slider.value() for slider in sliders) == original_values
    assert tuple(slider._display_value for slider in sliders) == original_display_values
    assert tuple(
        widget.text()
        for widget in (window.red_value, window.green_value, window.blue_value, window.brightness_value)
    ) == original_labels
    assert window.preview._color == original_preview[0]
    assert window.preview._brightness == original_preview[1]


def test_the_colour_demo_visibly_moves_through_more_than_one_colour(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()
    QApplication.instance().processEvents()

    try:
        samples = []
        for _ in range(4):
            QTest.qWait(520)
            samples.append(
                tuple(
                    slider.value()
                    for slider in (
                        window.red_slider,
                        window.green_slider,
                        window.blue_slider,
                        window.brightness_slider,
                    )
                )
            )
            assert not overlay._spotlight_rect.isEmpty()
        assert len(set(samples)) >= 4, "the colour demonstration looked like one static frame"
        assert any(sample[2] > sample[0] for sample in samples[:3]), "the cool colour pass was lost"
        assert samples[-1][0] > samples[-1][1], "the final magenta pass was lost"
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_a_demo_scene_fades_in_without_becoming_a_saved_scene(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    before_settings = deepcopy(window._settings)
    before_ids = [tile.scene_id for tile in window.scenes_grid.tiles()]
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()
    overlay._go_tour_step(1)
    QApplication.instance().processEvents()

    try:
        for _ in range(30):
            if overlay._demo_saved.get("kind") == "scene":
                break
            QTest.qWait(20)
        assert overlay._demo_saved.get("kind") == "scene"
        tile = overlay._demo_saved["tile"]
        expanded = overlay._demo_saved["grid_height"]
        QTest.qWait(360)
        assert 0 < window.scenes_grid.maximumHeight() < expanded, "the new scene appeared in one hard cut"
        assert 0.0 < tile.graphicsEffect().opacity() < 1.0
        assert window._settings == before_settings

        overlay._go_tour_step(2)
        QTest.qWait(500)
        assert [item.scene_id for item in window.scenes_grid.tiles()] == before_ids
        assert window._settings == before_settings
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_screen_sync_gets_a_visual_preview_and_restores_it(window, tour) -> None:
    preview = window.ambient_preview
    original = (preview._raw, preview._color, window.ambient_status_label.text())

    tour._begin_tour()
    tour._go_tour_step(2)
    QApplication.instance().processEvents()

    assert preview._raw is not None
    assert preview._color is not None
    assert window._tr("onboarding.demo_sync") == window.ambient_status_label.text()

    tour._go_tour_step(3)
    QApplication.instance().processEvents()
    assert (preview._raw, preview._color, window.ambient_status_label.text()) == original


def test_screen_sync_animates_the_profile_and_both_controls_without_saving(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    profile = window.ambient_profile_segment
    sliders = (window.ambient_saturation_slider, window.ambient_smoothing_slider)
    original_profile = profile.current_key()
    original_values = tuple(slider.value() for slider in sliders)
    original_settings = deepcopy(window._settings)
    emissions = [0]
    for slider in sliders:
        slider.valueChanged.connect(lambda _value: emissions.__setitem__(0, emissions[0] + 1))
    profile.selected.connect(lambda _key: emissions.__setitem__(0, emissions[0] + 1))
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()
    overlay._go_tour_step(2)
    QApplication.instance().processEvents()

    try:
        for _ in range(40):
            if overlay._demo_saved.get("kind") == "sync":
                break
            QTest.qWait(20)
        assert overlay._demo_saved.get("kind") == "sync"
        QTest.qWait(1400)
        assert profile.current_key() != original_profile
        assert tuple(slider.value() for slider in sliders) != original_values
        assert emissions[0] == 0
        assert window._settings == original_settings

        overlay._go_tour_step(3)
        QTest.qWait(500)
        assert profile.current_key() == original_profile
        assert tuple(slider.value() for slider in sliders) == original_values
        assert window._settings == original_settings
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_the_rules_step_draws_a_demo_rule_without_saving_one(window, tour) -> None:
    before = window._automations.rules()

    tour._begin_tour()
    tour._go_tour_step(3)
    QApplication.instance().processEvents()

    assert tour._demo_saved["kind"] == "rule"
    assert window.automations_empty_hint.isVisible()
    assert window._tr("onboarding.demo_rule_title") in window.automations_empty_hint.text()
    assert window._tr("onboarding.demo_rule_on") in window.automations_empty_hint.text()
    assert window._automations.rules() == before
    target_top = tour.mapFromGlobal(window.automations_rules_card.mapToGlobal(QPoint(0, 0)))
    assert tour._spotlight_rect == QRectF(
        target_top.x(),
        target_top.y(),
        window.automations_rules_card.width(),
        window.automations_rules_card.height(),
    )


def test_the_demo_rule_expands_smoothly_and_the_frame_follows_it(
    window, preserve_motion_policy
) -> None:
    preserve_motion_policy.set_provider(None)
    preserve_motion_policy.set_mode("full")
    overlay = OnboardingOverlay(window._onboarding_labels(), window)
    overlay.sectionRequested.connect(lambda key: select_section(window, key))
    overlay.open()
    overlay._begin_tour()
    overlay._go_tour_step(3)
    QApplication.instance().processEvents()

    try:
        hint = window.automations_empty_hint
        for _ in range(30):
            if overlay._demo_saved.get("kind") == "rule":
                break
            QTest.qWait(20)
        assert overlay._demo_saved.get("kind") == "rule"
        expanded = overlay._demo_saved["expanded_height"]
        assert hint.maximumHeight() < expanded

        QTest.qWait(360)
        middle_height = hint.maximumHeight()
        assert 0 < middle_height < expanded, "the demo rule jumped directly to full height"
        top_left = overlay.mapFromGlobal(window.automations_rules_card.mapToGlobal(QPoint(0, 0)))
        assert overlay._spotlight_rect.bottom() == pytest.approx(
            top_left.y() + window.automations_rules_card.height()
        )

        QTest.qWait(1350)
        assert hint.maximumHeight() == expanded
        assert hint.graphicsEffect().opacity() == pytest.approx(1.0)
    finally:
        if overlay.isVisible():
            overlay._finish()
        QApplication.instance().processEvents()


def test_the_connection_demo_changes_no_real_connection_state(window, tour, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(window._ble, "scan", lambda: calls.append("scan"))
    monkeypatch.setattr(window._ble, "connect_to_address", lambda *_a, **_k: calls.append("connect"))
    before = (window._is_connected, window._connect_in_progress, list(window._devices))

    tour._begin_tour()
    original_status = window.device_status.text()
    original_hint = window.device_status_hint.text()
    original_dot = window.device_status_dot.styleSheet()
    tour._go_tour_step(5)
    QApplication.instance().processEvents()

    tour._apply_connection_demo(0.1)
    assert "#707783" in window.device_status_dot.styleSheet()
    assert window.device_status.text() == window._tr("onboarding.demo_status_disconnected")
    tour._apply_connection_demo(0.45)
    assert "#f5b94a" in window.device_status_dot.styleSheet()
    assert window.device_status.text() == window._tr("onboarding.demo_status_searching")
    tour._apply_connection_demo(1.0)

    assert (window._is_connected, window._connect_in_progress, window._devices) == before
    assert calls == []
    assert window.device_status.text() == window._tr("onboarding.demo_status_connected")
    assert window.device_status_hint.text() == window._tr("onboarding.demo_strip_name")
    assert window._tr("onboarding.demo_status_connected") in window.device_status.text()
    assert tour._target is window.device_status_card
    status_top = tour.mapFromGlobal(window.device_status_card.mapToGlobal(QPoint(0, 0)))
    assert tour._spotlight_rect == QRectF(
        status_top.x(),
        status_top.y(),
        window.device_status_card.width(),
        window.device_status_card.height(),
    )

    tour._go_tour_step(6)
    QApplication.instance().processEvents()
    assert window.device_status.text() == original_status
    assert window.device_status_hint.text() == original_hint
    assert window.device_status_dot.styleSheet() == original_dot


def test_manual_navigation_stops_autoplay_from_moving_under_the_user(window, tour) -> None:
    tour._begin_tour()
    QApplication.instance().processEvents()
    assert tour._autoplay is True

    tour._manual_next()
    QApplication.instance().processEvents()
    stopped_at = tour._tour_index
    tour._auto_next()
    QApplication.instance().processEvents()

    assert tour._autoplay is False
    assert tour._tour_index == stopped_at


def test_finishing_a_reopened_tour_restores_the_page_and_scroll(window, tour) -> None:
    select_section(window, "automations")
    window.body_scroll.verticalScrollBar().setValue(17)
    # The overlay captured Color at construction, so this test explicitly makes
    # the remembered destination the one a reopened About-tour would carry.
    tour._initial_section = "automations"
    tour._initial_scroll = 17
    tour._begin_tour()
    tour._go_tour_step(6)
    QApplication.instance().processEvents()

    tour._finish()
    QApplication.instance().processEvents()

    assert window._section_stack.currentWidget() is window._nav_pages["automations"]
    assert window.body_scroll.verticalScrollBar().value() == 17
