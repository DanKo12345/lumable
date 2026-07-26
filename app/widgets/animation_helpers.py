from __future__ import annotations

import weakref

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation

from app.motion_policy import motion_policy

# Finite animations started (not completed) via play_or_complete, so that turning
# Reduced Motion on mid-flight can finish them. WeakSet: an animation drops out
# automatically when its owner is gone, so this never keeps anything alive.
_running_finite: weakref.WeakSet = weakref.WeakSet()


def _complete_running_on_reduced(reduced: bool) -> None:
    if not reduced:
        return
    # Snapshot first: a synchronous finished handler may delete the owner (which
    # mutates the WeakSet) or otherwise change the set while we iterate.
    for animation in tuple(_running_finite):
        try:
            total = animation.totalDuration()
            if animation.state() == QAbstractAnimation.State.Running and total >= 0:
                animation.setCurrentTime(total)  # finish it; do NOT re-start
        except RuntimeError:
            # The wrapper outlived its C++ QObject (WeakSet only drops it after a
            # Python GC). Any access raises RuntimeError — drop the stale entry.
            _running_finite.discard(animation)


# One subscription for the whole app: individual widgets never connect themselves.
motion_policy.changed.connect(_complete_running_on_reduced)


def make_property_animation(target, property_name: bytes, duration: int, easing: QEasingCurve.Type) -> QPropertyAnimation:
    animation = QPropertyAnimation(target, property_name, target)
    animation.setDuration(duration)
    animation.setEasingCurve(easing)
    return animation


def motion_reduced() -> bool:
    """The one place widgets ask whether UI motion should be reduced."""
    return motion_policy.reduced


def play_or_complete(animation: QAbstractAnimation) -> None:
    """Start the animation, or — when motion is reduced — advance it straight to
    its end THROUGH the Qt engine.

    Driving it via ``setCurrentTime(totalDuration())`` (rather than poking the
    end value onto the target) means ``valueChanged`` reaches the final value and
    ``finished`` still fires, so cleanup wired to ``finished`` runs and animation
    groups complete every child. Works for QPropertyAnimation and groups alike.

    Infinite/looping animations have no natural end (``totalDuration() < 0``) and
    must NOT be routed here — stop them and apply a static state at the call site.
    """
    if not motion_reduced():
        # Track finite animations BEFORE starting so a stateChanged handler that
        # flips the policy to reduced during start() can still see this one.
        # Infinite/looping ones are stopped by their category-2 owners with a
        # static state, so they are deliberately not tracked here.
        if animation.totalDuration() >= 0:
            _running_finite.add(animation)
        animation.start()
        return
    total = animation.totalDuration()
    if total < 0:
        animation.stop()  # infinite: the caller owns the static end state
        return
    animation.start()
    animation.setCurrentTime(total)


def restart_animation(animation: QPropertyAnimation, start, end) -> None:
    animation.stop()
    animation.setStartValue(start)
    animation.setEndValue(end)
    play_or_complete(animation)


class ButtonAnimationMixin:
    def _init_button_motion(self) -> None:
        # Spring motion: the scale slightly overshoots and settles instead of a
        # flat ease, giving presses/hovers the lively "bounce" feel of iOS.
        self._scale_anim = make_property_animation(self, b"scaleValue", 240, QEasingCurve.OutBack)
        self._ripple_anim = make_property_animation(self, b"rippleValue", 420, QEasingCurve.OutCubic)
        # Connect on the button itself (a QObject), so Qt disconnects the signal
        # automatically when the button is destroyed — no manual bookkeeping and
        # no duplicate subscriptions on re-init (called once per button).
        motion_policy.changed.connect(self._on_button_motion_changed)
        if motion_reduced():
            self._reset_button_motion()

    def _on_button_motion_changed(self, reduced: bool) -> None:
        if reduced:
            self._reset_button_motion()

    def _reset_button_motion(self) -> None:
        # Drop any in-flight ripple and return the scale to its resting 1.0.
        self._scale_anim.stop()
        self._ripple_anim.stop()
        self._scale = 1.0
        self._ripple = 0.0
        self._ripple_opacity = 0.0
        self.update()

    def _animate_button_scale(self, end_value: float) -> None:
        if motion_reduced():
            self._scale_anim.stop()
            self._scale = 1.0
            self.update()
            return
        restart_animation(self._scale_anim, self._scale, end_value)

    def _handle_button_enter(self) -> None:
        self._animate_button_scale(1.04)

    def _handle_button_leave(self) -> None:
        self._animate_button_scale(1.0)

    def _handle_button_press(self, x: float, y: float) -> None:
        if not motion_reduced():  # no new ripples under reduced motion
            self._ripple_x = x
            self._ripple_y = y
            self._ripple = 0.0
            self._ripple_opacity = 1.0
            restart_animation(self._ripple_anim, 0.0, 1.0)
        self._animate_button_scale(0.98)

    def _handle_button_release(self) -> None:
        self._animate_button_scale(1.04 if self.underMouse() else 1.0)
