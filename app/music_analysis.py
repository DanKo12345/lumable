"""Deciding what is silence and what is a beat, from numbers alone.

Separated from capture so it can be fed synthetic blocks: a test can play a
tone, a burst of bass or a room that is merely quiet, without a sound card and
without waiting in real time. Nothing here keeps audio — only a handful of
running numbers about the signal that just went past.

Three things the fixed threshold it replaces could not do.

**Silence is relative to the room.** A hard floor is wrong on both sides: on a
laptop with a noisy card the strip twitches all evening, and on a silent desktop
a genuinely quiet passage is thrown away. The floor is measured instead —
falling quickly toward a new quiet level and rising slowly, so a long quiet
stretch teaches it what quiet is here while a passage of music does not.

**Opening and closing at the same level flickers.** A signal sitting exactly on
the threshold crosses it many times a second. It opens higher than it closes,
so once sound is heard it takes a real drop to be called silence again.

**A beat is not loudness.** Bass energy is compared as a *share* of the block's
total, so turning the volume up raises everything and changes nothing: a genuine
kick is bass growing while the rest does not. And the wait between beats is
counted in milliseconds rather than blocks, because a block is not a unit of
time — it changes with the device's sample rate and buffer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# How fast the measured floor moves. Down quickly, because a quieter room is
# news; up slowly, because music is not the floor rising.
_FLOOR_FALL = 0.25
_FLOOR_RISE = 0.004
# Sound has to reach this multiple of the floor to count, and drop to the lower
# one before it is silence again.
_OPEN_RATIO = 2.6
_CLOSE_RATIO = 1.7
# Below this the floor is not believable as a measurement — a device that
# reports perfect digital silence would otherwise make every faint sound huge.
_MIN_FLOOR = 0.0006
# And above this it is not believable either. Room noise and card hiss live
# below about 0.01; even quiet music sits above it. Without a ceiling the floor
# climbs into the music it is supposed to let through — a signal that never
# falls silent looks exactly like loud noise, and the strip goes dark while
# something is plainly playing. Chosen low enough that quiet music still opens
# the gate: with the ratio below, sound from about 0.021 upward is heard.
_MAX_FLOOR = 0.008

# A beat is bass growing as a share of the block. This much above its own
# recent share, at least.
_BEAT_RATIO = 1.28
_SHARE_RATE = 0.08
# The shortest gap between two beats. Fast enough for 200 bpm, slow enough that
# one kick cannot be counted three times.
MIN_BEAT_GAP_MS = 110.0
_ENVELOPE_DECAY = 0.82


@dataclass(frozen=True)
class Reading:
    """What one block turned out to be."""

    level: float = 0.0
    beat: bool = False
    # Which beat this envelope belongs to, counted from the start of the run.
    #
    # The envelope alone cannot say: a decaying value is indistinguishable from
    # a weaker new one, so anything downstream that wants to know "is this still
    # the beat I was waiting for" has nothing to compare. Zero until the first
    # beat, and unchanged while one decays.
    beat_id: int = 0
    envelope: float = 0.0
    silent: bool = True
    noise_floor: float = 0.0


@dataclass
class AnalysisStats:
    """Counters for the diagnostics block. No audio, no device names."""

    blocks: int = 0
    beats: int = 0
    silent_blocks: int = 0
    noise_floor: float = 0.0
    peak_level: float = 0.0


def normalize_above(rms: float, floor: float, ceiling: float = 0.25) -> float:
    """Map an RMS above a floor onto 0..1, with the same curve as before.

    The square root keeps quiet passages visible without loud ones flattening
    everything — that part of the old behaviour is deliberately unchanged.
    """
    if rms <= floor:
        return 0.0
    span = max(1e-6, ceiling - floor)
    return min(1.0, (rms - floor) / span) ** 0.5


class MusicAnalyzer:
    """One source's idea of silence and of a beat.

    Holds the history for whichever source is being listened to. Switching
    between system audio and a microphone, stopping and starting, or a capture
    error all call :meth:`reset` — a microphone's floor describes a room, a
    loopback's describes a silent digital line, and carrying one over to the
    other is how a strip ends up either deaf or twitching.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._floor = 0.0
        self._open = False
        self._share_avg = 0.0
        self._env = 0.0
        self._beat_id = 0
        self._last_beat_ms: float | None = None
        self._seen = 0
        self.stats = AnalysisStats()

    # ── the floor ─────────────────────────────────────────────────────
    def _update_floor(self, rms: float) -> float:
        """Track the quiet, and only while it is quiet.

        Learning goes on while the gate is shut, because that is when what is
        being heard is the room. Once real sound is coming through, the floor is
        held: adapting to music means slowly deciding the music is the silence.
        """
        if self._floor <= 0.0:
            self._floor = min(_MAX_FLOOR, max(_MIN_FLOOR, rms))
            return self._floor
        if rms < self._floor:
            # Quieter than we thought: that is news, and it is always worth
            # hearing, open gate or not.
            self._floor += (rms - self._floor) * _FLOOR_FALL
        elif not self._open and rms < self._floor * _OPEN_RATIO:
            # Louder, but not loud enough to be sound, and nothing is currently
            # getting through. That is the room, so learn from it — slowly.
            #
            # Both conditions are needed. Learning while sound is coming through
            # means slowly deciding the music is the silence; learning from
            # blocks well above the threshold is worse still, because raising
            # the floor raises the level at which the gate shuts, which lets in
            # another rise. That loop walks the floor up through the music until
            # the strip goes dark.
            self._floor += (rms - self._floor) * _FLOOR_RISE
        self._floor = min(_MAX_FLOOR, max(_MIN_FLOOR, self._floor))
        return self._floor

    def _gate(self, rms: float, floor: float, manual_floor: float) -> bool:
        """Whether this block counts as sound, with hysteresis.

        ``manual_floor`` is the microphone's own gate: a minimum strictness the
        user asked for, never a replacement for the measurement. Taking the
        larger of the two means turning the slider up can only ever make the app
        harder to trigger, which is what someone reaching for it wants.
        """
        open_at = max(floor * _OPEN_RATIO, manual_floor)
        close_at = max(floor * _CLOSE_RATIO, manual_floor * 0.85)
        if self._open:
            self._open = rms > close_at
        else:
            self._open = rms > open_at
        return self._open

    # ── the beat ──────────────────────────────────────────────────────
    def _update_beat(self, bass: float, total: float, now_ms: float) -> bool:
        """A rise in the bass *share*, no sooner than the cooldown allows."""
        share = bass / total if total > 1e-9 else 0.0
        if self._share_avg <= 0.0:
            self._share_avg = share
            return False
        ready = (
            self._last_beat_ms is None or (now_ms - self._last_beat_ms) >= MIN_BEAT_GAP_MS
        )
        beat = ready and share > self._share_avg * _BEAT_RATIO
        # The average follows regardless, so a sustained heavy bass line becomes
        # the new normal instead of a beat on every block.
        self._share_avg += (share - self._share_avg) * _SHARE_RATE
        if beat:
            self._last_beat_ms = now_ms
        return beat

    # ── one block ─────────────────────────────────────────────────────
    def feed(
        self,
        *,
        bass: float,
        mid: float,
        treble: float,
        rms: float,
        now_ms: float,
        manual_gate: float = 0.0,
    ) -> Reading:
        """Judge one block. ``manual_gate`` is an RMS, not a fraction."""
        self._seen += 1
        self.stats.blocks += 1
        floor = self._update_floor(rms)
        self.stats.noise_floor = floor

        sounding = self._gate(rms, floor, manual_gate)
        if not sounding:
            # Silence: the envelope keeps falling rather than holding, so the
            # strip settles instead of pulsing on a beat that has passed.
            self._env = max(0.0, self._env * _ENVELOPE_DECAY)
            self.stats.silent_blocks += 1
            return Reading(
                level=0.0,
                beat_id=self._beat_id,
                envelope=self._env,
                silent=True,
                noise_floor=floor,
            )

        beat = self._update_beat(bass, bass + mid + treble, now_ms)
        self._env = 1.0 if beat else max(0.0, self._env * _ENVELOPE_DECAY)
        if beat:
            self.stats.beats += 1
            self._beat_id += 1

        level = normalize_above(rms, max(floor * _CLOSE_RATIO, manual_gate))
        self.stats.peak_level = max(self.stats.peak_level, level)
        return Reading(
            level=level,
            beat=beat,
            beat_id=self._beat_id,
            envelope=self._env,
            silent=False,
            noise_floor=floor,
        )


    def level_for(self, rms: float, manual_gate: float = 0.0) -> float:
        """Loudness of an already-smoothed RMS against the floor just measured.

        The gate and the onset are judged on the raw block — a transient does
        not survive smoothing — while brightness follows the smoothed value, so
        the strip glides. Both use the same floor, which is why it is asked for
        here rather than recomputed.
        """
        if not self._open:
            return 0.0
        return normalize_above(rms, max(self._floor * _CLOSE_RATIO, manual_gate))


@dataclass(frozen=True)
class MusicSyncReport:
    """What the diagnostics block says about a run."""

    source: str = ""
    seconds: float = 0.0
    noise_floor: float = 0.0
    beats: int = 0
    silent_blocks: int = 0
    blocks: int = 0
    peak_level: float = 0.0
    # What the experimental onset detector would have said, had it been the one
    # driving the strip. It is not: it runs beside the working detector and is
    # only counted, so a run on real music can be compared before anything
    # changes. ``agreements`` are the blocks both called a strike.
    onset_blocks: int = 0
    onset_candidates: int = 0
    onset_agreements: int = 0
    settings: dict = field(default_factory=dict)
