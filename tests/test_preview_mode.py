"""Screen Sync with nothing plugged in, and a strip that comes and goes.

The rule the whole mode rests on is negative: a run started with no strip must
never write to one. Not when a strip is plugged in halfway through, not when the
power button is pressed, not through any door at all. So the strip here is not a
recorder of calls — it is an object that raises on being touched, and the test
that matters is the one where nothing raises.

The second half is the opposite case: a run that *was* lighting a strip, whose
link drops. That one keeps its intent and comes back, but only with a picture
captured after the break.
"""

from __future__ import annotations

import itertools
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from app.ambient_controller import ScreenSample
from app.fusion_coordinator import FusionCoordinator
from app.fusion_ui_controller import LIVE, PREVIEW, FusionUiController


class _UntouchableStrip:
    """Anything at all done to the radio is a failure, reported where it happened."""

    def __getattr__(self, name: str):
        raise AssertionError(f"a preview reached the strip: BLE.{name} was called")


class _CountingStrip:
    def __init__(self) -> None:
        self.writes: list[tuple[int, int, int]] = []
        self.powers: list[bool] = []

    def set_color_stream(self, red, green, blue, observer=None):
        self.writes.append((red, green, blue))
        if observer is not None:
            observer(True)
        return True

    def set_power(self, enabled) -> None:
        self.powers.append(bool(enabled))


class _Preview:
    """Stands in for the capsule beside the card."""

    def __init__(self) -> None:
        self.final: tuple[int, int, int] | None = None
        self.cleared = 0

    def set_final(self, rgb) -> None:
        self.final = tuple(int(v) for v in rgb)

    def clear_final(self) -> None:
        self.cleared += 1
        self.final = None

    def set_source(self, _rgb) -> None:
        pass


class _Button:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked
        self.presses = 0

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        self._checked = bool(value)
        self.presses += 1


class _Sources:
    """The two capture cards, handing out a new token on every start."""

    def __init__(self) -> None:
        self.token = 0
        self.starts = 0
        self.stops = 0

    def start_listening(self) -> int:
        self.starts += 1
        self.token += 1
        return self.token

    def stop_listening(self) -> None:
        self.stops += 1

    def has_audio_source(self) -> bool:
        return True

    def beat_strength(self) -> float:
        return 0.5

    def refresh_shared_state(self) -> None:
        pass

    def connect_samples(self, _slot) -> None:
        pass


class _Colour:
    def red(self) -> int:
        return 10

    def green(self) -> int:
        return 20

    def blue(self) -> int:
        return 30


class _Host(QObject):
    """A QObject, because the coordinator is parented to the window."""

    def __init__(self, *, connected: bool, ble) -> None:
        super().__init__()
        self._is_connected = connected
        self._ble = ble
        self._settings: dict = {}
        self._ambient_ui = _Sources()
        self._music_ui = _Sources()
        self.power_button = _Button(checked=False)
        self.power_toggles = 0
        self.ambient_preview = _Preview()
        self.brightness_slider = None

    def stop_streams(self, exclude=None) -> None:
        pass

    def _current_color(self):
        return _Colour()

    def _toggle_power(self) -> None:
        self.power_toggles += 1
        self._ble.set_power(self.power_button.isChecked())


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _controller(host, monkeypatch, *, licensed: bool = True) -> FusionUiController:
    import app.fusion_ui_controller as mod

    monkeypatch.setattr(mod, "can_use", lambda _feature: licensed)
    monkeypatch.setattr(mod, "save_settings", lambda _settings: None)
    controller = FusionUiController(host)
    controller.coordinator().frame_composed.connect(controller._on_frame_composed)
    return controller


_frames = itertools.count()


def _feed_screen(controller: FusionUiController, colour=None) -> None:
    """One captured frame, and the tick that composes it.

    The colour moves a little each time on purpose: the engine writes when the
    target changes, so a test feeding one unvarying colour gets a single write
    and then silence — which looks exactly like a link that has stopped working.
    """
    coordinator = controller.coordinator()
    if colour is None:
        colour = (180 + next(_frames) % 40, 120, 40)
    coordinator.submit_screen(
        ScreenSample(
            session_token=coordinator._screen_token,
            captured_at=time.monotonic(),
            rgb=colour,
        )
    )
    coordinator._tick()


def _run_until_shown(app, controller, host, *, limit: float = 3.0) -> None:
    deadline = time.monotonic() + limit
    while host.ambient_preview.final is None and time.monotonic() < deadline:
        _feed_screen(controller)
        app.processEvents()
        time.sleep(0.01)


# ── nothing reaches the strip ─────────────────────────────────────────
def test_a_preview_without_a_strip_never_touches_the_radio(app, monkeypatch) -> None:
    """Including the power button it would have pressed on the way in.

    Starting live switches the strip on first, so the colours have somewhere to
    land. A preview has no strip to switch on, and pressing it anyway would be
    this mode reaching hardware while claiming not to.
    """
    host = _Host(connected=False, ble=_UntouchableStrip())
    controller = _controller(host, monkeypatch)

    assert controller.intended_target() == PREVIEW
    assert controller.activate() is True
    try:
        assert controller.target() == PREVIEW
        assert controller.coordinator().measures_a_link() is False, (
            "a preview was set up to time a link it does not have"
        )
        _run_until_shown(app, controller, host)
        assert host.ambient_preview.final is not None, "the preview never showed anything"
        assert host.power_toggles == 0, "the power button was pressed for a preview"
        assert host.power_button.presses == 0
    finally:
        controller.stop_if_running()


def test_a_strip_plugged_in_during_a_preview_stays_dark(app, monkeypatch) -> None:
    """The target is decided once, by the press that started the run.

    Reading it live instead would mean that plugging a strip in — an act with
    nothing to do with this card — silently turns a quiet preview into a lit
    room. Whoever wants that presses the button again, which by then says so.
    """
    host = _Host(connected=False, ble=_UntouchableStrip())
    controller = _controller(host, monkeypatch)
    controller.activate()
    try:
        _run_until_shown(app, controller, host)

        host._is_connected = True  # the strip turns up
        controller.note_link_back()  # and announces itself
        for _ in range(20):
            _feed_screen(controller)
            app.processEvents()
            time.sleep(0.01)

        assert controller.target() == PREVIEW, "a preview promoted itself to a live run"
        assert controller.status_key() == "fusion.preview.strip_unused"
    finally:
        controller.stop_if_running()


def test_a_free_licence_previews_instead_of_lighting(app, monkeypatch) -> None:
    """The mode is Pro. Watching what it would do is not.

    What must not happen is the halfway state: a Free run that lights the strip,
    or a Free card that says it is running when nothing is."""
    host = _Host(connected=True, ble=_UntouchableStrip())
    controller = _controller(host, monkeypatch, licensed=False)

    assert controller.intended_target() == PREVIEW
    assert controller.live_unavailable_reason() == "fusion.needs_pro"
    assert controller.activate() is True
    try:
        _run_until_shown(app, controller, host)
        assert host.ambient_preview.final is not None
        assert controller.status_key() == "fusion.preview.strip_unused"
    finally:
        controller.stop_if_running()


def test_the_power_button_leaves_a_preview_alone(app, monkeypatch) -> None:
    """It switches a strip on and off. A preview has no strip in it to switch.

    Obeying it would make one button mean two different things depending on what
    happens to be plugged in — and would stop the capture of somebody who was
    only ever looking at the screen.
    """
    host = _Host(connected=False, ble=_UntouchableStrip())
    controller = _controller(host, monkeypatch)
    controller.activate()
    try:
        _run_until_shown(app, controller, host)
        starts_before = host._ambient_ui.starts

        controller.set_powered(False)

        assert controller.is_running() is True, "the preview was stopped by the power button"
        assert host._ambient_ui.stops == 0, "the capture was stopped"
        assert host._ambient_ui.starts == starts_before
    finally:
        controller.stop_if_running()


# ── what the card shows is what was delivered ─────────────────────────
def test_the_shown_colour_is_the_one_that_was_delivered(app, monkeypatch) -> None:
    """Byte for byte, and taken from the delivery rather than worked out again.

    A preview that recomputed the colour from the same parts would be a second
    copy of the rounding rule, and the two would eventually disagree about a
    number nobody could then explain.
    """
    delivered: list[tuple[int, int, int]] = []

    class _Watched(FusionCoordinator):
        def _deliver(self, red, green, blue, token, beat_id):
            accepted = super()._deliver(red, green, blue, token, beat_id)
            if accepted is not False:
                delivered.append((red, green, blue))
            return accepted

    import app.fusion_ui_controller as mod

    monkeypatch.setattr(mod, "FusionCoordinator", _Watched)
    host = _Host(connected=False, ble=_UntouchableStrip())
    controller = _controller(host, monkeypatch)
    controller.activate()
    try:
        _run_until_shown(app, controller, host)
        assert delivered, "nothing was delivered"
        assert host.ambient_preview.final == delivered[-1]
    finally:
        controller.stop_if_running()


def test_a_frame_with_nothing_to_show_clears_the_preview(app, monkeypatch) -> None:
    """A screen that stopped arriving must not leave its last colour sitting
    there looking current. Absence is shown as absence."""
    host = _Host(connected=False, ble=_UntouchableStrip())
    controller = _controller(host, monkeypatch)
    controller.activate()
    try:
        _run_until_shown(app, controller, host)
        assert host.ambient_preview.final is not None

        # Nothing further is captured, so the base goes stale on its own.
        coordinator = controller.coordinator()
        deadline = time.monotonic() + 3.0
        while host.ambient_preview.final is not None and time.monotonic() < deadline:
            coordinator._tick()
            app.processEvents()
            time.sleep(0.02)

        assert host.ambient_preview.cleared >= 1, "the stale colour stayed on screen"
        assert host.ambient_preview.final is None
    finally:
        controller.stop_if_running()


# ── a live run whose strip comes and goes ─────────────────────────────
def test_a_live_run_survives_a_lost_link_and_waits_for_a_new_frame(app, monkeypatch) -> None:
    """The intent is kept, the writing stops, and the return is not immediate.

    What is held when the link breaks describes a screen from before it broke.
    Handing that to the strip the moment it answers is the stale frame this
    design refuses everywhere else, so the capture is taken again from scratch
    and writing waits for a picture from after the break.
    """
    strip = _CountingStrip()
    host = _Host(connected=True, ble=strip)
    controller = _controller(host, monkeypatch)

    assert controller.intended_target() == LIVE
    controller.activate()
    try:
        deadline = time.monotonic() + 3.0
        while not strip.writes and time.monotonic() < deadline:
            _feed_screen(controller)
            app.processEvents()
            time.sleep(0.01)
        assert strip.writes, "a live run never wrote to the strip"
        assert controller.coordinator().measures_a_link() is True
        token_before = controller.coordinator()._screen_token

        host._is_connected = False
        controller.note_link_lost()
        assert controller.status_key() == "fusion.preview.link_lost"
        assert controller.coordinator().measures_a_link() is False

        wrote_before = len(strip.writes)
        for _ in range(20):
            _feed_screen(controller)
            app.processEvents()
            time.sleep(0.01)
        assert len(strip.writes) == wrote_before, "a dead link was written to"
        assert controller.is_running() is True, "the run was torn down over a radio"

        host._is_connected = True
        controller.note_link_back()
        assert controller.status_key() == "fusion.preview.waiting_frame"
        assert controller.coordinator()._screen_token != token_before, (
            "the capture kept its old token, so a frame from before the break "
            "would still be accepted as current"
        )
        assert len(strip.writes) == wrote_before, "writing resumed before a fresh frame"

        deadline = time.monotonic() + 3.0
        while len(strip.writes) == wrote_before and time.monotonic() < deadline:
            _feed_screen(controller)
            app.processEvents()
            time.sleep(0.01)
        assert len(strip.writes) > wrote_before, "the strip never came back"
        assert controller.coordinator().measures_a_link() is True
        assert controller.status_key() == "fusion.status.screen"
    finally:
        controller.stop_if_running()
