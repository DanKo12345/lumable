"""Who owns the strip today, and what that costs.

These pin the behaviour Fusion is meant to change, before it changes. Every one
of them passes right now — that is the point. They are a description of the
limit, written down so the difference is visible rather than argued about:

* only one thing may drive the strip, so turning music on kills screen sync;
* a scene applied from anywhere takes the strip and nothing gives it back;
* the music analysis only runs while music *owns* the strip, which is the wall
  "screen colour, music brightness" walks into.

No audio device and no screen: capture is faked at the boundary, and the
threads only have to stay alive for ``is_running`` to mean what it means.
"""

from __future__ import annotations

import pathlib
import sys
import threading
import types

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication


class _FakeShot:
    def __init__(self) -> None:
        self.width = 4
        self.height = 4
        self.bgra = bytes([40, 80, 120, 255] * 16)


class _FakeSct:
    monitors = [
        {"left": 0, "top": 0, "width": 8, "height": 8},
        {"left": 0, "top": 0, "width": 8, "height": 8},
    ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, _region):
        return _FakeShot()


def _quiet_reader(_options):
    """A capture that keeps the thread alive without burning a core."""
    stop = threading.Event()

    def read(_size):
        stop.wait(0.01)
        return [[0.0, 0.0]] * 8

    return read, lambda: None, 48000


@pytest.fixture(scope="module")
def _app_window():
    """One window for the whole file.

    A MainWindow brings a BLE loop, an API server and a set of timers with it.
    Building seven of them and relying on teardown to unpick each one is how a
    test file starts hanging for reasons that have nothing to do with what it
    is testing.

    It also has to isolate the data directory itself. The suite's autouse
    isolation is function-scoped, and pytest builds higher-scoped fixtures
    first — so a window built here would read and write the developer's real
    LumaBLE settings, and their saved Fusion mode would decide what these tests
    see. That is not a hypothetical: it is how this file started failing.
    """
    import tempfile

    import app.ambient_ui_controller as ambient_module
    import app.fusion_ui_controller as fusion_module
    import app.music_ui_controller as music_module
    from app import storage
    from app.main_window import MainWindow
    from app.music_controller import MusicController

    app = QApplication.instance() or QApplication([])
    data_dir = pathlib.Path(tempfile.mkdtemp(prefix="lumable-ownership-"))
    real_paths = (storage.DATA_DIR, storage.SETTINGS_PATH, storage.PROFILES_PATH)
    storage.DATA_DIR = data_dir
    storage.SETTINGS_PATH = data_dir / "settings.json"
    storage.PROFILES_PATH = data_dir / "profiles.json"
    real_mss = sys.modules.get("mss")
    sys.modules["mss"] = types.SimpleNamespace(mss=_FakeSct)
    ambient_can_use = ambient_module.can_use
    fusion_can_use = fusion_module.can_use
    music_can_use = music_module.can_use
    loopback = MusicController._open_loopback_reader
    mic = MusicController._open_mic_reader
    ambient_module.can_use = lambda _feature: True
    fusion_module.can_use = lambda _feature: True
    music_module.can_use = lambda _feature: True
    MusicController._open_loopback_reader = staticmethod(_quiet_reader)
    MusicController._open_mic_reader = staticmethod(_quiet_reader)

    win = MainWindow()
    # The strip is only pretend-connected, so the power calls in these tests
    # fail asynchronously and the window answers with a modal box. Nothing here
    # is about how errors are shown, and a modal in a test run waits forever.
    win._show_error = lambda *_args, **_kwargs: None
    app.processEvents()
    try:
        yield win
    finally:
        win._ambient_ui.shutdown()
        win._music_ui.shutdown()
        win._ble.shutdown()
        win.close()
        ambient_module.can_use = ambient_can_use
        fusion_module.can_use = fusion_can_use
        music_module.can_use = music_can_use
        MusicController._open_loopback_reader = loopback
        MusicController._open_mic_reader = mic
        storage.DATA_DIR, storage.SETTINGS_PATH, storage.PROFILES_PATH = real_paths
        if real_mss is None:
            sys.modules.pop("mss", None)
        else:
            sys.modules["mss"] = real_mss


@pytest.fixture()
def window(_app_window):
    """The same window, put back to a known state before each test."""
    _app_window.stop_streams()
    _app_window._is_connected = True
    _app_window.power_button.setChecked(True)
    QApplication.instance().processEvents()
    return _app_window


def _start_screen_sync(window) -> None:
    assert window._ambient_ui.activate() is True, "screen sync would not start"


def _start_music(window) -> None:
    assert window._music_ui.activate() is True, "music would not start"


# ── one owner at a time ───────────────────────────────────────────────
def test_starting_music_stops_screen_sync(window) -> None:
    """The limit Fusion exists to remove. There is one colour going to the
    strip and one owner allowed to produce it, so wanting both means losing
    one."""
    _start_screen_sync(window)
    assert window._ambient_ui.is_running()

    _start_music(window)

    assert window._music_ui.is_running()
    assert not window._ambient_ui.is_running(), "screen sync survived — the limit is gone"


def test_starting_screen_sync_stops_music(window) -> None:
    _start_music(window)
    assert window._music_ui.is_running()

    _start_screen_sync(window)

    assert window._ambient_ui.is_running()
    assert not window._music_ui.is_running()


def test_turning_the_light_off_by_hand_stops_the_capture(window) -> None:
    """A manual command still outranks everything: nothing is captured and
    nothing is written while the strip is off."""
    _start_screen_sync(window)

    window.power_button.setChecked(False)
    window._toggle_power()

    assert not window._fusion_ui.coordinator().output_allowed()
    assert not window._ambient_ui._ambient.is_running(), "the screen was still being captured"


def test_the_mode_survives_a_power_cycle(window) -> None:
    """The change 0.4.0 makes on purpose, and the reason this file was written.

    Before, "screen sync" was not a setting but a running object: switching the
    strip off destroyed it and switching back on left a dark strip and a card
    claiming nothing was on. Now power moves only the third of the three states
    — permission to write — and the mode comes back with its capture.
    """
    _start_screen_sync(window)

    window.power_button.setChecked(False)
    window._toggle_power()
    assert window._fusion_ui.is_running(), "the mode was destroyed rather than paused"
    assert not window._fusion_ui.coordinator().output_allowed()

    window.power_button.setChecked(True)
    window._toggle_power()

    assert window._fusion_ui.is_running()
    assert window._fusion_ui.coordinator().output_allowed()
    assert window._ambient_ui._ambient.is_running(), "the capture did not come back"


# ── nothing gives the strip back ──────────────────────────────────────
def test_a_scene_takes_the_strip_and_never_returns_it(window) -> None:
    """Whether that is right depends on what the scene was for — a scene meant
    to replace the mode should, a scene meant to show something for a moment
    should not. Today there is no way to say which, so both behave the same.

    Applying goes through a backend that marshals onto the Qt thread, which
    needs an event loop this test has not got; the step being pinned is the one
    the real service performs first — turning the PC mode off, which is
    ``stop_streams`` under another name.
    """
    from app import scene_store
    from app.scene_apply import SceneApplyService
    from app.scenes import make_scene

    scene = scene_store.save_scene(window._settings, make_scene("Alert", {"power": True}))
    assert scene is not None
    _start_screen_sync(window)

    class _Backend:
        """The parts of the real backend the apply service reaches for."""

        def set_pc_mode(self, _mode, _preset=None) -> bool:
            window.stop_streams()
            return True

        def set_power(self, *_args, **_kwargs) -> bool:
            return True

        def set_color(self, *_args, **_kwargs) -> bool:
            return True

        def set_brightness(self, *_args, **_kwargs) -> bool:
            return True

        def set_effect(self, *_args, **_kwargs) -> bool:
            return True

        def set_speed(self, *_args, **_kwargs) -> bool:
            return True

    SceneApplyService(_Backend()).apply(scene, capabilities=None)

    assert not window._ambient_ui.is_running()
    QApplication.instance().processEvents()
    assert not window._ambient_ui.is_running(), "still gone a moment later"


# ── the wall Fusion walks into ────────────────────────────────────────
def test_the_music_analysis_only_runs_while_music_owns_the_strip(window) -> None:
    """"Screen colour, music brightness" needs the sound analysed while
    something else is driving the strip. Today listening and owning are the
    same act: stop owning and the analysis stops with it.
    """
    _start_music(window)
    QApplication.instance().processEvents()
    assert window._music_ui.is_running()

    _start_screen_sync(window)

    assert not window._music_ui.is_running()
    # And with it, the thing Fusion needs to keep: nothing is listening.
    assert window._music_ui._music._thread is None


def test_the_two_modes_have_no_shared_output_to_compose_into(window) -> None:
    """Each mode owns its own stream engine and writes to the strip itself, so
    there is no single place where a final colour is decided. That is what a
    compositor has to become."""
    ambient_engine = window._ambient_ui._ambient._engine
    music_engine = window._music_ui._music._engine

    assert ambient_engine is not music_engine
