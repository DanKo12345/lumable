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

import app.music_controller as module
import app.music_ui_controller as music_ui_module
from app.main_layout import select_section
from app.music_controller import OWNER_FUSION, OWNER_OUTPUT, OWNER_PREVIEW, MusicController, MusicOptions


class _Device:
    """Counts opens and closes; each read waits for a block, as a device does."""

    def __init__(self, *, fail: bool = False) -> None:
        self.opens = 0
        self.closes = 0
        self.fail = fail

    def reader(self, _options):
        self.opens += 1
        if self.fail:
            raise OSError("device removed")

        def read(_size):
            sleep(0.005)
            return [[0.2, 0.2]] * 256

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
        return _Device().reader(options)

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
    timers = [value for value in vars(ui).values() if isinstance(value, QTimer)]
    assert timers == [ui._meter_timer] and ui._meter_timer.interval() == 50
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
        assert window.music_reaction_section.isEnabled(), "Fusion's listening left the sliders locked"
        assert not window.music_bands_row.graphicsEffect().isEnabled(), "the bands stayed faded"
    finally:
        ui.stop_listening()
    assert not window.music_reaction_section.isEnabled()


def test_a_check_can_be_tuned_without_pro(window, monkeypatch):
    monkeypatch.setattr(music_ui_module, "can_use", lambda feature: False)
    _press_check(window)
    assert window.music_reaction_section.isEnabled(), "the check could not try the sliders"
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
    monkeypatch.setattr(music_ui_module, "list_audio_inputs", lambda: [])
    ui = window._music_ui
    ui._on_source_type_changed("mic")
    try:
        window.music_gate_slider.setValue(value)
        ui._apply_options()
        threshold = MusicController._manual_gate(ui._music.options())
        assert ui._gate_value_for_rms(threshold) == pytest.approx(value)
    finally:
        window.music_gate_slider.setValue(16)
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
