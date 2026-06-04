from __future__ import annotations

import pytest

from app import feature_gate


def test_free_mode_limits_pro_features(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings: False)

    assert feature_gate.is_pro() is False
    assert feature_gate.can_use("schedule") is False
    assert feature_gate.can_use("profile_import") is False
    assert feature_gate.can_use("extra_drivers") is True
    assert feature_gate.can_use("unknown_future_feature") is True
    assert feature_gate.free_effect_limit() == feature_gate.FREE_EFFECT_COUNT
    assert feature_gate.profile_limit() == feature_gate.FREE_PROFILE_MAX


def test_verified_license_unlocks_pro_features(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "load_settings", lambda: {"license": {"activated": True}})
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings: True)

    assert feature_gate.is_pro() is True
    assert feature_gate.can_use("schedule") is True
    assert feature_gate.can_use("profile_import") is True
    assert feature_gate.free_effect_limit() == feature_gate.PRO_LIMIT_SENTINEL
    assert feature_gate.profile_limit() == feature_gate.PRO_LIMIT_SENTINEL


def test_require_feature_raises_for_locked_feature(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings: False)

    with pytest.raises(feature_gate.ProFeatureError) as error:
        feature_gate.require_feature("schedule")

    assert error.value.feature == "schedule"


def test_profile_capacity_raises_at_free_limit(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings: False)

    feature_gate.ensure_profile_capacity(feature_gate.FREE_PROFILE_MAX - 1)
    with pytest.raises(feature_gate.ProfileLimitError):
        feature_gate.ensure_profile_capacity(feature_gate.FREE_PROFILE_MAX)


def test_profile_capacity_allows_verified_pro_counts(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "load_settings", lambda: {"license": {"activated": True}})
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings: True)

    feature_gate.ensure_profile_capacity(100)
