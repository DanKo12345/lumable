"""Listening to sound without owning the strip.

The limit pinned in ``test_stream_ownership`` is that analysing the audio and
driving the strip are one act, so "screen colour, music brightness" cannot
exist: whichever mode takes the line stops the other from hearing anything.
These tests are the separation — the same capture thread, the same analysis,
and a choice about what leaves the controller.

Emissions are captured with a direct connection so the worker thread's signals
arrive without an event loop; what is being checked is what the capture loop
decides to emit, which is exactly where the decision lives.
"""

from __future__ import annotations

import threading
from time import monotonic, sleep

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

import app.music_controller as module
from app.music_controller import MusicController, MusicOptions


class _Sound:
    """A capture device that plays a fixed block for as long as it is read."""

    def __init__(self, frames: int = 1024, rate: int = 48000, delay: float = 0.0) -> None:
        self.frames = frames
        self.rate = rate
        self.delay = delay
        self.reads = 0

    def reader(self, _options):
        def read(_size):
            # A real device hands a block back when it is full, so a read waits.
            if self.delay:
                sleep(self.delay)
            self.reads += 1
            return [[0.3, 0.3]] * self.frames

        return read, lambda: None, self.rate


def _listen(controller: MusicController, sound: _Sound, *, sink=None, blocks: int = 6):
    """Run the real capture loop until enough blocks have gone through."""
    seen: list = []
    colours: list[tuple[int, int, int]] = []
    owned: list[bool] = []
    enough = threading.Event()

    def on_modulation(sample):
        seen.append(sample)
        if len(seen) >= blocks:
            enough.set()

    def on_colour(red, green, blue):
        colours.append((red, green, blue))

    controller.modulation_sampled.connect(on_modulation, Qt.DirectConnection)
    controller.color_sampled.connect(on_colour, Qt.DirectConnection)
    original = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(sound.reader)
    try:
        if sink is None:
            controller.start_listening()
        else:
            controller.start_output(sink)
        assert enough.wait(5.0), "the capture loop produced nothing"
        # Asked while it is actually running: after stop() everything is false
        # and the check would pass for the wrong reason.
        owned.append(controller.owns_output())
    finally:
        controller.stop()
        MusicController._open_loopback_reader = original
        # Left connected, a second run would keep filling the first run's lists
        # and every claim about "this run" would be about both.
        controller.modulation_sampled.disconnect(on_modulation)
        controller.color_sampled.disconnect(on_colour)
    return seen, colours, owned[0] if owned else False


@pytest.fixture()
def controller():
    made = MusicController()
    made.configure(source="system")
    yield made
    made.stop()


# ── listening only ────────────────────────────────────────────────────
def test_listening_without_a_sink_never_touches_the_strip(controller) -> None:
    """The whole point. Analysis runs, and nothing about the strip changes."""
    seen, colours, owned = _listen(controller, _Sound())

    assert len(seen) >= 6
    assert owned is False
    assert controller.owns_output() is False
    assert colours == [], "a colour was emitted with nowhere legitimate to send it"


def test_listening_only_still_measures_the_sound(controller) -> None:
    """A silent listener would be indistinguishable from a broken one."""
    seen, _colours, _owned = _listen(controller, _Sound(), blocks=40)

    assert max(sample.level for sample in seen) > 0.0


def test_a_sink_is_what_makes_it_the_owner(controller) -> None:
    """The old behaviour, unchanged, and now an explicit choice rather than the
    only thing the controller can do."""
    seen, colours, owned = _listen(controller, _Sound(), sink=lambda *_a: None)

    assert owned is True
    assert colours, "music reactivity stopped driving the strip"
    assert len(seen) >= 6


def test_stopping_gives_the_output_back(controller) -> None:
    _listen(controller, _Sound(), sink=lambda *_a: None)

    assert controller.owns_output() is False


# ── what the modulation carries ───────────────────────────────────────
def test_the_block_duration_is_the_real_one(controller) -> None:
    """A block is not a unit of time. A device that hands back half of what was
    asked for, or runs at another rate, must not make everything downstream
    think the music went stale."""
    sound = _Sound(frames=512, rate=16000)

    seen, _colours, _owned = _listen(controller, sound)

    assert all(abs(sample.block_seconds - 512 / 16000) < 1e-9 for sample in seen)


def test_the_level_handed_over_has_no_beat_folded_into_it(controller) -> None:
    """The beat slider belongs to whoever composes the frame. A level that
    already contains the impulse would have it applied twice."""
    options = MusicOptions(source="system", beat_strength=0.9)
    original_analyze = module.analyze_block
    original_clock = module.monotonic
    clock = [1000.0]
    module.monotonic = lambda: clock[0]
    try:
        # A steady bed, then a bass burst — the shape the analyser calls a beat.
        for values in [(0.2, 0.2, 0.2, 0.05)] * 12 + [(4.0, 0.2, 0.2, 0.05)]:
            module.analyze_block = lambda _b, _s, v=values: v
            result = controller._process_block(None, 48000, options)
            clock[0] += 0.02
    finally:
        module.analyze_block = original_analyze
        module.monotonic = original_clock

    assert result.beat_envelope > 0.0, "no beat was detected to check against"
    assert max(result.rgb) > round(result.level * 255), (
        "the colour did not get the beat, so this proves nothing"
    )
    assert result.level <= 1.0


def test_a_sample_is_stamped_when_the_sound_arrived_not_when_it_was_handled(
    controller,
) -> None:
    """Qt is free to hold a queued signal, and a composer timing staleness from
    arrival would call a late block fresh — the one measurement silence depends
    on. Delivery is delayed here on purpose: the stamp has to be older than the
    moment the receiver sees it, by about the delay."""
    delay = 0.05
    lag: list[float] = []
    enough = threading.Event()

    def slow_receiver(sample):
        sleep(delay)
        lag.append(monotonic() - sample.captured_at)
        if len(lag) >= 3:
            enough.set()

    controller.modulation_sampled.connect(slow_receiver, Qt.DirectConnection)
    sound = _Sound()
    original = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(sound.reader)
    try:
        controller.start_listening()
        assert enough.wait(5.0), "the capture loop produced nothing"
    finally:
        controller.stop()
        MusicController._open_loopback_reader = original
        controller.modulation_sampled.disconnect(slow_receiver)

    assert min(lag) >= delay * 0.8, (
        f"the stamp moved with the handler, so it is a delivery time: {lag}"
    )


def test_the_stamp_is_not_a_whole_block_behind(controller) -> None:
    """A read waits for the block to fill. Stamping before the wait rather than
    after it dates every sample to the start of the block, so a fresh reading
    arrives already a block old — and on a slow device that is most of the
    staleness budget spent before anything has happened."""
    delay = 0.08
    ages: list[float] = []
    enough = threading.Event()

    def on_sample(sample):
        ages.append(monotonic() - sample.captured_at)
        if len(ages) >= 3:
            enough.set()

    controller.modulation_sampled.connect(on_sample, Qt.DirectConnection)
    sound = _Sound(delay=delay)
    original = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(sound.reader)
    try:
        controller.start_listening()
        assert enough.wait(5.0), "the capture loop produced nothing"
    finally:
        controller.stop()
        MusicController._open_loopback_reader = original
        controller.modulation_sampled.disconnect(on_sample)

    assert max(ages) < delay * 0.5, f"samples arrive already a block old: {ages}"


def test_every_run_gets_its_own_token(controller) -> None:
    """A block emitted just before a stop can arrive after the next start. The
    token is how a composer tells the two runs apart instead of mixing them."""
    first, _colours, _owned = _listen(controller, _Sound())
    second, _colours, _owned = _listen(controller, _Sound())

    first_token = {sample.session_token for sample in first}
    second_token = {sample.session_token for sample in second}
    assert len(first_token) == 1 and len(second_token) == 1
    assert first_token != second_token
    assert controller.session_token() == second_token.pop()


def test_starting_output_and_starting_listening_are_different_words(controller) -> None:
    """There is no call that silently does the wrong one of the two. A start
    that forgot its sink used to be a working music mode turned quiet, with
    nothing raising anywhere."""
    assert not hasattr(controller, "start")
    assert hasattr(controller, "start_output")
    assert hasattr(controller, "start_listening")


def test_a_capture_failure_stops_the_modulation_too(controller) -> None:
    """Stale numbers from a device that has gone wrong are worse than none:
    downstream they look exactly like a quiet passage."""
    seen: list = []
    failures: list[str] = []
    controller.modulation_sampled.connect(seen.append, Qt.DirectConnection)
    controller.failed.connect(failures.append, Qt.DirectConnection)

    def broken(_options):
        raise RuntimeError("device gone")

    original = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(broken)
    try:
        controller.start_listening()
        thread = controller._thread
        if thread is not None:
            thread.join(timeout=5.0)
    finally:
        controller.stop()
        MusicController._open_loopback_reader = original

    assert failures, "the failure was swallowed"
    assert seen == []


# ── the experimental detector runs beside, and drives nothing ─────────
def test_the_trial_detector_never_touches_what_the_strip_shows(controller) -> None:
    """It is an experiment. Whatever it decides, the colour and the beat handed
    over are the working detector's — otherwise the A/B would be comparing a
    thing against itself."""
    from app.onset_detection import OnsetReading

    options = MusicOptions(source="system", beat_strength=0.9)
    original = module.analyze_block
    fed = []

    class _AlwaysHears:
        stats = type("S", (), {"blocks": 0, "onsets": 0})()

        def feed(self, magnitudes, freqs, now_ms):
            fed.append(now_ms)
            self.stats.blocks += 1
            self.stats.onsets += 1
            return OnsetReading(onset=True, flux=1.0, low_flux=1.0, low_share=1.0)

        def reset(self):
            pass

    controller._onset = _AlwaysHears()
    try:
        module.analyze_block = lambda _b, _s: (0.2, 0.2, 0.2, 0.05)
        quiet = controller._process_block([[0.0, 0.0]] * 512, 48000, options)
    finally:
        module.analyze_block = original

    assert quiet.beat_envelope == 0.0, "the trial detector reached the strip"
    assert quiet.beat_id == 0
    assert fed, "the trial detector was never asked"


def test_a_trial_detector_that_cannot_run_does_not_stop_the_music(controller) -> None:
    """It is wrapped for one reason: an experiment that fails must cost a
    measurement, not a frame the strip is waiting for."""
    options = MusicOptions(source="system")
    original = module.analyze_block

    class _Broken:
        stats = type("S", (), {"blocks": 0, "onsets": 0})()

        def feed(self, *_args):
            raise RuntimeError("no numpy today")

        def reset(self):
            pass

    controller._onset = _Broken()
    try:
        module.analyze_block = lambda _b, _s: (0.9, 0.2, 0.2, 0.3)
        result = controller._process_block([[0.4, 0.4]] * 512, 48000, options)
    finally:
        module.analyze_block = original

    assert result.rgb is not None
    assert isinstance(result.level, float)


def test_the_trial_counts_reach_the_report(controller) -> None:
    controller._onset.stats.blocks = 900
    controller._onset.stats.onsets = 61
    controller._onset_agreements = 44

    report = controller.music_report()

    assert report.onset_blocks == 900
    assert report.onset_candidates == 61
    assert report.onset_agreements == 44
