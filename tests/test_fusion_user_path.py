"""The path a person actually takes, from the card to the strip and back.

Choose *Экран + музыка* on the screen card, press start, and the colour that
reaches the BLE layer should be the picture's, dimmed by what the music is
doing. Then press stop and everything lets go.

Driven by clicks rather than by calling the controllers: the point is that the
widgets are wired to the thing that was built, and every previous mistake in
this work was found below the level the user actually touches.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

SCREEN_COLOUR = (210, 70, 30)


class _FakeShot:
    def __init__(self) -> None:
        self.width = 4
        self.height = 4
        red, green, blue = SCREEN_COLOUR
        self.bgra = bytes([blue, green, red, 255] * 16)


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


def _music_reader(_options):
    """A steady piece of music: loud enough to open the gate, not silent."""
    step = [0]

    def read(_size):
        step[0] += 1
        # A slow swell so the level moves rather than sitting on one number,
        # which is what a gate with hysteresis is built for.
        amplitude = 0.25 + 0.15 * ((step[0] % 8) / 8.0)
        time.sleep(0.005)
        return [[amplitude, -amplitude]] * 512

    return read, lambda: None, 48000


class _Strip:
    def __init__(self) -> None:
        self.writes: list[tuple[int, int, int]] = []
        self.lock = threading.Lock()

    def set_color_stream(self, red, green, blue, **_kwargs) -> bool:
        with self.lock:
            self.writes.append((red, green, blue))
        return True

    def count(self) -> int:
        with self.lock:
            return len(self.writes)


@pytest.fixture()
def window(monkeypatch):
    import app.ambient_ui_controller as ambient_module
    import app.fusion_ui_controller as fusion_module
    import app.music_ui_controller as music_module
    from app.main_window import MainWindow
    from app.music_controller import MusicController

    app = QApplication.instance() or QApplication([])
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=_FakeSct))
    for module in (ambient_module, fusion_module, music_module):
        monkeypatch.setattr(module, "can_use", lambda _feature: True)
    monkeypatch.setattr(
        MusicController, "_open_loopback_reader", staticmethod(_music_reader), raising=True
    )

    win = MainWindow()
    win._show_error = lambda *_a, **_k: None
    win._is_connected = True
    strip = _Strip()
    monkeypatch.setattr(win._ble, "set_color_stream", strip.set_color_stream, raising=False)
    win._strip = strip
    app.processEvents()
    try:
        yield win
    finally:
        win._fusion_ui.shutdown()
        win._ambient_ui.shutdown()
        win._music_ui.shutdown()
        win._ble.shutdown()
        win.close()


def _click_second_segment(segment) -> None:
    """Press the right-hand half of a two-option control, as a person would."""
    segment.resize(200, 40)
    QTest.mouseClick(segment, Qt.LeftButton, pos=QPoint(150, 20))


def _pump(app, seconds: float, until=None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.01)
    app.processEvents()


def _section(report: str, heading: str) -> str:
    """One block of the diagnostics text, found by its heading line.

    Blocks are separated by a blank line and start with their heading, so a
    block is matched whole. Splitting on the bare word instead cut the Live
    Sync block in half, because "Fusion" also appears inside it.
    """
    for block in report.split('\n\n'):
        if block.startswith(heading):
            return block
    raise AssertionError("no " + heading + " block in the report")


def test_screen_plus_music_from_the_card_to_the_strip_and_back(window) -> None:
    app = QApplication.instance()
    strip = window._strip

    # ── choose the mode, by clicking it ───────────────────────────────
    _click_second_segment(window.fusion_mode_segment)
    assert window.fusion_mode_segment.current_key() == "screen_music"
    assert window._fusion_ui.mode() == "screen_music"
    assert window._settings["fusion"]["mode"] == "screen_music", "the choice was not saved"

    # The music card stops offering its own start: one mode, one stop button.
    assert window.music_toggle_button.isEnabled() is False
    assert window.music_status_label.text() == window._tr("fusion.music_shared")

    # ── start it, by pressing the card's button ───────────────────────
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    assert window._fusion_ui.is_running(), "the mode did not start"

    _pump(app, 5.0, until=lambda: strip.count() >= 4)
    assert strip.count() >= 2, "nothing reached the strip"

    # ── the colour is the screen's, the brightness is the music's ─────
    stats = window._fusion_ui.stats()
    assert stats["mode"] == "screen_music"
    assert stats["music_stale"] is False, "the music was never heard"
    assert stats["music_activity"] > 0.0
    assert stats["brightness_factor"] < 1.0, "the music moved nothing"

    written = strip.writes[-1]
    assert written[0] > written[1] > written[2], f"not the screen's colour: {written}"

    # Compared against the composed frame rather than the raw screen colour: the
    # capture pipeline shapes what it grabs — saturation, gamma and the chosen
    # profile all move it — so the base is legitimately not the pixel value the
    # fake screen returned. What has to hold is that the write is that base
    # scaled: the ratios between the channels survive, the level drops.
    base = window._fusion_ui.coordinator().last_frame().rgb
    assert max(written) < max(base), f"the music never dimmed anything: {written} of {base}"
    assert base[0] > base[1] > base[2], f"the base lost the screen's hue: {base}"
    ratio = max(written) / max(base)
    for index in range(3):
        assert abs(written[index] - base[index] * ratio) <= 12, (
            f"the hue moved: written {written}, base {base}"
        )

    # ── stop it, from the same button ─────────────────────────────────
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    app.processEvents()
    settled = strip.count()

    assert window._fusion_ui.is_running() is False
    assert window._ambient_ui.is_running() is False
    assert window._music_ui.is_running() is False

    _pump(app, 0.5)
    assert strip.count() == settled, "commands kept going out after the stop"


def test_going_back_to_screen_only_leaves_music_its_own_card(window) -> None:
    """The old standalone mode has to keep working exactly as it did."""
    _click_second_segment(window.fusion_mode_segment)
    assert window.music_toggle_button.isEnabled() is False

    segment = window.fusion_mode_segment
    segment.resize(200, 40)
    QTest.mouseClick(segment, Qt.LeftButton, pos=QPoint(50, 20))

    assert window._fusion_ui.mode() == "screen"
    assert window.music_toggle_button.isEnabled() is True
    assert window._settings["fusion"]["mode"] == "screen"


def test_the_saved_mode_comes_back_through_the_settings_file(window) -> None:
    """Reloading the same dictionary this window is already holding proves
    nothing: the choice has to survive the file, and the file is validated on
    the way in. A key the validator does not know about is dropped there,
    silently, and the mode comes back as Screen on the next launch."""
    from app.storage import load_settings

    _click_second_segment(window.fusion_mode_segment)

    reloaded = load_settings()

    assert reloaded.get("fusion", {}).get("mode") == "screen_music", (
        f"the choice did not survive the file: {reloaded.get('fusion')}"
    )

    # And a fresh controller reading that file lands on the same mode.
    window._fusion_ui.set_mode("screen", persist=False)
    window._settings = reloaded
    window._fusion_ui.load_settings()
    window._ambient_ui.sync_mode_segment()

    assert window._fusion_ui.mode() == "screen_music"
    assert window.fusion_mode_segment.current_key() == "screen_music"


def test_the_mode_travels_in_a_backup(window) -> None:
    """It is a choice someone made, so it belongs with the scenes and the
    hotkeys rather than with the machine's own settings."""
    import json

    from app.backup import build_backup, inspect_backup, restore_into

    _click_second_segment(window.fusion_mode_segment)
    document = build_backup(window._settings)

    check = inspect_backup(json.dumps(document))
    restored, _report = restore_into({"fusion": {"mode": "screen"}}, check.payload)

    assert restored["fusion"]["mode"] == "screen_music"


def test_the_tray_and_a_hotkey_do_not_tear_music_out_of_the_shared_mode(window) -> None:
    """Pressing "music" while the combined mode is chosen has to mean that mode.

    Starting the old standalone reaction instead would take the strip off the
    screen — and the tray tick would then say music is on for a mode nobody
    chose.
    """
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)

    # This is what both the tray entry and the global hotkey call.
    assert window._music_ui.toggle() is True
    app.processEvents()

    assert window._fusion_ui.is_running() is True
    assert window._music_ui.is_running() is True, "the tray tick would say music is off"
    assert window._music_ui._music.owns_output() is False, "music took the strip on its own"

    assert window._music_ui.toggle() is False
    app.processEvents()

    assert window._fusion_ui.is_running() is False
    assert window._ambient_ui.is_running() is False


def test_the_standalone_music_mode_is_untouched_when_the_screen_is_alone(window) -> None:
    """Back on Screen only, the old behaviour has to be exactly the old one."""
    app = QApplication.instance()
    assert window._fusion_ui.mode() == "screen"

    assert window._music_ui.toggle() is True
    app.processEvents()

    assert window._music_ui._music.owns_output() is True, "music stopped driving the strip"
    assert window._fusion_ui.is_running() is False

    assert window._music_ui.toggle() is False
    app.processEvents()
    assert window._music_ui.is_running() is False


def test_losing_the_audio_device_leaves_the_screen_running(window) -> None:
    """A microphone unplugged mid-run is the audio source's problem, not the
    mode's: the picture still drives the strip. But the interface must stop
    claiming "screen and music" while nothing is listening — and the music card
    must offer its own button back, because there is no longer anything shared
    to point at.
    """
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 5.0, until=lambda: window._strip.count() >= 3)
    assert window._strip.count() >= 1
    assert window.music_status_label.text() == window._tr("fusion.music_shared")

    # The device goes away, the way the controller really reports it.
    window._music_ui._music.stop()
    window._music_ui._on_failed("audio_capture_unavailable: device gone")
    app.processEvents()

    before = window._strip.count()
    _pump(app, 3.0, until=lambda: window._strip.count() > before)

    assert window._fusion_ui.is_running() is True, "the screen half stopped too"
    assert window._ambient_ui.is_running() is True
    assert window._strip.count() > before, "the screen stopped reaching the strip"

    assert window._fusion_ui.audio_lost() is True
    assert window._fusion_ui.stats()["audio_lost"] is True
    assert window._music_ui.is_running() is False, "the card still claimed music was on"
    assert window.music_toggle_button.isEnabled() is True, "no way back to music"
    assert window.music_status_label.text() == window._tr("fusion.audio_lost")
    assert window.ambient_status_label.text() == window._tr("fusion.audio_lost")

    # The mode itself is untouched: plugging the device back in resumes it.
    assert window._fusion_ui.mode() == "screen_music"
    assert window._settings["fusion"]["mode"] == "screen_music"


def test_the_restored_button_takes_the_audio_back_and_keeps_the_screen(window) -> None:
    """Pressed by a person, not called as a method. Its ordinary handler starts
    the old standalone reaction, which stops Screen Sync to take the strip —
    the opposite of what someone whose microphone came back is asking for."""
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 5.0, until=lambda: window._strip.count() >= 2)

    window._music_ui._music.stop()
    window._music_ui._on_failed("audio_capture_unavailable: device gone")
    app.processEvents()
    assert window._fusion_ui.audio_lost() is True
    assert window.music_toggle_button.isEnabled() is True

    QTest.mouseClick(window.music_toggle_button, Qt.LeftButton)
    app.processEvents()

    assert window._fusion_ui.audio_lost() is False
    assert window._music_ui._music.is_running() is True
    assert window._fusion_ui.is_running() is True, "the screen half was stopped"
    assert window._fusion_ui.mode() == "screen_music"
    assert window._music_ui._music.owns_output() is False, "music took the strip for itself"
    assert window.music_status_label.text() == window._tr("fusion.music_shared")


def test_a_power_cycle_clears_a_stale_audio_complaint(window) -> None:
    """The flag describes the device, so a start that opened it has to clear the
    flag — otherwise the card apologises for a microphone that is listening."""
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 5.0, until=lambda: window._strip.count() >= 2)

    window._music_ui._music.stop()
    window._music_ui._on_failed("audio_capture_unavailable: device gone")
    app.processEvents()
    assert window._fusion_ui.audio_lost() is True

    window.power_button.setChecked(False)
    window._toggle_power()
    window.power_button.setChecked(True)
    window._toggle_power()
    app.processEvents()

    assert window._music_ui._music.is_running() is True, "audio did not come back"
    assert window._fusion_ui.audio_lost() is False, "the card still says the device is gone"
    # And the cards say so too: healthy state behind an interface still
    # apologising is the same defect one layer up.
    assert window.music_status_label.text() == window._tr("fusion.music_shared")
    assert window.ambient_status_label.text() == window._tr("fusion.status.screen_music")
    assert window.music_toggle_button.isEnabled() is False, (
        "the recovery button is still offered for a device that came back"
    )


def test_the_report_does_not_credit_screen_sync_with_fusion_writes(window) -> None:
    """The numbers have to come from the controller that is actually asked, not
    from a flag a test passed in by hand. While Fusion owns the output, Screen
    Sync's own report must say so rather than print zeros for commands it never
    made."""
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 5.0, until=lambda: window._strip.count() >= 2)
    assert window._fusion_ui.is_running()

    stats = window._ambient_ui.stats()
    assert stats["link_owned_by_fusion"] is True

    report = window._diagnostics_ctrl.text(include_crashes=False)
    live_sync = _section(report, "Live Sync")
    fusion_block = _section(report, "Fusion")

    assert "link rejections:" not in live_sync, (
        "Screen Sync reported writes it never made: " + live_sync
    )
    assert "written by Fusion" in live_sync
    assert "commands:" in fusion_block, "the Fusion block did not report its own writes"


def test_the_report_still_describes_the_run_after_it_is_stopped(window) -> None:
    """The usual order: stop, then export. A block that only exists while
    running is a block nobody sees when they need it, and Screen Sync must not
    take the writes back the moment Fusion lets go of them."""
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 5.0, until=lambda: window._strip.count() >= 2)

    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    app.processEvents()
    assert window._fusion_ui.is_running() is False

    report = window._diagnostics_ctrl.text(include_crashes=False)
    fusion_block = _section(report, "Fusion")
    live_sync = _section(report, "Live Sync")

    assert "mode: screen_music" in fusion_block, "the finished run vanished from the report"
    assert "commands:" in fusion_block
    assert "link rejections:" not in live_sync, (
        "Screen Sync claimed the writes back once Fusion stopped: " + live_sync
    )
    assert "written by Fusion" in live_sync


def test_a_refused_frame_is_not_counted_as_a_command(window) -> None:
    """set_color_stream returns False when the link is busy — a dropped frame,
    not a sent one. Counting it as submitted reports a command that can never
    settle, so succeeded + failed never add up to submitted and the report is
    unreadable in exactly the situation it is exported for."""
    app = QApplication.instance()
    accepted = {"value": False}

    def busy_link(red, green, blue, observer=None, **_kwargs):
        if accepted["value"] and observer is not None:
            observer(True)
        return accepted["value"]

    window._ble.set_color_stream = busy_link
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 3.0, until=lambda: window._fusion_ui.stats()["link_rejections"] >= 2)

    refused = window._fusion_ui.stats()
    assert refused["link_rejections"] >= 1, "the link never refused anything"
    assert refused["commands_submitted"] == 0, "a refused frame was counted as sent"

    accepted["value"] = True
    _pump(app, 3.0, until=lambda: window._fusion_ui.stats()["commands_submitted"] >= 1)

    taken = window._fusion_ui.stats()
    assert taken["commands_submitted"] >= 1
    assert taken["commands_succeeded"] + taken["commands_failed"] <= taken["commands_submitted"]


def test_a_late_result_from_the_previous_run_is_not_credited_to_this_one(window) -> None:
    """Outcomes arrive on the BLE thread and can land after a stop. Without the
    run they settle into counters that were just zeroed, and a fresh session
    starts with someone else's numbers."""
    app = QApplication.instance()
    stale: list = []

    def slow_link(red, green, blue, observer=None, **_kwargs):
        if observer is not None:
            stale.append(observer)
        return True

    window._ble.set_color_stream = slow_link
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 3.0, until=lambda: bool(stale))
    assert stale, "nothing was ever written"

    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    app.processEvents()
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    app.processEvents()

    # The first run's write finally settles, after the second has begun.
    for observer in stale:
        observer(True)

    assert window._fusion_ui.stats()["commands_succeeded"] == 0, (
        "the previous run's result landed in this run's counters"
    )


def test_a_result_arriving_inside_its_own_write_cannot_outrun_it(window) -> None:
    """A write that fails immediately calls back before set_color_stream even
    returns. Counted there, a snapshot taken from inside the observer shows a
    success for a command that does not exist yet — succeeded above submitted,
    which makes the whole block unreadable."""
    app = QApplication.instance()
    seen: list[dict] = []

    def instant_link(red, green, blue, observer=None, **_kwargs):
        if observer is not None:
            # Synchronously, from inside the call, as a fast failure does.
            observer(True)
            seen.append(window._fusion_ui.stats())
        return True

    window._ble.set_color_stream = instant_link
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 3.0, until=lambda: bool(seen))
    assert seen, "nothing was ever written"

    for snapshot in seen:
        assert snapshot["commands_succeeded"] <= snapshot["commands_submitted"], (
            f"a result outran its own command: {snapshot}"
        )

    settled = window._fusion_ui.stats()
    assert settled["commands_submitted"] >= 1
    assert settled["commands_succeeded"] == settled["commands_submitted"], (
        f"the held results were never counted: {settled}"
    )


def test_an_earlier_write_settling_during_a_refusal_is_not_lost(window) -> None:
    """The sequence that loses a success.

    A is accepted and its result is still on the way. B is attempted, and A
    settles inside that attempt. B is then refused — and if the held result is
    addressed only to the run, A's success is discarded as though it belonged
    to B. One accepted command would then have no outcome at all, for ever.
    """
    app = QApplication.instance()
    pending: list = []
    attempts = {"count": 0}

    def link(red, green, blue, observer=None, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            pending.append(observer)  # A: accepted, result still to come
            return True
        if attempts["count"] == 2:
            # B: A's result lands inside this attempt, and then B is refused.
            for settle in pending:
                settle(True)
            pending.clear()
            return False
        return False

    window._ble.set_color_stream = link
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 3.0, until=lambda: attempts["count"] >= 2)
    assert attempts["count"] >= 2, "the second attempt never happened"

    stats = window._fusion_ui.stats()
    assert stats["commands_submitted"] == 1, stats
    assert stats["commands_succeeded"] == 1, (
        "the accepted write's success was thrown away with the refused one: " + str(stats)
    )
    assert stats["commands_failed"] == 0, stats
    assert stats["link_rejections"] >= 1, stats


# ── the combined mode's settings, where the mode is ───────────────────
def test_the_settings_button_belongs_to_the_combined_mode(window) -> None:
    """Nothing appears on the card until the mode that owns it is chosen, and
    the panel is collapsed — so the card and the guided tour are the size they
    always were."""
    # isHidden rather than isVisible: the window is never shown in a test, so
    # every widget in it reports invisible and the check would pass for the
    # wrong reason.
    assert window.fusion_tune_button.isHidden() is True
    assert window.fusion_tune_row.isHidden() is True

    _click_second_segment(window.fusion_mode_segment)

    assert window.fusion_tune_button.isHidden() is False
    assert window.fusion_tune_row.isHidden() is True, "the panel opened by itself"

    QTest.mouseClick(window.fusion_tune_button, Qt.LeftButton)
    assert window.fusion_tune_row.isHidden() is False
    assert window.fusion_tune_button._role == "accent_soft"

    # Back to Screen: the settings go with the mode, and come back collapsed.
    segment = window.fusion_mode_segment
    segment.resize(200, 40)
    QTest.mouseClick(segment, Qt.LeftButton, pos=QPoint(50, 20))

    assert window.fusion_tune_button.isHidden() is True
    assert window.fusion_tune_row.isHidden() is True
    assert window.fusion_tune_button._role == "ghost"
    _click_second_segment(window.fusion_mode_segment)
    assert window.fusion_tune_row.isHidden() is True, "it remembered being open"


def test_the_two_beat_sliders_are_one_value(window) -> None:
    """Not two settings that happen to agree. Whichever is moved, the other
    follows, one number is saved, and the running mode is told once."""
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    QTest.mouseClick(window.ambient_toggle_button, Qt.LeftButton)
    _pump(app, 5.0, until=lambda: window._strip.count() >= 2)

    window.fusion_beat_slider.setValue(90)
    app.processEvents()
    assert window.music_beat_slider.value() == 90, "the music card did not follow"
    assert window.music_beat_value.text() == "90%"
    assert window.fusion_beat_value.text() == "90%"
    assert window._settings["music"]["beat"] == 90, "one number was not saved"
    assert window._fusion_ui.coordinator()._beat_gain == pytest.approx(0.9)

    window.music_beat_slider.setValue(20)
    app.processEvents()
    assert window.fusion_beat_slider.value() == 20, "the screen card did not follow"
    assert window.fusion_beat_value.text() == "20%"
    assert window._settings["music"]["beat"] == 20
    assert window._fusion_ui.coordinator()._beat_gain == pytest.approx(0.2)


def test_the_two_source_choosers_are_one_value(window) -> None:
    """The same for the audio source, including reopening the device: the
    compact control hands the change to the music card's own handler rather
    than repeating what switching source means."""
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    assert window.fusion_source_segment.current_key() == "system"

    window.fusion_source_segment.resize(200, 40)
    QTest.mouseClick(window.fusion_source_segment, Qt.LeftButton, pos=QPoint(150, 20))
    app.processEvents()

    assert window.music_source_segment.current_key() == "mic"
    assert window._music_ui._source == "mic"

    window.music_source_segment.set_current("system", animate=False)
    window._music_ui._on_source_type_changed("system")
    app.processEvents()

    assert window.fusion_source_segment.current_key() == "system"


def test_the_collapsed_panel_holds_no_room_open(window) -> None:
    """What can be checked without a shown window: the row is genuinely hidden
    rather than merely empty, and it has a real size waiting for it. How much
    height it actually costs is measured with the real platform plugin — see
    test_fusion_mode_row_layout.
    """
    app = QApplication.instance()
    _click_second_segment(window.fusion_mode_segment)
    app.processEvents()

    assert window.fusion_tune_row.isHidden() is True
    assert window.fusion_tune_row.sizeHint().height() > 0, "the panel has nothing in it"

    QTest.mouseClick(window.fusion_tune_button, Qt.LeftButton)
    app.processEvents()
    assert window.fusion_tune_row.isHidden() is False
