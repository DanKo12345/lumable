"""The hotkeys panel: what a typo may and may not cost you.

A global combination is taken from the whole system, so the expensive mistakes
here are the silent ones — a key quietly restored to a default, or a working
combination dropped because a different field was mid-edit.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.hotkeys import DEFAULT_HOTKEYS, SUGGESTED_HOTKEYS


@pytest.fixture()
def window():
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    app.processEvents()
    try:
        yield win
    finally:
        win._ble.shutdown()
        win.close()


def _error(window, action: str) -> str:
    """The message a field is showing. Read as text rather than visibility: an
    unshown window reports every widget as hidden."""
    return window.hotkey_error_labels[action].text()


def _saved_bindings(window) -> dict:
    return dict(window._settings.get("hotkeys", {}).get("bindings", {}))


def test_a_typo_does_not_cost_the_combination_that_was_working(window) -> None:
    """The behaviour worth paying for: someone edits one field, mistypes, and
    everything they had keeps working. Substituting the default here would hand
    back a combination they had deliberately changed."""
    window._settings["hotkeys"] = {
        "enabled": True,
        "bindings": {**DEFAULT_HOTKEYS, "toggle_power": "Ctrl+Shift+L"},
    }
    window._hotkey_ui.sync_controls()
    applied: list[bool] = []
    window._apply_hotkeys = lambda: applied.append(True)

    window.hotkey_inputs["toggle_power"].setText("Ctrl+Ctrl")
    window._hotkey_ui._persist()

    assert _saved_bindings(window)["toggle_power"] == "Ctrl+Shift+L"
    assert applied == [], "a form with a bad field must not be re-registered"
    assert _error(window, "toggle_power")


def test_one_bad_field_does_not_save_the_others_either(window) -> None:
    """Half-applying would take a working key away from one action because of a
    typo in another."""
    window._settings["hotkeys"] = {"enabled": True, "bindings": dict(DEFAULT_HOTKEYS)}
    window._hotkey_ui.sync_controls()

    window.hotkey_inputs["toggle_power"].setText("Ctrl+Ctrl")
    window.hotkey_inputs["next_scene"].setText("Ctrl+Alt+9")
    window._hotkey_ui._persist()

    assert _saved_bindings(window)["next_scene"] == DEFAULT_HOTKEYS["next_scene"]


def test_clearing_a_field_gives_the_combination_up(window) -> None:
    window._settings["hotkeys"] = {
        "enabled": True,
        "bindings": {**DEFAULT_HOTKEYS, "toggle_power": "Ctrl+Shift+L"},
    }
    window._hotkey_ui.sync_controls()

    window.hotkey_inputs["toggle_power"].setText("")
    window._hotkey_ui._persist()

    assert _saved_bindings(window)["toggle_power"] == ""


def test_a_valid_change_is_saved_and_applied(window) -> None:
    window._settings["hotkeys"] = {"enabled": True, "bindings": dict(DEFAULT_HOTKEYS)}
    window._hotkey_ui.sync_controls()
    applied: list[bool] = []
    window._apply_hotkeys = lambda: applied.append(True)

    window.hotkey_inputs["toggle_music"].setText("Ctrl+Alt+M")
    window._hotkey_ui._persist()

    assert _saved_bindings(window)["toggle_music"] == "Ctrl+Alt+M"
    assert applied == [True]


def test_the_two_failures_read_differently(window) -> None:
    """A spec that will not parse is a typing problem. A spec Windows refused is
    not the user's mistake at all — the combination is fine and something else
    holds it. One message for both would tell half of them to fix what is not
    broken."""
    window._settings["hotkeys"] = {"enabled": True, "bindings": dict(DEFAULT_HOTKEYS)}
    window._hotkey_ui.sync_controls()

    window.hotkey_inputs["toggle_music"].setText("Ctrl+Ctrl")
    window._hotkey_ui.refresh_errors()
    typing_error = window.hotkey_error_labels["toggle_music"].text()

    window.hotkey_inputs["toggle_music"].setText("Ctrl+Alt+M")
    window._hotkey_controller._failed = {"toggle_music": "Ctrl+Alt+M"}
    window._hotkey_ui.refresh_errors()
    taken_error = window.hotkey_error_labels["toggle_music"].text()

    assert typing_error and taken_error and typing_error != taken_error
    assert "Ctrl+Alt+M" in taken_error, "the refused combination must be named"


def test_a_refused_combination_clears_only_after_the_system_accepts_it(window) -> None:
    """Typing has not asked the system anything, so it cannot answer."""
    window._settings["hotkeys"] = {"enabled": True, "bindings": dict(DEFAULT_HOTKEYS)}
    window._hotkey_ui.sync_controls()
    window.hotkey_inputs["toggle_music"].setText("Ctrl+Alt+M")
    window._hotkey_controller._failed = {"toggle_music": "Ctrl+Alt+M"}
    window._hotkey_ui.refresh_errors()
    assert _error(window, "toggle_music")

    window._hotkey_ui.note_typing()
    assert _error(window, "toggle_music"), "typing must not clear a registration failure"

    window._hotkey_controller._failed = {}
    window._hotkey_ui.refresh_errors()
    assert not _error(window, "toggle_music")


def test_one_refused_action_leaves_the_others_alone(window) -> None:
    window._settings["hotkeys"] = {"enabled": True, "bindings": dict(DEFAULT_HOTKEYS)}
    window._hotkey_ui.sync_controls()
    window._hotkey_controller._failed = {"toggle_power": "Alt+L"}
    window._hotkey_ui.refresh_errors()

    assert _error(window, "toggle_power")
    assert not window.hotkey_error_labels["next_scene"].isVisible()


def test_the_suggestion_is_a_placeholder_and_not_a_value(window) -> None:
    window._settings["hotkeys"] = {"enabled": True, "bindings": {}}
    window._hotkey_ui.sync_controls()

    for action, suggested in SUGGESTED_HOTKEYS.items():
        field = window.hotkey_inputs[action]
        assert field.text() == "", "an unassigned action must show no value"
        assert field.placeholderText() == suggested


def test_the_error_names_its_action_for_a_screen_reader(window) -> None:
    window._settings["hotkeys"] = {"enabled": True, "bindings": dict(DEFAULT_HOTKEYS)}
    window._hotkey_ui.sync_controls()

    window.hotkey_inputs["toggle_music"].setText("Ctrl+Ctrl")
    window._hotkey_ui.refresh_errors()

    described = window.hotkey_inputs["toggle_music"].accessibleDescription()
    assert window._tr("hotkeys.action.toggle_music") in described
    assert window.hotkey_error_labels["toggle_music"].text() in described


def test_an_unparseable_field_reports_the_saved_value_not_the_default(window) -> None:
    """Checked on the collected bindings directly. The form also refuses to save
    at all when a field is bad, which hides this — until someone changes that
    flow and the default quietly comes back."""
    window._settings["hotkeys"] = {
        "enabled": True,
        "bindings": {**DEFAULT_HOTKEYS, "toggle_power": "Ctrl+Shift+L"},
    }
    window._hotkey_ui.sync_controls()

    window.hotkey_inputs["toggle_power"].setText("Ctrl+Ctrl")
    bindings, invalid = window._hotkey_ui._collect_bindings()

    assert invalid == ["toggle_power"]
    assert bindings["toggle_power"] == "Ctrl+Shift+L"
    assert bindings["toggle_power"] != DEFAULT_HOTKEYS["toggle_power"]


def test_a_long_error_wraps_instead_of_widening_the_card(window) -> None:
    """Russian messages are the long ones. A message that pushed the card wider
    would put the whole page into sideways scrolling because of one typo."""
    window.resize(860, 420)
    window.show()
    QApplication.instance().processEvents()
    window._settings["hotkeys"] = {"enabled": True, "bindings": {"toggle_power": "Ctrl+Ctrl"}}
    window._hotkey_ui.sync_controls()
    window._hotkey_ui.refresh_errors()
    QApplication.instance().processEvents()

    label = window.hotkey_error_labels["toggle_power"]
    assert label.text()
    assert label.wordWrap()
    assert label.maximumWidth() <= window.hotkeys_card.contentsRect().width()
    assert not window.body_scroll.horizontalScrollBar().isVisible()
