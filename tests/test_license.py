from __future__ import annotations

import base64
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.install_identity import identity_hash
from app.license import (
    _LS_MAX_RESPONSE_BYTES,
    _clear_license,
    _ls_post,
    _NoRedirects,
    _read_json_response,
    activate_license_key,
    deactivate_license,
    local_verdict,
    normalize_license_key,
    store_receipt,
    validate_license_state,
)
from app.license_receipt import (
    AUDIENCE,
    EXPECTED_VARIANT_ID,
    MAX_LIFETIME,
    RECEIPT_VERSION,
    canonical_bytes,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
INSTALL = identity_hash("a" * 64)
KEY_ID = "k1"


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _Opener:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _signing_keys():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, {KEY_ID: public}


def test_lemon_request_refuses_redirects_and_identifies_the_app() -> None:
    opener = _Opener(_Response(b'{"valid": true}'))
    with patch("app.license.urllib_request.build_opener", return_value=opener) as build:
        result = _ls_post("validate", {"license_key": "secret", "instance_id": "one"})

    assert result == {"valid": True}
    assert build.call_args.args[0] is _NoRedirects
    assert opener.request.get_header("User-agent").startswith("LumaBLE/")
    assert opener.timeout == 10.0


def test_lemon_response_is_bounded() -> None:
    response = _Response(b"x" * (_LS_MAX_RESPONSE_BYTES + 1))
    with pytest.raises(URLError):
        _read_json_response(response)


def test_lemon_server_error_is_not_returned_as_a_licence_answer() -> None:
    failure = HTTPError(
        "https://api.lemonsqueezy.com/v1/licenses/validate",
        503,
        "unavailable",
        {},
        _Response(b'{"valid": false}'),
    )
    opener = _Opener(failure)
    with (
        patch("app.license.urllib_request.build_opener", return_value=opener),
        pytest.raises(URLError),
    ):
        _ls_post("validate", {"license_key": "secret", "instance_id": "one"})


def _receipt(private, **overrides) -> dict:
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "key_id": KEY_ID,
        "audience": AUDIENCE,
        "license_id": "42",
        "instance_id": "inst-uuid-001",
        "variant_id": EXPECTED_VARIANT_ID,
        "installation_hash": INSTALL,
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + MAX_LIFETIME).isoformat(),
    }
    receipt.update(overrides)
    receipt["signature"] = base64.b64encode(private.sign(canonical_bytes(receipt))).decode()
    return receipt

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
        "receipt": None,
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
        "receipt": None,
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
        "receipt": None,
        "grace_days": 7,
    }


def test_normalize_license_key_ignores_case_and_spaces() -> None:
    assert normalize_license_key(" dollza dev pro ") == "DOLLZADEVPRO"


# ---------------------------------------------------------------------------
# the local check: a receipt, and nothing else
# ---------------------------------------------------------------------------
def test_a_fresh_timestamp_without_a_receipt_grants_nothing() -> None:
    """The door the whole redesign exists to close.

    A key, an instance and a date within every window the old rules allowed —
    all of it typed into a file anybody can edit. Under the previous contract
    this was Pro, offline, indefinitely. Now it is a licence with no receipt,
    which is Free until one is fetched and checked.
    """
    settings = {
        "license": {
            "license_key": "ANYTHING",
            "instance_id": "ALSO-ANYTHING",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    }

    verdict = local_verdict(
        settings, installation_hash=INSTALL, public_keys={}, now=datetime.now(UTC)
    )

    assert verdict.ok is False
    assert verdict.reason == "no_receipt"


def test_nothing_at_all_grants_nothing() -> None:
    assert local_verdict(
        {}, installation_hash=INSTALL, public_keys={}, now=datetime.now(UTC)
    ).ok is False


def test_a_signed_receipt_is_what_grants_pro() -> None:
    private, keys = _signing_keys()
    settings = {"license": {"license_key": "K", "instance_id": "I"}}
    store_receipt(settings, _receipt(private))

    verdict = local_verdict(
        settings, installation_hash=INSTALL, public_keys=keys, now=NOW
    )

    assert verdict.ok is True


def test_a_receipt_belonging_to_another_installation_grants_nothing() -> None:
    """The copied settings file. The signature is fine; it is about somebody
    else's machine."""
    private, keys = _signing_keys()
    settings = {"license": {"license_key": "K", "instance_id": "I"}}
    store_receipt(settings, _receipt(private))

    verdict = local_verdict(
        settings, installation_hash=identity_hash("z" * 64), public_keys=keys, now=NOW
    )

    assert verdict.ok is False


def test_a_build_with_no_keys_believes_nothing() -> None:
    """Which is the state until the service is deployed, and deliberately so. A
    build that fell back to something else "just until the keys arrive" would
    make that fallback the real check."""
    private, _keys = _signing_keys()
    settings = {"license": {"license_key": "K", "instance_id": "I"}}
    store_receipt(settings, _receipt(private))

    assert local_verdict(
        settings, installation_hash=INSTALL, public_keys={}, now=NOW
    ).ok is False


def test_an_expired_receipt_asks_for_a_new_one_rather_than_ending_the_licence() -> None:
    private, keys = _signing_keys()
    settings = {"license": {"license_key": "K", "instance_id": "I"}}
    store_receipt(settings, _receipt(private))

    verdict = local_verdict(
        settings,
        installation_hash=INSTALL,
        public_keys=keys,
        now=NOW + MAX_LIFETIME + timedelta(seconds=1),
    )

    assert verdict.ok is False
    assert verdict.is_expired is True
    assert settings["license"]["license_key"] == "K", "an expired receipt cost the licence"


def test_the_receipt_survives_being_validated() -> None:
    """Not tidied, either: what makes it good is a signature over exact bytes,
    and a validator straightening its fields would be changing them."""
    private, _keys = _signing_keys()
    settings = {"license": {"license_key": "K", "instance_id": "I"}}
    store_receipt(settings, _receipt(private))
    original = dict(settings["license"]["receipt"])

    state = validate_license_state(settings["license"])

    assert state["receipt"] == original


def test_clearing_a_licence_takes_the_receipt_with_it() -> None:
    """Otherwise Pro would outlive the answer that ended it, by up to a
    fortnight."""
    private, _keys = _signing_keys()
    settings = {"license": {"license_key": "K", "instance_id": "I"}}
    store_receipt(settings, _receipt(private))

    _clear_license(settings["license"])

    assert settings["license"]["receipt"] is None
    assert settings["license"]["license_key"] == ""


# ---------------------------------------------------------------------------
# activate_license_key
# ---------------------------------------------------------------------------

# The identity every activation in this file happens under. Real activations
# take one from the protected store; here it only has to be a stable string,
# because what is being tested is what gets sent and what gets kept.
INSTALL = "9f2c" * 10 + "abc"

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
        result = activate_license_key("ls-testkey", settings, installation_hash=INSTALL)
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
        result = activate_license_key("ls-testkey", settings, installation_hash=INSTALL)
    assert result is False
    assert settings == {}


def test_activate_license_key_rejected_by_server() -> None:
    settings: dict = {}
    with patch("app.license._ls_post", return_value={"activated": False, "error": "Invalid key"}):
        result = activate_license_key("WRONG-KEY", settings, installation_hash=INSTALL)
    assert result is False
    assert settings == {}


@pytest.mark.parametrize("missing", ["license_key", "instance"])
def test_activate_license_key_requires_ids_from_successful_response(missing: str) -> None:
    settings: dict = {}
    response = dict(_ACTIVATE_SUCCESS)
    response[missing] = {}
    with patch("app.license._ls_post", return_value=response):
        result = activate_license_key("ls-testkey", settings, installation_hash=INSTALL)
    assert result is False
    assert settings == {}


def test_activate_license_key_does_not_change_settings_on_rejection() -> None:
    settings = {"license": {"activated": False, "edition": "free", "kind": ""}}
    with patch("app.license._ls_post", return_value={"activated": False, "error": "Not found"}):
        result = activate_license_key("wrong", settings, installation_hash=INSTALL)
    assert result is False
    assert settings["license"]["edition"] == "free"


def test_activate_license_key_network_error() -> None:
    settings: dict = {}
    with patch("app.license._ls_post", side_effect=URLError("no network")):
        result = activate_license_key("LS-SOME-KEY", settings, installation_hash=INSTALL)
    assert result is False
    assert settings == {}


def test_activate_license_key_empty_key() -> None:
    settings: dict = {}
    assert activate_license_key("", settings, installation_hash=INSTALL) is False
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


def test_deactivate_license_keeps_state_on_ambiguous_json() -> None:
    settings = {
        "license": {
            "license_key": "LS-VALIDKEY",
            "instance_id": "inst-uuid",
            "edition": "pro",
        }
    }

    responses = iter([{"deactivated": False}, {"error": "service unavailable"}])
    with patch("app.license._ls_post", side_effect=lambda *_args: next(responses)):
        result = deactivate_license(settings)

    assert result is False
    assert settings["license"]["license_key"] == "LS-VALIDKEY"
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


def _free_labels() -> dict:
    return {
        "title": "LumaBLE Pro",
        "hero_title": "Unlock every feature",
        "subtitle": "Value first",
        "have_key": "I already have a key",
        "key_label": "License key",
        "placeholder": "Paste key",
        "activate": "Activate",
        "activating": "Checking",
        "buy": "Buy LumaBLE Pro",
        "back": "Back",
        "close": "Close",
        "cancel": "Cancel",
        "ok": "OK",
        "invalid": "Invalid",
        "activated": "Activated",
        "buy_unavailable": "No purchase page",
        "feat_music": "Music & mic",
        "feat_music_desc": "React to audio",
        "feat_screen": "Screen sync",
        "feat_screen_desc": "Mirror the screen",
        "feat_diy": "Custom effects",
        "feat_diy_desc": "Custom colour transitions and code sharing",
        "feat_schedule": "Schedule",
        "feat_schedule_desc": "Automatic power by day",
        "feat_effects": "Every effect and mode",
        "feat_effects_desc": "A full set and custom quick modes",
        "feat_profiles": "Unlimited profiles",
        "feat_profiles_desc": "Import and export configurations",
    }


def test_license_overlay_hides_key_until_requested() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    overlay = LicenseOverlay(_free_labels(), lambda _key: (False, "Invalid"), parent, buy_callback=lambda: False)
    try:
        # isHidden() reflects the explicit setVisible state without needing the
        # top-level shown (isVisible() is always False on an unshown tree).
        # Default free view: value + buy hero, key field hidden.
        assert overlay._field_box.isHidden() is True
        assert overlay._buy_row.isHidden() is False

        overlay._reveal_key()
        assert overlay._key_revealed is True
        assert overlay._field_box.isHidden() is False
        assert overlay._reveal_row.isHidden() is False
        assert overlay._buy_row.isHidden() is True

        overlay._hide_key()
        assert overlay._key_revealed is False
        assert overlay._field_box.isHidden() is True
        assert overlay._buy_row.isHidden() is False
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_overlay_features_grid_reflects_supplied_labels() -> None:
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    overlay = LicenseOverlay(_free_labels(), lambda _key: (False, "Invalid"), parent)
    try:
        names = {
            w.text()
            for w in overlay._panel.findChildren(QLabel)
            if w.objectName() == "licenseFeatureName"
        }
        # Only the two feature keys supplied render; scenes never appear.
        assert "Music & mic" in names
        assert "Screen sync" in names
        assert all("сцен" not in n.lower() and "scene" not in n.lower() for n in names)
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_purchase_view_has_the_premium_hierarchy() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QWidget

    from app.widgets.icon_tile import IconTile
    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(1280, 860)
    parent.show()
    overlay = LicenseOverlay(_free_labels(), lambda _key: (False, "Invalid"), parent)
    try:
        overlay.open()
        app.processEvents()
        assert overlay._title_label.text() == "LumaBLE"
        assert overlay._title_pro_label is not None
        assert overlay._title_pro_label.text() == "Pro"
        assert overlay._hero_title is not None
        assert overlay._hero_title.text() == "Unlock every feature"
        assert overlay.buy_button._role == "premium"
        assert overlay.buy_button._icon_kind == "crown"
        assert (overlay.buy_button.width(), overlay.buy_button.height()) == (400, 52)
        assert overlay._have_key_link.text().endswith("→")
        assert overlay._have_key_link.accessibleName() == "I already have a key"
        feature_icons = overlay._panel.findChildren(IconTile)
        assert feature_icons
        assert all((icon.width(), icon.height()) == (42, 42) for icon in feature_icons)
        descriptions = {
            label.text(): label
            for label in overlay._panel.findChildren(QLabel)
            if label.objectName() == "licenseFeatureDesc"
        }
        left = descriptions["A full set and custom quick modes"]
        right = descriptions["Import and export configurations"]
        assert right.alignment() & Qt.AlignTop
        assert left.mapTo(overlay._panel, left.rect().topLeft()).y() == right.mapTo(
            overlay._panel,
            right.rect().topLeft(),
        ).y()
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_overlay_activate_button_runs_a_checking_indicator() -> None:
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    overlay = LicenseOverlay(_free_labels(), lambda _key: (False, "Invalid"), parent)
    try:
        assert overlay._spinner_timer.isActive() is False
        overlay._set_activating(True)
        assert overlay._spinner_timer.isActive() is True
        assert overlay._activate_button.text().startswith("Checking")
        overlay._tick_spinner()
        assert overlay._activate_button.text().startswith("Checking")
        overlay._set_activating(False)
        assert overlay._spinner_timer.isActive() is False
        assert overlay._activate_button.text() == "Activate"
    finally:
        overlay.close_overlay()
        parent.deleteLater()
        app.processEvents()


def test_license_overlay_refuses_to_close_while_activating() -> None:
    """Closing mid-activation would destroy the running worker QThread. The ×
    button and Esc both route through close_overlay, which must refuse until the
    key check finishes."""
    import threading

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget

    from app.widgets.license_overlay import LicenseOverlay

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    release = threading.Event()

    def blocking_activate(_key: str) -> tuple[bool, str]:
        release.wait(timeout=5)
        return False, "Invalid"

    overlay = LicenseOverlay(_free_labels(), blocking_activate, parent)
    closed: list[int] = []
    overlay.closed.connect(lambda: closed.append(1))
    try:
        overlay._reveal_key()
        overlay.key_input.setText("KEY-123")
        overlay._activate()
        worker = overlay._activate_worker
        assert worker is not None
        assert worker.isRunning() is True

        # Both close paths must be refused while the worker runs.
        overlay.close_overlay()
        overlay.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert closed == []
        assert overlay.isHidden() is False

        # Let the worker finish; closing is allowed only once the OS thread has
        # actually stopped (finished), not merely once `done` was handled.
        release.set()
        for _ in range(250):
            if overlay._activate_worker is None:
                break
            QTest.qWait(20)
        assert overlay._activate_worker is None
        assert worker.isFinished() is True

        overlay.close_overlay()
        assert closed == [1]
    finally:
        release.set()
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


# ---------------------------------------------------------------------------
# the name an activation goes under
# ---------------------------------------------------------------------------
def test_the_instance_name_is_only_the_installation() -> None:
    """The whole of the binding, and it carries nothing else.

    The signing server has no way to know a machine's name and therefore no way
    to rebuild a string containing one — which is why the readable dashboard
    entry was given up. Matching part of a name rather than all of it is the
    looseness this exists to remove.
    """
    from app.license import INSTANCE_NAME_PREFIX, canonical_instance_name

    name = canonical_instance_name(INSTALL)

    assert name == f"{INSTANCE_NAME_PREFIX}{INSTALL}"
    assert INSTALL in name and name.startswith("LumaBLE:")

    import platform

    host = platform.node().strip()
    if host:
        assert host not in name, "the machine's name leaked into the binding"


def test_a_real_length_name_stays_within_what_a_field_should_hold() -> None:
    """The hash is 43 characters, so the whole name is 51. There is no
    documented limit, which is why the live activation has to confirm it — but
    a change that made it much longer should be noticed here first."""
    from app.install_identity import identity_hash
    from app.license import canonical_instance_name

    name = canonical_instance_name(identity_hash("a" * 64))

    assert len(name) == 51


def test_an_installation_with_no_identity_cannot_activate() -> None:
    """An activation whose name the server cannot rebuild is a slot spent on an
    instance no receipt could ever be issued for — a licence gone for nothing.
    """
    from app.license import canonical_instance_name

    assert canonical_instance_name("") == ""
    assert canonical_instance_name(None) == ""

    settings: dict = {}
    calls = []
    with patch("app.license._ls_post", side_effect=lambda *a, **k: calls.append(a) or {}):
        assert activate_license_key("ls-testkey", settings, installation_hash="") is False

    assert calls == [], "an activation was attempted without an identity"
    assert settings == {}


def test_the_activation_sends_exactly_the_canonical_name() -> None:
    """What the server will compare against, byte for byte."""
    from app.license import canonical_instance_name

    sent = {}

    def _capture(endpoint, payload):
        sent.update(payload)
        return _ACTIVATE_SUCCESS

    settings: dict = {}
    with patch("app.license._ls_post", side_effect=_capture):
        assert activate_license_key("ls-testkey", settings, installation_hash=INSTALL) is True

    assert sent["instance_name"] == canonical_instance_name(INSTALL)
