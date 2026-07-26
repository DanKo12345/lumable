from __future__ import annotations

from PySide6.QtCore import Property, QObject, QParallelAnimationGroup, QPropertyAnimation

from app.widgets.animation_helpers import motion_reduced, play_or_complete, restart_animation


class _Box(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._v = 0.0

    def _get(self) -> float:
        return self._v

    def _set(self, value: float) -> None:
        self._v = value

    v = Property(float, _get, _set)


def _anim(box: _Box) -> QPropertyAnimation:
    anim = QPropertyAnimation(box, b"v")
    anim.setDuration(200)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    return anim


def test_play_or_complete_jumps_to_end_when_reduced(preserve_motion_policy) -> None:
    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("reduced")
    assert motion_reduced() is True

    box = _Box()
    anim = _anim(box)
    play_or_complete(anim)

    # The end value is actually applied, and nothing is left running.
    assert box.property("v") == 1.0
    assert anim.state() == QPropertyAnimation.State.Stopped


def test_play_or_complete_animates_when_motion_is_full(preserve_motion_policy) -> None:
    policy = preserve_motion_policy
    policy.set_mode("full")
    assert motion_reduced() is False

    box = _Box()
    anim = _anim(box)
    play_or_complete(anim)

    assert anim.state() == QPropertyAnimation.State.Running
    anim.stop()


def test_reduced_completion_drives_finished_and_valuechanged(preserve_motion_policy) -> None:
    # The completion must go THROUGH the Qt engine: finished fires exactly once
    # (so cleanup wired to it runs) and valueChanged reaches the final value.
    policy = preserve_motion_policy
    policy.set_mode("reduced")

    box = _Box()
    anim = _anim(box)
    finished: list[bool] = []
    values: list[float] = []
    anim.finished.connect(lambda: finished.append(True))
    anim.valueChanged.connect(lambda v: values.append(float(v)))

    play_or_complete(anim)

    assert finished == [True]
    assert values and values[-1] == 1.0
    assert box.property("v") == 1.0
    assert anim.state() == QPropertyAnimation.State.Stopped


def test_reduced_completion_finishes_every_child_of_a_group(preserve_motion_policy) -> None:
    policy = preserve_motion_policy
    policy.set_mode("reduced")

    box1, box2 = _Box(), _Box()
    a1 = _anim(box1)
    a2 = QPropertyAnimation(box2, b"v")
    a2.setDuration(300)
    a2.setStartValue(0.0)
    a2.setEndValue(2.0)
    group = QParallelAnimationGroup()
    group.addAnimation(a1)
    group.addAnimation(a2)
    finished: list[bool] = []
    group.finished.connect(lambda: finished.append(True))

    play_or_complete(group)

    assert box1.property("v") == 1.0
    assert box2.property("v") == 2.0
    assert finished == [True]
    assert group.state() == QParallelAnimationGroup.State.Stopped


def test_switching_to_reduced_completes_a_running_animation(preserve_motion_policy) -> None:
    # The other half of the contract: motion may be reduced WHILE an animation is
    # already running. Flipping the policy must finish it in place.
    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    box = _Box()
    anim = _anim(box)
    finished: list[bool] = []
    anim.finished.connect(lambda: finished.append(True))

    play_or_complete(anim)  # full → actually animates, and is tracked
    assert anim.state() == QPropertyAnimation.State.Running

    policy.set_mode("reduced")  # changed(True) → finish the running animation

    assert box.property("v") == 1.0
    assert anim.state() == QPropertyAnimation.State.Stopped
    assert finished == [True]


def test_switching_to_reduced_survives_a_deleted_animation(preserve_motion_policy) -> None:
    # The tracked wrapper can outlive its C++ QObject (the WeakSet only drops it
    # on a Python GC). Flipping to reduced must skip the stale entry, not crash.
    import shiboken6

    from app.widgets.animation_helpers import _running_finite

    policy = preserve_motion_policy
    policy.set_provider(None)
    policy.set_mode("full")

    box = _Box()
    anim = _anim(box)
    play_or_complete(anim)  # tracked + running
    assert anim in _running_finite

    shiboken6.delete(anim)  # kill the underlying C++ object; the wrapper lingers

    policy.set_mode("reduced")  # must not raise despite the dead animation

    assert anim not in _running_finite  # the stale entry was discarded


def test_restart_animation_lands_final_value_when_reduced(preserve_motion_policy) -> None:
    policy = preserve_motion_policy
    policy.set_mode("reduced")

    box = _Box()
    anim = QPropertyAnimation(box, b"v")
    anim.setDuration(200)
    restart_animation(anim, 0.0, 0.5)

    assert box.property("v") == 0.5
    assert anim.state() == QPropertyAnimation.State.Stopped
