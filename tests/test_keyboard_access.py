"""Keyboard and accessibility guarantees for the main shell.

Everything the mouse can reach must be reachable from the keyboard, and a screen
reader must be able to name it. These tests drive real key events rather than
calling the handlers directly, so they fail if focus policy or event routing
regresses.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
from app.feature_gate import invalidate_pro_cache
from app.main_layout import select_section
from app.main_window import MainWindow
from app.widgets.value_chip import ValueChip


def _auto_repeat(key) -> QKeyEvent:
    """A key press flagged as an auto-repeat, which QTest never produces."""
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.NoModifier, "", True)


def _wheel(widget, delta: int = -120) -> None:
    """Send a wheel event to a widget's centre, as the mouse would."""
    centre = widget.rect().center()
    event = QWheelEvent(
        QPoint(centre.x(), centre.y()),
        widget.mapToGlobal(centre),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.instance().sendEvent(widget, event)


def test_wheel_over_the_sidebar_leaves_the_body_scroll_alone() -> None:
    """Scrolling the nav rail must not drag the content page with it."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        window.show()
        select_section(window, "color")
        app.processEvents()

        body_bar = window.body_scroll.verticalScrollBar()
        body_bar.setValue(0)
        app.processEvents()

        _wheel(window.nav_scroll.viewport())
        app.processEvents()

        assert body_bar.value() == 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_focusing_a_control_below_the_fold_scrolls_it_into_view() -> None:
    """Tabbing to an off-screen control must bring it into view, otherwise the
    focus ring lands somewhere the user cannot see."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        window.show()
        select_section(window, "color")
        app.processEvents()

        body = window.body_scroll
        bar = body.verticalScrollBar()
        assert bar.maximum() > 0, "the page must actually be scrollable for this test"
        bar.setValue(0)
        app.processEvents()

        # Find a focusable control that currently sits below the visible area.
        target = None
        for child in body.widget().findChildren(object):
            if not hasattr(child, "focusPolicy") or child.focusPolicy() == Qt.NoFocus:
                continue
            if not child.isVisible():
                continue
            top = child.mapTo(body.widget(), child.rect().topLeft()).y()
            if top > bar.value() + body.viewport().height():
                target = child
                break
        assert target is not None, "expected at least one focusable control below the fold"

        target.setFocus(Qt.TabFocusReason)
        app.processEvents()

        visible_top = bar.value()
        visible_bottom = visible_top + body.viewport().height()
        focus_top = target.mapTo(body.widget(), target.rect().topLeft()).y()
        focus_bottom = target.mapTo(body.widget(), target.rect().bottomLeft()).y()
        # Both edges: a control whose top is on screen but whose bottom is cut
        # off is still not usable, and checking only the top would pass it.
        assert visible_top <= focus_top
        assert focus_bottom <= visible_bottom
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_focus_follow_is_only_subscribed_while_the_window_is_visible() -> None:
    """``focusChanged`` belongs to the QApplication, so a window that stays
    subscribed after it is gone keeps handling focus for the whole process."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        assert window._focus_follow_wired is True

        window.hide()
        app.processEvents()
        assert window._focus_follow_wired is False

        # Re-showing re-subscribes exactly once; the guard must make repeated
        # calls harmless rather than stacking or raising on disconnect.
        window.show()
        window._set_focus_follow(True)
        assert window._focus_follow_wired is True
        window.hide()
        window._set_focus_follow(False)
        assert window._focus_follow_wired is False
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_day_toggle_activates_from_the_keyboard() -> None:
    """The weekday chips are a custom QWidget, so Space/Enter have to be wired
    explicitly -- a mouse-only toggle makes the schedule unusable without one."""
    from app.widgets.day_toggle import DayToggle

    QApplication.instance() or QApplication([])
    toggle = DayToggle("Mon", lambda: {})
    try:
        assert toggle.focusPolicy() != Qt.NoFocus, "chip cannot receive keyboard focus"

        clicks: list[int] = []
        toggle.clicked.connect(lambda: clicks.append(1))
        toggle.show()
        toggle.setFocus()

        QTest.keyClick(toggle, Qt.Key_Space)
        assert clicks == [1]

        QTest.keyClick(toggle, Qt.Key_Return)
        assert clicks == [1, 1]
    finally:
        toggle.close()


def test_day_toggle_reports_its_state_to_assistive_tools() -> None:
    """A screen reader must be able to tell that the chip is a checkable control
    and whether it is currently on — a name alone does not convey that."""
    from PySide6.QtGui import QAccessible

    from app.widgets.day_toggle import DayToggle

    QApplication.instance() or QApplication([])
    toggle = DayToggle("Mon", lambda: {})
    try:
        toggle.show()
        interface = QAccessible.queryAccessibleInterface(toggle)
        assert interface is not None

        assert interface.text(QAccessible.Text.Name) == "Mon"
        assert interface.state().checkable
        assert not interface.state().checked

        toggle.setChecked(True)
        assert QAccessible.queryAccessibleInterface(toggle).state().checked

        toggle.setText("Tue")
        assert QAccessible.queryAccessibleInterface(toggle).text(QAccessible.Text.Name) == "Tue"
    finally:
        toggle.close()


def test_value_chip_is_a_button_that_names_what_it_shows() -> None:
    """The readout opens a value editor, so it must report itself as a button —
    as a styled QLabel it announced itself as static text — and its name has to
    carry the purpose, because "50%" alone means nothing read out of context."""
    from PySide6.QtGui import QAccessible

    from app.widgets.value_chip import ValueChip

    QApplication.instance() or QApplication([])
    chip = ValueChip("50%")
    try:
        chip.set_purpose("Brightness")
        chip.show()

        interface = QAccessible.queryAccessibleInterface(chip)
        assert interface is not None
        assert interface.role() == QAccessible.Role.Button
        assert interface.text(QAccessible.Text.Name) == "Brightness: 50%"

        chip.setText("70%")
        assert QAccessible.queryAccessibleInterface(chip).text(QAccessible.Text.Name) == "Brightness: 70%"
    finally:
        chip.close()


def test_value_chip_activates_once_per_key_press() -> None:
    from app.widgets.value_chip import ValueChip

    QApplication.instance() or QApplication([])
    chip = ValueChip("50%")
    try:
        clicks: list[int] = []
        chip.clicked.connect(lambda: clicks.append(1))
        chip.show()
        chip.setFocus()

        QTest.keyClick(chip, Qt.Key_Space)
        QTest.keyClick(chip, Qt.Key_Return)
        assert clicks == [1, 1]

        # Holding the key must not open the editor over and over. QTest.keyPress
        # always sends a fresh press, so an auto-repeat has to be built by hand.
        before = len(clicks)
        for _ in range(3):
            QApplication.instance().sendEvent(chip, _auto_repeat(Qt.Key_Return))
        assert len(clicks) == before, "auto-repeat must not re-activate the chip"
    finally:
        chip.close()


def test_scene_tile_is_a_checkable_button_naming_its_scene() -> None:
    from PySide6.QtGui import QAccessible

    from app.widgets.scene_tile_grid import SceneTile, SceneTileData

    QApplication.instance() or QApplication([])
    data = SceneTileData(scene_id="s1", name="Evening", color="#ff8800", target_label="Desk")
    tile = SceneTile(data, 1.0)
    try:
        tile.show()
        interface = QAccessible.queryAccessibleInterface(tile)
        assert interface is not None
        # RadioButton, not CheckBox: exactly one scene is live, so "one of a set"
        # is what a screen reader should hear.
        assert interface.role() == QAccessible.Role.RadioButton
        assert interface.text(QAccessible.Text.Name) == "Evening — Desk"
        assert interface.state().checkable
        assert not interface.state().checked

        tile.set_active(True)
        assert QAccessible.queryAccessibleInterface(tile).state().checked
    finally:
        tile.close()


def test_scene_tile_does_not_mark_itself_active_on_activation() -> None:
    """Applying a scene can fail or be superseded, so the tile must stay
    unmarked until the controller confirms the scene is actually in use."""
    from app.widgets.scene_tile_grid import SceneTile, SceneTileData

    QApplication.instance() or QApplication([])
    data = SceneTileData(scene_id="s1", name="Evening", color="#ff8800", target_label="Desk")
    tile = SceneTile(data, 1.0)
    try:
        applied: list[int] = []
        tile.clicked.connect(lambda: applied.append(1))
        tile.show()
        tile.setFocus()

        QTest.keyClick(tile, Qt.Key_Space)
        assert applied == [1]
        assert tile.is_active() is False  # not highlighted by the click itself

        tile.set_active(True)  # the controller confirms it
        assert tile.is_active() is True
    finally:
        tile.close()


def _scene_grid(app, count: int, width: int):
    """A shown grid of `count` scenes, sized so it lays out in two columns."""
    from app.widgets.scene_tile_grid import SceneTileData, SceneTileGrid

    grid = SceneTileGrid(1.0)
    grid.resize(width, 400)
    grid.set_scenes(
        [
            SceneTileData(scene_id=f"s{i}", name=f"Scene {i}", color="#ff8800", target_label="Desk")
            for i in range(count)
        ],
        active_id="s0",
    )
    grid.show()
    grid.activateWindow()
    app.processEvents()
    return grid


def test_arrow_keys_move_focus_between_scene_tiles() -> None:
    """Arrowing must land on the neighbouring tile.

    Two separate traps: an auto-exclusive button answers arrows by *clicking*
    its neighbour, and focusNextPrevChild() treats the whole radio group as one
    tab stop, so it jumps to whatever button follows the grid instead.
    """
    app = QApplication.instance() or QApplication([])
    grid = _scene_grid(app, count=4, width=400)
    try:
        assert grid._columns == 2, "this test needs a two-column layout"
        tiles = grid.tiles()

        tiles[0].setFocus()
        app.processEvents()
        assert QApplication.focusWidget() is tiles[0]

        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Right)
        assert QApplication.focusWidget() is tiles[1]

        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)
        assert QApplication.focusWidget() is tiles[3]  # one row down, same column

        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Left)
        assert QApplication.focusWidget() is tiles[2]

        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Up)
        assert QApplication.focusWidget() is tiles[0]
    finally:
        grid.close()


def test_arrow_keys_wrap_at_the_edges_instead_of_leaving_the_grid() -> None:
    app = QApplication.instance() or QApplication([])
    grid = _scene_grid(app, count=4, width=400)
    try:
        tiles = grid.tiles()

        tiles[0].setFocus()
        app.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Left)
        assert QApplication.focusWidget() is tiles[3], "focus escaped past the first tile"

        tiles[3].setFocus()
        app.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Right)
        assert QApplication.focusWidget() is tiles[0], "focus escaped past the last tile"

        tiles[3].setFocus()
        app.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)
        assert QApplication.focusWidget() is tiles[1], "focus escaped past the last row"
    finally:
        grid.close()


def test_vertical_arrows_stay_in_their_column_when_the_last_row_is_short() -> None:
    """5 tiles in 2 columns leaves a half-empty last row.

    Stepping a flat ±columns would silently change column there: Up from tile 0
    would land on tile 3, i.e. in the other column.
    """
    app = QApplication.instance() or QApplication([])
    grid = _scene_grid(app, count=5, width=400)
    try:
        assert grid._columns == 2
        tiles = grid.tiles()  # column 0 = 0, 2, 4;  column 1 = 1, 3

        tiles[0].setFocus()
        app.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Up)
        assert QApplication.focusWidget() is tiles[4], "wrapped into the wrong column"

        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)
        assert QApplication.focusWidget() is tiles[0]

        tiles[3].setFocus()
        app.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)
        assert QApplication.focusWidget() is tiles[1], "the short column must wrap within itself"
    finally:
        grid.close()


def test_arrowing_between_scene_tiles_does_not_apply_them() -> None:
    app = QApplication.instance() or QApplication([])
    grid = _scene_grid(app, count=4, width=400)
    try:
        applied: list[str] = []
        grid.scene_activated.connect(applied.append)
        tiles = grid.tiles()

        tiles[0].setFocus()
        app.processEvents()
        for key in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Left, Qt.Key_Up):
            QTest.keyClick(QApplication.focusWidget(), key)

        assert applied == [], "arrowing must not apply a scene"
        # The marker stays where the controller put it, wherever focus went.
        assert [tile.is_active() for tile in tiles] == [True, False, False, False]
    finally:
        grid.close()


def test_scene_tile_opens_its_menu_from_the_keyboard() -> None:
    """The "…" menu is a mouse zone; without a keyboard route to it, deleting a
    scene would be mouse-only."""
    from app.widgets.scene_tile_grid import SceneTile, SceneTileData

    app = QApplication.instance() or QApplication([])
    data = SceneTileData(scene_id="s1", name="Evening", color="#ff8800", target_label="Desk")
    tile = SceneTile(data, 1.0)
    try:
        requests: list[object] = []
        tile.menu_requested.connect(lambda pos: requests.append(pos))
        tile.show()
        tile.setFocus()

        QTest.keyClick(tile, Qt.Key_Menu)
        app.processEvents()
        assert len(requests) == 1, "the context-menu key must open the tile menu"

        QTest.keyClick(tile, Qt.Key_F10, Qt.ShiftModifier)
        app.processEvents()
        assert len(requests) == 2, "Shift+F10 must open the tile menu"
    finally:
        tile.close()


def test_clicking_an_rgb_readout_edits_that_slider() -> None:
    """``clicked`` carries a bool. If it lands in a lambda's captured default the
    handler silently receives False instead of the widget it was bound to, and
    the wrong thing — or nothing — gets edited."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        edits: list[tuple] = []
        window._edit_slider_value = lambda slider, chip, **kw: edits.append((slider, chip))

        for slider, chip in (
            (window.red_slider, window.red_value),
            (window.green_slider, window.green_value),
            (window.blue_slider, window.blue_value),
        ):
            edits.clear()
            chip.click()
            app.processEvents()
            assert edits == [(slider, chip)], "the readout must edit its own slider"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_clicking_a_diy_step_chip_targets_that_step(monkeypatch) -> None:
    """Same trap on the DIY rows, where the captured value is a step id: False
    would quietly read as step 0."""
    # DIY is Pro-gated; in Free mode the chips are disabled and click() is a
    # no-op, so the test would pass without ever exercising the connection.
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    invalidate_pro_cache()

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        diy = window._diy_ui
        steps = diy._steps
        assert len(steps) >= 2, "need at least two steps to tell them apart"
        second_id = steps[1]["id"]

        cycled: list[object] = []
        edited: list[object] = []
        diy._cycle_motion = lambda step_id: cycled.append(step_id)
        diy._edit_duration = lambda step_id: edited.append(step_id)
        diy._rebuild_rows()
        app.processEvents()

        chips = window.diy_list.findChildren(ValueChip)
        assert all(chip.isEnabled() for chip in chips), "Pro gate still disables the chips"
        # Two chips per row (motion, duration); the second row starts at index 2.
        chips[2].click()
        chips[3].click()
        app.processEvents()

        assert cycled == [second_id]
        assert edited == [second_id]
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_diy_motion_names_fit_inside_their_chips(monkeypatch) -> None:
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    invalidate_pro_cache()

    from app.diy_effects import MOTION_KEYS
    from app.widgets.diy_row import DiyRow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        window._diy_ui._steps = [
            {"id": index + 1, "rgb": [120, 80, 200], "duration_ms": 1000, "motion": motion}
            for index, motion in enumerate(MOTION_KEYS)
        ]
        window._diy_ui._rebuild_rows()
        app.processEvents()

        chips = window.diy_list.findChildren(ValueChip)
        motion_chips = chips[::2]
        assert len(motion_chips) == len(MOTION_KEYS)
        for chip in motion_chips:
            text_width = chip.fontMetrics().horizontalAdvance(chip.text())
            assert chip.width() >= text_width + 20, f"{chip.text()!r} is clipped inside the motion chip"
            row = chip.parentWidget()
            while row is not None and not isinstance(row, DiyRow):
                row = row.parentWidget()
            assert row is not None
            chip_rect = chip.rect().translated(chip.mapTo(row, QPoint(0, 0)))
            assert row.rect().contains(chip_rect), f"{chip.text()!r} runs outside its DIY row"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_diy_library_actions_stay_compact_and_named_at_the_minimum_size(monkeypatch) -> None:
    monkeypatch.setattr("app.feature_gate.is_license_active", lambda _settings, **_kw: True)
    invalidate_pro_cache()

    from app.widgets.diy_row import DiyRow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        window.show()
        select_section(window, "effects")
        app.processEvents()
        window.body_scroll.ensureWidgetVisible(window.diy_card, 0, 16)
        app.processEvents()

        assert window.diy_save_button.text()
        for button in (
            window.diy_delete_button,
            window.diy_share_button,
            window.diy_import_button,
        ):
            assert button.text() == ""
            assert button.accessibleName()
            assert button.toolTip()
            assert button.width() == button.height()

        def left(widget) -> int:
            return widget.mapTo(window.diy_card, QPoint(0, 0)).x()

        def right(widget) -> int:
            return left(widget) + widget.width()

        left_column = (
            window.diy_library_label,
            window.diy_saved_combo,
            window.diy_timeline_label,
            window.diy_timeline_hint,
            window.diy_preview,
            window.diy_list,
            window.diy_add_button,
            window.diy_playback_label,
            window.diy_transition_label,
        )
        assert len({left(widget) for widget in left_column}) == 1

        right_column = (
            window.diy_import_button,
            window.diy_timeline_label,
            window.diy_preview,
            window.diy_list,
            window.diy_speed_value,
            window.diy_run_button,
        )
        assert len({right(widget) for widget in right_column}) == 1

        rows = window.diy_list.findChildren(DiyRow)
        assert len(rows) >= 2
        preview_bottom = window.diy_preview.mapTo(window.diy_card, QPoint(0, 0)).y() + window.diy_preview.height()
        first_top = rows[0].mapTo(window.diy_card, QPoint(0, 0)).y()
        first_bottom = first_top + rows[0].height()
        second_top = rows[1].mapTo(window.diy_card, QPoint(0, 0)).y()
        assert first_top - preview_bottom == second_top - first_bottom
        assert window.diy_preview.height() >= window._sz(44)
        assert window.body_scroll.horizontalScrollBar().maximum() == 0
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_timer_pill_purpose_follows_the_language() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        def switch(code: str) -> str:
            index = window.language_combo.findData(code)
            assert index >= 0
            window.language_combo.setCurrentIndex(index)
            app.processEvents()
            return window.timer_sleep_pill.accessibleName()

        english = switch("en")
        russian = switch("ru")
        assert english.strip() and russian.strip()
        assert english != russian, "the pill kept announcing the old language"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_settings_controls_announce_what_they_change() -> None:
    """Each settings row keeps its label in a separate QLabel, so a control on
    its own would only announce its value ("Auto") with no hint of what it sets.
    The row label has to reach the control."""
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        for attr in ("language_combo", "performance_combo", "motion_combo", "theme_button"):
            control = getattr(window, attr)
            assert control.accessibleName().strip(), f"{attr} has no accessible name"
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()


def test_settings_accessible_names_follow_the_language() -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        def switch(code: str) -> str:
            index = window.language_combo.findData(code)
            assert index >= 0, f"language {code} missing from the combo"
            window.language_combo.setCurrentIndex(index)
            app.processEvents()
            return window.motion_combo.accessibleName()

        english = switch("en")
        russian = switch("ru")

        assert english.strip() and russian.strip()
        assert english != russian
    finally:
        window._ble.shutdown()
        window.close()
        app.processEvents()
