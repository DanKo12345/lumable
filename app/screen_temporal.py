"""The temporal half of screen sync: smooth the colour stream and tame flashes.

Deliberately separate from :mod:`app.screen_sample` (the spatial half). The
spatial stage answers "what colour is in *this* frame" with no memory; this
stage answers "given that stream of frame colours, what should the strip
actually show" — which is inherently about time. Split like this, a jittery
result is easy to place: too nervous ⇒ this file, wrong colour ⇒ the other.

It runs **last** in the pipeline — ``spatial extract → shape_color → this`` — so
the flash limiter bounds the exact RGB the strip receives. Shaping first (gamma,
saturation) would otherwise be free to re-amplify a jump the limiter just capped.

Qt-free. Stateful (it remembers the last emitted colour), so it must be
:meth:`reset` on mode start, profile change and resume-after-pause, or a stale
colour bleeds across sessions.

**Frame-rate independent.** Every call takes the real ``dt`` since the previous
frame: ``smoothing`` is a half-life in seconds and the flash limit is a rate per
second, so Desktop/Game/Movie feel identical whether capture runs at 12 fps or
drops to 4. (For ambient this is the *only* smoother — the shared
``ColorStreamEngine`` keeps its BLE send-rate cap but its own easing is switched
off, so the colour is never smoothed twice.)
"""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]

# Guard rails on dt: a hitch or a paused thread must not let one frame jump the
# whole way (huge dt) or divide by zero (dt≈0).
_MIN_DT = 0.001
_MAX_DT = 0.5


@dataclass(frozen=True)
class TemporalConfig:
    half_life_s: float = 0.12   # seconds to cover half the remaining gap
    max_rate: int = 480         # max per-channel change per second (flash limiter)
    max_step: int = 60          # absolute per-update cap, independent of dt


def _clamp8(value: float) -> int:
    return 0 if value < 0 else 255 if value > 255 else round(value)


def _coerce(rgb: RGB) -> RGB:
    return (_clamp8(rgb[0]), _clamp8(rgb[1]), _clamp8(rgb[2]))


class TemporalFilter:
    """Feed it one frame colour and the elapsed ``dt``; get the colour to show.

    ``half_life_s`` is exponential easing expressed in time; ``max_rate`` is a
    hard cap on how fast any channel may move; ``max_step`` bounds a single
    update no matter how large ``dt`` is (a thread hitch clamps dt to 0.5 s,
    which at ``max_rate`` alone would still allow a big jump). Together an
    explosion ramps up over a few frames instead of strobing the room.

    Seed it with the strip's current colour (constructor ``initial`` or
    ``reset(initial)``) so the very first frame after a start or a profile switch
    is limited too — otherwise a first-frame white flash would jump instantly.
    """

    def __init__(self, config: TemporalConfig | None = None, initial: RGB | None = None) -> None:
        self._config = config or TemporalConfig()
        self._last: RGB | None = _coerce(initial) if initial is not None else None

    def reset(self, initial: RGB | None = None) -> None:
        """Drop history. With ``initial`` the next frame is still rate-limited
        (seed from the strip's colour); without it the next frame shows as-is."""
        self._last = _coerce(initial) if initial is not None else None

    def set_config(self, config: TemporalConfig) -> None:
        self._config = config

    @property
    def last(self) -> RGB | None:
        return self._last

    def push(self, rgb: RGB, dt: float) -> RGB:
        target = _coerce(rgb)
        if self._last is None:
            self._last = target
            return target

        dt = _MIN_DT if dt < _MIN_DT else _MAX_DT if dt > _MAX_DT else dt
        half_life = max(1e-4, self._config.half_life_s)
        alpha = 1.0 - 0.5 ** (dt / half_life)  # fraction of the gap to close this frame
        step_cap = max(1.0, min(self._config.max_rate * dt, float(self._config.max_step)))

        out = []
        for prev, new in zip(self._last, target, strict=True):
            delta = (new - prev) * alpha
            if delta > step_cap:
                delta = step_cap
            elif delta < -step_cap:
                delta = -step_cap
            nxt = _clamp8(prev + delta)
            # Integer-EMA stall guard: once the remaining gap × alpha rounds to
            # zero the value would freeze a few units short of the target (a bias
            # light never quite reaching its floor). Nudge one step so it always
            # converges — 1 is within any flash cap, so this can't cause a jump.
            if nxt == prev and new != prev:
                nxt = prev + (1 if new > prev else -1)
            out.append(nxt)
        result = (out[0], out[1], out[2])
        self._last = result
        return result
