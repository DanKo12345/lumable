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

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

import app.music_controller as module
from app.music_controller import MusicController, MusicOptions


class _Sound:
    """A capture device that plays a fixed block for as long as it is read."""

    def __init__(self, frames: int = 1024, rate: int = 48000) -> None:
        self.frames = frames
        self.rate = rate
        self.reads = 0

    def reader(self, _options):
        def read(_size):
            self.reads += 1
            return [[0.3, 0.3]] * self.frames

        return read, lambda: None, self.rate


def _listen(controller: MusicController, sound: _Sound, *, sink=None, blocks: int = 6):
    """Run the real capture loop until enough blocks have gone through."""
    seen: list[tuple[float, float, float]] = []
    colours: list[tuple[int, int, int]] = []
    owned: list[bool] = []
    enough = threading.Event()

    def on_modulation(level, envelope, block_seconds):
        seen.append((level, envelope, block_seconds))
        if len(seen) >= blocks:
            enough.set()

    controller.modulation_sampled.connect(on_modulation, Qt.DirectConnection)
    controller.color_sampled.connect(
        lambda r, g, b: colours.append((r, g, b)), Qt.DirectConnection
    )
    original = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(sound.reader)
    try:
        controller.start(sink)
        assert enough.wait(5.0), "the capture loop produced nothing"
        # Asked while it is actually running: after stop() everything is false
        # and the check would pass for the wrong reason.
        owned.append(controller.owns_output())
    finally:
        controller.stop()
        MusicController._open_loopback_reader = original
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

    assert max(level for level, _e, _b in seen) > 0.0


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

    assert all(abs(block_seconds - 512 / 16000) < 1e-9 for _l, _e, block_seconds in seen)


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


def test_a_capture_failure_stops_the_modulation_too(controller) -> None:
    """Stale numbers from a device that has gone wrong are worse than none:
    downstream they look exactly like a quiet passage."""
    seen: list = []
    failures: list[str] = []
    controller.modulation_sampled.connect(lambda *a: seen.append(a), Qt.DirectConnection)
    controller.failed.connect(failures.append, Qt.DirectConnection)

    def broken(_options):
        raise RuntimeError("device gone")

    original = MusicController._open_loopback_reader
    MusicController._open_loopback_reader = staticmethod(broken)
    try:
        controller.start()
        thread = controller._thread
        if thread is not None:
            thread.join(timeout=5.0)
    finally:
        controller.stop()
        MusicController._open_loopback_reader = original

    assert failures, "the failure was swallowed"
    assert seen == []
