"""The sound check and the one capture it shares.

A check listens without the strip, and it shares a single capture with the music
reaction and with Fusion instead of opening a second one. These pin who may hold
that capture, what joining or leaving does to it, what the meters are given, and
when a check has to end. No audio device is opened: capture is faked at the
boundary, as in the other music tests.
"""

from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import threading
from time import monotonic, sleep

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import app.music_calibration as music_calibration_module
import app.music_controller as module
import app.music_ui_controller as music_ui_module
from app.main_layout import select_section
from app.music_controller import (
    OWNER_CALIBRATION,
    OWNER_FUSION,
    OWNER_OUTPUT,
    OWNER_PREVIEW,
    MusicController,
    MusicOptions,
)


class _Device:
    """Counts opens and closes; each read waits for a block, as a device does."""

    def __init__(self, *, fail: bool = False, level: float = 0.2) -> None:
        self.opens = 0
        self.closes = 0
        self.fail = fail
        self.level = level

    def reader(self, _options):
        self.opens += 1
        if self.fail:
            raise OSError("device removed")

        def read(_size):
            sleep(0.005)
            return [[self.level, self.level]] * 256

        def close():
            self.closes += 1

        return read, close, 48000


def _until(predicate, timeout: float = 3.0) -> None:
    app = QApplication.instance() or QApplication([])
    deadline = monotonic() + timeout
    while not predicate():
        assert monotonic() < deadline, "timed out waiting"
        app.processEvents()
        sleep(0.005)


@pytest.fixture()
def device(monkeypatch):
    made = _Device()
    monkeypatch.setattr(MusicController, "_open_loopback_reader", lambda self, options: made.reader(options))
    return made


@pytest.fixture()
def controller(device):
    made = MusicController()
    made.configure(source="system")
    yield made
    made.stop()


# ── who holds the capture ─────────────────────────────────────────────
def test_the_capture_is_held_by_named_owners_and_asking_twice_changes_nothing(controller, device):
    first = controller.acquire(OWNER_PREVIEW)
    assert controller.acquire(OWNER_PREVIEW) == first
    _until(lambda: device.opens == 1)
    assert controller.owners() == {OWNER_PREVIEW}
    controller.release(OWNER_PREVIEW)
    assert not controller.is_running(), "one release did not close what one owner held"
    with pytest.raises(ValueError):
        controller.acquire("screen")


def test_the_first_owner_opens_the_device_and_the_last_one_closes_it(controller, device):
    controller.acquire(OWNER_PREVIEW)
    controller.acquire(OWNER_FUSION)
    _until(lambda: device.opens == 1)
    controller.release(OWNER_PREVIEW)
    assert controller.is_running() and device.closes == 0
    controller.release(OWNER_FUSION)
    assert not controller.is_running()
    assert (device.opens, device.closes) == (1, 1)


def test_turning_the_reaction_on_during_a_check_only_starts_the_strip_stream(controller, device):
    token = controller.acquire(OWNER_PREVIEW)
    _until(lambda: device.opens == 1)
    assert controller.acquire(OWNER_OUTPUT, lambda *rgb: None) == token
    assert controller.owns_output()
    assert device.opens == 1, "the device was reopened"
    assert controller.session_token() == token


def test_turning_the_reaction_off_keeps_the_check_listening(controller, device):
    controller.acquire(OWNER_PREVIEW)
    controller.acquire(OWNER_OUTPUT, lambda *rgb: None)
    _until(lambda: device.opens == 1)
    controller.release(OWNER_OUTPUT)
    assert not controller.owns_output()
    assert controller.is_running() and device.closes == 0
    assert controller.owners() == {OWNER_PREVIEW}


def test_a_new_device_replaces_one_capture_with_one_and_keeps_its_owners(controller, device):
    token = controller.acquire(OWNER_PREVIEW)
    controller.acquire(OWNER_OUTPUT, lambda *rgb: None)
    _until(lambda: device.opens == 1)
    old = controller._thread
    assert controller.restart_capture() == token + 1 == controller.session_token()
    _until(lambda: device.opens == 2)
    assert not old.is_alive()
    assert controller._thread is not old and controller._thread.is_alive()
    assert controller.owners() == {OWNER_PREVIEW, OWNER_OUTPUT}
    assert controller.owns_output(), "the strip stream stopped with the device"


def test_a_capture_that_gives_up_leaves_no_owners_behind(monkeypatch):
    monkeypatch.setattr(module, "CAPTURE_RETRY_DELAYS", ())
    broken = _Device(fail=True)
    monkeypatch.setattr(MusicController, "_open_loopback_reader", lambda self, options: broken.reader(options))
    app = QApplication.instance() or QApplication([])
    controller = MusicController()
    failures = []
    controller.failed.connect(failures.append)
    try:
        token = controller.acquire(OWNER_PREVIEW)
        _until(lambda: not controller.is_running() and bool(failures))
        app.processEvents()
        assert controller.owners() == frozenset()
        assert controller._owners == set(), "a dead capture still lists who held it"
        broken.fail = False
        assert controller.acquire(OWNER_PREVIEW) == token + 1, "holding again did not open a new session"
    finally:
        controller.stop()


# ── what the meters are given ─────────────────────────────────────────
def test_the_meters_get_one_frozen_reading_of_what_the_colour_is_made_of(controller, monkeypatch):
    given = []
    real = module.bands_to_rgb

    def spy(bass, mid, treble, level, **kwargs):
        given.append((bass, mid, treble))
        return real(bass, mid, treble, level, **kwargs)

    monkeypatch.setattr(module, "bands_to_rgb", spy)
    token = controller.acquire(OWNER_PREVIEW)
    _until(lambda: controller.meter_reading().captured_at > 0)
    first = controller.meter_reading()
    _until(lambda: controller.meter_reading() is not first)
    latest = controller.meter_reading()
    assert first.session_token == latest.session_token == token
    assert (latest.bass, latest.mid, latest.treble) in given
    with pytest.raises(dataclasses.FrozenInstanceError):
        latest.bass = 0.0


def test_clipping_is_judged_before_the_channels_are_mixed_down():
    controller = MusicController()
    options = MusicOptions()
    opposite = [[1.0, -1.0]] * 512
    assert module.analyze_block(opposite, 48000)[3] == 0.0, "the mixdown is silence"
    assert controller._process_block(opposite, 48000, options).clipped is True
    assert controller._process_block([[0.8, 0.8]] * 512, 48000, options).clipped is False


# ── the check in the window ───────────────────────────────────────────
# Every device the window's capture opened, across the whole file.
_WINDOW_OPENS: list[int] = []
# The level the window's device plays: a loud steady tone unless a test needs a room.
_WINDOW_LEVEL = [0.2]


@pytest.fixture(scope="module")
def window():
    """One window for the whole file, with the capture faked at the device."""
    from app import storage
    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    data_dir = pathlib.Path(tempfile.mkdtemp(prefix="lumable-sound-check-"))
    real_paths = (storage.DATA_DIR, storage.SETTINGS_PATH, storage.PROFILES_PATH)
    storage.DATA_DIR = data_dir
    storage.SETTINGS_PATH = data_dir / "settings.json"
    storage.PROFILES_PATH = data_dir / "profiles.json"
    real_reader = MusicController._open_loopback_reader

    real_mic_reader = MusicController._open_mic_reader

    def counted(self, options):
        _WINDOW_OPENS.append(1)
        return _Device(level=_WINDOW_LEVEL[0]).reader(options)

    # Both sources, so a test on the microphone never opens a real one.
    MusicController._open_loopback_reader = counted
    MusicController._open_mic_reader = counted
    made = MainWindow()
    made.show()
    app.processEvents()
    try:
        yield made
    finally:
        made._music_ui.shutdown()
        made._ble.shutdown()
        made.close()
        MusicController._open_loopback_reader = real_reader
        MusicController._open_mic_reader = real_mic_reader
        storage.DATA_DIR, storage.SETTINGS_PATH, storage.PROFILES_PATH = real_paths
        app.processEvents()


@pytest.fixture(autouse=True)
def _on_the_music_page(request):
    if "window" not in request.fixturenames:
        yield
        return
    window = request.getfixturevalue("window")
    window._music_ui.note_session(locked=False, asleep=False)
    window.showNormal()
    select_section(window, "music")
    QApplication.instance().processEvents()
    yield
    window._music_ui._cancel_calibration()
    window._music_ui.stop_sound_check()
    window._music_ui.stop_if_running()
    window._music_ui._music.stop()
    window.showNormal()


def _press_check(window) -> None:
    QTest.mouseClick(window.music_check_button, Qt.LeftButton)


def test_opening_the_music_page_does_not_start_listening(window):
    select_section(window, "color")
    select_section(window, "music")
    QApplication.instance().processEvents()
    assert not window._music_ui._music.is_running()


def test_a_sound_check_listens_without_pro_and_writes_nothing_to_the_strip(window, monkeypatch):
    monkeypatch.setattr(music_ui_module, "can_use", lambda feature: False)
    writes = []
    monkeypatch.setattr(window._ble, "set_color_stream", lambda *rgb: writes.append(rgb))
    _press_check(window)
    music = window._music_ui._music
    _until(lambda: music.meter_reading().captured_at > 0)
    assert music.owners() == {OWNER_PREVIEW}
    assert not music.owns_output()
    sleep(0.2)
    QApplication.instance().processEvents()
    assert writes == []


def test_a_second_press_stops_the_check_at_once(window):
    _press_check(window)
    assert window._music_ui.is_checking_sound()
    _press_check(window)
    assert not window._music_ui.is_checking_sound()
    assert not window._music_ui._music.is_running()


def test_a_check_stops_by_itself_after_thirty_seconds(window, monkeypatch):
    assert music_ui_module.SOUND_CHECK_SECONDS == 30
    _press_check(window)
    started = monotonic()
    monkeypatch.setattr(music_ui_module, "monotonic", lambda: started + 29.9)
    window._music_ui._refresh_meters()
    assert window._music_ui.is_checking_sound()
    monkeypatch.setattr(music_ui_module, "monotonic", lambda: started + 30.01)
    window._music_ui._refresh_meters()
    assert not window._music_ui.is_checking_sound()
    assert not window._music_ui._music.is_running()


def _device_error(window):
    # The way the controller reports a device that has gone for good.
    window._music_ui._music.stop()
    window._music_ui._on_failed("audio_capture_unavailable: device gone")


@pytest.mark.parametrize(
    "goes_away",
    [
        lambda window: select_section(window, "color"),
        lambda window: window.hide(),
        lambda window: window.showMinimized(),
        lambda window: window._windows_session.locked.emit(),
        lambda window: window._windows_session.slept.emit(),
        _device_error,
    ],
    ids=["page", "hidden", "minimised", "locked", "asleep", "device error"],
)
def test_a_check_ends_when_nobody_can_see_it(window, goes_away, monkeypatch):
    # A failed device is reported in a dialog; nobody is here to close it.
    monkeypatch.setattr(window, "_show_error", lambda *args, **kwargs: None)
    _press_check(window)
    assert window._music_ui.is_checking_sound()
    goes_away(window)
    QApplication.instance().processEvents()
    assert not window._music_ui.is_checking_sound()
    assert not window._music_ui._music.is_running()


def test_leaving_the_page_while_music_reacts_stops_only_the_meters(window):
    ui = window._music_ui
    ui._music.start_output(lambda *rgb: True)
    ui._update_meter_timer()
    # One timer draws the meters. The only other one lets a calibration's result
    # go once, and never repeats.
    timers = [value for value in vars(ui).values() if isinstance(value, QTimer)]
    assert [timer for timer in timers if not timer.isSingleShot()] == [ui._meter_timer]
    assert ui._meter_timer.interval() == 50
    assert len(timers) == 2 and ui._hold_timer in timers
    assert ui._meter_timer.isActive()
    select_section(window, "color")
    assert not ui._meter_timer.isActive(), "the meters kept drawing a page nobody sees"
    assert ui._music.is_running() and ui._music.owns_output(), "leaving the page stopped the music"
    select_section(window, "music")
    assert ui._meter_timer.isActive()
    ui._music.release(OWNER_OUTPUT)


def test_the_check_neither_adds_a_card_nor_makes_this_one_taller(window):
    from app.widgets import GlassCard

    page = window._nav_pages["music"]
    cards = page.findChildren(GlassCard)
    idle = window.music_card.sizeHint().height()
    _press_check(window)
    _until(lambda: window._music_ui._music.meter_reading().captured_at > 0)
    QApplication.instance().processEvents()
    assert page.findChildren(GlassCard) == cards
    assert window.music_card.sizeHint().height() == idle
    assert window.music_colors_label.height() == window.music_reaction_label.height()


# ── review follow-ups ─────────────────────────────────────────────────
def test_a_restart_that_cannot_stop_the_old_capture_says_so(monkeypatch):
    monkeypatch.setattr(module, "CAPTURE_STOP_TIMEOUT_S", 0.05)
    stuck = threading.Event()
    let_go = threading.Event()
    opens = []

    def reader(self, options):
        opens.append(1)

        def read(_size):
            # A read that sits in the driver and will not come back in time.
            stuck.set()
            let_go.wait(5.0)
            return [[0.0, 0.0]] * 64

        return read, (lambda: None), 48000

    monkeypatch.setattr(MusicController, "_open_loopback_reader", reader)
    controller = MusicController()
    try:
        controller.acquire(OWNER_FUSION)
        assert stuck.wait(2.0)
        assert controller.restart_capture() == 0, "a restart that did not happen reported a session"
        assert controller.owners() == frozenset()
        assert len(opens) == 1, "a second capture was opened beside the stuck one"
    finally:
        let_go.set()
        controller.stop()


def test_the_combined_mode_leaves_the_music_controls_live(window, monkeypatch):
    monkeypatch.setattr(music_ui_module, "can_use", lambda feature: True)
    ui = window._music_ui
    ui.start_listening()
    try:
        assert window.music_speed_slider.isEnabled(), "Fusion's listening left the sliders locked"
        assert not window.music_bands_row.graphicsEffect().isEnabled(), "the bands stayed faded"
    finally:
        ui.stop_listening()
    assert not window.music_speed_slider.isEnabled()


def test_a_check_can_be_tuned_without_pro(window, monkeypatch):
    monkeypatch.setattr(music_ui_module, "can_use", lambda feature: False)
    _press_check(window)
    assert window.music_speed_slider.isEnabled(), "the check could not try the sliders"
    assert window.music_bands_row.isEnabled()


@pytest.mark.parametrize("taker", ["reaction", "fusion"])
def test_a_light_mode_takes_over_the_check_without_reopening_the_device(window, monkeypatch, taker):
    monkeypatch.setattr(window._ble, "set_color_stream", lambda *rgb: True)
    ui = window._music_ui
    _press_check(window)
    _until(lambda: ui._music.meter_reading().captured_at > 0)
    opened = len(_WINDOW_OPENS)
    powered = window.power_button.isChecked()
    try:
        if taker == "reaction":
            window.power_button.setChecked(True)
            ui._start()
        else:
            ui.start_listening()
        assert not ui.is_checking_sound(), "the check kept running under a light mode"
        assert ui._music.owners() == {OWNER_OUTPUT if taker == "reaction" else OWNER_FUSION}
        assert len(_WINDOW_OPENS) == opened, "the device was reopened"
    finally:
        ui.stop_listening()
        window.power_button.setChecked(powered)


@pytest.mark.parametrize("away, back", [("locked", "unlocked"), ("slept", "woke")])
def test_a_locked_or_sleeping_machine_stops_the_meters_but_not_the_music(window, away, back):
    ui = window._music_ui
    ui._music.start_output(lambda *rgb: True)
    ui._update_meter_timer()
    assert ui._meter_timer.isActive()
    getattr(window._windows_session, away).emit()
    assert not ui._meter_timer.isActive(), "the meters kept drawing on a locked screen"
    assert ui._music.owns_output(), "locking stopped the music"
    getattr(window._windows_session, back).emit()
    assert ui._meter_timer.isActive()
    ui._music.release(OWNER_OUTPUT)


# ── the room's level on the noise gate ────────────────────────────────
def test_the_meters_carry_the_rms_the_gate_judged(controller):
    # Loud and then quiet: a smoothed value would still be on its way down,
    # while the gate — and so the room level — judges the quiet block itself.
    options = MusicOptions()
    loud, quiet = [[0.4, 0.4]] * 512, [[0.01, 0.01]] * 512
    controller._process_block(loud, 48000, options)
    assert controller._process_block(quiet, 48000, options).rms == pytest.approx(
        module.analyze_block(quiet, 48000)[3]
    )
    controller.acquire(OWNER_PREVIEW)
    _until(lambda: controller.meter_reading().captured_at > 0)
    assert controller.meter_reading().rms == pytest.approx(module.analyze_block([[0.2, 0.2]] * 256, 48000)[3])


@pytest.mark.parametrize("value", [0, 16, 50, 100])
def test_the_room_level_and_the_gate_handle_share_one_scale(window, monkeypatch, value):
    from app.music_gate import GATE_DB_DEFAULT, slider_for_db

    monkeypatch.setattr(music_ui_module, "list_audio_inputs", lambda: [])
    ui = window._music_ui
    ui._on_source_type_changed("mic")
    try:
        window.music_gate_slider.setValue(value)
        ui._apply_options()
        threshold = MusicController._manual_gate(ui._music.options())
        assert ui._gate_value_for_rms(threshold) == pytest.approx(value)
    finally:
        window.music_gate_slider.setValue(round(slider_for_db(GATE_DB_DEFAULT)))
        ui._on_source_type_changed("system")


def test_the_room_level_is_shown_on_the_gate_only_for_the_microphone(window, monkeypatch):
    monkeypatch.setattr(music_ui_module, "list_audio_inputs", lambda: [])
    ui = window._music_ui
    gate = window.music_gate_slider
    ui._on_source_type_changed("mic")
    try:
        _press_check(window)
        _until(lambda: (gate.live_level() or 0.0) > 0.0)
        ui._on_source_type_changed("system")
        ui._refresh_meters()
        assert gate.live_level() is None, "system audio showed a room level on a gate it does not have"
        ui._on_source_type_changed("mic")
        _until(lambda: (gate.live_level() or 0.0) > 0.0)
        _press_check(window)
        assert gate.live_level() is None, "the level stayed on the gate after listening stopped"
    finally:
        ui._on_source_type_changed("system")


def test_a_slider_without_a_live_level_paints_exactly_as_before():
    from PySide6.QtGui import QImage

    from app.widgets.liquid_slider import LiquidSlider

    QApplication.instance() or QApplication([])

    def render(slider):
        image = QImage(slider.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        slider.render(image)
        return image

    plain = LiquidSlider("green")
    used = LiquidSlider("green")
    for slider in (plain, used):
        slider.resize(300, 56)
        slider.jump_to(40)
    used.set_live_level(20.0, passing=True)
    assert render(used) != render(plain), "the live level was not drawn"
    used.set_live_level(None)
    assert render(used) == render(plain), "a slider without a live level no longer paints as before"


# ── a swatch never touches its meter ──────────────────────────────────
@pytest.mark.parametrize("scale", [0.78, 0.85, 0.9, 1.0, 1.1])  # the whole range resolve_ui_scale allows
def test_a_band_meter_keeps_a_clear_gap_below_its_swatch_at_every_ui_scale(scale):
    from app.panels.music_panel import _band_row_margins

    def sz(value):
        return max(1, round(value * scale))

    top, bottom, thickness = _band_row_margins(sz)
    assert top >= 0
    assert top + bottom == 2 * sz(4), "the band row changed height"
    assert bottom - thickness >= 4, "the swatch touches its meter"


def test_the_swatches_clear_their_meters_in_the_window(window):
    for band in ("bass", "mid", "treble"):
        swatch = getattr(window, f"music_{band}_swatch")
        meter = window.music_band_meters[band]
        assert meter.geometry().top() - swatch.geometry().bottom() - 1 >= 4, f"the {band} swatch touches its meter"
        assert swatch.parentWidget().height() == window._sz(32) + 2 * window._sz(4), "the band row changed height"


# ── lines as long as the band is bright ───────────────────────────────
def test_the_meters_get_the_brightness_the_colour_was_made_with(monkeypatch):
    import numpy as np

    given = []
    real = module.bands_to_rgb

    def spy(bass, mid, treble, level, **kwargs):
        given.append(level)
        return real(bass, mid, treble, level, **kwargs)

    monkeypatch.setattr(module, "bands_to_rgb", spy)
    controller = MusicController()
    options = MusicOptions(beat_strength=1.0)
    t = np.arange(1024) / 48000
    steady = (np.sin(2 * np.pi * 1000 * t) * 0.05).astype(np.float32)
    hit = (steady + np.sin(2 * np.pi * 60 * t) * 0.08).astype(np.float32)
    for _ in range(6):
        controller._process_block(steady, 48000, options)
    struck = controller._process_block(hit, 48000, options)
    assert struck.beat_envelope > 0.0, "the test needs a beat to fold in"
    assert struck.color_level == given[-1], "the meters were not given the colour's brightness"
    assert struck.color_level > struck.level, "the beat was folded into level, which Fusion reads bare"


def test_the_capture_hands_the_brightness_on_to_the_meters(controller, monkeypatch):
    # Built in the block and read by the interface: the capture thread is what
    # carries it across, and a reading without it would draw every line at zero.
    given = []
    real = module.bands_to_rgb

    def spy(bass, mid, treble, level, **kwargs):
        given.append(level)
        return real(bass, mid, treble, level, **kwargs)

    monkeypatch.setattr(module, "bands_to_rgb", spy)
    controller.acquire(OWNER_PREVIEW)
    _until(lambda: controller.meter_reading().captured_at > 0 and not controller.meter_reading().silent)
    reading = controller.meter_reading()
    assert reading.color_level > 0.0, "the meters were handed no brightness"
    assert reading.color_level in given


def test_a_meter_line_is_its_band_share_times_the_brightness():
    from app.music_controller import MeterReading

    reading = MeterReading(bass=1.0, mid=0.5, treble=0.25, color_level=0.4, silent=False)
    assert music_ui_module.MusicUiController._meter_targets(reading, True) == pytest.approx((0.4, 0.2, 0.1))
    assert music_ui_module.MusicUiController._meter_targets(reading, False) == (0.0, 0.0, 0.0)


# ── the gate in decibels ──────────────────────────────────────────────
def test_the_gate_reads_out_in_decibels_and_is_saved_as_decibels(window):
    from app.music_gate import GATE_DB_DEFAULT, db_for_slider, format_db, slider_for_db

    slider = window.music_gate_slider
    try:
        slider.setValue(23)
        assert window.music_gate_value.text() == window._tr("music.gate_value", value=format_db(db_for_slider(23)))
        saved = window._settings["music"]
        assert saved["gate_db"] == pytest.approx(db_for_slider(23), abs=0.05)
        assert "gate" not in saved, "the old percent was written beside the decibels"
    finally:
        slider.setValue(round(slider_for_db(GATE_DB_DEFAULT)))


def test_an_old_settings_file_keeps_its_microphone_threshold(window, monkeypatch):
    from app.storage import validate_music

    monkeypatch.setattr(music_ui_module, "list_audio_inputs", lambda: [])
    ui = window._music_ui
    kept = window._settings.get("music")
    try:
        # What an older build saved: a linear 16 % on the microphone.
        window._settings["music"] = validate_music({"gate": 16, "source": "mic"})
        ui.sync_controls()
        ui._apply_options()
        assert MusicController._manual_gate(ui._music.options()) == pytest.approx(0.02, rel=0.01)
    finally:
        window._settings["music"] = kept
        ui.sync_controls()


# ── calibrating the microphone gate ───────────────────────────────────
ROOM_RMS = 0.001  # a steady room at -60 dBFS


@pytest.fixture()
def quiet_mic(window, monkeypatch):
    monkeypatch.setattr(music_ui_module, "list_audio_inputs", lambda: [])
    monkeypatch.setattr(window, "_show_error", lambda *args, **kwargs: None)
    # The window is shared: an earlier test may have left a result on show.
    window._music_ui._restore_status()
    _WINDOW_LEVEL[0] = ROOM_RMS
    window._music_ui._on_source_type_changed("mic")
    window._music_ui._set_gate_visible_instant(True)
    yield window
    window._music_ui._cancel_calibration()
    window._music_ui._on_source_type_changed("system")
    _WINDOW_LEVEL[0] = 0.2


def _press_calibrate(window) -> None:
    QTest.mouseClick(window.music_calibrate_button, Qt.LeftButton)


def test_calibration_takes_over_the_check_without_reopening_the_device(quiet_mic):
    window = quiet_mic
    ui = window._music_ui
    _press_check(window)
    _until(lambda: ui._music.meter_reading().captured_at > 0)
    opened = len(_WINDOW_OPENS)
    _press_calibrate(window)
    assert ui.is_calibrating() and not ui.is_checking_sound()
    assert ui._music.owners() == {OWNER_CALIBRATION}
    assert len(_WINDOW_OPENS) == opened, "the device was reopened"


def test_a_quiet_room_sets_the_gate_just_above_it_and_saves_it(quiet_mic):
    from math import ceil, log10

    from app.music_gate import db_for_slider, format_db, slider_for_db

    window = quiet_mic
    ui = window._music_ui
    _press_check(window)
    _press_calibrate(window)
    _until(lambda: ui._calibration is None, timeout=8.0)
    expected = ceil(slider_for_db(20 * log10(ROOM_RMS) + 8.0) - 1e-9)
    assert window.music_gate_slider.value() == expected
    assert window._settings["music"]["gate_db"] == pytest.approx(db_for_slider(expected), abs=0.05)
    assert window.music_status_label.text() == window._tr(
        "music.calibration_done", value=format_db(db_for_slider(expected))
    )
    assert OWNER_CALIBRATION not in ui._music.owners()


@pytest.mark.parametrize(
    "interrupt",
    [
        _press_calibrate,  # the one that hands back to the check
        lambda window: select_section(window, "color"),
        lambda window: window.hide(),
        lambda window: window.showMinimized(),
        lambda window: window._windows_session.locked.emit(),
        lambda window: window._windows_session.slept.emit(),
        _device_error,
        lambda window: window._music_ui._on_source_type_changed("system"),
        lambda window: window._music_ui._on_source_changed(),
    ],
    ids=["cancel", "page", "hidden", "minimised", "locked", "asleep", "device error", "source", "device"],
)
def test_an_interrupted_calibration_leaves_the_gate_as_it_was(quiet_mic, interrupt):
    window = quiet_mic
    ui = window._music_ui
    slider_before = window.music_gate_slider.value()
    saved_before = window._settings["music"].get("gate_db")
    _press_check(window)
    _press_calibrate(window)
    _until(lambda: ui._calibration is not None and ui._calibration.measured_seconds > 0.3)
    interrupt(window)
    QApplication.instance().processEvents()
    assert ui._calibration is None and not ui.is_calibrating()
    assert OWNER_CALIBRATION not in ui._music.owners()
    assert window.music_gate_slider.value() == slider_before, "the gate moved"
    assert window._settings["music"].get("gate_db") == saved_before, "a threshold was saved"
    resumes = interrupt is _press_calibrate
    assert ui.is_checking_sound() is resumes, "the check came back when it should not have, or not at all"


def test_a_calibration_that_hears_nothing_gives_up_without_saving(quiet_mic, monkeypatch):
    window = quiet_mic
    ui = window._music_ui
    monkeypatch.setattr(music_calibration_module, "TIMEOUT_S", 0.3)
    # A sample from another session: the capture never feeds it a block.
    monkeypatch.setattr(ui._music, "begin_noise_sample", lambda: music_calibration_module.NoiseSample(-1))
    slider_before = window.music_gate_slider.value()
    _press_check(window)
    _press_calibrate(window)
    _until(lambda: ui._calibration is None, timeout=3.0)
    assert window.music_gate_slider.value() == slider_before
    assert window.music_status_label.text() == window._tr("music.calibration_no_audio")
    assert not ui.is_checking_sound(), "a device that sent nothing handed back to a check"


def test_the_calibrate_button_keeps_one_width_in_every_language_at_the_largest_scale(monkeypatch):
    import app.main_window as main_window_module
    from app.constants import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
    from app.localization import localization_manager
    from app.ui_scale import MAX_SCALE

    monkeypatch.setattr(main_window_module, "resolve_ui_scale", lambda screen: MAX_SCALE)
    monkeypatch.setattr(music_ui_module, "list_audio_inputs", lambda: [])
    app = QApplication.instance() or QApplication([])
    made = main_window_module.MainWindow()
    language = localization_manager.language
    try:
        assert made._ui_scale == MAX_SCALE
        made.resize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        made.show()
        select_section(made, "music")
        made._music_ui._on_source_type_changed("mic")
        made._music_ui._set_gate_visible_instant(True)
        app.processEvents()
        button, row = made.music_calibrate_button, made.music_gate_row
        widths = set()
        for code in localization_manager.available_languages():
            localization_manager.set_language(code)
            made._ui_localization.apply_texts()
            app.processEvents()
            widths.add(button.width())
            for key in ("music.calibrate", "music.calibrate_cancel"):
                assert button.fontMetrics().horizontalAdvance(made._tr(key)) <= button.width(), f"{code}: {key} is cut"
            card = made.music_card
            assert made.music_gate_slider.width() == made.music_speed_slider.width(), (
                f"{code}: the gate slider is shorter than its neighbours"
            )
            assert made.music_gate_value.mapTo(card, made.music_gate_value.rect().topLeft()).x() == (
                made.music_speed_value.mapTo(card, made.music_speed_value.rect().topLeft()).x()
            ), f"{code}: the gate readout left the column of readouts"
            column = made.music_gate_label_column
            assert button.geometry().right() < column.width(), f"{code}: Calibrate spills out of the label column"
            assert row.height() <= made.music_speed_slider.height() + 2, f"{code}: the gate row grew taller"
        assert len(widths) == 1, f"the button changed width between languages: {widths}"
    finally:
        localization_manager.set_language(language)
        made._music_ui.shutdown()
        made._ble.shutdown()
        made.close()
        app.processEvents()


def test_calibration_starts_directly_with_the_reaction_off_and_no_pro(quiet_mic, monkeypatch):
    window = quiet_mic
    ui = window._music_ui
    monkeypatch.setattr(music_ui_module, "can_use", lambda feature: False)
    ui._apply_enabled_state()
    assert not ui.is_checking_sound() and not ui._reacting()
    assert window.music_calibrate_button.isEnabled(), "Calibrate needs nothing but a microphone"
    assert not window.music_gate_slider.isEnabled(), "the other controls came alive with it"
    opened = len(_WINDOW_OPENS)
    _press_calibrate(window)
    assert ui.is_calibrating()
    assert not window.music_check_button.isEnabled(), "a check could start over the calibration"
    _until(lambda: ui._calibration is None, timeout=8.0)
    assert len(_WINDOW_OPENS) == opened + 1, "the hand-over to the check reopened the device"
    assert ui._music.owners() == {OWNER_PREVIEW}
    left = ui._check_deadline - monotonic()
    assert 8.5 <= left <= music_ui_module.CHECK_AFTER_CALIBRATION_S, "no short look at the new gate"
    assert window.music_check_button.isEnabled()


def test_a_calibration_during_a_check_hands_back_the_time_that_was_left(quiet_mic):
    window = quiet_mic
    ui = window._music_ui
    _press_check(window)
    _until(lambda: ui._music.meter_reading().captured_at > 0)
    opened = len(_WINDOW_OPENS)
    left_before = ui._check_deadline - monotonic()
    _press_calibrate(window)
    _until(lambda: ui._calibration is None, timeout=8.0)
    assert ui.is_checking_sound() and ui._music.owners() == {OWNER_PREVIEW}
    assert len(_WINDOW_OPENS) == opened, "the device was reopened"
    assert ui._check_deadline - monotonic() == pytest.approx(left_before, abs=0.6)


def test_a_room_too_noisy_to_calibrate_still_hands_back_to_the_check(quiet_mic):
    window = quiet_mic
    ui = window._music_ui
    _WINDOW_LEVEL[0] = 0.2  # a loud steady tone: far above -30 dBFS
    slider_before = window.music_gate_slider.value()
    _press_check(window)
    _press_calibrate(window)
    _until(lambda: ui._calibration is None, timeout=8.0)
    assert window.music_status_label.text() == window._tr("music.calibration_too_noisy")
    assert window.music_gate_slider.value() == slider_before
    assert ui.is_checking_sound()


def test_a_calibration_owns_the_status_while_music_reacts_and_gives_it_back(quiet_mic, monkeypatch):
    window = quiet_mic
    ui = window._music_ui
    monkeypatch.setattr(music_ui_module, "CALIBRATION_RESULT_HOLD_S", 0.3)
    monkeypatch.setattr(window._ble, "set_color_stream", lambda *rgb: True)
    powered = window.power_button.isChecked()
    try:
        window.power_button.setChecked(True)
        ui._start()
        listening = window._tr("music.listening")
        assert window.music_status_label.text() == listening
        _press_calibrate(window)
        assert window.music_status_label.text() == window._tr("music.calibration_hold", seconds=3)
        _until(lambda: ui._calibration is None, timeout=8.0)
        assert window.music_status_label.text() != listening, "the result was never shown"
        _until(lambda: window.music_status_label.text() == listening, timeout=3.0)
        assert not ui.is_checking_sound(), "a check was started beside a running reaction"
    finally:
        ui.stop_if_running()
        window.power_button.setChecked(powered)


def test_the_calibration_is_fed_only_the_frames_that_arrived(monkeypatch):
    # A device may hand back an empty block. The rest of the pipeline treats it
    # as a whole one; a calibration must not count it as time in the room.
    from itertools import cycle

    import numpy as np

    fed = []

    class Recorded(music_calibration_module.NoiseSample):
        def add(self, seconds, rms, clipped):
            fed.append(seconds)
            super().add(seconds, rms, clipped)

    sizes = cycle([0, 128, 0, 0, 128])

    def reader(self, options):
        def read(_size):
            sleep(0.002)
            return np.full((next(sizes), 1), 0.001, np.float32)

        return read, (lambda: None), 48000

    monkeypatch.setattr(MusicController, "_open_mic_reader", reader)
    monkeypatch.setattr(module, "NoiseSample", Recorded)
    made = MusicController()
    made.configure(source="mic")
    try:
        made.acquire(OWNER_CALIBRATION)
        made.begin_noise_sample()
        _until(lambda: len(fed) >= 20)
    finally:
        made.stop()
    assert set(fed) == {128 / 48000}, "an empty block went in, or was counted as the size asked for"


def test_a_microphone_sending_a_broken_signal_is_not_calibrated_on(quiet_mic):
    window = quiet_mic
    ui = window._music_ui
    _WINDOW_LEVEL[0] = float("nan")
    slider_before = window.music_gate_slider.value()
    saved_before = window._settings["music"].get("gate_db")
    _press_calibrate(window)
    _until(lambda: ui._calibration is None, timeout=3.0)
    assert window.music_gate_slider.value() == slider_before, "the gate moved"
    assert window._settings["music"].get("gate_db") == saved_before, "a threshold was saved"
    assert window.music_status_label.text() == window._tr("music.calibration_no_audio")
    assert not ui.is_checking_sound(), "a broken signal handed back to a check"


def _result_on_show_then_nothing_listening(window, outcome):
    """Calibrate straight from a card that is off and end in ``outcome``."""
    ui = window._music_ui
    _press_calibrate(window)
    if outcome == "cancelled":
        _press_calibrate(window)
    else:
        _until(lambda: ui._calibration is None, timeout=8.0)
    assert not ui._music.owners(), "the test needs nobody left listening"
    _until(lambda: not ui._meter_timer.isActive(), timeout=1.0)


@pytest.mark.parametrize(
    "outcome",
    [music_calibration_module.UNSTABLE, music_calibration_module.TOO_NOISY, music_calibration_module.CLIPPED,
     "cancelled"],
)
def test_a_direct_result_goes_away_by_itself_with_nothing_listening(quiet_mic, monkeypatch, outcome):
    window = quiet_mic
    label = window.music_status_label
    monkeypatch.setattr(music_ui_module, "CALIBRATION_RESULT_HOLD_S", 0.3)
    monkeypatch.setattr(music_calibration_module, "judge",
                        lambda *args: music_calibration_module.Calibration(outcome))
    before = label.text()
    _result_on_show_then_nothing_listening(window, outcome)
    assert label.text() != before, "the result was never shown"
    _until(lambda: label.text() == before, timeout=2.0)


def test_leaving_the_page_while_a_result_is_on_show_still_ends_it(quiet_mic, monkeypatch):
    window = quiet_mic
    label = window.music_status_label
    monkeypatch.setattr(music_ui_module, "CALIBRATION_RESULT_HOLD_S", 0.3)
    monkeypatch.setattr(music_calibration_module, "judge",
                        lambda *args: music_calibration_module.Calibration(music_calibration_module.UNSTABLE))
    before = label.text()
    _result_on_show_then_nothing_listening(window, music_calibration_module.UNSTABLE)
    select_section(window, "color")
    _until(lambda: label.text() == before, timeout=2.0)


def test_calibrating_again_over_a_result_on_show_gives_back_the_words_from_before(quiet_mic, monkeypatch):
    window = quiet_mic
    label = window.music_status_label
    before = label.text()
    monkeypatch.setattr(music_ui_module, "CALIBRATION_RESULT_HOLD_S", 30.0)
    _press_calibrate(window)
    _press_calibrate(window)
    assert label.text() == window._tr("music.calibration_cancelled")
    monkeypatch.setattr(music_ui_module, "CALIBRATION_RESULT_HOLD_S", 0.3)
    _press_calibrate(window)  # again, while the first result is on show
    _press_calibrate(window)
    _until(lambda: label.text() == before, timeout=2.0)


@pytest.mark.parametrize("source, heard", [("system", True), ("mic", False)])
def test_opening_the_capture_starts_the_analyser_for_its_source(monkeypatch, source, heard):
    # Through the real path: acquire opens the session, the session resets the
    # analyser, and the capture thread feeds it quiet music from its first block.
    import numpy as np

    rng = np.random.default_rng(3)
    quiet = 10 ** (-44 / 20)

    def reader(self, options):
        def read(size):
            sleep(0.002)
            block = rng.standard_normal((size, 1)).astype(np.float32)
            return block * np.float32(quiet / float(np.sqrt(np.mean(block ** 2))))

        return read, (lambda: None), 48000

    monkeypatch.setattr(MusicController, "_open_loopback_reader", reader)
    monkeypatch.setattr(MusicController, "_open_mic_reader", reader)
    made = MusicController()
    # No manual gate, as the window configures it for system audio.
    made.configure(source=source, blocksize=256, noise_gate_rms=0.0)
    try:
        made.acquire(OWNER_PREVIEW)
        _until(lambda: made._analyzer.stats.blocks >= 60)
        stats = made._analyzer.stats
        silent, blocks = stats.silent_blocks, stats.blocks
    finally:
        made.stop()
    if heard:
        assert silent == 0, f"system audio took quiet music for silence: {silent} of {blocks} blocks"
    else:
        assert silent == blocks, "the microphone stopped learning its room from the first block"


def test_a_new_capture_forgets_the_lift(monkeypatch):
    import numpy as np

    from app.music_analysis import LEVEL_CEILING

    release = threading.Event()

    def reader(self, options):
        def read(size):
            release.wait(2.0)
            return np.zeros((size, 1), np.float32)

        return read, (lambda: None), 48000

    monkeypatch.setattr(MusicController, "_open_loopback_reader", reader)
    made = MusicController()
    made.configure(source="system", noise_gate_rms=0.0)
    quiet = 10 ** (-44 / 20)
    tone = (np.sin(2 * np.pi * 180 * np.arange(1024) / 48000) * quiet * np.sqrt(2)).astype(np.float32).reshape(-1, 1)
    for _ in range(60):
        made._process_block(tone, 48000, made.options())
    span = LEVEL_CEILING - made._analyzer.gate_for(0.0)
    assert made._loudness.gain_db(span) > 0.0, "the test needs a lift to forget"
    try:
        made.acquire(OWNER_PREVIEW)
        assert made._loudness.gain_db(span) == 0.0, "a new capture kept the last one's lift"
    finally:
        release.set()
        made.stop()


def test_the_lift_stays_under_the_strips_own_brightness(window, monkeypatch):
    # The reaction lifts quiet music in the colour it streams. The strip's own
    # brightness is the person's limit: never written by the reaction, and on a
    # driver that scales the colour itself, the stream at 3% stays under 3%.
    import numpy as np

    from app.ble_drivers.triones import TrionesDriver

    rate, rms, frames = 48000, 10 ** (-44 / 20), [0]

    def reader(self, options):
        def read(size):
            sleep(0.004)
            t = (frames[0] + np.arange(size)) / rate
            frames[0] += size
            mono = np.sin(2 * np.pi * 180 * t) * rms * np.sqrt(2)
            return np.stack([mono, mono], axis=1).astype(np.float32)

        return read, (lambda: None), rate

    monkeypatch.setattr(MusicController, "_open_loopback_reader", reader)
    # No strip is connected: an error dialog would wait for a click nobody makes.
    monkeypatch.setattr(window, "_show_error", lambda *args, **kwargs: None)
    sent, brightness_written = [], []
    monkeypatch.setattr(window._ble, "set_color_stream", lambda *rgb: sent.append(rgb) or True)
    monkeypatch.setattr(window._ble, "set_brightness", lambda value: brightness_written.append(value))
    ui = window._music_ui
    ui._on_source_type_changed("system")
    powered = window.power_button.isChecked()
    try:
        window.power_button.setChecked(True)
        ui._start()
        # Unlifted, -44 dBFS reaches about a fifth of the scale: under 60 of 255.
        _until(lambda: bool(sent) and max(sent[-1]) > 100, timeout=6.0)
    finally:
        ui.stop_if_running()
        window.power_button.setChecked(powered)

    assert brightness_written == [], "the reaction wrote the strip's brightness"
    driver = TrionesDriver()
    driver.remember_brightness(3)
    for rgb in sent:
        payload = driver.color_payloads(*rgb)[0]
        assert payload[0] == 0x56 and max(payload[1:4]) <= round(255 * 0.03), f"{rgb} went past the strip's 3%"


def _contrast(first, second) -> float:
    def luminance(colour):
        def linear(value):
            value /= 255.0
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        return 0.2126 * linear(colour.red()) + 0.7152 * linear(colour.green()) + 0.0722 * linear(colour.blue())

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _gate_slider_image(dark: bool, live: float | None, passing: bool):
    """The gate slider with its handle at 40, painted on its card, and where to look."""
    from PySide6.QtGui import QColor, QImage

    from app.theme import theme_manager
    from app.widgets.liquid_slider import LiquidSlider

    QApplication.instance() or QApplication([])
    was_dark = theme_manager.is_dark
    theme_manager.set_dark(dark)
    try:
        slider = LiquidSlider("green")
        slider.setRange(0, 100)
        slider.resize(400, 56)
        slider.jump_to(40)
        slider.set_live_level(live, passing=passing)
        image = QImage(slider.size(), QImage.Format_ARGB32_Premultiplied)
        # The card the gate sits on, opaque: the groove itself is translucent.
        image.fill(QColor(28, 29, 32) if dark else QColor(248, 248, 250))
        slider.render(image)
    finally:
        theme_manager.set_dark(was_dark)
    scale = slider._scale
    left, width = 14.0 * scale, slider.width() - 28.0 * scale

    def x_at(value):
        return left + width * value / 100.0

    return image, x_at, slider.height() / 2 + 3.0 * scale, 7.2 * scale


@pytest.mark.parametrize("passing", [False, True], ids=["below the gate", "getting through"])
@pytest.mark.parametrize("dark", [True, False], ids=["dark theme", "light theme"])
def test_the_live_level_reads_against_the_fill_and_the_empty_track(dark, passing):
    # The line runs from the start of the track: over the fill up to the handle,
    # then over the empty groove. Both parts have to be seen, in both themes, and
    # most of all while the room is still below the gate.
    image, x_at, cy, groove = _gate_slider_image(dark, 70.0, passing)
    beside = groove * 0.42  # inside the groove, just outside the line

    def against_its_surroundings(x):
        return _contrast(image.pixelColor(round(x), round(cy)), image.pixelColor(round(x), round(cy - beside)))

    over_fill, over_groove = against_its_surroundings(x_at(20)), against_its_surroundings(x_at(58))
    assert over_fill >= 3.0, f"the line is lost in the fill: {over_fill:.2f}:1"
    assert over_groove >= 2.0, f"the line is lost on the empty track: {over_groove:.2f}:1"


@pytest.mark.parametrize("dark", [True, False], ids=["dark theme", "light theme"])
def test_the_handle_stays_on_top_of_the_live_level(dark):
    with_line, x_at, cy, _ = _gate_slider_image(dark, 70.0, True)
    without, _, _, _ = _gate_slider_image(dark, None, False)
    centre = round(x_at(40))
    # The handle is 245/255 opaque by design, so whatever lies under it shows by
    # at most 10 levels. A line painted over it would differ by a hundred or more.
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            a = with_line.pixelColor(centre + dx, round(cy) + dy)
            b = without.pixelColor(centre + dx, round(cy) + dy)
            worst = max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))
            assert worst <= 255 - 245, f"the line shows through the handle at {dx},{dy}: {a.name()} vs {b.name()}"
