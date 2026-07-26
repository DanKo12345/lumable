from __future__ import annotations

import app.windows_motion as wm
from app.motion_policy import MotionPolicy


def test_windows_motion_reduced_inverts_the_animation_flag(monkeypatch) -> None:
    # Animations enabled → NOT reduced; animations disabled → reduced.
    monkeypatch.setattr(wm, "_client_area_animation_enabled", lambda: True)
    assert wm.windows_motion_reduced() is False

    monkeypatch.setattr(wm, "_client_area_animation_enabled", lambda: False)
    assert wm.windows_motion_reduced() is True


def test_provider_error_is_absorbed_by_the_policy(monkeypatch) -> None:
    def boom() -> bool:
        raise OSError("no API here")

    monkeypatch.setattr(wm, "_client_area_animation_enabled", boom)
    policy = MotionPolicy(provider=wm.windows_motion_reduced)  # system mode
    policy.refresh()
    # A probe failure must never flip the UI into reduced motion.
    assert policy.reduced is False


def test_reduced_flows_through_the_policy_in_system_mode(monkeypatch) -> None:
    monkeypatch.setattr(wm, "_client_area_animation_enabled", lambda: False)  # animations off
    policy = MotionPolicy(provider=wm.windows_motion_reduced)
    policy.refresh()
    assert policy.reduced is True
