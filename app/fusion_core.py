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

**A modulation** is what the music is doing. It moves brightness and it never
touches hue: the screen says *what colour*, the music says *how much of it*.
Modulation is bounded — at its quietest it takes brightness down to
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

# How far down music may pull the base brightness. Not a slider: v1 fixes the
# range so that "Screen + Music" has one predictable character, and the only
# thing the user aims is the beat impulse. 0.65 is deep enough to be plainly
# visible on a wall and shallow enough that a quiet passage still lights a room.
MODULATION_FLOOR = 0.65

# How much a beat may add on top, at full "Бит". Headroom, not a target: it is
# added to an already-modulated brightness and the result is clipped, so a beat
# in a loud passage is a smaller jump than a beat in a quiet one — which is how
# a beat sounds.
BEAT_HEADROOM = 0.35

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
    brightness: float = 1.0
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
    at: float = 0.0
    block_seconds: float = 0.05


@dataclass(frozen=True)
class TransientOverlay:
    """Something shown on top for a moment, then gone."""

    rgb: RGB
    brightness: float = 1.0
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
    brightness: float = 0.0
    should_send: bool = False
    reason: str = "no_base"
    activity: float = 0.0
    music_stale: bool = False
    base_stale: bool = False
    overlay: bool = False
    base_source: str = ""

    @property
    def brightness8(self) -> int:
        """Brightness as the 0..255 the drivers speak."""
        return _clamp8(self.brightness * 255.0)


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
            self._base = None
            self._music = None
            self._activity = 0.0

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

        brightness = _clamp(base.brightness)
        if activity > 0.0 and music is not None:
            # The last known modulation keeps being applied while the influence
            # fades. Dropping it the instant the audio goes stale would make
            # silence a cut rather than a fade, and the smoothing above would be
            # decoration — the strip would still snap back to the base in one
            # frame. The influence reaching zero is what ends it, and it reaches
            # zero exactly.
            # Quiet music pulls brightness down toward the floor; loud music
            # leaves it where the base put it. The factor passes through exactly
            # 1.0 at zero influence, which is what makes silence a true return.
            factor = MODULATION_FLOOR + (1.0 - MODULATION_FLOOR) * _clamp(music.level)
            brightness *= 1.0 + activity * (factor - 1.0)
            brightness += (
                activity * _clamp(music.beat_envelope) * _clamp(beat_gain) * BEAT_HEADROOM
            )
        brightness = _clamp(brightness)

        rgb = base.rgb
        reason = "composed"
        if overlay_weight > 0.0 and overlay is not None:
            rgb = (
                _clamp8(rgb[0] + (overlay.rgb[0] - rgb[0]) * overlay_weight),
                _clamp8(rgb[1] + (overlay.rgb[1] - rgb[1]) * overlay_weight),
                _clamp8(rgb[2] + (overlay.rgb[2] - rgb[2]) * overlay_weight),
            )
            brightness += (_clamp(overlay.brightness) - brightness) * overlay_weight
            reason = "overlay"

        return ComposedFrame(
            rgb=(_clamp8(rgb[0]), _clamp8(rgb[1]), _clamp8(rgb[2])),
            brightness=_clamp(brightness),
            should_send=True,
            reason=reason,
            activity=activity,
            music_stale=music_stale,
            base_stale=False,
            overlay=overlay_weight > 0.0,
            base_source=base.source,
        )
