"""The real path: two capture threads, one coordinator, one write to the strip.

These run the actual controllers — screen capture against a fake screen, audio
against a fake device — wired to a real :class:`FusionCoordinator`, and watch
what reaches the BLE end. The claims worth making are about what does *not*
happen: no source writes on its own, and two sources do not mean twice the
commands.

The contract is deliberately about *streaming*. Power, a colour chosen by hand,
a scene and a DIY effect write to the strip directly and should — they are
single commands from a person. What must not exist is a second streaming route.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.ambient_controller import AmbientController, ScreenSample
from app.fusion_coordinator import FusionCoordinator
from app.music_controller import MusicController, MusicModulationSample


class _Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


class _Strip:
    """Every write that reaches the BLE end, and who asked for it."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int, int]] = []

    def sink(self, red, green, blue, *_labels) -> bool:
        self.writes.append((red, green, blue))
        return True


class _FakeShot:
    def __init__(self, colour) -> None:
        self.width = 4
        self.height = 4
        blue, green, red = colour[2], colour[1], colour[0]
        self.bgra = bytes([blue, green, red, 255] * 16)


class _FakeScreen:
    """A screen showing one flat colour, swappable mid-run."""

    colour = (200, 60, 40)

    monitors = [
        {"left": 0, "top": 0, "width": 8, "height": 8},
        {"left": 0, "top": 0, "width": 8, "height": 8},
    ]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def grab(self, _region):
        return _FakeShot(_FakeScreen.colour)


def _quiet_audio(_options):
    def read(_size):
        time.sleep(0.005)
        return [[0.3, 0.3]] * 1024

    return read, lambda: None, 48000


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def screen(monkeypatch):
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=_FakeScreen))
    _FakeScreen.colour = (200, 60, 40)
    made = AmbientController()
    yield made
    made.stop()


@pytest.fixture()
def music(monkeypatch):
    monkeypatch.setattr(
        MusicController, "_open_loopback_reader", staticmethod(_quiet_audio), raising=True
    )
    made = MusicController()
    made.configure(source="system")
    yield made
    made.stop()


def _drain(coordinator, clock, app, *, seconds: float, step: float = 0.05) -> None:
    """Tick a coordinator on a driven clock, the way its timer would.

    Composition runs on the injected clock so a stale frame can be reached in a
    line, but the engine paces its writes against real elapsed time and ticks on
    its own timer — so the event loop is run for real between steps. Two clocks
    on purpose: what is fresh is a question about the picture, how often to write
    is a question about the link.
    """
    for _ in range(max(1, int(seconds / step))):
        clock.advance(step)
        coordinator._tick()
        app.processEvents()
        time.sleep(0.02)
        app.processEvents()


def _drain_until_written(coordinator, clock, app, strip, *, limit: float = 3.0) -> None:
    """Tick until the engine has actually written, or give up loudly.

    The engine paces itself against real time, so "long enough" is not a number
    a test can pick once and rely on across machines and load.
    """
    deadline = time.monotonic() + limit
    while not strip.writes and time.monotonic() < deadline:
        _drain(coordinator, clock, app, seconds=0.05)
    assert strip.writes, "nothing was written even while the screen was fresh"


def _pump(app, seconds: float, until=None) -> None:
    """Run the Qt event loop for real time, which is where the ticks happen."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.005)
    app.processEvents()


# ── the real path, end to end ─────────────────────────────────────────
def test_the_screen_colour_reaches_the_strip_through_the_coordinator(app, screen) -> None:
    strip = _Strip()
    coordinator = FusionCoordinator(tick_ms=20, send_interval_ms=40)
    screen.screen_sampled.connect(coordinator.submit_screen, Qt.QueuedConnection)
    coordinator.start(strip.sink, mode="screen")
    coordinator.expect_screen(screen.start_listening())
    try:
        _pump(app, 2.0, until=lambda: len(strip.writes) >= 3)
    finally:
        screen.stop()
        coordinator.stop()

    assert strip.writes, "nothing ever reached the strip"
    red, green, blue = strip.writes[-1]
    assert red > green and red > blue, f"not the colour on the screen: {strip.writes[-1]}"


def test_neither_source_writes_to_the_strip_on_its_own(app, screen, music) -> None:
    """The claim that matters. Both capture threads run at full speed and the
    only thing holding a sink is the coordinator."""
    strip = _Strip()
    coordinator = FusionCoordinator(tick_ms=20, send_interval_ms=40)
    screen.screen_sampled.connect(coordinator.submit_screen, Qt.QueuedConnection)
    music.modulation_sampled.connect(coordinator.submit_music, Qt.QueuedConnection)
    coordinator.start(strip.sink, mode="screen_music")
    coordinator.expect_screen(screen.start_listening())
    coordinator.expect_music(music.start_listening())
    owned = []
    try:
        _pump(app, 2.0, until=lambda: len(strip.writes) >= 5)
        # Asked while both are capturing. After stop() every engine is idle and
        # the check would pass for the wrong reason.
        owned = [screen.owns_output(), music.owns_output()]
    finally:
        screen.stop()
        music.stop()
        coordinator.stop()

    assert strip.writes, "nothing reached the strip, so this proves nothing"
    assert owned == [False, False], "a source was driving the strip alongside Fusion"


def test_two_sources_do_not_double_the_commands(app, screen, music) -> None:
    """Screen frames and audio blocks arrive at unrelated rates. If each one
    caused a write, the strip would get roughly the sum of the two — and which
    arrived last would decide the colour."""
    strip = _Strip()
    interval_ms = 60
    coordinator = FusionCoordinator(tick_ms=15, send_interval_ms=interval_ms)
    screen.screen_sampled.connect(coordinator.submit_screen, Qt.QueuedConnection)
    music.modulation_sampled.connect(coordinator.submit_music, Qt.QueuedConnection)
    coordinator.start(strip.sink, mode="screen_music")
    coordinator.expect_screen(screen.start_listening())
    coordinator.expect_music(music.start_listening())
    started = time.monotonic()
    try:
        _pump(app, 2.0)
    finally:
        elapsed = time.monotonic() - started
        screen.stop()
        music.stop()
        coordinator.stop()

    ceiling = elapsed / (interval_ms / 1000.0) + 2
    assert len(strip.writes) <= ceiling, (
        f"{len(strip.writes)} writes in {elapsed:.1f}s, above the paced ceiling {ceiling:.0f}"
    )
    assert len(strip.writes) >= 3, "the pacing swallowed everything"


def test_a_sample_does_not_compose_a_frame_by_itself() -> None:
    """Composing where the sample lands would put the decision on whichever
    capture thread happened to arrive last, and the frame rate would become the
    sum of two unrelated sources rather than one tick."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)

    coordinator.submit_screen(
        ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 20, 30))
    )

    assert coordinator.last_frame().should_send is False, "a sample composed on its own"
    coordinator._tick()
    assert coordinator.last_frame().rgb == (10, 20, 30)


def test_blocking_output_by_hand_accepts_nothing_further(app) -> None:
    """One guarantee on its own: from the moment the call returns, no further
    command is accepted. The base is fresh throughout, so nothing else can
    explain a write."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
        _drain_until_written(coordinator, clock, app, strip)

        coordinator.set_output_allowed(False)
        accepted = len(strip.writes)
        # Everything that could still deliver one, with the base still fresh.
        _drain(coordinator, clock, app, seconds=0.3)
    finally:
        coordinator.stop()

    assert len(strip.writes) == accepted, (
        f"{len(strip.writes) - accepted} commands accepted after the block: {strip.writes}"
    )


def test_a_stale_base_stops_the_output_at_the_next_tick(app) -> None:
    """The other guarantee, and it belongs to the tick.

    Moving the clock does not make anything stale by itself — nothing has read
    it yet. Staleness is noticed when the coordinator next composes, which in a
    running app is at most one tick away, and it is from there that no further
    command may be accepted. Asserting over the window before that would be
    asking the engine to know something no code has looked at.
    """
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
        _drain_until_written(coordinator, clock, app, strip)

        clock.advance(5.0)
        coordinator._tick()
        noticed = coordinator.last_frame()
        accepted = len(strip.writes)

        _drain(coordinator, clock, app, seconds=0.3)
    finally:
        coordinator.stop()

    assert noticed.should_send is False
    assert noticed.reason == "base_stale"
    assert len(strip.writes) == accepted, (
        f"{len(strip.writes) - accepted} commands accepted after the base went stale"
    )


# ── late and out-of-order samples ─────────────────────────────────────
def test_a_screen_frame_from_a_previous_run_is_refused() -> None:
    """A queued frame emitted just before a stop can be delivered after the next
    start. Composed, it would put the previous session's colour on the strip."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(7)

    coordinator.submit_screen(ScreenSample(session_token=6, captured_at=clock.now, rgb=(9, 9, 9)))
    coordinator.submit_screen(
        ScreenSample(session_token=7, captured_at=clock.now, rgb=(10, 20, 30))
    )
    coordinator._tick()

    assert coordinator.last_frame().rgb == (10, 20, 30)
    assert coordinator.dropped_samples()[0] == 1


def test_a_music_block_from_a_previous_run_is_refused() -> None:
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_music(3)

    coordinator.submit_music(MusicModulationSample(session_token=2, captured_at=clock.now))

    assert coordinator.dropped_samples()[1] == 1


def test_a_late_music_block_is_judged_by_when_it_was_captured() -> None:
    """Delivery is not capture. A block held by the event loop and composed as
    if it were fresh is the reason silence would never settle."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)
    coordinator.expect_screen(1)

    coordinator.submit_screen(
        ScreenSample(session_token=1, captured_at=clock.now, rgb=(200, 120, 40))
    )
    # Captured a second ago, delivered only now.
    coordinator.submit_music(
        MusicModulationSample(
            session_token=1, captured_at=clock.now - 1.0, level=0.0, block_seconds=0.02
        )
    )
    coordinator._tick()

    assert coordinator.last_frame().music_stale is True


def test_a_late_screen_frame_stops_the_output_rather_than_repeating(app) -> None:
    """A frozen picture looks exactly like a working one, which is what makes it
    worse than sending nothing."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.submit_screen(
        ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
    )
    coordinator._tick()
    assert coordinator.last_frame().should_send is True

    clock.advance(5.0)
    coordinator._tick()

    assert coordinator.last_frame().should_send is False
    assert coordinator.last_frame().reason == "base_stale"


def test_both_sources_arriving_at_once_make_one_frame() -> None:
    """The tick is what decides, so simultaneous events are not a race about
    which one wins — they are both simply in the same frame."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)

    coordinator.submit_screen(
        ScreenSample(session_token=1, captured_at=clock.now, rgb=(200, 120, 40))
    )
    coordinator.submit_music(
        MusicModulationSample(session_token=1, captured_at=clock.now, level=0.5)
    )
    coordinator._tick()
    frame = coordinator.last_frame()

    assert frame.rgb == (200, 120, 40)
    assert frame.base_source == "screen"
    assert frame.music_stale is False


def test_a_burst_of_samples_composes_the_newest_and_not_a_backlog() -> None:
    """Capture threads are faster than the tick. What arrived in between is
    replaced, not queued, or the strip would fall further behind the longer it
    ran."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)

    for value in range(1, 40):
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(value, value, value))
        )
    coordinator._tick()

    assert coordinator.last_frame().rgb == (39, 39, 39)


def test_samples_from_two_threads_do_not_tear_a_frame() -> None:
    """Both sources push while the tick composes. A frame must be one screen
    sample and one music sample, never half of each."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)
    stop = threading.Event()
    frames: list = []

    def push_screen() -> None:
        while not stop.is_set():
            coordinator.submit_screen(
                ScreenSample(session_token=1, captured_at=clock.now, rgb=(120, 120, 120))
            )

    def push_music() -> None:
        while not stop.is_set():
            coordinator.submit_music(
                MusicModulationSample(session_token=1, captured_at=clock.now, level=0.5)
            )

    workers = [threading.Thread(target=push_screen), threading.Thread(target=push_music)]
    for worker in workers:
        worker.start()
    try:
        for _ in range(200):
            coordinator._tick()
            frames.append(coordinator.last_frame())
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=5)

    composed = [frame for frame in frames if frame.should_send]
    assert composed, "nothing composed while the threads were pushing"
    assert all(frame.rgb == (120, 120, 120) for frame in composed)


# ── power ─────────────────────────────────────────────────────────────
def test_power_off_stops_the_writes_and_keeps_the_mode() -> None:
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.start(strip.sink, mode="screen_music")
    try:
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()

        coordinator.set_output_allowed(False)
        clock.advance(0.05)
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
    finally:
        coordinator.stop()

    assert coordinator.last_frame().should_send is False
    assert coordinator.last_frame().reason == "output_blocked"
    assert coordinator.mode() == "screen_music"


# ── brightness_factor rides in the colour ────────────────────────────────────
def test_brightness_is_folded_into_the_colour_not_sent_beside_it(app) -> None:
    """A separate brightness_factor command on every audio block would double the
    traffic on a link that manages about ten writes a second."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)
    coordinator.start(strip.sink, mode="screen_music")
    try:
        # Settle with quiet music so the modulation is fully wound in.
        for index in range(80):
            clock.advance(0.05)
            coordinator.submit_screen(
                ScreenSample(session_token=1, captured_at=clock.now, rgb=(200, 200, 200))
            )
            coordinator.submit_music(
                MusicModulationSample(
                    session_token=1, captured_at=clock.now, level=0.0, block_seconds=0.02
                )
            )
            coordinator._tick()
            if index >= 70:
                # Only the settled end needs the engine to actually write.
                app.processEvents()
                time.sleep(0.02)
                app.processEvents()
    finally:
        coordinator.stop()

    frame = coordinator.last_frame()
    assert frame.brightness_factor < 0.7, "the music was not modulating at all"
    assert frame.rgb == (200, 200, 200), "the composed colour was dimmed twice"
    # And the dimming actually left the coordinator: the frame keeps the screen's
    # colour, the write carries it scaled.
    written = strip.writes[-1]
    assert written == pytest.approx(
        tuple(round(200 * frame.brightness_factor) for _ in range(3)), abs=2
    ), f"brightness_factor never reached the strip: {written}"


# ── power acts on all three states ────────────────────────────────────
class _Sources:
    """Stands in for the screen and the microphone: records, hands out tokens."""

    def __init__(self) -> None:
        self.running = False
        self.starts = 0
        self.stops = 0
        self._token = 100

    def start(self) -> tuple[int, int]:
        self.running = True
        self.starts += 1
        self._token += 1
        return (self._token, self._token)

    def stop(self) -> None:
        self.running = False
        self.stops += 1


def test_power_off_stops_capture_instead_of_running_it_for_nothing() -> None:
    """Grabbing the screen twenty times a second and holding a microphone open
    for a strip that is off costs battery and puts a recording indicator on
    someone's taskbar with nothing to explain it."""
    clock = _Clock()
    sources = _Sources()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(_Strip().sink, mode="screen_music")
    try:
        coordinator.set_powered(True)
        assert sources.running is True

        coordinator.set_powered(False)
    finally:
        coordinator.stop()

    assert sources.running is False
    assert coordinator.mode() == "screen_music", "the choice was forgotten"


def test_power_on_starts_capture_again_and_waits_for_a_fresh_frame() -> None:
    """The already-agreed rule, now with the sources following it: what was
    captured before the strip went off describes a screen from minutes ago."""
    clock = _Clock()
    sources = _Sources()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.set_powered(True)
        first_token = sources._token
        coordinator.submit_screen(
            ScreenSample(session_token=first_token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
        assert coordinator.last_frame().should_send is True

        coordinator.set_powered(False)
        clock.advance(120.0)
        coordinator.set_powered(True)
        coordinator._tick()
        stale_frame = coordinator.last_frame()

        # A frame from the run before, arriving late, is not what comes back.
        coordinator.submit_screen(
            ScreenSample(session_token=first_token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
        still_nothing = coordinator.last_frame()

        clock.advance(0.05)
        coordinator.submit_screen(
            ScreenSample(session_token=sources._token, captured_at=clock.now, rgb=(30, 40, 50))
        )
        coordinator._tick()
        fresh = coordinator.last_frame()
    finally:
        coordinator.stop()

    assert sources.starts == 2
    assert stale_frame.should_send is False and stale_frame.reason == "no_base"
    assert still_nothing.should_send is False, "the previous run's frame came back"
    assert fresh.rgb == (30, 40, 50)


def test_nothing_is_written_between_power_off_and_the_first_fresh_frame(app) -> None:
    clock = _Clock()
    sources = _Sources()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.set_powered(True)
        coordinator.submit_screen(
            ScreenSample(session_token=sources._token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        _drain_until_written(coordinator, clock, app, strip)
        before_off = len(strip.writes)

        coordinator.set_powered(False)
        _drain(coordinator, clock, app, seconds=0.3)
        after_off = len(strip.writes)

        coordinator.set_powered(True)
        _drain(coordinator, clock, app, seconds=0.3)
    finally:
        coordinator.stop()

    assert after_off == before_off, "writes continued after the strip was switched off"
    assert len(strip.writes) == after_off, "a colour went out before any fresh frame"


# ── the brightness slider stays the strip's own ceiling ───────────────
class _Backend:
    """A BLE facade that records which commands were asked for."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def set_color_stream(self, red, green, blue, *_labels) -> bool:
        self.calls.append("color")
        return True

    def set_brightness(self, _value) -> bool:
        self.calls.append("brightness")
        return True


def test_no_hardware_brightness_command_is_sent_on_audio_blocks(app) -> None:
    """The slider is the strip's ceiling and belongs to the person who set it.
    Fusion moves the colour underneath it, one command per frame — a brightness
    command per audio block would both fight the slider and double the traffic
    on a link that manages about ten writes a second."""
    clock = _Clock()
    backend = _Backend()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)
    coordinator.start(backend.set_color_stream, mode="screen_music")
    try:
        for _ in range(60):
            clock.advance(0.05)
            coordinator.submit_screen(
                ScreenSample(session_token=1, captured_at=clock.now, rgb=(200, 200, 200))
            )
            coordinator.submit_music(
                MusicModulationSample(
                    session_token=1, captured_at=clock.now, level=0.1, block_seconds=0.02
                )
            )
            coordinator._tick()
            app.processEvents()
            time.sleep(0.005)
    finally:
        coordinator.stop()

    assert "color" in backend.calls, "nothing was written at all"
    assert "brightness" not in backend.calls


class _EagerSources:
    """A device that hands over a sample from inside its own start and stop.

    A capture thread joined during ``stop()`` can run one more block, and a
    device can deliver something the moment it is opened. An ordinary late
    callback usually misses the dangerous window; this one lands in it every
    time, and ticks there too, because a real event loop can run inside a join.
    """

    def __init__(self, coordinator, clock) -> None:
        self.coordinator = coordinator
        self.clock = clock
        self.token = 100
        self.running = False

    def _deliver(self, colour) -> None:
        self.coordinator.submit_screen(
            ScreenSample(session_token=self.token, captured_at=self.clock.now, rgb=colour)
        )
        # Whatever else is happening, a tick can land here.
        self.coordinator._tick()

    def start(self) -> tuple[int, int]:
        self.running = True
        self.token += 1
        # Delivered while starting, before the coordinator has been told the new
        # token: the strip is still off as far as anything here knows.
        self._deliver((255, 0, 0))
        return (self.token, 0)

    def stop(self) -> None:
        # One last frame on the way out, exactly in the window.
        self._deliver((255, 0, 0))
        self.running = False


def test_a_sample_delivered_inside_stop_cannot_reach_the_strip(app) -> None:
    """The window the order exists to close. Refusing permission after stopping
    the sources leaves room for one more colour on a strip that is off."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    sources = _EagerSources(coordinator, clock)
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.set_powered(True)
        clock.advance(0.05)
        coordinator.submit_screen(
            ScreenSample(session_token=sources.token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        _drain_until_written(coordinator, clock, app, strip)
        before_off = len(strip.writes)

        coordinator.set_powered(False)
        _drain(coordinator, clock, app, seconds=0.3)
    finally:
        coordinator.stop()

    assert len(strip.writes) == before_off, (
        f"{len(strip.writes) - before_off} colours went out during or after power off"
    )
    assert coordinator.last_frame().should_send is False


def test_a_sample_delivered_inside_start_does_not_beat_the_first_real_frame(app) -> None:
    """Coming back on, a device's opening sample describes the room or the
    screen from before the light was on. Permission is granted last so it has
    nowhere to go."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    sources = _EagerSources(coordinator, clock)
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.set_powered(True)
        after_start = coordinator.last_frame()

        clock.advance(0.05)
        coordinator.submit_screen(
            ScreenSample(session_token=sources.token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
        first_real = coordinator.last_frame()
    finally:
        coordinator.stop()

    assert after_start.should_send is False, "the opening sample was sent"
    assert after_start.reason == "no_base"
    assert first_real.rgb == (10, 200, 90)


def test_the_light_never_comes_back_on_black(app) -> None:
    """The engine starts from a colour, and its own is black. Waking it when
    power returns rather than when there is a frame worth sending puts a black
    write on the strip in the moment someone is looking at it."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    sources = _Sources()
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.set_powered(True)
        coordinator.submit_screen(
            ScreenSample(session_token=sources._token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        _drain_until_written(coordinator, clock, app, strip)
        coordinator.set_powered(False)
        _drain(coordinator, clock, app, seconds=0.3)

        coordinator.set_powered(True)
        coordinator.submit_screen(
            ScreenSample(session_token=sources._token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        _drain(coordinator, clock, app, seconds=0.3)
    finally:
        coordinator.stop()

    assert (0, 0, 0) not in strip.writes, f"a black frame was written: {strip.writes}"
    assert strip.writes[-1] != (0, 0, 0)


class _SlowLink:
    """A BLE link where a write is accepted now and finishes later.

    The two are worth telling apart. Calling the sink means a command has been
    *accepted for sending* — from that moment it is on its way and no amount of
    stopping recalls it. What must be true after a power off is that no *new*
    command is accepted; a write already handed to the link finishing afterwards
    is physics, not a defect.
    """

    def __init__(self) -> None:
        self.accepted: list[tuple[int, int, int]] = []
        self.finished: list[tuple[int, int, int]] = []
        self._in_flight: list[tuple[int, int, int]] = []

    def sink(self, red, green, blue, *_labels) -> bool:
        self._in_flight.append((red, green, blue))
        return True

    def settle(self) -> None:
        self.accepted.extend(self._in_flight)
        self.finished.extend(self._in_flight)
        self._in_flight.clear()


def test_power_off_accepts_no_further_command(app) -> None:
    """The guarantee, stated in the only terms that are actually enforceable."""
    clock = _Clock()
    link = _SlowLink()
    sources = _Sources()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.attach_sources(start=sources.start, stop=sources.stop)
    coordinator.start(link.sink, mode="screen")
    try:
        coordinator.set_powered(True)
        coordinator.submit_screen(
            ScreenSample(session_token=sources._token, captured_at=clock.now, rgb=(10, 200, 90))
        )
        deadline = time.monotonic() + 3.0
        while not link._in_flight and time.monotonic() < deadline:
            _drain(coordinator, clock, app, seconds=0.05)
        link.settle()
        accepted_before = len(link.accepted)
        assert accepted_before, "nothing was accepted while the strip was on"

        coordinator.set_powered(False)
        # Everything that could still deliver one: the event loop, the sources'
        # own stop, and the coordinator's remaining ticks.
        _drain(coordinator, clock, app, seconds=0.5)
        link.settle()
    finally:
        coordinator.stop()

    assert len(link.accepted) == accepted_before, (
        f"{len(link.accepted) - accepted_before} commands accepted after power off: "
        f"{link.accepted[accepted_before:]}"
    )


def test_blocking_output_cancels_the_aimed_colour_immediately(app) -> None:
    """Immediately, not on the next tick.

    The composing tick also cancels an aimed colour when a frame says not to
    send, which hides the difference in normal settings — the next tick is
    thirty milliseconds away and the engine has not reached its turn. So the two
    are pulled apart here: a coordinator that ticks rarely and an engine that
    writes often, which is the same shape as a real one whose tick is delayed by
    a device being closed on the UI thread. In that window, blocking output and
    cancelling what was aimed have to be one act.
    """
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock, tick_ms=100000, send_interval_ms=33)
    coordinator.expect_screen(1)
    coordinator.start(strip.sink, mode="screen")
    try:
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
        )
        coordinator._tick()
        # Aimed but not yet due: the send interval has not come round.
        coordinator.set_powered(False)
        # Only the event loop from here — no further coordinator tick.
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)
            app.processEvents()
    finally:
        coordinator.stop()

    assert strip.writes == [], f"a colour went out after power off: {strip.writes}"


def test_starting_writes_nothing_before_the_first_screen_frame(app) -> None:
    """The seed describes the strip as it was before the mode began. Starting
    the engine with it puts that colour out during the moment between pressing
    start and the first frame arriving — visible on any machine where capture
    takes a moment to open."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock, send_interval_ms=33)
    coordinator.expect_screen(1)
    coordinator.start(strip.sink, mode="screen", initial=(17, 23, 41))
    try:
        # A slow start: the event loop runs, and no sample has arrived yet.
        for _ in range(12):
            app.processEvents()
            time.sleep(0.02)
            app.processEvents()
        before_any_frame = list(strip.writes)

        clock.advance(0.05)
        coordinator.submit_screen(
            ScreenSample(session_token=1, captured_at=clock.now, rgb=(10, 200, 90))
        )
        _drain_until_written(coordinator, clock, app, strip)
    finally:
        coordinator.stop()

    assert before_any_frame == [], f"a colour went out before any frame: {before_any_frame}"
    assert strip.writes[0] == (10, 200, 90), "the first write was not the first frame"


def test_refused_samples_are_counted_per_run(app) -> None:
    """They sit next to the command counts in the report, and those are zeroed
    every start. A lifetime total beside per-run numbers is read as the same
    scale, and the second report of a session looks alarming for no reason."""
    clock = _Clock()
    strip = _Strip()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.start(strip.sink, mode="screen")
    coordinator.expect_screen(1)
    try:
        coordinator.submit_screen(
            ScreenSample(session_token=99, captured_at=clock.now, rgb=(1, 2, 3))
        )
        assert coordinator.dropped_samples() == (1, 0)
        coordinator.stop()

        coordinator.start(strip.sink, mode="screen")
    finally:
        coordinator.stop()

    assert coordinator.dropped_samples() == (0, 0), "last run's refusals came along"


# ── the beat has to survive long enough to be composed ────────────────
def test_the_strongest_onset_between_ticks_is_the_one_composed() -> None:
    """Audio blocks arrive about every 21 ms and the tick composes about every
    33, so keeping only the latest block loses the strike before anything has
    looked at it: a peak of 1.0 is replaced by the next block's 0.82, and the
    beat is a fifth weaker before the link has had any say."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)
    coordinator.submit_screen(
        ScreenSample(session_token=1, captured_at=clock.now, rgb=(200, 120, 40))
    )

    # The peak, then the same beat decaying — both inside one tick.
    for envelope in (1.0, 0.82, 0.67):
        coordinator.submit_music(
            MusicModulationSample(
                session_token=1, captured_at=clock.now, level=0.5,
                beat_envelope=envelope, beat_id=7,
            )
        )
    # Asserted on what arrived, before the hold has had a say: the hold would
    # put the peak back and hide the fact that it had been dropped here.
    assert coordinator._pending_music.beat_envelope == 1.0, "the peak was overwritten"
    assert coordinator._pending_music.beat_id == 7

    coordinator._tick()
    assert coordinator._compositor._music.beat_envelope == 1.0


def test_a_newer_beat_replaces_the_one_being_held() -> None:
    """Holding the strongest ever seen would leave the strip stuck at a peak
    from a beat that has passed. Only the *current* beat is kept whole."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_music(1)

    coordinator.submit_music(
        MusicModulationSample(
            session_token=1, captured_at=clock.now, beat_envelope=1.0, beat_id=7
        )
    )
    coordinator.submit_music(
        MusicModulationSample(
            session_token=1, captured_at=clock.now, beat_envelope=0.4, beat_id=8
        )
    )

    assert coordinator._pending_music.beat_envelope == 0.4
    assert coordinator._pending_music.beat_id == 8


def test_the_loudness_is_the_latest_block_not_the_loudest() -> None:
    """Level and onset are different kinds of number: one describes how loud it
    is now, the other that something was struck. Keeping both as the maximum
    would leave the strip bright through a passage that has gone quiet."""
    clock = _Clock()
    coordinator = FusionCoordinator(clock=clock)
    coordinator.expect_music(1)

    for level in (0.9, 0.5, 0.2):
        coordinator.submit_music(
            MusicModulationSample(
                session_token=1, captured_at=clock.now, level=level, beat_id=3
            )
        )

    assert coordinator._pending_music.level == 0.2


# ── a struck beat waits for a write to carry it ───────────────────────
def _beat_rig(*, accept: bool = True):
    """A coordinator whose link can be told to accept or refuse."""
    clock = _Clock()
    state = {"accept": accept, "writes": [], "attempts": 0}

    def sink(red, green, blue, *_labels):
        state["attempts"] += 1
        if not state["accept"]:
            return False
        state["writes"].append((red, green, blue))
        return True

    coordinator = FusionCoordinator(clock=clock, send_interval_ms=33)
    coordinator.expect_screen(1)
    coordinator.expect_music(1)
    coordinator.start(sink, mode="screen_music")
    return coordinator, clock, state


def _play_block(coordinator, clock, *, envelope: float, beat_id: int, level: float = 0.5) -> None:
    coordinator.submit_screen(
        ScreenSample(session_token=1, captured_at=clock.now, rgb=(200, 120, 40))
    )
    coordinator.submit_music(
        MusicModulationSample(
            session_token=1, captured_at=clock.now, level=level,
            beat_envelope=envelope, beat_id=beat_id,
        )
    )


def test_a_beat_keeps_its_full_strength_until_a_write_carries_it(app) -> None:
    """The strike lands wherever the paced write happens to fall — on average
    two thirds of the way down its own decay, in the worst phase under half.
    Held at its peak, every beat that is shown at all is shown whole."""
    coordinator, clock, _state = _beat_rig()
    try:
        for _ in range(40):
            clock.advance(0.05)
            _play_block(coordinator, clock, envelope=0.0, beat_id=0)
            coordinator._tick()

        # The strike, then the same beat decaying while no write goes out.
        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        struck = coordinator._tick() or coordinator.last_frame()

        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=0.82, beat_id=1)
        coordinator._tick()
        later = coordinator.last_frame()
    finally:
        coordinator.stop()

    assert struck.beat_id == 1
    assert later.beat_id == 1
    assert later.beat_boost == pytest.approx(struck.beat_boost, abs=0.01), (
        "the beat faded before anything carried it"
    )


def test_a_refused_write_does_not_end_the_beat_s_turn(app) -> None:
    """A busy link is not a beat that has been shown. It keeps its turn."""
    coordinator, clock, state = _beat_rig(accept=False)
    try:
        # Settled first. The music's influence starts at zero and fades in, so a
        # strike on the very first tick carries no boost at all and the frame
        # would name no beat — the check would pass without meaning anything.
        for _ in range(40):
            clock.advance(0.05)
            _play_block(coordinator, clock, envelope=0.0, beat_id=0)
            coordinator._tick()

        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()
        assert coordinator.last_frame().beat_id == 1, "the frame carried no beat to release"

        # Waited for the link to have actually been asked and to have refused:
        # a hold that survives because nothing tried yet proves nothing.
        deadline = time.monotonic() + 3.0
        while state["attempts"] == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert state["attempts"] >= 1, "the link was never asked"
        assert state["writes"] == [], "the refusal did not take"

        assert coordinator._held_beat is not None, "a refusal ended the beat's turn"
        assert coordinator._held_beat[0] == 1
    finally:
        coordinator.stop()


def test_a_newer_beat_takes_the_turn_from_an_older_one(app) -> None:
    """With the link busy the two cannot both be shown. The one still sounding
    is the one worth showing, so nothing here promises every beat is seen."""
    coordinator, clock, _state = _beat_rig(accept=False)
    try:
        clock.advance(0.05)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()
        assert coordinator._held_beat[0] == 1

        clock.advance(0.05)
        _play_block(coordinator, clock, envelope=1.0, beat_id=2)
        coordinator._tick()

        assert coordinator._held_beat[0] == 2
    finally:
        coordinator.stop()


def test_a_beat_that_missed_its_moment_is_not_shown_late(app) -> None:
    """A strike arriving after the next has sounded reads as a stutter, and one
    arriving seconds later — when a stalled screen comes back — reads as a
    fault. The hold has an end."""
    coordinator, clock, _state = _beat_rig(accept=False)
    try:
        clock.advance(0.05)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()
        assert coordinator._held_beat is not None

        clock.advance(5.0)
        _play_block(coordinator, clock, envelope=0.0, beat_id=1)
        coordinator._tick()

        assert coordinator._held_beat is None, "a stale beat was still waiting to fire"
        assert coordinator.last_frame().beat_boost == 1.0
    finally:
        coordinator.stop()


def test_the_wait_is_measured_from_the_sound_not_from_the_tick(app) -> None:
    """The figure has to describe the beat's own wait. Measuring from the tick
    would hide exactly the delay the tick contributes, which is most of it."""
    coordinator, clock, state = _beat_rig()
    try:
        for _ in range(40):
            clock.advance(0.05)
            _play_block(coordinator, clock, envelope=0.0, beat_id=0)
            coordinator._tick()

        struck_at = clock.now
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        # Time passes before anything composes it, and more before it is written.
        clock.advance(0.04)
        coordinator._tick()
        clock.advance(0.03)

        deadline = time.monotonic() + 3.0
        while state["attempts"] == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert state["writes"], "nothing carried the beat"

        p50, p95, count = coordinator.beat_delays_ms()
    finally:
        coordinator.stop()

    assert count == 1
    expected = (clock.now - struck_at) * 1000.0
    assert p50 == pytest.approx(expected, abs=1.0), (
        f"measured {p50} ms for a beat that waited {expected:.0f} ms"
    )
    assert p95 == p50


def test_nothing_is_measured_for_a_beat_no_command_carried(app) -> None:
    """A beat the link refused was never shown, so it has no delay — counting it
    as one would report a wait that ended when it did not."""
    coordinator, clock, _state = _beat_rig(accept=False)
    try:
        for _ in range(40):
            clock.advance(0.05)
            _play_block(coordinator, clock, envelope=0.0, beat_id=0)
            coordinator._tick()
        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()
        app.processEvents()
        time.sleep(0.08)
        app.processEvents()

        assert coordinator.beat_delays_ms() == (0.0, 0.0, 0)
    finally:
        coordinator.stop()


def test_the_delay_window_does_not_grow_without_end(app) -> None:
    """It sits on the write path, so an unbounded list would be a leak that
    grows with every beat of every evening."""
    coordinator, clock, _state = _beat_rig()
    try:
        coordinator._beat_delays_ms = [1.0] * 500
        coordinator._beat_struck_at = {9: clock.now}
        coordinator._deliver(1, 2, 3, 0, 9)

        assert len(coordinator._beat_delays_ms) <= 120
    finally:
        coordinator.stop()


def _settle_music(coordinator, clock, *, ticks: int = 40) -> None:
    """Wind the music's influence in, so a strike actually produces a boost."""
    for _ in range(ticks):
        clock.advance(0.05)
        _play_block(coordinator, clock, envelope=0.0, beat_id=0)
        coordinator._tick()


def test_a_beat_already_shown_is_not_armed_again_by_its_own_tail(app) -> None:
    """The blocks after a strike still carry its id, with the envelope decaying.
    Arming on those would send the same strike again and again — a tail smeared
    into one long flare, and one physical beat counted several times as if the
    link had carried several.
    """
    coordinator, clock, state = _beat_rig()
    try:
        _settle_music(coordinator, clock)

        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()

        deadline = time.monotonic() + 3.0
        while not state["writes"] and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert state["writes"], "nothing carried the beat"
        assert coordinator._held_beat is None, "acceptance did not end the turn"
        carried = coordinator.beat_delays_ms()[2]

        # The same beat, decaying, block after block.
        boosts = []
        for envelope in (0.82, 0.67, 0.55, 0.45, 0.37):
            clock.advance(0.02)
            _play_block(coordinator, clock, envelope=envelope, beat_id=1)
            coordinator._tick()
            boosts.append(coordinator.last_frame().beat_boost)
            app.processEvents()

        assert coordinator._held_beat is None, "the tail armed the strike again"
        assert coordinator.beat_delays_ms()[2] == carried, (
            "one strike was counted more than once"
        )
        assert boosts == sorted(boosts, reverse=True), f"the tail flared back up: {boosts}"
        assert max(boosts) < 1.35, "the full impulse was sent a second time"
    finally:
        coordinator.stop()


def test_a_beat_given_up_on_is_not_armed_again_either(app) -> None:
    """After the hold has expired the same id must stay expired. Otherwise the
    next block revives a strike the code has just decided was too late."""
    coordinator, clock, _state = _beat_rig(accept=False)
    try:
        _settle_music(coordinator, clock)

        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()
        assert coordinator._held_beat is not None

        clock.advance(5.0)
        _play_block(coordinator, clock, envelope=0.3, beat_id=1)
        coordinator._tick()
        assert coordinator._held_beat is None, "the stale strike was still waiting"

        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=0.25, beat_id=1)
        coordinator._tick()

        assert coordinator._held_beat is None, "a strike given up on was revived"
    finally:
        coordinator.stop()


def test_a_refused_attempt_still_leaves_the_beat_a_second_one(app) -> None:
    """The engine writes only on a tick, so with a 70 ms interval and a 33 ms
    tick the attempts fall about 99 ms apart. A hold shorter than two of those
    means the first refusal is the last chance — which a fixed 150 ms was."""
    coordinator, clock, state = _beat_rig()
    try:
        assert coordinator._beat_hold_s >= 0.2, coordinator._beat_hold_s
        _settle_music(coordinator, clock)

        state["accept"] = False
        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=1.0, beat_id=1)
        coordinator._tick()

        deadline = time.monotonic() + 3.0
        while state["attempts"] == 0 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert state["attempts"] >= 1 and not state["writes"], "the refusal never happened"

        # The link frees up, and the beat is still waiting at full strength.
        state["accept"] = True
        clock.advance(0.02)
        _play_block(coordinator, clock, envelope=0.55, beat_id=1)
        coordinator._tick()
        carried = coordinator.last_frame().beat_boost

        deadline = time.monotonic() + 3.0
        while not state["writes"] and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    finally:
        coordinator.stop()

    assert state["writes"], "the second attempt never came"
    assert carried == pytest.approx(1.35, abs=0.02), (
        f"the beat arrived weakened after the refusal: boost {carried}"
    )
    assert coordinator.beat_delays_ms()[2] == 1, "the strike was counted more than once"


def test_the_hold_is_measured_against_the_real_gap_between_attempts() -> None:
    """Not against the interval. The engine writes only on a tick, so a 100 ms
    interval on a 33 ms tick really means 132 ms between attempts, and a hold
    sized from the interval alone would again leave a refusal with no second
    chance. Checked where the floor does not hide it.
    """
    import math

    for tick, interval in ((33, 70), (33, 100), (33, 200), (16, 70)):
        coordinator = FusionCoordinator(tick_ms=tick, send_interval_ms=interval)
        cadence_ms = math.ceil(interval / tick) * tick

        assert coordinator._beat_hold_s * 1000.0 >= 2 * cadence_ms, (
            f"tick {tick} interval {interval}: a hold of "
            f"{coordinator._beat_hold_s * 1000:.0f} ms cannot outlast two "
            f"attempts {cadence_ms} ms apart"
        )


# ── from the sound to the bytes on the wire ───────────────────────────
class _ScriptedAudio:
    """A capture device playing a bed with kicks, one of them twice as hard.

    Paced at roughly the real block duration, because the beat cooldown is
    counted in wall-clock milliseconds: handed blocks as fast as the loop can
    take them, every strike after the first would fall inside it.
    """

    RATE = 48000
    FRAMES = 1024

    def __init__(self, *, before: int = 7, after: int = 4) -> None:
        self.script: list[float] = []
        for _ in range(40):
            self.script.append(0.0)          # settle the floor and the baseline
        for _ in range(before):
            self.script.extend([0.0] * 6)
            self.script.append(1.0)          # an ordinary kick
        self.script.extend([0.0] * 6)
        self.script.append(2.0)              # the accent, in the middle
        self.accent_position = before
        for _ in range(after):
            self.script.extend([0.0] * 6)
            self.script.append(1.0)
        self.script.extend([0.0] * 12)
        self._index = 0

    def _block(self, kick: float):
        import numpy as np

        # The bed is loud on purpose. Loudness alone already brightens a frame
        # through the level modulation, so a quiet bed would let this test pass
        # on volume and prove nothing about how hard the beat was struck. Held
        # above the normalisation ceiling, the level is pinned at one for every
        # sounding block and only the strike can tell the writes apart. It sits
        # at 440/880 Hz, clear of the 35-120 Hz band, so it does not raise the
        # baseline the attack is measured against.
        t = np.arange(self.FRAMES) / self.RATE
        bed = 0.40 * (np.sin(2 * np.pi * 440 * t) + 0.6 * np.sin(2 * np.pi * 880 * t))
        if kick > 0.0:
            bed = bed + kick * 0.9 * np.exp(-t * 45.0) * (
                np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 90 * t)
            )
        return np.column_stack((bed, bed)).astype(np.float32)

    def reader(self, _options):
        def read(_size):
            time.sleep(self.FRAMES / self.RATE)
            kick = self.script[min(self._index, len(self.script) - 1)]
            self._index += 1
            return self._block(kick)

        return read, lambda: None, self.RATE

    def finished(self) -> bool:
        return self._index >= len(self.script)


def test_an_accent_reaches_the_strip_as_a_brighter_write(app, screen, music) -> None:
    """The whole chain, from a struck drum to the bytes handed to the link.

    The analyser is tested on how hard a strike registers, and the compositor on
    what it does with that number, but neither says the two are joined up. This
    plays real sound through the real capture, the real analysis and the real
    coordinator, and looks only at what the BLE layer was actually asked to
    write.
    """
    pytest.importorskip("numpy")
    audio = _ScriptedAudio()
    written: list[tuple[tuple[int, int, int], int]] = []
    coordinator = FusionCoordinator(tick_ms=20, send_interval_ms=40)

    def sink(red, green, blue, *_labels):
        frame = coordinator.last_frame()
        written.append(((red, green, blue), frame.beat_id))
        return True

    monkey = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(audio.reader)
    screen.screen_sampled.connect(coordinator.submit_screen, Qt.QueuedConnection)
    music.modulation_sampled.connect(coordinator.submit_music, Qt.QueuedConnection)
    coordinator.start(sink, mode="screen_music")
    coordinator.set_beat_gain(1.0)
    try:
        coordinator.expect_screen(screen.start_listening())
        coordinator.expect_music(music.start_listening())
        _pump(app, 25.0, until=audio.finished)
        _pump(app, 0.4)
    finally:
        screen.stop()
        music.stop()
        coordinator.stop()
        MusicController._open_loopback_reader = monkey

    by_beat: dict[int, int] = {}
    for colour, beat_id in written:
        if beat_id:
            by_beat[beat_id] = max(by_beat.get(beat_id, 0), max(colour))
    assert len(by_beat) >= 4, f"too few strikes reached the strip: {by_beat}"

    strikes = [by_beat[key] for key in sorted(by_beat)]
    assert len(strikes) > audio.accent_position + 1, f"the accent never landed: {strikes}"
    accent = strikes[audio.accent_position]
    ordinary = strikes[:audio.accent_position] + strikes[audio.accent_position + 1 :]

    # Compared with the strikes on *both* sides of it. The music's influence
    # fades in over the first seconds, so a later beat is brighter than an early
    # one whatever it was struck at — an accent placed at the end would be
    # measuring that ramp and nothing else.
    assert accent > max(ordinary), (
        f"the accent was written no brighter than the ordinary beats around it: "
        f"{ordinary} against {accent}"
    )
    # And the colour is still the screen's: a beat brightens, it does not tint.
    accent_colour = next(
        colour for colour, beat in written if beat and max(colour) == accent
    )
    assert accent_colour[0] > accent_colour[1] > accent_colour[2], accent_colour
