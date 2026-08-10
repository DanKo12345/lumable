"""The tray menu: what it may claim about a strip nobody is looking at.

The menu is rebuilt every time it opens, and everything in it is read from the
app at that moment. The failure worth guarding against is a menu that describes
a state the app left behind — a tick on a mode a licence refused to start, or a
scene offered while nothing is connected.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu

from app import scene_store
from app.scenes import make_scene


@pytest.fixture()
def window(monkeypatch):
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win._tray_controller._quick_menu = QMenu(win)
    app.processEvents()
    try:
        yield win
    finally:
        win._ble.shutdown()
        win.close()


def _rebuild(window, *, pro: bool = True, connected: bool = True) -> list:
    import app.tray_controller as module

    module.can_use = lambda _feature: pro
    window._is_connected = connected
    window._tray_controller.rebuild_quick_menu()
    return list(window._tray_controller._quick_menu.actions())


def _find(actions: list, text: str):
    for action in actions:
        if action.text() == text:
            return action
        menu = action.menu()
        if menu is not None and menu.title() == text:
            return action
    return None


def test_the_status_says_what_the_app_believes(window) -> None:
    actions = _rebuild(window, connected=True)
    assert _find(actions, window._tr("tray.status_connected")) is not None

    window._connect_in_progress = True
    actions = _rebuild(window, connected=False)
    assert _find(actions, window._tr("tray.status_connecting")) is not None

    window._connect_in_progress = False
    actions = _rebuild(window, connected=False)
    assert _find(actions, window._tr("tray.status_disconnected")) is not None


def test_a_mode_is_ticked_only_while_it_actually_runs(window) -> None:
    """Never set on the way in. A start that a licence or a missing connection
    refused would otherwise leave a tick on a mode that never began."""
    window._ambient_ui.is_running = lambda: False
    window._music_ui.is_running = lambda: False
    actions = _rebuild(window)
    assert not _find(actions, window._tr("tray.screen_sync")).isChecked()

    window._ambient_ui.is_running = lambda: True
    actions = _rebuild(window)
    assert _find(actions, window._tr("tray.screen_sync")).isChecked()
    assert not _find(actions, window._tr("tray.music")).isChecked()


def test_a_refused_start_leaves_no_tick_behind(window) -> None:
    """The menu is rebuilt from is_running, so a toggle that was blocked shows
    as off the next time it is opened."""
    window._ambient_ui.is_running = lambda: False
    window._ambient_ui.toggle = lambda: False  # a gate said no
    actions = _rebuild(window)
    screen_sync = _find(actions, window._tr("tray.screen_sync"))
    screen_sync.trigger()

    actions = _rebuild(window)
    assert not _find(actions, window._tr("tray.screen_sync")).isChecked()


def test_both_modes_stay_available_so_switching_is_one_click(window) -> None:
    """Blocking the other mode would be a second copy of a policy the owners
    already enforce — and it would make changing your mind take two steps."""
    window._ambient_ui.is_running = lambda: True
    window._music_ui.is_running = lambda: False

    actions = _rebuild(window)

    assert _find(actions, window._tr("tray.music")).isEnabled()
    assert _find(actions, window._tr("tray.screen_sync")).isEnabled()


def test_a_locked_mode_says_it_needs_pro(window) -> None:
    actions = _rebuild(window, pro=False)
    screen_sync = _find(actions, window._tr("tray.screen_sync"))

    assert screen_sync is None, "the whole submenu is replaced by the upsell"


def test_without_a_connection_the_modes_say_why(window) -> None:
    window._ambient_ui.is_running = lambda: False
    actions = _rebuild(window, connected=False)
    screen_sync = _find(actions, window._tr("tray.screen_sync"))

    assert not screen_sync.isEnabled()
    assert screen_sync.toolTip() == window._tr("tray.reason_disconnected")


def test_a_running_mode_can_still_be_stopped_when_the_strip_drops(window) -> None:
    """Otherwise the only way to stop a mode that lost its strip would be to
    open the window."""
    window._ambient_ui.is_running = lambda: True

    actions = _rebuild(window, connected=False)

    assert _find(actions, window._tr("tray.screen_sync")).isEnabled()


def test_the_scenes_offered_are_the_ones_last_used(window) -> None:
    settings = window._settings
    for name in ("Read", "Film", "Party"):
        scene_store.save_scene(settings, make_scene(name, {"power": True}))
    ids = {s["name"]: s["scene_id"] for s in scene_store.list_scenes(settings)}
    scene_store.note_scene_applied(settings, ids["Party"])

    actions = _rebuild(window)
    scenes = _find(actions, window._tr("tray.scenes")).menu()

    assert next(a.text() for a in scenes.actions()) == "Party"


def test_scenes_are_not_offered_without_a_strip_to_apply_them_to(window) -> None:
    """The submenu carries the state: greying every name inside it instead
    makes the user open a list to find out nothing in it works."""
    scene_store.save_scene(window._settings, make_scene("Read", {"power": True}))

    actions = _rebuild(window, connected=False)

    assert not _find(actions, window._tr("tray.scenes")).isEnabled()


def test_nothing_that_writes_to_the_strip_is_offered_without_one(window) -> None:
    """A click that quietly does nothing reads as the app being broken. Power
    and scenes already refused; brightness and a saved colour are writes too."""
    actions = _rebuild(window, connected=False)

    for title in ("tray.brightness", "tray.recent_colors", "tray.scenes"):
        entry = _find(actions, window._tr(title))
        assert entry is not None, title
        assert not entry.isEnabled(), title
    # The power item is labelled by what the click would do, so look for either.
    power = _find(actions, window._tr("color.power_on")) or _find(
        actions, window._tr("color.power_off")
    )
    assert power is not None and not power.isEnabled()


def test_everything_comes_back_once_a_strip_is_there(window) -> None:
    actions = _rebuild(window, connected=True)

    for title in ("tray.brightness", "tray.recent_colors"):
        assert _find(actions, window._tr(title)).isEnabled(), title
