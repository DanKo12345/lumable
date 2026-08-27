from __future__ import annotations

import pytest

from app import feature_gate


class _Identity:
    """Only the part the gate asks about."""

    installation_hash = "9f2c" * 10 + "abc"
    highest_seen = None


def _say_pro(monkeypatch, answer: bool, settings: dict | None = None, identity=None):
    """Stand in for the local decision: a receipt, an identity and a clock.

    The three of them together are what ``is_pro`` asks, and asking them for
    real would mean signing a receipt and writing a protected file in every
    test about profile limits. What each of the three decides has its own
    tests; this is about what the gate does with the answer.
    """
    monkeypatch.setattr(
        feature_gate,
        "_local_state",
        lambda: (answer, settings if settings is not None else {}, identity),
    )
    feature_gate.invalidate_pro_cache()
    return settings


def test_scenes_are_free_not_a_pro_feature() -> None:
    """Scenes are Free in 0.3.2 — the dead ``scenes_full`` gate was removed so
    the Pro window and the source of truth can't advertise them as Pro."""
    assert "scenes_full" not in feature_gate.PRO_FEATURES
    assert feature_gate.can_use("scenes_full") is True


def test_free_mode_limits_pro_features(monkeypatch) -> None:
    _say_pro(monkeypatch, False)

    assert feature_gate.is_pro() is False
    assert feature_gate.can_use("schedule") is False
    assert feature_gate.can_use("profile_import") is False
    assert feature_gate.can_use("color_picker_hsv") is True
    assert feature_gate.can_use("extra_drivers") is True
    assert feature_gate.can_use("unknown_future_feature") is True
    assert feature_gate.free_effect_limit() == feature_gate.FREE_EFFECT_COUNT
    assert feature_gate.profile_limit() == feature_gate.FREE_PROFILE_MAX


def test_verified_license_unlocks_pro_features(monkeypatch) -> None:
    _say_pro(monkeypatch, True)

    assert feature_gate.is_pro() is True
    assert feature_gate.can_use("schedule") is True
    assert feature_gate.can_use("profile_import") is True
    assert feature_gate.free_effect_limit() == feature_gate.PRO_LIMIT_SENTINEL
    assert feature_gate.profile_limit() == feature_gate.PRO_LIMIT_SENTINEL


def test_a_licence_with_no_receipt_asks_for_one_in_the_background(monkeypatch) -> None:
    """The case a licence lands in when the service was unreachable during
    activation: everything Lemon Squeezy granted is on the machine, and the one
    thing missing is a receipt. The next run asks for that and nothing else — it
    must not activate again, because the slot is already spent.
    """
    settings = {"license": {"license_key": "KEY", "instance_id": "INSTANCE"}}
    identity = _Identity()
    asked: list = []
    _say_pro(monkeypatch, False, settings, identity)
    monkeypatch.setattr(
        feature_gate,
        "obtain_receipt",
        lambda payload, who, now: asked.append((payload, who)) or "unavailable",
    )
    monkeypatch.setattr(feature_gate, "advance_high_water", lambda who, _now: who)

    assert feature_gate.refresh_pro_status() is False
    assert asked == [(settings, identity)]
    assert settings["license"]["license_key"] == "KEY", "a failed refresh cost the licence"


def test_a_receipt_that_still_holds_is_left_alone(monkeypatch) -> None:
    """Asking daily is asking daily. A receipt issued this morning is not a
    reason to talk to anybody."""
    settings = {"license": {"receipt": {"issued_at": "2026-08-26T12:00:00+00:00"}}}
    asked: list = []
    _say_pro(monkeypatch, True, settings, _Identity())
    monkeypatch.setattr(feature_gate, "is_refresh_due", lambda *_a, **_k: False)
    monkeypatch.setattr(
        feature_gate, "obtain_receipt", lambda *args, **kwargs: asked.append(args) or "issued"
    )
    monkeypatch.setattr(feature_gate, "advance_high_water", lambda who, _now: who)

    assert feature_gate.refresh_pro_status() is True
    assert asked == [], "a receipt in good standing was refreshed anyway"


def test_the_clock_mark_moves_only_on_the_background_path(monkeypatch) -> None:
    """It is a write, and writes do not belong on the thread drawing the
    window."""
    saved: list = []
    identity = _Identity()
    _say_pro(monkeypatch, True, {}, identity)
    monkeypatch.setattr(feature_gate, "is_refresh_due", lambda *_a, **_k: False)
    monkeypatch.setattr(feature_gate, "advance_high_water", lambda _who, _now: "moved")
    monkeypatch.setattr(feature_gate, "save_identity", lambda who: saved.append(who) or True)

    assert feature_gate.is_pro() is True
    assert saved == [], "the interface thread wrote to disk"

    feature_gate.invalidate_pro_cache()
    feature_gate.refresh_pro_status()

    assert saved == ["moved"]


def test_force_pro_env_unlocks_pro_features(monkeypatch) -> None:
    monkeypatch.setenv("LUMABLE_FORCE_PRO", "1")
    monkeypatch.setattr(feature_gate.sys, "frozen", False, raising=False)
    _say_pro(monkeypatch, False)

    assert feature_gate.is_pro() is True
    assert feature_gate.can_use("schedule") is True
    assert feature_gate.can_use("custom_quick_modes") is True


def test_force_pro_env_is_ignored_in_frozen_build(monkeypatch) -> None:
    monkeypatch.setenv("LUMABLE_FORCE_PRO", "1")
    monkeypatch.setattr(feature_gate.sys, "frozen", True, raising=False)
    _say_pro(monkeypatch, False)

    assert feature_gate.is_pro() is False
    assert feature_gate.can_use("schedule") is False


def test_require_feature_raises_for_locked_feature(monkeypatch) -> None:
    _say_pro(monkeypatch, False)

    with pytest.raises(feature_gate.ProFeatureError) as error:
        feature_gate.require_feature("schedule")

    assert error.value.feature == "schedule"


def test_profile_capacity_raises_at_free_limit(monkeypatch) -> None:
    _say_pro(monkeypatch, False)

    feature_gate.ensure_profile_capacity(feature_gate.FREE_PROFILE_MAX - 1)
    with pytest.raises(feature_gate.ProfileLimitError):
        feature_gate.ensure_profile_capacity(feature_gate.FREE_PROFILE_MAX)


def test_profile_capacity_allows_verified_pro_counts(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "load_settings", lambda: {"license": {"activated": True}})
    _say_pro(monkeypatch, True)

    feature_gate.ensure_profile_capacity(100)
