from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.main_layout import select_section
from app.main_window import MainWindow
from app.widgets import LiquidButton
from app.widgets.license_overlay import LicenseOverlay
from app.widgets.logs_overlay import LogsOverlay

_LICENSE_LABELS = {
    "title": "LumaBLE Pro",
    "hero_title": "Разблокируйте все возможности",
    "subtitle": "Разблокируйте все возможности",
    "active_title": "Pro активен",
    "active_license": "Лицензия активна на этом ПК.",
    "active_dev": "Dev Pro активен.",
    "key_label": "Лицензионный ключ",
    "placeholder": "Вставьте ключ",
    "activate": "Активировать",
    "activating": "Проверка",
    "buy": "Купить LumaBLE Pro",
    "have_key": "У меня уже есть ключ",
    "back": "Назад",
    "ok": "ОК",
    "cancel": "Отмена",
    "close": "Закрыть",
    "invalid": "Неверный ключ",
    "activated": "Активировано",
    "buy_unavailable": "Страница покупки недоступна",
    "deactivate": "Деактивировать",
    "deactivate_confirm": "Точно деактивировать?",
    "deactivated": "Деактивировано",
    "feat_music": "Музыка",
    "feat_music_desc": "Свет под звук",
    "feat_screen": "Экран",
    "feat_screen_desc": "Синхронизация с экраном",
    "feat_diy": "DIY",
    "feat_diy_desc": "Свои эффекты",
    "feat_schedule": "Расписание",
    "feat_schedule_desc": "По времени",
    "feat_effects": "Эффекты",
    "feat_effects_desc": "Больше анимаций",
    "feat_profiles": "Профили",
    "feat_profiles_desc": "Наборы настроек",
}


def _settle_open_animation(overlay) -> None:
    """Drive an overlay's open animation straight to its end state.

    The panel slides in from a few pixels below where it comes to rest, so any
    geometry measured while it is still running sees a panel hanging past the
    window bottom. A fixed ``qWait`` only *probably* covers that: the confirm
    test waited 200ms for a 205ms animation and passed only because widgets left
    alive by earlier tests made ``processEvents()`` slow enough to cover the
    difference. Completing the animations removes the guesswork entirely.
    """
    app = QApplication.instance()
    # Some overlays kick the animation off from a zero-timer, so process events
    # first to let a deferred start fire, then complete whatever is running.
    for _ in range(3):
        app.processEvents()
        running = [
            anim
            for anim in overlay.findChildren(QAbstractAnimation)
            if anim.totalDuration() >= 0 and anim.state() == QAbstractAnimation.State.Running
        ]
        for anim in running:
            anim.setCurrentTime(anim.totalDuration())
        if running:
            app.processEvents()
            break


def _panel_fits(overlay, parent) -> bool:
    panel = overlay._panel
    top = panel.mapTo(parent, panel.rect().topLeft()).y()
    bottom = panel.mapTo(parent, panel.rect().bottomLeft()).y()
    return top >= 0 and bottom <= parent.height()


def _inside_panel(widget, panel) -> bool:
    bottom = widget.mapTo(panel, widget.rect().bottomLeft()).y()
    top = widget.mapTo(panel, widget.rect().topLeft()).y()
    return top >= 0 and bottom <= panel.height()


def test_dense_page_scrolls_at_the_minimum_window_size() -> None:
    """At the smallest window size the body must SCROLL, not compress: the
    vertical scrollbar has a positive range so the bottom row (the primary
    action) stays reachable."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        select_section(window, "color")
        app.processEvents()
        window.body_scroll.widget().adjustSize()
        app.processEvents()

        assert window.body_scroll.verticalScrollBar().maximum() > 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


_AUTOMATION_RULES = [
    {
        "id": "evening",
        "name": "Evening",
        "trigger": {"kind": "time", "time_at": "21:00", "days": [0, 1, 2, 3, 4, 5, 6]},
        "action": {"type": "set_power", "power": True, "target": "primary"},
        "execution": "background",
    },
    {
        "id": "weekend-night",
        "trigger": {"kind": "time", "time_at": "23:30", "days": [4, 5]},
        "action": {"type": "set_power", "power": False, "target": "primary"},
        "execution": "background",
    },
    {
        "id": "coding",
        "name": "Coding",
        "trigger": {"kind": "app_foreground", "app": "code.exe"},
        "action": {"type": "apply_scene", "scene_id": "scene-desk"},
    },
    {
        "id": "away",
        "trigger": {"kind": "no_input", "minutes": 20},
        "action": {"type": "set_power", "power": False, "target": "primary"},
        "enabled": False,
    },
    {
        "id": "fallback",
        "name": "Movie night",
        "trigger": {"kind": "always"},
        "action": {"type": "apply_scene", "scene_id": "scene-gone"},
    },
]


def _fill_automations(window) -> None:
    """The busiest honest state of the automations page.

    Five rules of four different kinds, a pause the machine has not been told about
    (which is the two-line one), and the 0.3.5 bridge card. Anything that fits this
    fits the page.
    """
    from app.automation.runtime import PAUSE_PENDING
    from app.automation.windows_tasks import TaskSyncResult

    window._settings["automations"] = {
        "enabled": True,
        "rules": _AUTOMATION_RULES,
        "legacy_bridge": True,
    }
    window._settings["scenes"] = [
        {"scene_id": "scene-desk", "name": "Warm desk", "state": {"rgb": [255, 170, 90]}}
    ]
    controller = window._automations
    controller.is_running = lambda: True
    controller.pause_status = lambda: PAUSE_PENDING
    controller.paused_until = lambda: None
    controller._last_task_result = TaskSyncResult(unchanged=("evening", "weekend-night"))
    controller.journal = lambda limit=100: _automation_journal()[:limit]
    window._automation_ui.sync_controls()


def _automation_journal() -> list:
    """A few entries covering all four outcomes, so the history card has rows."""
    from datetime import datetime, timedelta

    from app.automation.journal import (
        KIND_CANCELLED,
        KIND_ERROR,
        KIND_SKIPPED,
        KIND_SUCCESS,
        JournalEntry,
    )

    now = datetime.now()
    kinds = (
        (KIND_SUCCESS, "coding", "scene_applied", "", 1),
        (KIND_SKIPPED, "evening", "", "disconnected", 6),
        (KIND_ERROR, "weekend-night", "execution_timeout", "", 1),
        (KIND_CANCELLED, "fallback", "execution_cancelled", "", 1),
    )
    return [
        JournalEntry(
            id=index,
            kind=kind,
            rule_id=rule_id,
            message_code=code,
            reason=reason,
            count=count,
            first_seen=now - timedelta(minutes=index * 30),
            last_seen=now - timedelta(minutes=index * 30),
            uid=f"entry-{index}",
        )
        for index, (kind, rule_id, code, reason, count) in enumerate(kinds)
    ]


def _fits_horizontally(widget, parent) -> bool:
    left = widget.mapTo(parent, widget.rect().topLeft()).x()
    right = widget.mapTo(parent, widget.rect().topRight()).x()
    return left >= 0 and right <= parent.width()


def _automation_page_is_intact(window) -> None:
    """Every card fits the page's width, and no row's control is cut off.

    Width is the axis that has no escape hatch: the page scrolls vertically, so a
    tall page is fine, but a card wider than the canvas takes its right-hand column —
    which is where every toggle on this screen lives — off the edge.
    """
    canvas = window.body_scroll.widget()
    page = window._nav_pages["automations"]
    cards = (
        window.automations_card,
        window.automations_rules_card,
        window.automations_journal_card,
        window.automations_bridge_card,
    )
    for card in cards:
        assert card.isVisibleTo(page), "a card on the automations page is hidden"
        assert _fits_horizontally(card, canvas), "a card is wider than the page"

    for button in (
        window.automations_toggle_button,
        window.automations_pause_button,
        window.automations_bridge_button,
    ):
        assert _fits_horizontally(button, canvas), "a control fell off the page"

    # Each rule's own toggle stays inside its row, and the generated detail line is
    # given the height it needs rather than being clipped to one line.
    for row in window._automation_ui._rows:
        toggle = row.findChildren(LiquidButton)[0]
        assert _fits_horizontally(toggle, row), "a rule's toggle is outside its row"

    status = window.automations_pause_status
    assert "\n" in status.text(), "this check wants the two-line pause state"
    assert status.heightForWidth(status.width()) <= status.height(), "the pause caveat is clipped"


def test_the_automations_page_scrolls_instead_of_clipping_at_the_minimum_window() -> None:
    """Five rules, a two-line pause row and the bridge card are together taller than a
    860×420 window. That has to scroll: the bridge card carries an irreversible action
    and a rule's toggle is its only switch, so neither may be cut off the bottom."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        select_section(window, "automations")
        _fill_automations(window)
        app.processEvents()
        window.body_scroll.widget().adjustSize()
        app.processEvents()

        assert window.body_scroll.verticalScrollBar().maximum() > 0, "the page did not scroll"
        assert window.body_scroll.horizontalScrollBar().maximum() == 0, "the page scrolls sideways"
        _automation_page_is_intact(window)
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_the_rule_editor_fits_and_scrolls_at_the_minimum_window() -> None:
    """The form is taller than a 860×420 window. Header and footer stay put while the
    fields scroll: the two things that may never be off-screen are the reason a rule
    cannot be saved and the button that saves it."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        select_section(window, "automations")
        _fill_automations(window)
        app.processEvents()

        window.automations_add_button.click()
        editor = window._automation_ui._editor
        assert editor is not None
        _settle_open_animation(editor)
        app.processEvents()

        panel = editor._panel
        assert panel.mapTo(window, panel.rect().topLeft()).y() >= 0
        assert panel.mapTo(window, panel.rect().bottomLeft()).y() <= window.height()
        # Pinned: the title, the problem line, and every footer button.
        for widget in (
            editor._close_button,
            editor.problem_label,
            editor.cancel_button,
            editor.save_button,
        ):
            assert _inside_panel(widget, panel), f"{widget.objectName()} fell outside the panel"
        # And the fields give up the height instead, by scrolling.
        assert editor._scroll.verticalScrollBar().maximum() > 0
        # Seven day chips plus the label column have to fit the content width with
        # that scrollbar showing — otherwise Sunday sits underneath it.
        viewport = editor._scroll.viewport()
        for chip in editor.day_buttons:
            assert _fits_horizontally(chip, viewport), "a day chip is under the scrollbar"

        # Growing the window gives the panel its full height back.
        window.resize(1280, 860)
        editor._fit_to_parent()
        app.processEvents()
        from app.widgets.rule_editor_overlay import PANEL_MAX_H

        assert panel.maximumHeight() == PANEL_MAX_H
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_the_current_nav_item_is_scrolled_into_view() -> None:
    """On a short window the rail scrolls, and a section can be opened from something
    other than its own button — restoring the last section on start-up, or the status
    card jumping to Settings. The highlight would then sit outside the visible part of
    the list, so the page said one thing and the sidebar showed another."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        window._apply_compact_sidebar()
        app.processEvents()
        rail = window.nav_scroll
        assert rail.verticalScrollBar().maximum() > 0, "this check needs a rail that scrolls"

        # The last item in the list is the one the rail has to move for.
        last_key = list(window._nav_buttons)[-1]
        select_section(window, last_key)
        # The reveal is deferred by a zero timer: on the first pass the rail has not
        # been laid out, so scrolling immediately would move nothing.
        app.processEvents()
        app.processEvents()

        button = window._nav_buttons[last_key]
        viewport = rail.viewport()
        top = button.mapTo(viewport, button.rect().topLeft()).y()
        bottom = button.mapTo(viewport, button.rect().bottomLeft()).y()
        assert top >= 0, "the current nav item is above the visible part of the rail"
        assert bottom <= viewport.height(), "the current nav item is below it"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_the_automations_page_stays_intact_at_a_normal_window_size() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        # The size the committed snapshot in docs/screenshots was taken at, so the
        # picture and this check describe the same layout.
        window.resize(1280, 860)
        select_section(window, "automations")
        _fill_automations(window)
        app.processEvents()
        window.body_scroll.widget().adjustSize()
        app.processEvents()

        assert window.body_scroll.horizontalScrollBar().maximum() == 0
        _automation_page_is_intact(window)
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_sidebar_compacts_at_minimum_height() -> None:
    """At the minimum window height the sidebar keeps the primary connection
    status and all nav items, but deliberately hides the secondary hint so the
    footer doesn't clip off the bottom of the rail."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        # Show (offscreen) so QMainWindow actually constrains its central widget
        # to the window height — otherwise child geometry reflects the unbounded
        # size hint and the containment checks below are meaningless.
        window.show()
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        window._apply_compact_sidebar()
        app.processEvents()

        # Primary status stays; every nav item stays reachable (via the nav
        # scroll); secondary hint is intentionally dropped in the compact sidebar.
        assert window.device_status.isVisibleTo(window)
        assert window._sidebar_compact is True
        assert not window.device_status_hint.isVisibleTo(window)

        # Prove no physical clip (not just the absence of hide()): the nav scroll
        # area and the status card sit fully inside the window, and the primary
        # status sits fully inside its card.
        def _contained_vertically(widget, parent) -> bool:
            top = widget.mapTo(parent, widget.rect().topLeft()).y()
            bottom = widget.mapTo(parent, widget.rect().bottomLeft()).y()
            return 0 <= top and bottom <= parent.height()

        assert _contained_vertically(window.nav_scroll, window)
        assert _contained_vertically(window.device_status_card, window)
        assert _contained_vertically(window.device_status, window.device_status_card)

        # No nav item is dropped — every one remains a child of the scrolled list
        # and thus reachable, even when the list is taller than its viewport.
        nav_list = window.nav_scroll.widget()
        for button in window._nav_buttons.values():
            assert button.parentWidget() is nav_list
        if window.nav_scroll.widget().height() > window.nav_scroll.viewport().height():
            assert window.nav_scroll.verticalScrollBar().maximum() > 0

        # Growing the window back restores the hint (it was wanted).
        window.resize(1320, 860)
        window._apply_compact_sidebar()
        app.processEvents()
        assert window._sidebar_compact is False
        assert window.device_status_hint.isVisibleTo(window)
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_logs_overlay_panel_fits_the_minimum_window() -> None:
    """The logs panel must fit a 860×420 window so its close button (bottom of
    the panel) never falls off-screen — the log scrolls inside instead."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        app.processEvents()

        labels = {"title": "Логи", "subtitle": "события", "empty": "пусто", "close": "Закрыть"}
        overlay = LogsOverlay(labels, "line\n" * 400, window)
        overlay.open()
        _settle_open_animation(overlay)

        panel = overlay._panel
        top = panel.mapTo(window, panel.rect().topLeft()).y()
        bottom = panel.mapTo(window, panel.rect().bottomLeft()).y()
        assert top >= 0
        assert bottom <= window.height()
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_about_overlay_panel_fits_and_scrolls_at_minimum_window() -> None:
    """About panel fits 860×420 with header/footer pinned and the middle
    scrolling; both footer buttons stay inside the panel; growing the window
    restores the normal max height."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        app.processEvents()

        window._show_about_overlay()
        overlay = window._overlay_controller._about_overlay
        overlay._fit_to_parent()
        _settle_open_animation(overlay)

        panel = overlay._panel
        assert panel.mapTo(window, panel.rect().topLeft()).y() >= 0
        assert panel.mapTo(window, panel.rect().bottomLeft()).y() <= window.height()

        # Both footer buttons stay inside the panel (not clipped by its bottom).
        for button in (overlay._guide_button, overlay._ok_button):
            assert button.mapTo(panel, button.rect().bottomLeft()).y() <= panel.height()

        # The middle content scrolls (the supported-controllers list is long).
        assert overlay._scroll.verticalScrollBar().maximum() > 0

        # Growing the window restores the normal max height.
        window.resize(1320, 860)
        overlay._fit_to_parent()
        app.processEvents()
        assert overlay._panel.maximumHeight() == 620
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


# --- Pro (License) overlay: three states must fit a 860×420 window ------------


def _open_license(parent, app, **kwargs) -> LicenseOverlay:
    overlay = LicenseOverlay(_LICENSE_LABELS, lambda _key: (False, "Invalid"), parent, **kwargs)
    overlay.open()
    _settle_open_animation(overlay)
    return overlay


def test_license_free_overlay_fits_and_scrolls_at_minimum_window() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    overlay = _open_license(parent, app, buy_callback=lambda: False)
    try:
        assert _panel_fits(overlay, parent)
        # Pinned CTA and close stay inside the panel; the benefits scroll.
        assert _inside_panel(overlay.buy_button, overlay._panel)
        assert _inside_panel(overlay._close_button, overlay._panel)
        assert overlay._scroll.verticalScrollBar().maximum() > 0
        assert overlay._hero_title is not None
        assert overlay.buy_button.width() == 400
        assert overlay.buy_button.height() == 52
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_active_overlay_fits_at_minimum_window() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    overlay = _open_license(parent, app, mode="dev")
    try:
        assert _panel_fits(overlay, parent)
        assert _inside_panel(overlay._cancel_button, overlay._panel)  # the OK button
        assert _inside_panel(overlay._close_button, overlay._panel)
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_revealed_key_fits_and_field_is_reachable() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    overlay = _open_license(parent, app, buy_callback=lambda: False)
    try:
        overlay._reveal_key()
        QTest.qWait(320)  # height animation + deferred ensureWidgetVisible
        assert _panel_fits(overlay, parent)
        # Back / Activate stay pinned inside the panel...
        assert _inside_panel(overlay._back_button, overlay._panel)
        assert _inside_panel(overlay._activate_button, overlay._panel)
        # ...and the key field was scrolled into the visible panel area.
        assert _inside_panel(overlay.key_input, overlay._panel)
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_key_field_is_centred_in_the_available_space() -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1280, 860)
    parent.show()
    overlay = _open_license(parent, app, buy_callback=lambda: False)
    try:
        overlay._reveal_key()
        QTest.qWait(320)
        viewport = overlay._scroll.viewport()
        assert overlay._features_grid is not None
        features_bottom = overlay._features_grid.mapTo(
            viewport,
            QPoint(0, overlay._features_grid.height()),
        ).y()
        field_top = overlay._field_box.mapTo(viewport, QPoint()).y()
        field_bottom = overlay._field_box.mapTo(
            viewport,
            QPoint(0, overlay._field_box.height()),
        ).y()
        gap_above = field_top - features_bottom
        gap_below = viewport.height() - field_bottom
        assert abs(gap_above - gap_below) < 20
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_panel_restores_height_when_window_grows() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    overlay = _open_license(parent, app, buy_callback=lambda: False)
    try:
        assert overlay._panel.maximumHeight() < overlay._preferred_height()
        parent.resize(1320, 860)
        overlay._fit_to_parent()
        app.processEvents()
        assert overlay._panel.maximumHeight() == overlay._preferred_height()
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_close_is_guarded_while_activation_worker_runs() -> None:
    import threading

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()

    release = threading.Event()

    def blocking_activate(_key):
        release.wait(2.0)
        return False, "Invalid"

    overlay = LicenseOverlay(_LICENSE_LABELS, blocking_activate, parent, buy_callback=lambda: False)
    overlay.open()
    QTest.qWait(50)
    try:
        overlay._reveal_key()
        overlay.key_input.setText("SOME-KEY")
        overlay._activate()
        QTest.qWait(30)
        worker = overlay._activate_worker
        assert worker is not None and worker.isRunning()

        # While a key check is in flight the footer actions are disabled...
        assert overlay._activate_button.isEnabled() is False
        assert overlay._back_button.isEnabled() is False

        # ...so × (close), Esc, Back and Activate must all be no-ops: no teardown
        # of the live thread, no footer state change, and no second worker.
        overlay.close_overlay()
        overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        overlay._back_button.click()
        overlay._activate_button.click()
        overlay._activate()  # a direct re-entry must also refuse

        assert overlay._activate_worker is worker  # same single worker, no new one
        assert worker.isRunning()
        assert not overlay.isHidden()
        assert overlay._key_revealed is True  # footer stayed on the key screen
    finally:
        release.set()
        QTest.qWait(200)
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_confirm_overlay_grows_for_a_long_name_and_fits_window() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.profile_action_overlay import ProfileConfirmOverlay

    long_name = "Гостиная — светодиодная лента за телевизором с очень длинным названием ELK-BLEDOM 8E"
    labels = {
        "title": "Удалить профиль?",
        "message": f"Профиль «{long_name}» будет удалён без возможности восстановления. "
        "Это действие нельзя отменить.",
        "cancel": "Отмена",
        "confirm": "Удалить профиль",
    }
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    overlay = ProfileConfirmOverlay(
        labels, parent, confirm_role="danger", toggle_label="Оставить ленту подключённой", toggle_checked=True
    )
    overlay.open()
    _settle_open_animation(overlay)
    try:
        # The long name grew the message beyond its floor (not clipped in the box)...
        assert overlay._message_label.minimumHeight() > 58
        # ...and the panel, danger CTA and toggle still fit the window.
        assert _panel_fits(overlay, parent)
        assert _inside_panel(overlay._confirm_button, overlay._panel)
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_color_picker_fits_and_scrolls_at_minimum_window() -> None:
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.color_picker_overlay import PANEL_HEIGHT_WITH_HISTORY, ColorPickerOverlay

    labels = {
        "hex": "HEX", "red": "Красный", "green": "Зелёный", "blue": "Синий",
        "recent": "Недавние", "cancel": "Отмена", "ok": "ОК",
    }
    history = [{"r": 255, "g": 0, "b": 0}, {"r": 0, "g": 255, "b": 0}, {"r": 0, "g": 0, "b": 255}]
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    picker = ColorPickerOverlay("Выбор цвета", QColor(120, 80, 200), labels, history, parent)
    picker.open()
    _settle_open_animation(picker)
    try:
        # Panel fits; pinned OK/Cancel stay inside it; the middle controls scroll.
        assert _panel_fits(picker, parent)
        assert _inside_panel(picker._ok_button, picker._panel)
        assert _inside_panel(picker._cancel_button, picker._panel)
        assert picker._scroll.verticalScrollBar().maximum() > 0
        # The colour plane keeps its full precision height.
        assert picker.color_plane.height() == 145
        # Growing the window restores the preferred (with-history) height.
        parent.resize(1320, 860)
        picker._fit_to_parent()
        app.processEvents()
        assert picker._panel.maximumHeight() == PANEL_HEIGHT_WITH_HISTORY
    finally:
        picker.reject()
        parent.deleteLater()
        app.processEvents()


def test_confirm_overlay_scrolls_overlong_message_and_recomputes_on_resize() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.profile_action_overlay import ProfileConfirmOverlay

    # Long enough that it overflows the tiny window by a wide margin, yet still
    # fits a deliberately tall window — so the fit/overflow verdict can never be
    # borderline (font metrics vary a little with theme/language left by earlier
    # tests, which must not flip this result).
    huge = "Очень длинное имя профиля пользователя " * 30
    labels = {
        "title": "Удалить профиль?",
        "message": f"Профиль «{huge}» будет удалён навсегда.",
        "cancel": "Отмена",
        "confirm": "Удалить",
    }
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1320, 1400)  # start large enough that the whole message fits
    parent.show()
    overlay = ProfileConfirmOverlay(labels, parent, confirm_role="danger")
    overlay.open()
    _settle_open_animation(overlay)
    scrollbar = overlay._message_scroll.verticalScrollBar()
    try:
        # Large window: the whole message fits, no scrollbar.
        assert scrollbar.maximum() == 0

        # Shrink to the minimum: the message scrolls (not clipped) and the panel
        # + danger CTA still fit the window. The overlay's resizeEvent re-fits the
        # message; the base eventFilter drives this from the parent on a real
        # window, which we emulate deterministically with setGeometry here.
        parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        overlay.setGeometry(parent.rect())
        app.processEvents()
        assert scrollbar.maximum() > 0
        assert _panel_fits(overlay, parent)
        assert _inside_panel(overlay._confirm_button, overlay._panel)

        # Grow again: the scrollbar disappears — the message is shown in full.
        parent.resize(1320, 1400)
        overlay.setGeometry(parent.rect())
        app.processEvents()
        assert scrollbar.maximum() == 0
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_short_confirm_message_is_centred_between_title_and_actions() -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.profile_action_overlay import ProfileConfirmOverlay

    labels = {
        "title": "Удалить сцену",
        "message": "Сцена «hhh» будет удалена.",
        "cancel": "Отмена",
        "confirm": "Удалить",
    }
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
    parent.show()
    overlay = ProfileConfirmOverlay(labels, parent, confirm_role="danger")
    overlay.open()
    _settle_open_animation(overlay)
    try:
        title_bottom = overlay._title_label.mapTo(
            overlay._panel,
            QPoint(0, overlay._title_label.height()),
        ).y()
        message_top = overlay._message_scroll.mapTo(overlay._panel, QPoint()).y()
        message_bottom = overlay._message_scroll.mapTo(
            overlay._panel,
            QPoint(0, overlay._message_scroll.height()),
        ).y()
        actions_top = overlay._cancel_button.mapTo(overlay._panel, QPoint()).y()
        assert abs((message_top - title_bottom) - (actions_top - message_bottom)) < 6
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()
