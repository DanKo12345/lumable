from __future__ import annotations

from app.motion_policy import (
    DEFAULT_MOTION_MODE,
    MotionPolicy,
    normalize_motion_mode,
)


def test_normalize_unknown_mode_falls_back_to_system() -> None:
    assert normalize_motion_mode("banana") == "system"
    assert normalize_motion_mode("") == "system"
    assert normalize_motion_mode(None) == "system"
    assert normalize_motion_mode("REDUCED") == "reduced"
    assert normalize_motion_mode("full") == "full"


def test_default_state_is_not_reduced() -> None:
    policy = MotionPolicy()
    assert policy.mode == DEFAULT_MOTION_MODE == "system"
    assert policy.reduced is False


def test_construction_does_not_probe_the_provider() -> None:
    # Proves laziness without touching the global singleton (order-independent):
    # the provider is only consulted on refresh(), never at construction.
    calls = 0

    def counting() -> bool:
        nonlocal calls
        calls += 1
        return True

    policy = MotionPolicy(provider=counting)
    assert calls == 0
    assert policy.reduced is False

    policy.refresh()
    assert calls == 1
    assert policy.reduced is True


def test_reapplying_system_mode_still_reads_the_provider() -> None:
    # Startup: set_provider(...) then set_mode(stored) where stored is already
    # the default "system" — re-applying the same mode must still resolve.
    policy = MotionPolicy(provider=lambda: True)
    assert policy.mode == "system"
    policy.set_mode("system")
    assert policy.reduced is True


def test_reduced_mode_forces_reduced_ignoring_provider() -> None:
    policy = MotionPolicy(provider=lambda: False)
    policy.set_mode("reduced")
    assert policy.reduced is True


def test_full_mode_forces_animations_on_ignoring_provider() -> None:
    policy = MotionPolicy(provider=lambda: True)
    policy.set_mode("full")
    assert policy.reduced is False


def test_system_mode_defers_to_provider_and_rereads_on_refresh() -> None:
    state = {"reduced": True}
    policy = MotionPolicy(provider=lambda: state["reduced"])
    policy.refresh()  # mode is already "system"
    assert policy.reduced is True

    state["reduced"] = False
    policy.refresh()  # a changed Windows setting is picked up on refresh
    assert policy.reduced is False


def test_provider_error_falls_back_to_not_reduced() -> None:
    def boom() -> bool:
        raise OSError("no accessibility API here")

    policy = MotionPolicy(provider=boom)  # system mode
    policy.refresh()
    assert policy.reduced is False


def test_changed_emits_resolved_state_only_on_change() -> None:
    emissions: list[bool] = []
    policy = MotionPolicy(provider=lambda: True)
    policy.changed.connect(emissions.append)

    policy.set_mode("reduced")  # False -> True
    policy.refresh()  # still reduced -> no emission
    policy.set_mode("full")  # True -> False

    assert emissions == [True, False]


def test_unknown_mode_via_set_mode_normalizes_to_system() -> None:
    policy = MotionPolicy(provider=lambda: False)
    policy.set_mode("banana")
    assert policy.mode == "system"


def test_set_provider_does_not_refresh_on_its_own() -> None:
    policy = MotionPolicy()  # system, no provider -> reduced False
    emissions: list[bool] = []
    policy.changed.connect(emissions.append)

    policy.set_provider(lambda: True)  # installing a provider must not flip state...
    assert policy.reduced is False
    assert emissions == []

    policy.refresh()  # ...only an explicit refresh does
    assert policy.reduced is True
    assert emissions == [True]
