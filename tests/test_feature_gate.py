from __future__ import annotations

import pytest

from app import feature_gate


def test_free_mode_limits_pro_features(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: False)

    assert feature_gate.is_pro() is False
    assert feature_gate.can_use("schedule") is False
    assert feature_gate.can_use("profile_import") is False
    assert feature_gate.can_use("color_picker_hsv") is True
    assert feature_gate.can_use("extra_drivers") is True
    assert feature_gate.can_use("unknown_future_feature") is True
    assert feature_gate.free_effect_limit() == feature_gate.FREE_EFFECT_COUNT
    assert feature_gate.profile_limit() == feature_gate.FREE_PROFILE_MAX


def test_verified_license_unlocks_pro_features(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "load_settings", lambda: {"license": {"activated": True}})
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: True)

    assert feature_gate.is_pro() is True
    assert feature_gate.can_use("schedule") is True
    assert feature_gate.can_use("profile_import") is True
    assert feature_gate.free_effect_limit() == feature_gate.PRO_LIMIT_SENTINEL
    assert feature_gate.profile_limit() == feature_gate.PRO_LIMIT_SENTINEL


def test_verified_license_state_is_saved_when_revalidated(monkeypatch) -> None:
    settings = {"license": {"license_key": "KEY", "instance_id": "INSTANCE", "checked_at": "old"}}
    saved: list[dict] = []

    def activate(payload, **_kw):
        payload["license"]["checked_at"] = "new"
        payload["license"]["edition"] = "pro"
        return True

    monkeypatch.setattr(feature_gate, "load_settings", lambda: settings)
    monkeypatch.setattr(feature_gate, "is_license_active", activate)
    monkeypatch.setattr(feature_gate, "save_settings", lambda payload: saved.append(dict(payload)))

    # Persistence of a freshly revalidated license happens off the UI thread.
    assert feature_gate.refresh_pro_status() is True
    assert saved == [settings]


def test_force_pro_env_unlocks_pro_features(monkeypatch) -> None:
    monkeypatch.setenv("LUMABLE_FORCE_PRO", "1")
    monkeypatch.setattr(feature_gate.sys, "frozen", False, raising=False)
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: False)

    assert feature_gate.is_pro() is True
    assert feature_gate.can_use("schedule") is True
    assert feature_gate.can_use("custom_quick_modes") is True


def test_force_pro_env_is_ignored_in_frozen_build(monkeypatch) -> None:
    monkeypatch.setenv("LUMABLE_FORCE_PRO", "1")
    monkeypatch.setattr(feature_gate.sys, "frozen", True, raising=False)
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: False)

    assert feature_gate.is_pro() is False
    assert feature_gate.can_use("schedule") is False


def test_require_feature_raises_for_locked_feature(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: False)

    with pytest.raises(feature_gate.ProFeatureError) as error:
        feature_gate.require_feature("schedule")

    assert error.value.feature == "schedule"


def test_profile_capacity_raises_at_free_limit(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: False)

    feature_gate.ensure_profile_capacity(feature_gate.FREE_PROFILE_MAX - 1)
    with pytest.raises(feature_gate.ProfileLimitError):
        feature_gate.ensure_profile_capacity(feature_gate.FREE_PROFILE_MAX)


def test_profile_capacity_allows_verified_pro_counts(monkeypatch) -> None:
    monkeypatch.setattr(feature_gate, "load_settings", lambda: {"license": {"activated": True}})
    monkeypatch.setattr(feature_gate, "is_license_active", lambda _settings, **_kw: True)

    feature_gate.ensure_profile_capacity(100)
