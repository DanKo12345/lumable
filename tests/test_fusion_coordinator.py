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


def test_nothing_is_written_while_the_frame_says_not_to(app) -> None:
    """``should_send`` is the whole answer. A frame that says no and is written
    anyway is how a stale picture or a switched-off strip lights up."""
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
        clock.advance(0.2)
        _drain(coordinator, clock, app, seconds=0.3)
        assert strip.writes, "nothing was written even while the screen was fresh"
        settled = len(strip.writes)

        # The screen stops arriving, then the strip is switched off.
        clock.advance(5.0)
        _drain(coordinator, clock, app, seconds=0.3)
        coordinator.set_output_allowed(False)
        _drain(coordinator, clock, app, seconds=0.3)
    finally:
        coordinator.stop()

    assert len(strip.writes) == settled, (
        f"{len(strip.writes) - settled} writes after the frame said not to send"
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


# ── brightness rides in the colour ────────────────────────────────────
def test_brightness_is_folded_into_the_colour_not_sent_beside_it(app) -> None:
    """A separate brightness command on every audio block would double the
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
    assert frame.brightness < 0.7, "the music was not modulating at all"
    assert frame.rgb == (200, 200, 200), "the composed colour was dimmed twice"
    # And the dimming actually left the coordinator: the frame keeps the screen's
    # colour, the write carries it scaled.
    written = strip.writes[-1]
    assert written == pytest.approx(
        tuple(round(200 * frame.brightness) for _ in range(3)), abs=2
    ), f"brightness never reached the strip: {written}"
