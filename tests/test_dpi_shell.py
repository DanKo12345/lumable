from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.main_layout import select_section
from app.main_window import MainWindow
from app.widgets.license_overlay import LicenseOverlay
from app.widgets.logs_overlay import LogsOverlay

_LICENSE_LABELS = {
    "title": "LumaBLE Pro",
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

        # No nav item is dropped — all eight remain children of the scrolled list
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
