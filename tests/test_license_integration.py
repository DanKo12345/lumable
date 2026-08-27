"""Turning a licence into Pro, and what each answer is allowed to change.

Three rules carry this file. A receipt is stored only once it has been checked
here. Exactly two answers may end a licence, and both come from the service
having reached Lemon Squeezy. And the time is not allowed to run backwards,
because an expired receipt would otherwise be revived by winding a clock.

Everything is driven through real signed receipts and the real verifier: what
is stood in for is the network, never the checking.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import feature_gate
from app.install_identity import Identity, identity_hash
from app.license_client import (
    INVALID,
    ISSUED,
    RATE_LIMITED,
    REVOKED,
    UNAVAILABLE,
    IssueResult,
    is_refresh_due,
    refresh_delay_seconds,
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


def _signing_keys():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private, {KEY_ID: public}


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


def _licence(**extra) -> dict:
    licence = {"license_key": "LS-KEY", "instance_id": "inst-uuid-001"}
    licence.update(extra)
    return {"license": licence}


def _answering(monkeypatch, result: IssueResult, saved: list | None = None):
    # `saved if saved is not None` and not `saved or []`: an empty list is
    # falsy, so the second spelling quietly appends to a fresh list nobody can
    # see, and every assertion about what was written passes by never seeing
    # anything.
    written = saved if saved is not None else []
    monkeypatch.setattr(feature_gate, "request_receipt", lambda **_kwargs: result)
    monkeypatch.setattr(feature_gate, "save_settings", written.append)
    monkeypatch.setattr(feature_gate, "public_keys", dict)


IDENTITY = Identity(installation_id="a" * 64)


# ── what may be stored ────────────────────────────────────────────────
def test_a_verified_receipt_is_stored_and_turns_pro_on(monkeypatch) -> None:
    private, _keys = _signing_keys()
    receipt = _receipt(private)
    settings = _licence()
    saved: list = []
    _answering(monkeypatch, IssueResult(ISSUED, receipt), saved)

    outcome = feature_gate.obtain_receipt(settings, IDENTITY, now=NOW)

    assert outcome == ISSUED
    assert settings["license"]["receipt"] == receipt
    assert settings["license"]["edition"] == "pro"
    assert saved == [settings], "a receipt was accepted and never written down"


def test_nothing_is_stored_when_the_answer_was_not_a_receipt(monkeypatch) -> None:
    """The client already refuses a 200 that does not verify. This is the other
    end of that: the gate stores what the client vouched for, and nothing it
    merely received."""
    settings = _licence()
    saved: list = []
    _answering(monkeypatch, IssueResult(UNAVAILABLE), saved)

    outcome = feature_gate.obtain_receipt(settings, IDENTITY, now=NOW)

    assert outcome == UNAVAILABLE
    assert "receipt" not in settings["license"]
    assert saved == []


def test_a_receipt_arriving_beside_a_refusal_is_not_stored(monkeypatch) -> None:
    """What decides is the verdict, not whether something receipt-shaped came
    with it.

    The client does not answer this way today, and that is exactly why the rule
    is written here rather than assumed: this function is handed whatever the
    client returns, and "it never sends one" is a property of another module
    that somebody could change without ever looking at this one.
    """
    private, _keys = _signing_keys()
    settings = _licence()
    saved: list = []
    _answering(monkeypatch, IssueResult(UNAVAILABLE, _receipt(private)), saved)

    outcome = feature_gate.obtain_receipt(settings, IDENTITY, now=NOW)

    assert outcome == UNAVAILABLE
    assert "receipt" not in settings["license"], "a refusal was stored as a receipt"
    assert saved == []


# ── what may be taken away ────────────────────────────────────────────
@pytest.mark.parametrize("outcome", [INVALID, REVOKED])
def test_the_two_verdicts_end_the_licence(monkeypatch, outcome: str) -> None:
    private, _keys = _signing_keys()
    settings = _licence(receipt=_receipt(private))
    saved: list = []
    _answering(monkeypatch, IssueResult(outcome), saved)

    feature_gate.obtain_receipt(settings, IDENTITY, now=NOW)

    assert settings["license"]["license_key"] == ""
    assert settings["license"]["receipt"] is None
    assert saved == [settings], "a licence was ended in memory only"


@pytest.mark.parametrize("outcome", [UNAVAILABLE, RATE_LIMITED, "instance_mismatch", "malformed_response"])
def test_every_other_answer_leaves_the_licence_exactly_as_it_was(
    monkeypatch, outcome: str
) -> None:
    """A service that cannot answer must never be able to cancel a licence.

    This is the rule the whole design rests on, and the one that would be
    easiest to lose by widening a condition.
    """
    private, _keys = _signing_keys()
    receipt = _receipt(private)
    settings = _licence(receipt=receipt)
    before = dict(settings["license"])
    saved: list = []
    _answering(monkeypatch, IssueResult(outcome), saved)

    feature_gate.obtain_receipt(settings, IDENTITY, now=NOW)

    assert settings["license"] == before
    assert saved == []


def test_a_licence_with_nothing_to_ask_about_asks_nothing(monkeypatch) -> None:
    asked: list = []
    monkeypatch.setattr(
        feature_gate,
        "request_receipt",
        lambda **kwargs: asked.append(kwargs) or IssueResult(UNAVAILABLE),
    )

    assert feature_gate.obtain_receipt({}, IDENTITY, now=NOW) == "no_licence"
    assert feature_gate.obtain_receipt(_licence(instance_id=""), IDENTITY, now=NOW) == "no_licence"
    assert asked == []


# ── the clock ─────────────────────────────────────────────────────────
def test_a_clock_behind_the_mark_refuses_pro_rather_than_becoming_it() -> None:
    """The mark is not used as the time, and the difference is the whole point.

    Substituting it freezes the clock at whatever moment it recorded, so a
    receipt that should have expired never does: leave the date in the past and
    Pro lasts forever. That is the opposite of what the mark is for, and it is
    what the first version of this did — with a test asserting it.
    """
    marked = Identity(installation_id="a" * 64, highest_seen=NOW)

    assert feature_gate.clock_went_back(marked, NOW - timedelta(days=30)) is True
    assert feature_gate.clock_went_back(marked, NOW) is False
    assert feature_gate.clock_went_back(marked, NOW + timedelta(days=1)) is False
    assert feature_gate.clock_went_back(Identity(installation_id="a" * 64), NOW) is False


def test_a_receipt_that_should_have_expired_does_not_survive_a_wound_back_clock(
    monkeypatch, tmp_path
) -> None:
    """The scenario the whole guard exists for.

    A receipt, a mark recorded while it was still good, and then a machine left
    permanently in the past. Under the substitution this was Pro forever; the
    receipt's fortnight simply never arrived.
    """
    from app import install_identity, storage

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    private, keys = _signing_keys()
    settings = _licence(receipt=_receipt(private))
    # Inside the receipt's fortnight on purpose. A mark past the expiry would
    # be refused by either design — the substitution would simply hand over an
    # expired moment — and the test would prove nothing about which one is in
    # place. Here the substitution yields a moment the receipt is still good
    # at, so it keeps Pro alive forever while the clock stays put.
    marked = Identity(installation_id="a" * 64, highest_seen=NOW + timedelta(days=1))

    monkeypatch.setattr(feature_gate, "load_settings", lambda: settings)
    monkeypatch.setattr(feature_gate, "public_keys", lambda: keys)
    monkeypatch.setattr(
        feature_gate,
        "load_identity",
        lambda **_kw: install_identity.Outcome(install_identity.LOADED, marked),
    )
    feature_gate.invalidate_pro_cache()

    # And the machine is left a month in the past, which is where somebody
    # winding a clock back leaves it.
    monkeypatch.setattr(feature_gate, "datetime", _FrozenClock(NOW - timedelta(days=30)))

    assert feature_gate.is_pro() is False, "a wound-back clock kept an expired receipt alive"
    assert settings["license"]["license_key"] == "LS-KEY", "a wrong date cost the licence"
    assert settings["license"]["receipt"] is not None

    # And the way back is the clock, not the network: nothing was thrown away,
    # so putting the date right is enough on its own.
    monkeypatch.setattr(feature_gate, "datetime", _FrozenClock(NOW + timedelta(days=2)))
    feature_gate.invalidate_pro_cache()
    assert feature_gate.is_pro() is True, "a corrected clock did not give Pro back"


def test_a_clock_that_is_merely_a_little_out_is_believed() -> None:
    """Machines correct themselves by seconds. Treating that as tampering would
    switch Pro off for everybody whose clock syncs while the app is open."""
    marked = Identity(installation_id="a" * 64, highest_seen=NOW)

    assert feature_gate.clock_went_back(marked, NOW - timedelta(seconds=30)) is False
    assert feature_gate.clock_went_back(marked, NOW - timedelta(hours=1)) is True


class _FrozenClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self, _tz=None) -> datetime:
        return self._when


# ── when to ask again ─────────────────────────────────────────────────
def test_the_next_check_is_counted_from_the_signature_not_the_launch() -> None:
    """Anchoring it to a launch would let anybody put the next check off
    forever by restarting often enough, which is a way of never being told a
    licence was revoked."""
    private, _keys = _signing_keys()
    receipt = _receipt(private)
    offset = timedelta(seconds=refresh_delay_seconds(INSTALL))

    just_before = NOW + timedelta(days=1) + offset - timedelta(seconds=1)
    just_after = NOW + timedelta(days=1) + offset

    assert is_refresh_due(receipt, installation_hash=INSTALL, now=just_before) is False
    assert is_refresh_due(receipt, installation_hash=INSTALL, now=just_after) is True


def test_a_receipt_that_cannot_be_read_is_due_immediately() -> None:
    """Something is wrong with it, and asking is how that gets repaired."""
    assert is_refresh_due(None, installation_hash=INSTALL, now=NOW) is True
    assert is_refresh_due({}, installation_hash=INSTALL, now=NOW) is True
    assert is_refresh_due(
        {"issued_at": "whenever"}, installation_hash=INSTALL, now=NOW
    ) is True


def test_an_issue_time_without_a_zone_is_read_as_utc() -> None:
    naive = {"issued_at": NOW.replace(tzinfo=None).isoformat()}

    assert is_refresh_due(naive, installation_hash=INSTALL, now=NOW) is False
