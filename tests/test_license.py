from __future__ import annotations

from app.license import activate_license_key, is_license_active, normalize_license_key, validate_license_state


def test_license_activation_is_disabled_until_backend_exists() -> None:
    settings: dict = {}

    assert activate_license_key("any-key", settings) is False
    assert settings == {}
    assert is_license_active(settings) is False


def test_invalid_key_does_not_change_settings() -> None:
    settings = {"license": {"activated": False, "edition": "free", "kind": ""}}

    assert activate_license_key("wrong", settings) is False
    assert settings["license"]["edition"] == "free"


def test_license_state_normalizes_broken_payload() -> None:
    expected_free_state = {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "",
        "license_key": "",
        "license_id": "",
        "instance_id": "",
        "checked_at": "",
        "grace_days": 7,
    }
    assert validate_license_state("broken") == expected_free_state
    assert validate_license_state({"activated": True, "edition": "pro", "kind": "dev"}) == {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "",
        "license_key": "",
        "license_id": "",
        "instance_id": "",
        "checked_at": "",
        "grace_days": 7,
    }


def test_license_state_preserves_future_lemonsqueezy_fields() -> None:
    assert validate_license_state(
        {
            "license_key": "LS-123",
            "license_id": "lic_123",
            "instance_id": "inst_123",
            "checked_at": "2026-06-05T12:00:00Z",
        }
    ) == {
        "activated": False,
        "edition": "free",
        "kind": "",
        "provider": "lemonsqueezy",
        "license_key": "LS-123",
        "license_id": "lic_123",
        "instance_id": "inst_123",
        "checked_at": "2026-06-05T12:00:00Z",
        "grace_days": 7,
    }


def test_normalize_license_key_ignores_case_and_spaces() -> None:
    assert normalize_license_key(" dollza dev pro ") == "DOLLZADEVPRO"
