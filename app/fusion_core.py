"""One place where the colour going to the strip is decided.

Today each mode owns its own stream engine and writes to the strip itself, so
"screen colour, music brightness" has nowhere to happen — there is no single
final frame, only two owners taking the line from each other. This is that
single frame, with no Qt, no capture and no BLE anywhere near it, so every rule
below can be played out on synthetic input in microseconds.

Three inputs go in and one frame comes out.

**A base** is whatever decides the colour — screen capture, or a plain chosen
colour. It carries its own timestamp because a base that has stopped arriving
must not keep being sent: a frozen picture on the wall is worse than nothing,
and it is indistinguishable from a working one.

**A modulation** is what the music is doing. It moves the brightness factor and
never
touches hue: the screen says *what colour*, the music says *how much of it*.
Modulation is bounded — at its quietest it takes the factor down to
``MODULATION_FLOOR`` of the base, never to black — because a strip that goes
dark in every quiet passage reads as broken rather than musical.

**An overlay** is something shown for a moment on top: a notification, an
alert. It has a duration and it fades, and when it is over the frame returns to
exactly what it would have been. Built here and tested here; nothing in 0.4.0
turns an existing scene into one.

An overlay currently needs a fresh base to sit on — with none, nothing is sent.
That is defensible only while an overlay is not a user-facing feature: it is
composed *onto* a picture and there would be nothing to return to. A real
notification or an emergency colour probably has to light the strip whether or
not Screen Sync is running, so this is a decision to revisit rather than a rule.

Two things are deliberately separate from all of that, because conflating them
is what today's code does:

``mode``          what the user chose. Survives everything.
``sources``       whether capture and audio are actually running.
``output``        whether anything may be written to the strip at all.

Power is only the third. Turning the strip off stops the writing and forgets
nothing; turning it back on does not release the last frame it happened to be
holding — that frame describes a screen from some minutes ago. The base is
dropped, and the next real one is waited for.

The frame says ``should_send`` outright. A caller must never have to infer
"nothing to send" from a black colour, because black is also a legitimate
colour to send.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

RGB = tuple[int, int, int]

# How far down music may pull the base factor. Not a slider: v1 fixes the
# range so that "Screen + Music" has one predictable character, and the only
# thing the user aims is the beat impulse. 0.65 is deep enough to be plainly
# visible on a wall and shallow enough that a quiet passage still lights a room.
MODULATION_FLOOR = 0.65

# A beat has to be visible against a picture that is already moving, and the
# two things that stopped it being visible are worth naming.
#
# On a bright frame there was nowhere to go: the level was already at the
# ceiling and the impulse was clipped away — at full volume it was measurably
# *zero*. So while music is being heard, the level is held below the ceiling by
# this much, and the beat is what spends the reserve.
MAX_BEAT_RESERVE = 0.18
# On a dark frame the reserve buys little: returning to full simply restores the
# same dark colour. So a beat also amplifies the colour itself, limited by the
# brightest channel so the ratios between them survive — an unlimited gain would
# clip red first on a warm frame and slide the hue toward yellow, which is the
# one thing this mode promises not to do.
MAX_BEAT_GAIN = 1.35

# How quickly the music's influence arrives and leaves. Arrival is quick enough
# to feel like a response; departure is slow, because silence between tracks or
# between phrases must not snap the strip back to full brightness.
ACTIVITY_ATTACK_S = 0.25
ACTIVITY_RELEASE_S = 0.90
# Below this the influence is simply over, and the frame is the base exactly.
# Without a snap an exponential approach leaves a permanent fraction of a
# percent of modulation, and "returns to the base" becomes almost true, which
# is not a property anything can be tested against.
_ACTIVITY_EPSILON = 0.002

# Audio arrives in blocks, and a block is not a unit of time — it changes with
# the device's sample rate and buffer. Staleness is counted in blocks and then
# converted, so a slow device is not permanently considered stale.
MUSIC_STALE_BLOCKS = 3.0
# ...with a floor, so one dropped block on a fast device does not read as
# silence. The jump that would cause is exactly what this avoids.
MIN_MUSIC_STALE_S = 0.25

# A base older than this is not describing what is on the screen any more.
BASE_STALE_S = 0.75


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _clamp8(value: float) -> int:
    return max(0, min(255, round(value)))


@dataclass(frozen=True)
class BaseSample:
    """What colour the strip should be, before music has a say."""

    rgb: RGB
    brightness_factor: float = 1.0
    source: str = "screen"
    at: float = 0.0


@dataclass(frozen=True)
class MusicModulation:
    """What the music is doing right now.

    ``block_seconds`` is the real duration of the audio block this came from,
    and it is what staleness is measured against.
    """

    level: float = 0.0
    beat_envelope: float = 0.0
    # Which beat the envelope belongs to. A decaying value cannot be told from a
    # weaker new one, so anything deciding "has this beat been shown yet" needs
    # the identity rather than the number.
    beat_id: int = 0
    at: float = 0.0
    block_seconds: float = 0.05


@dataclass(frozen=True)
class TransientOverlay:
    """Something shown on top for a moment, then gone."""

    rgb: RGB
    brightness_factor: float = 1.0
    started_at: float = 0.0
    duration: float = 1.0
    fade_in: float = 0.15
    fade_out: float = 0.35

    def weight_at(self, now: float) -> float:
        """How much of the frame this overlay owns, 0..1."""
        elapsed = now - self.started_at
        if elapsed < 0.0 or elapsed >= self.duration:
            return 0.0
        if self.fade_in > 0.0 and elapsed < self.fade_in:
            return _clamp(elapsed / self.fade_in)
        remaining = self.duration - elapsed
        if self.fade_out > 0.0 and remaining < self.fade_out:
            return _clamp(remaining / self.fade_out)
        return 1.0


@dataclass(frozen=True)
class ComposedFrame:
    """The one answer. ``should_send`` is the answer to "anything to write?"."""

    rgb: RGB = (0, 0, 0)
    # A fraction of the base, never a device brightness. The strip keeps its own
    # hardware brightness — the slider a person set — and this scales the colour
    # underneath it. At a hardware 50% and a factor of 0.65 the wall shows about
    # a third of full, which is correct and is why the two are never added up or
    # reported as one number.
    brightness_factor: float = 0.0
    # What a beat multiplies the colour by, already limited so no channel
    # clips. 1.0 whenever there is no beat, which is most frames.
    beat_boost: float = 1.0
    # Which beat that boost belongs to, so whoever writes to the strip can say
    # afterwards which strike actually went out. 0 when the frame carries none.
    beat_id: int = 0
    should_send: bool = False
    reason: str = "no_base"
    activity: float = 0.0
    music_stale: bool = False
    base_stale: bool = False
    overlay: bool = False
    base_source: str = ""


class FusionCompositor:
    """Holds the three states and turns the three inputs into one frame.

    Pure: the only thing it reaches for outside itself is the clock, and that is
    injected so a test can play out a minute of silence without waiting one.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._mode = "off"
        self._sources_running = False
        self._output_allowed = True
        self._base: BaseSample | None = None
        self._music: MusicModulation | None = None
        self._overlay: TransientOverlay | None = None
        self._activity = 0.0
        self._last_tick: float | None = None

    # ── the three states, kept apart on purpose ───────────────────────
    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        """Choose what the strip is doing. Nothing else clears this."""
        if mode != self._mode:
            self._mode = mode
            self.forget_inputs()

    @property
    def sources_running(self) -> bool:
        return self._sources_running

    def set_sources_running(self, running: bool) -> None:
        self._sources_running = bool(running)

    @property
    def output_allowed(self) -> bool:
        return self._output_allowed

    def set_output_allowed(self, allowed: bool) -> None:
        """Power, in effect. Blocks writing; keeps the chosen mode.

        Coming back allows writing again but drops the base: what was last
        captured describes a screen from before the strip was switched off, and
        sending it would show a stale frame at the moment someone is looking.
        The next real sample is waited for instead.
        """
        allowed = bool(allowed)
        if allowed and not self._output_allowed:
            self._base = None
            self._music = None
            self._activity = 0.0
        self._output_allowed = allowed

    def forget_inputs(self) -> None:
        """Drop the base, the modulation and the influence; keep the mode.

        Separate from :meth:`set_output_allowed` so a caller can clear at the
        exact point in a sequence it means to, rather than as a side effect of
        changing permission.
        """
        self._base = None
        self._music = None
        self._activity = 0.0
        # The clock reading too, or the pause counts as elapsed time on the next
        # frame: five minutes of "dt" makes the smoothing step 1.0 and the very
        # first block after a gap arrives at full influence, which is the jump
        # the fade exists to prevent.
        self._last_tick = None

    # ── inputs ────────────────────────────────────────────────────────
    def submit_base(self, sample: BaseSample) -> None:
        self._base = sample

    def submit_music(self, modulation: MusicModulation) -> None:
        self._music = modulation

    def show_overlay(self, overlay: TransientOverlay) -> None:
        self._overlay = overlay

    def clear_overlay(self) -> None:
        self._overlay = None

    # ── the influence of music, arriving and leaving ──────────────────
    def _music_is_stale(self, music: MusicModulation, now: float) -> bool:
        window = max(MIN_MUSIC_STALE_S, music.block_seconds * MUSIC_STALE_BLOCKS)
        return (now - music.at) > window

    def _advance_activity(self, target: float, now: float) -> float:
        """Move the influence toward where it should be, in real time.

        Framed as a time constant rather than a per-call fraction because the
        caller's rate is not fixed — a slower capture must not mean slower fades.
        """
        elapsed = 0.0 if self._last_tick is None else max(0.0, now - self._last_tick)
        self._last_tick = now
        tau = ACTIVITY_ATTACK_S if target > self._activity else ACTIVITY_RELEASE_S
        if elapsed <= 0.0:
            step = 0.0
        elif tau <= 0.0:
            step = 1.0
        else:
            # 1 - exp(-dt/tau), without importing math for one call.
            step = _clamp(1.0 - (2.718281828459045 ** (-elapsed / tau)))
        self._activity += (target - self._activity) * step
        if target <= 0.0 and self._activity < _ACTIVITY_EPSILON:
            self._activity = 0.0
        self._activity = _clamp(self._activity)
        return self._activity

    # ── the frame ─────────────────────────────────────────────────────
    def compose(self, *, beat_gain: float = 1.0) -> ComposedFrame:
        """Decide what to send, or that nothing should be sent."""
        now = self._clock()
        base = self._base
        base_stale = base is not None and (now - base.at) > BASE_STALE_S

        music = self._music
        music_stale = music is None or self._music_is_stale(music, now)
        target = 0.0 if music_stale else 1.0
        activity = self._advance_activity(target, now)

        overlay = self._overlay
        overlay_weight = overlay.weight_at(now) if overlay is not None else 0.0
        if overlay is not None and overlay_weight <= 0.0 and now >= (
            overlay.started_at + overlay.duration
        ):
            self._overlay = None

        if not self._output_allowed:
            # The mode, the base and the influence all stay exactly as they are.
            return ComposedFrame(
                reason="output_blocked",
                activity=activity,
                music_stale=music_stale,
                base_stale=base_stale,
                base_source=base.source if base else "",
            )
        if base is None:
            return ComposedFrame(reason="no_base", activity=activity, music_stale=music_stale)
        if base_stale:
            # Nothing goes out. A stale base is not black and it is not the last
            # good frame either — it is an absence, and it says so.
            return ComposedFrame(
                reason="base_stale",
                activity=activity,
                music_stale=music_stale,
                base_stale=True,
                base_source=base.source,
            )

        beat_gain = _clamp(beat_gain)
        brightness_factor = _clamp(base.brightness_factor)
        boost = 1.0
        beat_id = 0
        if activity > 0.0 and music is not None:
            # The last known modulation keeps being applied while the influence
            # fades. Dropping it the instant the audio goes stale would make
            # silence a cut rather than a fade, and the smoothing above would be
            # decoration — the strip would still snap back to the base in one
            # frame. The influence reaching zero is what ends it, and it reaches
            # zero exactly.
            # Quiet music pulls the factor down toward the floor; loud music
            # takes it up to the ceiling. The factor passes through exactly 1.0
            # at zero influence, which is what makes silence a true return — and
            # it is why the reserve costs nothing while nothing is playing.
            #
            # The reserve scales with the slider rather than switching on above
            # zero: a step from 0% to 1% would otherwise darken every loud
            # passage by a fifth, in one jump, for a slider nudge.
            ceiling = 1.0 - MAX_BEAT_RESERVE * beat_gain
            factor = MODULATION_FLOOR + (ceiling - MODULATION_FLOOR) * _clamp(music.level)
            brightness_factor *= 1.0 + activity * (factor - 1.0)
            impulse = activity * _clamp(music.beat_envelope) * beat_gain
            boost = 1.0 + impulse * (MAX_BEAT_GAIN - 1.0)
            if boost > 1.0:
                beat_id = int(music.beat_id)
        brightness_factor = _clamp(brightness_factor)

        rgb = base.rgb
        if boost > 1.0:
            # Limited by whichever channel would reach 255 first. Scaling all
            # three by the same number is what keeps the hue; scaling until one
            # of them saturates and the others carry on is what loses it.
            headroom = 255.0 / max(1.0, max(rgb) * brightness_factor)
            boost = min(boost, max(1.0, headroom))
        reason = "composed"
        if overlay_weight > 0.0 and overlay is not None:
            rgb = (
                _clamp8(rgb[0] + (overlay.rgb[0] - rgb[0]) * overlay_weight),
                _clamp8(rgb[1] + (overlay.rgb[1] - rgb[1]) * overlay_weight),
                _clamp8(rgb[2] + (overlay.rgb[2] - rgb[2]) * overlay_weight),
            )
            brightness_factor += (_clamp(overlay.brightness_factor) - brightness_factor) * overlay_weight
            reason = "overlay"

        return ComposedFrame(
            rgb=(_clamp8(rgb[0]), _clamp8(rgb[1]), _clamp8(rgb[2])),
            brightness_factor=_clamp(brightness_factor),
            beat_boost=boost,
            beat_id=beat_id,
            should_send=True,
            reason=reason,
            activity=activity,
            music_stale=music_stale,
            base_stale=False,
            overlay=overlay_weight > 0.0,
            base_source=base.source,
        )
