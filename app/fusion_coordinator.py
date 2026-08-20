"""The one thing that writes a streamed colour to the strip.

::

    Screen sample ─┐
                   ├─ FusionCoordinator ─ ColorStreamEngine ─ BLE
    Music sample ──┘

Both sources are capture threads and neither sends anything. A screen frame
updates the base, an audio block updates the modulation, and on its own tick
this coordinator asks the compositor for one frame and hands it to one engine.

That shape is the point, not an implementation detail. Sending on every event
would work in a demo and then behave differently every run: two sources firing
at unrelated rates would double the command rate, and which of them arrived last
would decide what the strip shows. Here the rate belongs to the engine and
nothing else, whether one source is running or both.

**The factor travels in the colour.** The strip takes a colour and a hardware
brightness as two separate commands, and music moves its factor on every block —
sending both would double the traffic on a link that manages about ten writes a
second. The composed factor scales the RGB instead: one write, the hue the
screen chose, and the brightness slider left alone as the strip's own ceiling.

So the factor is never a device brightness and must not be reported as one. At a
hardware 50% and a factor of 0.65 the wall shows about a third of full. A
diagnostics block says both — the strip's brightness and Fusion's factor — and
never one number standing for the two.

**Only the current run is accepted.** Each source stamps its samples with the
token of its capture run, and a sample from any other run is dropped rather than
composed. Without that, a frame emitted just before a stop can arrive after the
next start and put a colour from the previous session on the strip.

**One clock.** The compositor, the samples and the staleness checks all read the
same injected monotonic source, so "how old is this" is a subtraction rather
than a comparison between two ideas of now.

What this does *not* claim to be is the only way anything reaches the strip.
Power, a colour chosen by hand, a scene and a DIY effect all write directly, and
should — they are single commands from a person, not a stream. The contract is
narrower and testable: while Fusion is running, no *streaming* source writes
except through here.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, Signal

from app.color_stream import ColorStreamEngine
from app.fusion_core import BaseSample, ComposedFrame, FusionCompositor, MusicModulation

RGB = tuple[int, int, int]

# How long a struck beat may wait for a write to carry it, as a multiple of the
# link's real cadence. Long enough that a refused attempt still leaves a second
# one: a fixed 150 ms looked reasonable and was not, because the engine only
# writes on a tick, so with a 70 ms interval and a 33 ms tick the attempts fall
# at about 99 ms and 198 ms — the first refusal was the last chance.
#
# Nothing hangs on the far end of it: a newer beat replaces an older one
# outright, so the only case that reaches the limit is a beat with no successor,
# and showing that one late by a fifth of a second is better than not at all.
_BEAT_HOLD_CADENCES = 2.2
_MIN_BEAT_HOLD_S = 0.22

# How many recent beats the delay figures describe.
_BEAT_DELAY_SAMPLES = 120


class FusionCoordinator(QObject):
    """Collects samples from any thread and composes on its own tick."""

    # The frame that was just composed, for previews and diagnostics. Emitted
    # whether or not it was sent, because "nothing was sent" is the interesting
    # case to be able to see.
    frame_composed = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        tick_ms: int = 33,
        send_interval_ms: int = 70,
    ) -> None:
        super().__init__(parent)
        self._clock = clock
        self._compositor = FusionCompositor(clock=clock)
        self._engine = ColorStreamEngine(self, send_interval_ms=send_interval_ms)
        # Passthrough: the screen's own temporal filter and the compositor's
        # activity weight are the smoothing. A third one here would ease an
        # already-eased colour and put the strip visibly behind the picture.
        self._engine.set_smoothing(1.0)
        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(tick_ms)))
        self._timer.timeout.connect(self._tick)
        # Samples arrive on capture threads; composing happens on the tick. The
        # lock is held only long enough to swap a reference, never across
        # compose, so a slow frame cannot stall a capture thread.
        self._lock = threading.Lock()
        self._pending_base: BaseSample | None = None
        self._pending_music: MusicModulation | None = None
        self._screen_token = 0
        self._music_token = 0
        self._beat_gain = 1.0
        self._last_frame = ComposedFrame()
        self._dropped_screen = 0
        self._dropped_music = 0
        # The strongest onset of the beat currently sounding, kept at its peak
        # until a write has carried it. Without this a beat is sampled wherever
        # the paced write happens to fall — on average two thirds of the way
        # down its own decay, and in the worst phase under half.
        self._held_beat: tuple[int, float] | None = None
        self._hold_expires_at = 0.0
        # The newest beat that has ever been held. A beat is armed once and
        # never again: after it has been shown, or given up on, the blocks that
        # follow still carry its id with a decaying envelope, and without this
        # they would arm the same strike over and over — sending it repeatedly,
        # smearing the tail into one long flare, and counting one strike several
        # times in the delay figures.
        self._latest_beat_id_seen = 0
        # The engine writes only on a tick, so the real gap between attempts is
        # the interval rounded up to whole ticks — 99 ms for the defaults, not 70.
        cadence = math.ceil(max(1, send_interval_ms) / max(1, tick_ms)) * max(1, tick_ms)
        self._beat_hold_s = max(_MIN_BEAT_HOLD_S, _BEAT_HOLD_CADENCES * cadence / 1000.0)
        # When each waiting beat was captured, so the wait can be measured from
        # the moment the sound was handed over rather than from the tick.
        self._beat_struck_at: dict[int, float] = {}
        self._beat_delays_ms: list[float] = []
        self._start_sources: Callable[[], tuple[int, int]] | None = None
        self._stop_sources: Callable[[], None] | None = None
        self._sink: Callable[..., None] | None = None
        self._initial: RGB = (0, 0, 0)

    # ── running ───────────────────────────────────────────────────────
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self, sink: Callable[..., None], *, mode: str, initial: RGB = (0, 0, 0)) -> None:
        """Take the output. ``sink`` is the only route to the strip from here.

        The engine is not started here. It writes as soon as it is running, and
        at this moment there is no screen frame yet — so it would put ``initial``
        on the strip, a colour from before the mode began. The first frame worth
        sending wakes it and seeds it with that frame; ``initial`` is kept only
        as the fallback seed for a caller that asks for one.
        """
        self._compositor.set_mode(mode)
        self._compositor.set_sources_running(True)
        # Zeroed with everything else the report counts. Left running, these
        # would be a lifetime total sitting next to per-run commands, and the
        # two would be read as the same scale.
        self._dropped_screen = 0
        self._dropped_music = 0
        self._sink = sink
        self._initial = initial
        self._held_beat = None
        self._latest_beat_id_seen = 0
        self._beat_struck_at = {}
        self._beat_delays_ms = []
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._engine.stop()
        self._compositor.set_sources_running(False)
        with self._lock:
            self._pending_base = None
            self._pending_music = None
        self._screen_token = 0
        self._music_token = 0

    # ── what counts as the current run ────────────────────────────────
    def expect_screen(self, token: int) -> None:
        self._screen_token = int(token)

    def expect_music(self, token: int) -> None:
        self._music_token = int(token)

    def set_beat_gain(self, gain: float) -> None:
        self._beat_gain = max(0.0, min(1.0, float(gain)))

    def attach_sources(
        self,
        *,
        start: Callable[[], tuple[int, int]],
        stop: Callable[[], None],
    ) -> None:
        """How to start and stop capture. ``start`` returns the two new tokens.

        Given to the coordinator rather than reached for, so power can act on
        all three states at once without this module knowing what a screen or a
        microphone is.
        """
        self._start_sources = start
        self._stop_sources = stop

    def set_output_allowed(self, allowed: bool) -> None:
        """Permission to write, on its own. See :meth:`set_powered` for power."""
        if allowed:
            self._compositor.set_output_allowed(True)
            return
        self._block_output()

    def _block_output(self) -> None:
        """Refuse permission and cancel what was aimed, as one act.

        The two halves are meaningless apart. Refusing to compose leaves the
        engine holding a colour it has not written yet, and every caller that
        blocks output has to remember to cancel it — which is exactly the kind
        of thing that gets forgotten on one of the paths and shows up as an
        occasional extra command nobody can reproduce.
        """
        self._compositor.set_output_allowed(False)
        self._silence_engine()

    def _deliver(self, red: int, green: int, blue: int, _token: int, beat_id: int) -> bool:
        """Hand one colour to the strip and note which beat, if any, it carried.

        Released on *acceptance*, not on the outcome: acceptance is the moment
        the colour is on its way and the light will show it. Waiting for the
        link's answer would hold the strike another few tens of milliseconds,
        during which a newer beat would be suppressed by an older one.

        A refused write releases nothing — the beat has not been shown, and it
        keeps its turn until it is, or until it is too late to matter.
        """
        sink = self._sink
        if sink is None:
            return False
        accepted = sink(red, green, blue)
        if accepted is not False and beat_id:
            struck_at = self._beat_struck_at.pop(beat_id, None)
            if struck_at is not None:
                delay = (self._clock() - struck_at) * 1000.0
                self._beat_delays_ms.append(delay)
                # A window, not a lifetime: what matters is how it is behaving
                # now, and an unbounded list on a per-write path is a leak.
                if len(self._beat_delays_ms) > _BEAT_DELAY_SAMPLES:
                    del self._beat_delays_ms[:-_BEAT_DELAY_SAMPLES]
            held = self._held_beat
            if held is not None and held[0] == beat_id:
                self._held_beat = None
        return accepted

    def beat_delays_ms(self) -> tuple[float, float, int]:
        """How long a struck beat waited for a command to carry it: p50, p95, n.

        Measured from the moment the audio block was handed over to the moment
        the command was accepted. It is the part this application controls, and
        it is *not* the delay a person hears: the device's own buffering before
        the block arrived, the transport to the strip and the controller's own
        reaction are all outside it and are not small.
        """
        samples = list(self._beat_delays_ms)
        if not samples:
            return (0.0, 0.0, 0)
        ordered = sorted(samples)

        def rank(fraction: float) -> float:
            index = min(len(ordered), max(1, math.ceil(fraction * len(ordered))))
            return ordered[index - 1]

        return (round(rank(0.5), 1), round(rank(0.95), 1), len(ordered))

    def _silence_engine(self) -> None:
        """Cancel anything aimed but not yet written.

        The engine paces itself, so a colour handed to it a moment ago is still
        waiting for its interval to come round. Refusing to compose does not
        recall it: it would land afterwards, on a strip that is stale, blocked or
        switched off. Stopped rather than told to forget, because stopping is
        what the engine offers — the next frame worth sending wakes it again and
        seeds it with that frame.
        """
        if self._engine.is_running():
            self._engine.stop()

    def set_powered(self, on: bool) -> None:
        """Power, acting on each of the three states for its own reason.

        *Chosen* is untouched: switching the strip off is not a change of mind
        about what it should be doing, and 0.4.0 exists partly because today it
        silently is one.

        *Capture* stops. Holding a microphone open and grabbing the screen
        twenty times a second for a strip that is off is a cost with no result —
        and on Windows it is a microphone indicator sitting on someone's taskbar
        with nothing to explain it.

        *Output* is refused, and on the way back the base and the modulation go
        with it: the next colour is the screen as it is when the light comes on,
        not the frame this was holding when it went off.
        """
        if on:
            # Permission comes last. Sources are started while writing is still
            # refused, so a sample a device hands over during its own start —
            # describing the room or the screen from before the light came on —
            # has nowhere to go.
            self._forget()
            if self._start_sources is not None:
                screen_token, music_token = self._start_sources()
                self.expect_screen(screen_token or 0)
                self.expect_music(music_token or 0)
            self._compositor.set_output_allowed(True)
            return
        # Permission goes first, and the tokens with it. Stopping the sources
        # first leaves a window: a capture that delivers a last sample inside its
        # own stop, or an event loop that runs while a thread is joined, can put
        # one more colour on a strip that has just been switched off.
        self._block_output()
        self._screen_token = 0
        self._music_token = 0
        if self._stop_sources is not None:
            self._stop_sources()
        self._forget()

    def _forget(self) -> None:
        """Drop everything held about the picture and the sound."""
        with self._lock:
            self._pending_base = None
            self._pending_music = None
        self._compositor.forget_inputs()

    def output_allowed(self) -> bool:
        return self._compositor.output_allowed

    def mode(self) -> str:
        return self._compositor.mode

    # ── inbound, from capture threads ─────────────────────────────────
    def submit_screen(self, sample) -> None:
        """Take a screen frame as the base. Never sends anything."""
        if not sample.session_token or sample.session_token != self._screen_token:
            self._dropped_screen += 1
            return
        base = BaseSample(
            rgb=tuple(sample.rgb),
            brightness_factor=1.0,
            source="screen",
            at=sample.captured_at,
        )
        with self._lock:
            self._pending_base = base

    def submit_music(self, sample) -> None:
        """Take an audio block as the modulation. Never sends anything.

        The loudness is whatever arrived last, but the onset is the *strongest*
        seen since the tick — they are different kinds of number and keeping
        both as "latest" loses the beat before anything has looked at it.

        Blocks arrive about every 21 ms and the tick composes about every 33, so
        on a typical run one tick in three sees a peak of 1.0 replaced by the
        next block's 0.82 before the frame is built. The strike was already a
        fifth weaker than it should be, before the link had any say.
        """
        if not sample.session_token or sample.session_token != self._music_token:
            self._dropped_music += 1
            return
        with self._lock:
            previous = self._pending_music
            envelope = float(sample.beat_envelope)
            beat_id = int(sample.beat_id)
            if (
                previous is not None
                and previous.beat_id == beat_id
                and previous.beat_envelope > envelope
            ):
                # The same beat, further into its decay. Keep the peak; a newer
                # beat replaces it outright, because that is what the ear hears.
                envelope = previous.beat_envelope
            self._pending_music = MusicModulation(
                level=sample.level,
                beat_envelope=envelope,
                beat_id=beat_id,
                at=sample.captured_at,
                block_seconds=sample.block_seconds,
            )
            held = self._held_beat
            if beat_id > self._latest_beat_id_seen:
                # A strike nobody has held yet. A newer one replaces an older
                # one outright: with the link busy the two cannot both be shown,
                # and the one still sounding is the one worth showing.
                self._latest_beat_id_seen = beat_id
                self._held_beat = (beat_id, envelope)
                self._hold_expires_at = self._clock() + self._beat_hold_s
                self._beat_struck_at = {beat_id: float(sample.captured_at)}
            elif held is not None and held[0] == beat_id and envelope > held[1]:
                # The same strike, arriving stronger than the block before it.
                self._held_beat = (beat_id, envelope)

    def _with_held_beat(self, music: MusicModulation) -> MusicModulation:
        """The modulation as composed, with a struck beat still at full strength.

        The hold is on the *value*, not on a particular frame: the screen colour
        keeps changing underneath and every frame composed while the hold lasts
        carries the strike, so it does not matter which of them the paced write
        happens to take. Holding one frame instead would simply let the engine
        displace it with the next one.
        """
        held = self._held_beat
        if held is None:
            return music
        if self._clock() >= self._hold_expires_at:
            # Its moment has passed. Shown now it would land after the next beat
            # had already sounded, or seconds late when a stalled screen returns.
            self._held_beat = None
            return music
        beat_id, envelope = held
        if music.beat_id != beat_id or music.beat_envelope >= envelope:
            return music
        return replace(music, beat_envelope=envelope)

    # ── the tick ──────────────────────────────────────────────────────
    def _tick(self) -> None:
        with self._lock:
            base = self._pending_base
            music = self._pending_music
            self._pending_base = None
            self._pending_music = None
        if base is not None:
            self._compositor.submit_base(base)
        if music is not None:
            self._compositor.submit_music(self._with_held_beat(music))

        frame = self._compositor.compose(beat_gain=self._beat_gain)
        self._last_frame = frame
        if frame.should_send:
            red, green, blue = frame.rgb
            # The factor dims, the beat's boost lifts. The boost is already
            # limited by the brightest channel, so this multiplication cannot
            # clip one channel while the others keep rising — which is what
            # would turn a beat into a hue change.
            scale = frame.brightness_factor * frame.beat_boost
            colour = (
                min(255, round(red * scale)),
                min(255, round(green * scale)),
                min(255, round(blue * scale)),
            )
            if not self._engine.is_running() and self._sink is not None:
                # Woken by the first frame there is actually something to send,
                # and seeded with that frame. Restarting it when the light comes
                # back on instead would put its starting colour — black — on the
                # strip before the screen had been looked at.
                self._engine.start(self._deliver, initial=colour, labelled_sink=True)
            # Labelled with the beat it carries, so the write's acceptance can
            # release the hold for that beat and nothing else.
            self._engine.set_target(*colour, 0, frame.beat_id)
        else:
            # Nothing should go out, including anything already aimed.
            self._silence_engine()
        self.frame_composed.emit(frame)

    # ── what happened ─────────────────────────────────────────────────
    def last_frame(self) -> ComposedFrame:
        return self._last_frame

    def dropped_samples(self) -> tuple[int, int]:
        """Screen and music samples refused as belonging to another run."""
        return (self._dropped_screen, self._dropped_music)

    def stream_error_count(self) -> int:
        return self._engine.error_count()

    def last_stream_error(self) -> str:
        return self._engine.last_error()
