"""The rule editor as the user meets it: create, edit, delete, and the keyboard.

The form's own rules are tested in test_automation_rule_form (no Qt there). What is
left for here is the part that only exists once there are widgets: which fields are
on screen, whether Save can be pressed, what reaches the facade, and whether any of
it can be done without a mouse.

The facade is a fake — the same one the screen tests use — because saving a rule
must be provably one call through the facade and nothing else.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

# The editor is opened from the automations screen, so it is tested against the same
# stand-in that screen's own tests use — see tests/automation_screen.py. The
# ``screen`` fixture itself comes from conftest.
from automation_screen import make_rule
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.automation.rules import (
    TRIGGER_WINDOWS_LOCKED,
    TRIGGER_WINDOWS_SLEEP,
    TRIGGER_WINDOWS_UNLOCKED,
    TRIGGER_WINDOWS_WAKE,
)
from app.automation_rule_form import (
    CHOICE_POWER_OFF,
    CHOICE_SCENE,
    EXECUTION_BACKGROUND,
)
from app.localization import localization_manager
from app.widgets.profile_action_overlay import ProfileConfirmOverlay
from app.widgets.rule_editor_overlay import RuleEditorOverlay


def _tr(key: str, **kwargs: object) -> str:
    return localization_manager.t(key, **kwargs)


@pytest.fixture(autouse=True)
def _english():
    previous = localization_manager.language
    localization_manager.set_language("en")
    yield
    localization_manager.set_language(previous)


def _editor(host) -> RuleEditorOverlay:
    editor = host._automation_ui._editor
    assert editor is not None, "no editor is open"
    return editor


def _pump() -> None:
    app = QApplication.instance() or QApplication([])
    for _ in range(3):
        app.processEvents()


# ── opening ───────────────────────────────────────────────────────────
def test_adding_a_rule_opens_an_editor_that_cannot_be_saved_unnamed(screen) -> None:
    """A new rule has to be named: with a list of "Switch the light off" rules,
    nothing tells them apart. The refusal is explained where the button is."""
    host, _controller = screen

    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor.save_button.isEnabled() is False
    assert editor.problem_label.isHidden() is False
    assert editor.problem_label.text() == _tr("automations.problem_name")

    editor.name_input.setText("Bedtime")

    assert editor.save_button.isEnabled() is True
    assert editor.problem_label.isHidden() is True


def test_a_new_rule_opens_on_its_name(screen) -> None:
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()

    assert QApplication.focusWidget() is _editor(host).name_input


def test_only_one_editor_opens_at_a_time(screen) -> None:
    """Two would each save over the other, and the second would be editing a rule
    the first had already replaced."""
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    first = _editor(host)

    host.automations_add_button.click()
    _pump()

    assert _editor(host) is first


def test_stopping_the_automation_ui_closes_its_editor(screen) -> None:
    host, controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    controller.stop()
    _pump()

    assert editor.isHidden()
    assert host._automation_ui._editor is None


def test_windows_events_are_offered_in_the_real_trigger_combo(screen) -> None:
    """A trigger supported by the engine is unusable until the editor offers it."""
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    combo = _editor(host).trigger_combo

    offered = {combo.itemData(index) for index in range(combo.count())}
    assert {
        TRIGGER_WINDOWS_LOCKED,
        TRIGGER_WINDOWS_UNLOCKED,
        TRIGGER_WINDOWS_SLEEP,
        TRIGGER_WINDOWS_WAKE,
    } <= offered


def test_editing_a_rule_loads_it(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [
        make_rule(
            id="rule-1",
            name="Coding",
            trigger={"kind": "app_foreground", "app": "code.exe"},
            action={"type": "apply_scene", "scene_id": "s1"},
        )
    ]
    host._settings["scenes"] = [{"scene_id": "s1", "name": "Warm desk", "state": {"rgb": [1, 2, 3]}}]
    controller.sync_controls()

    _edit_button(controller, 0).click()
    _pump()
    editor = _editor(host)

    assert editor.name_input.text() == "Coding"
    assert editor.app_input.text() == "code.exe"
    assert editor.form()["action"] == CHOICE_SCENE
    assert editor.form()["scene_id"] == "s1"
    assert editor.save_button.isEnabled() is True


def _edit_button(controller, index: int):
    from app.widgets import LiquidButton

    # Edit comes before the on/off toggle in the row, which is the reading order.
    return controller._rows[index].findChildren(LiquidButton)[0]


# ── what the form shows ───────────────────────────────────────────────
def test_only_the_fields_the_trigger_uses_are_shown(screen) -> None:
    """Left on screen, a day chip would collect a setting an app rule has nowhere to
    keep — and the schema would drop it without saying so."""
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    rows = editor._rows

    assert rows["time_at"].isHidden() is False  # a new rule starts as a daily time
    assert rows["days"].isHidden() is False
    assert rows["app"].isHidden() is True
    assert rows["minutes"].isHidden() is True

    editor.trigger_combo.setCurrentIndex(editor.trigger_combo.findData("app_foreground"))
    _pump()

    assert rows["app"].isHidden() is False
    assert rows["time_at"].isHidden() is True
    assert rows["days"].isHidden() is True


def test_the_scene_field_appears_only_for_a_scene_action(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor._rows["scene_id"].isHidden() is True

    editor.action_combo.setCurrentIndex(editor.action_combo.findData(CHOICE_SCENE))
    _pump()

    assert editor._rows["scene_id"].isHidden() is False


def test_a_time_rule_with_no_days_cannot_be_saved(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    editor.name_input.setText("Bedtime")

    for chip in editor.day_buttons:
        chip.setChecked(False)
    editor._on_changed()

    assert editor.save_button.isEnabled() is False
    assert editor.problem_label.text() == _tr("automations.problem_days")

    editor.day_buttons[0].setChecked(True)
    editor._on_changed()
    assert editor.save_button.isEnabled() is True


def test_background_is_offered_only_where_it_can_work(screen, monkeypatch) -> None:
    """A background rule becomes a Windows task that starts the app headless, and
    that path can only switch power at a time of day. Switching the action away takes
    the capability with it — and the flag, which the schema would drop anyway."""
    monkeypatch.setattr("app.automation_ui_controller.can_use", lambda _feature: True)
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    editor.name_input.setText("Bedtime")
    editor.background_button.setChecked(True)
    editor._on_changed()
    assert editor.form()["execution"] == EXECUTION_BACKGROUND
    assert editor.background_pro_badge.isHidden() is True
    assert editor.background_hint.isHidden() is True

    editor.action_combo.setCurrentIndex(editor.action_combo.findData(CHOICE_SCENE))
    _pump()

    assert editor.background_button.isEnabled() is False
    assert editor.background_button.isChecked() is False
    assert editor.background_hint.isHidden() is False


def test_background_execution_is_labelled_and_locked_in_free(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor.background_button.isEnabled() is False
    assert editor.background_button.isChecked() is False
    assert editor.background_pro_badge.isHidden() is False
    assert editor.background_pro_badge.text() == _tr("common.pro_badge")
    assert editor.background_hint.text() == _tr("automations.background_pro_hint")
    assert (
        editor.background_button.accessibleDescription()
        == _tr("automations.background_pro_hint")
    )


def test_opening_a_background_rule_in_free_does_not_silently_downgrade_it(
    screen,
) -> None:
    host, controller = screen
    host._automations.stored_rules = [
        make_rule(id="rule-background", name="Evening", execution="background")
    ]
    controller.sync_controls()

    _edit_button(controller, 0).click()
    _pump()
    editor = _editor(host)

    assert editor.background_button.isEnabled() is False
    assert editor.background_button.isChecked() is True
    assert editor.form()["execution"] == EXECUTION_BACKGROUND


def test_a_rule_whose_scene_is_gone_says_so_and_can_be_pointed_at_another(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [
        make_rule(id="rule-1", name="Desk", action={"type": "apply_scene", "scene_id": "gone"})
    ]
    host._settings["scenes"] = [{"scene_id": "s1", "name": "Warm desk", "state": {"rgb": [1, 2, 3]}}]
    controller.sync_controls()

    _edit_button(controller, 0).click()
    _pump()
    editor = _editor(host)

    assert editor.save_button.isEnabled() is False
    assert editor.problem_label.text() == _tr("automations.problem_scene_missing")

    editor.scene_combo.setCurrentIndex(editor.scene_combo.findData("s1"))
    _pump()

    assert editor.save_button.isEnabled() is True
    assert editor.problem_label.isHidden() is True


def test_priority_and_cooldown_are_folded_away(screen) -> None:
    """Real, and almost nobody needs them: the form has to read as "when / then" at
    a glance and still let them be reached."""
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor.advanced_box.isHidden() is True

    editor.advanced_button.setChecked(True)
    editor._toggle_advanced()
    _pump()

    assert editor.advanced_box.isHidden() is False
    assert editor.priority_combo.isVisibleTo(editor.advanced_box)
    assert editor.cooldown_combo.isVisibleTo(editor.advanced_box)


def test_editor_combos_are_tall_enough_for_their_own_style(screen) -> None:
    """The global combo style includes vertical padding. Constraining the widget
    below its minimum size hint cuts the rounded bottom edge off every field."""
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    for combo in (
        editor.trigger_combo,
        editor.idle_combo,
        editor.action_combo,
        editor.scene_combo,
        editor.priority_combo,
        editor.cooldown_combo,
    ):
        assert combo.maximumHeight() >= combo.minimumSizeHint().height()


def test_time_and_weekdays_share_one_control_height(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert {chip.height() for chip in editor.day_buttons} == {
        editor.time_button.height()
    }


def test_advanced_fields_open_with_a_real_transition(
    screen, preserve_motion_policy
) -> None:
    """The extra fields move the form rather than appearing in one hard jump."""
    preserve_motion_policy.set_mode("full")
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    editor.advanced_button.click()

    assert editor._advanced_height_anim.state() == QAbstractAnimation.Running
    QTest.qWait(70)
    middle = editor.advanced_box.maximumHeight()
    target = editor.advanced_box.sizeHint().height()
    assert 0 < middle < target

    QTest.qWait(180)
    assert editor._advanced_height_anim.state() == QAbstractAnimation.Stopped
    assert editor.advanced_box.maximumHeight() == target


def test_edit_footer_is_one_group_and_save_uses_the_strip_accent(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    controller.sync_controls()
    host.show()
    _edit_button(controller, 0).click()
    _pump()
    editor = _editor(host)
    assert editor.delete_button is not None

    delete_gap = editor.cancel_button.x() - (
        editor.delete_button.x() + editor.delete_button.width()
    )
    save_gap = editor.save_button.x() - (
        editor.cancel_button.x() + editor.cancel_button.width()
    )
    assert abs(delete_gap - save_gap) <= 2
    assert editor.save_button._role == "led"


def test_trigger_and_action_icons_follow_the_selected_choices(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor.trigger_icon.kind == "clock-3"
    assert editor.action_icon.kind == "lightbulb"

    editor.trigger_combo.setCurrentIndex(editor.trigger_combo.findData("no_input"))
    editor.action_combo.setCurrentIndex(editor.action_combo.findData(CHOICE_SCENE))
    _pump()

    assert editor.trigger_icon.kind == "moon"
    assert editor.action_icon.kind == "layers-3"


def test_background_uses_a_real_accessible_switch(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    switch = _editor(host).background_button

    interface = QAccessible.queryAccessibleInterface(switch)
    assert interface is not None
    assert interface.state().checkable
    assert not interface.state().checked

    switch.setChecked(True)
    _pump()
    assert interface.state().checked


def test_background_switch_moves_smoothly_and_respects_reduced_motion(
    screen, preserve_motion_policy, monkeypatch
) -> None:
    monkeypatch.setattr("app.automation_ui_controller.can_use", lambda _feature: True)
    preserve_motion_policy.set_mode("full")
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()
    switch = _editor(host).background_button

    switch.click()
    assert switch._animation.state() == QAbstractAnimation.Running
    QTest.qWait(60)
    assert 0.0 < switch._progress < 1.0
    QTest.qWait(160)
    assert switch._animation.state() == QAbstractAnimation.Stopped
    assert switch._progress == 1.0

    preserve_motion_policy.set_mode("reduced")
    switch.click()
    assert switch._animation.state() == QAbstractAnimation.Stopped
    assert switch._progress == 0.0


# ── saving ────────────────────────────────────────────────────────────
def test_saving_a_new_rule_goes_through_the_facade_and_gets_an_id(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    editor.name_input.setText("Bedtime")
    editor.action_combo.setCurrentIndex(editor.action_combo.findData(CHOICE_POWER_OFF))
    _pump()

    editor.save_button.click()
    _pump()

    calls = [call for call in host._automations.calls if call[0] == "save_rule"]
    assert len(calls) == 1, "the rule did not reach the facade exactly once"
    stored = calls[0][1]
    assert stored["name"] == "Bedtime"
    assert stored["action"] == {"type": "set_power", "power": False, "target": "primary"}
    assert stored["id"], "a new rule was saved without an id"
    assert host._automation_ui._editor is None, "the editor stayed open after saving"


def test_editing_a_rule_saves_it_under_the_same_id(screen) -> None:
    """A new id would leave the old rule behind and orphan its journal entries and
    its Windows task."""
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    controller.sync_controls()
    _edit_button(controller, 0).click()
    _pump()
    editor = _editor(host)

    editor.name_input.setText("Evening, later")
    editor.save_button.click()
    _pump()

    stored = next(call for call in host._automations.calls if call[0] == "save_rule")[1]
    assert stored["id"] == "rule-1"
    assert stored["name"] == "Evening, later"


def test_a_save_that_did_not_land_keeps_the_editor_open_and_says_so(screen) -> None:
    """Closing it would leave the user believing they have a rule they do not."""
    host, _controller = screen
    host._automations.writes_land = False
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    editor.name_input.setText("Bedtime")

    editor.save_button.click()
    _pump()

    assert host._automation_ui._editor is editor
    assert editor.problem_label.text() == _tr("automations.save_failed")


# ── deleting ──────────────────────────────────────────────────────────
def _confirm_overlay(host) -> ProfileConfirmOverlay:
    overlays = host.findChildren(ProfileConfirmOverlay)
    assert overlays, "no confirmation was asked for"
    return overlays[-1]


def test_deleting_asks_first(screen) -> None:
    """A rule is something the user built, not a selection."""
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    controller.sync_controls()
    _edit_button(controller, 0).click()
    _pump()

    _editor(host).delete_button.click()
    _pump()

    confirm = _confirm_overlay(host)
    assert "Evening" in confirm._message_label.text()
    assert [call for call in host._automations.calls if call[0] == "delete_rule"] == []


def test_confirming_deletes_the_rule_and_closes_the_editor(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    controller.sync_controls()
    _edit_button(controller, 0).click()
    _pump()
    _editor(host).delete_button.click()
    _pump()

    _confirm_overlay(host)._confirm_button.click()
    _pump()

    assert ("delete_rule", "rule-1") in host._automations.calls
    assert host._automation_ui._editor is None


def test_a_delete_that_did_not_land_keeps_the_editor_open_and_says_so(screen) -> None:
    """Deleting is a settings write like any other and can fail. Closed first, the
    user has confirmed a deletion, watched the editor go, and still has the rule."""
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    controller.sync_controls()
    _edit_button(controller, 0).click()
    _pump()
    editor = _editor(host)
    editor.delete_button.click()
    _pump()
    host._automations.writes_land = False

    _confirm_overlay(host)._confirm_button.click()
    _pump()

    assert host._automation_ui._editor is editor, "the editor closed on a failed delete"
    assert editor.problem_label.text() == _tr("automations.delete_failed")
    assert [rule.id for rule in host._automations.rules()] == ["rule-1"]


def test_backing_out_of_the_confirmation_deletes_nothing(screen) -> None:
    host, controller = screen
    host._automations.stored_rules = [make_rule(id="rule-1", name="Evening")]
    controller.sync_controls()
    _edit_button(controller, 0).click()
    _pump()
    _editor(host).delete_button.click()
    _pump()

    _confirm_overlay(host).close_overlay()
    _pump()

    assert [call for call in host._automations.calls if call[0] == "delete_rule"] == []
    assert host._automation_ui._editor is not None, "backing out closed the editor too"


def test_a_new_rule_is_not_offered_a_delete_button(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()

    assert _editor(host).delete_button is None


# ── the keyboard ──────────────────────────────────────────────────────
def test_escape_closes_the_editor_without_saving(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    editor.name_input.setText("Bedtime")

    QTest.keyClick(editor, Qt.Key_Escape)
    _pump()

    assert host._automation_ui._editor is None
    assert [call for call in host._automations.calls if call[0] == "save_rule"] == []


def test_enter_saves_a_form_that_is_ready_and_refuses_one_that_is_not(screen) -> None:
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    QTest.keyClick(editor, Qt.Key_Return)
    _pump()
    assert [call for call in host._automations.calls if call[0] == "save_rule"] == [], (
        "Enter saved a rule the button refuses to save"
    )

    editor.name_input.setText("Bedtime")
    QTest.keyClick(editor, Qt.Key_Return)
    _pump()
    assert len([call for call in host._automations.calls if call[0] == "save_rule"]) == 1


def test_every_control_in_the_editor_can_be_reached_from_the_keyboard(screen) -> None:
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    for control in (
        editor.name_input,
        editor.trigger_combo,
        editor.time_button,
        editor.action_combo,
        editor.background_button,
        editor.advanced_button,
        editor.cancel_button,
        editor.save_button,
        *editor.day_buttons,
    ):
        assert control.focusPolicy() != Qt.NoFocus, f"{control} cannot be focused"


def test_a_day_chip_in_the_editor_announces_itself_as_a_checkable_control(screen) -> None:
    """The chips are custom widgets, so the role and the checked state have to come
    from a real control — a screen reader cannot be told them any other way."""
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()
    chip = _editor(host).day_buttons[0]

    interface = QAccessible.queryAccessibleInterface(chip)
    assert interface is not None
    assert interface.state().checkable
    assert interface.state().checked  # a new rule starts on every day


def test_the_name_field_stops_where_the_schema_stops(screen) -> None:
    """The schema stores 80 characters. Typed past that and truncated on save, the
    user would name a rule one thing and be shown another."""
    from app.automation.controller import MAX_NAME_LENGTH

    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor.name_input.maxLength() == MAX_NAME_LENGTH

    editor.name_input.setText("N" * (MAX_NAME_LENGTH + 40))
    editor.save_button.click()
    _pump()

    typed = editor.name_input.text()
    stored = next(call for call in host._automations.calls if call[0] == "save_rule")[1]
    assert len(typed) == MAX_NAME_LENGTH
    assert stored["name"] == typed, "the name shown and the name saved differ"


def test_a_field_control_announces_what_it_sets(screen) -> None:
    """Each row keeps its label in a separate QLabel, so a control on its own would
    announce only its value."""
    host, _controller = screen
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)

    assert editor.name_input.accessibleName() == _tr("automations.field_name")
    assert editor.trigger_combo.accessibleName() == _tr("automations.field_trigger")
    assert editor.background_button.accessibleName() == _tr("automations.field_background")


def test_the_day_chips_can_be_toggled_with_the_keyboard(screen) -> None:
    host, _controller = screen
    host.show()
    host.automations_add_button.click()
    _pump()
    editor = _editor(host)
    chip = editor.day_buttons[2]
    chip.setFocus()
    _pump()

    QTest.keyClick(chip, Qt.Key_Space)
    _pump()

    assert chip.isChecked() is False
    assert 2 not in editor.form()["days"]
