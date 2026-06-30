from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.error import URLError

from app.license import (
    activate_license_key,
    deactivate_license,
    is_license_active,
    normalize_license_key,
    validate_license_state,
)

# ---------------------------------------------------------------------------
# validate_license_state
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# is_license_active
# ---------------------------------------------------------------------------


def test_is_license_active_returns_false_when_no_credentials() -> None:
    assert is_license_active({}) is False
    assert is_license_active({"license": {}}) is False
    assert is_license_active({"license": {"license_key": "KEY", "instance_id": ""}}) is False
    assert is_license_active({"license": {"license_key": "", "instance_id": "inst-uuid"}}) is False


def test_is_license_active_local_trusts_recent_without_network() -> None:
    # The UI-thread path (allow_network=False) trusts a recent check, no network.
    recent = datetime.now(UTC).isoformat()
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "checked_at": recent,
        }
    }
    with patch("app.license._ls_post") as mock_post:
        result = is_license_active(settings, allow_network=False)
    assert result is True
    mock_post.assert_not_called()


def test_is_license_active_network_revalidates_even_when_recent() -> None:
    # Hardening: a hand-edited recent timestamp must NOT skip the server check on
    # the authoritative path, so a forged local state can't grant Pro.
    recent = datetime.now(UTC).isoformat()
    settings = {
        "license": {
            "license_key": "LS-FORGED",
            "instance_id": "inst-uuid",
            "checked_at": recent,
        }
    }
    with patch("app.license._ls_post", return_value={"valid": False}) as mock_post:
        result = is_license_active(settings)  # allow_network=True by default
    assert result is False
    mock_post.assert_called_once()
    assert settings["license"]["edition"] == "free"


def test_is_license_active_rejects_forged_future_timestamp() -> None:
    # A future "checked_at" is forged: it earns neither the recent-shortcut nor
    # the offline grace window.
    future = (datetime.now(UTC) + timedelta(days=3650)).isoformat()
    settings = {
        "license": {
            "license_key": "LS-FORGED",
            "instance_id": "inst-uuid",
            "checked_at": future,
        }
    }
    with patch("app.license._ls_post") as mock_post:
        assert is_license_active(settings, allow_network=False) is False
        mock_post.assert_not_called()
    with patch("app.license._ls_post", side_effect=URLError("offline")):
        assert is_license_active(settings, allow_network=True) is False


def test_is_license_active_revalidates_when_stale() -> None:
    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "checked_at": stale,
        }
    }
    with patch("app.license._ls_post", return_value={"valid": True, "meta": {"variant_id": 1776109}}) as mock_post:
        result = is_license_active(settings)
    assert result is True
    mock_post.assert_called_once_with("validate", {"license_key": "LS-VALIDKEY", "instance_id": "inst-uuid"})
    assert settings["license"]["edition"] == "pro"


def test_is_license_active_clears_state_on_remote_invalidation() -> None:
    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    settings = {
        "license": {
            "license_key": "LS-REVOKED",
            "instance_id": "inst-uuid",
            "checked_at": stale,
        }
    }
    with patch("app.license._ls_post", return_value={"valid": False}):
        result = is_license_active(settings)
    assert result is False
    assert settings["license"]["instance_id"] == ""
    assert settings["license"]["license_id"] == ""
    assert settings["license"]["checked_at"] == ""
    assert settings["license"]["edition"] == "free"


def test_is_license_active_rejects_other_lemon_squeezy_variant() -> None:
    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    settings = {
        "license": {
            "license_key": "LS-OTHER-PRODUCT",
            "instance_id": "inst-uuid",
            "checked_at": stale,
        }
    }
    with patch("app.license._ls_post", return_value={"valid": True, "meta": {"variant_id": 123}}):
        result = is_license_active(settings)
    assert result is False
    assert settings["license"]["instance_id"] == ""
    assert settings["license"]["edition"] == "free"


def test_is_license_active_grants_grace_on_network_error() -> None:
    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "checked_at": stale,
        }
    }
    with patch("app.license._ls_post", side_effect=URLError("timeout")):
        result = is_license_active(settings)
    assert result is True


def test_is_license_active_denies_grace_after_grace_period() -> None:
    stale = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "checked_at": stale,
        }
    }
    with patch("app.license._ls_post", side_effect=URLError("timeout")):
        result = is_license_active(settings)
    assert result is False


# ---------------------------------------------------------------------------
# activate_license_key
# ---------------------------------------------------------------------------

_ACTIVATE_SUCCESS = {
    "activated": True,
    "error": None,
    "license_key": {"id": 42, "status": "active", "key": "LS-TESTKEY"},
    "instance": {"id": "inst-uuid-001", "name": "LumaBLE"},
    "meta": {"variant_id": 1776109},
}


def test_activate_license_key_success() -> None:
    settings: dict = {}
    with patch("app.license._ls_post", return_value=_ACTIVATE_SUCCESS):
        result = activate_license_key("ls-testkey", settings)
    assert result is True
    lic = settings["license"]
    assert lic["license_key"] == "LS-TESTKEY"
    assert lic["instance_id"] == "inst-uuid-001"
    assert lic["license_id"] == "42"
    assert lic["edition"] == "pro"
    assert lic["provider"] == "lemonsqueezy"
    assert lic["checked_at"] != ""


def test_activate_license_key_rejects_other_lemon_squeezy_variant() -> None:
    settings: dict = {}
    response = dict(_ACTIVATE_SUCCESS)
    response["meta"] = {"variant_id": 123}
    with patch("app.license._ls_post", return_value=response):
        result = activate_license_key("ls-testkey", settings)
    assert result is False
    assert settings == {}


def test_activate_license_key_rejected_by_server() -> None:
    settings: dict = {}
    with patch("app.license._ls_post", return_value={"activated": False, "error": "Invalid key"}):
        result = activate_license_key("WRONG-KEY", settings)
    assert result is False
    assert settings == {}


def test_activate_license_key_does_not_change_settings_on_rejection() -> None:
    settings = {"license": {"activated": False, "edition": "free", "kind": ""}}
    with patch("app.license._ls_post", return_value={"activated": False, "error": "Not found"}):
        result = activate_license_key("wrong", settings)
    assert result is False
    assert settings["license"]["edition"] == "free"


def test_activate_license_key_network_error() -> None:
    settings: dict = {}
    with patch("app.license._ls_post", side_effect=URLError("no network")):
        result = activate_license_key("LS-SOME-KEY", settings)
    assert result is False
    assert settings == {}


def test_activate_license_key_empty_key() -> None:
    settings: dict = {}
    assert activate_license_key("", settings) is False
    assert settings == {}


def test_deactivate_license_success_clears_local_state() -> None:
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "license_id": "42",
            "instance_id": "inst-uuid",
            "checked_at": datetime.now(UTC).isoformat(),
            "activated": True,
            "edition": "pro",
            "provider": "lemonsqueezy",
            "kind": "lemonsqueezy",
        }
    }

    with patch("app.license._ls_post", return_value={"deactivated": True}) as mock_post:
        result = deactivate_license(settings)

    assert result is True
    mock_post.assert_called_once_with("deactivate", {"license_key": "LS-VALIDKEY", "instance_id": "inst-uuid"})
    assert settings["license"]["license_key"] == ""
    assert settings["license"]["instance_id"] == ""
    assert settings["license"]["edition"] == "free"
    assert settings["license"]["provider"] == ""


def test_deactivate_license_keeps_state_on_network_error() -> None:
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "edition": "pro",
        }
    }

    with patch("app.license._ls_post", side_effect=URLError("offline")):
        result = deactivate_license(settings)

    assert result is False
    assert settings["license"]["license_key"] == "LS-VALIDKEY"
    assert settings["license"]["instance_id"] == "inst-uuid"


def test_deactivate_license_without_saved_instance_is_local_success() -> None:
    settings = {"license": {"license_key": "", "instance_id": "", "edition": "pro"}}

    assert deactivate_license(settings) is True
    assert settings["license"]["edition"] == "free"


def test_deactivate_license_confirms_via_validate_when_response_lost() -> None:
    # The server freed the slot, but the deactivate response never arrived.
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "license_id": "42",
            "edition": "pro",
        }
    }

    def fake_post(endpoint: str, _payload: dict) -> dict:
        if endpoint == "deactivate":
            raise URLError("lost response")
        return {"valid": False}

    with patch("app.license._ls_post", side_effect=fake_post):
        result = deactivate_license(settings)

    assert result is True
    assert settings["license"]["instance_id"] == ""
    assert settings["license"]["edition"] == "free"


def test_deactivate_license_keeps_state_when_still_valid() -> None:
    # deactivate did not confirm and the instance is still valid: keep Pro.
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "edition": "pro",
        }
    }

    def fake_post(endpoint: str, _payload: dict) -> dict:
        if endpoint == "deactivate":
            return {"deactivated": False, "error": "still active"}
        return {"valid": True, "meta": {"variant_id": 1776109}}

    with patch("app.license._ls_post", side_effect=fake_post):
        result = deactivate_license(settings)

    assert result is False
    assert settings["license"]["instance_id"] == "inst-uuid"


def test_license_overlay_active_mode_hides_key_input() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    labels = {
        "title": "Pro features",
        "subtitle": "Enter key",
        "active_title": "Pro is active",
        "active_license": "License active",
        "active_dev": "Dev Pro active",
        "key_label": "License key",
        "placeholder": "Paste key",
        "activate": "Activate",
        "buy": "Buy",
        "cancel": "Cancel",
        "ok": "OK",
        "invalid": "Invalid",
        "activated": "Activated",
        "buy_unavailable": "No purchase page",
        "deactivate": "Deactivate",
        "deactivated": "Deactivated",
        "deactivate_failed": "Could not deactivate",
    }
    overlay = LicenseOverlay(labels, lambda _key: (False, "Invalid"), parent, mode="dev")
    try:
        assert overlay.key_input.parentWidget().isVisible() is False
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_overlay_buy_button_uses_checkout_callback() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    labels = {
        "title": "Pro features",
        "subtitle": "Enter key",
        "active_title": "Pro is active",
        "active_license": "License active",
        "active_dev": "Dev Pro active",
        "key_label": "License key",
        "placeholder": "Paste key",
        "activate": "Activate",
        "buy": "Buy",
        "cancel": "Cancel",
        "ok": "OK",
        "invalid": "Invalid",
        "activated": "Activated",
        "buy_unavailable": "No purchase page",
        "deactivate": "Deactivate",
        "deactivated": "Deactivated",
        "deactivate_failed": "Could not deactivate",
    }
    calls: list[str] = []

    def buy() -> bool:
        calls.append("buy")
        return True

    overlay = LicenseOverlay(
        labels,
        lambda _key: (False, "Invalid"),
        parent,
        buy_callback=buy,
    )
    try:
        overlay.buy_button.click()
        assert calls == ["buy"]
        assert overlay.message_label.text() == ""
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_overlay_buy_button_falls_back_without_checkout_url() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    labels = {
        "title": "Pro features",
        "subtitle": "Enter key",
        "active_title": "Pro is active",
        "active_license": "License active",
        "active_dev": "Dev Pro active",
        "key_label": "License key",
        "placeholder": "Paste key",
        "activate": "Activate",
        "buy": "Buy",
        "cancel": "Cancel",
        "ok": "OK",
        "invalid": "Invalid",
        "activated": "Activated",
        "buy_unavailable": "No purchase page",
        "deactivate": "Deactivate",
        "deactivated": "Deactivated",
        "deactivate_failed": "Could not deactivate",
    }
    overlay = LicenseOverlay(labels, lambda _key: (False, "Invalid"), parent, buy_callback=lambda: False)
    try:
        overlay.buy_button.click()
        assert overlay.message_label.text() == "No purchase page"
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()
