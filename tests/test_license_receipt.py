"""What a signed receipt has to survive before it is believed.

The tests sign with a key pair made here, so nothing depends on the real one,
and every case is written by making a genuine receipt and then spoiling exactly
one thing about it. A test that hand-wrote a "bad" receipt would prove only
that some string is not a signature.

The order of the checks matters as much as the checks. Nothing about a
receipt's *contents* is acted on until its signature holds, because until then
the contents are whatever somebody typed into a file.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest

# No importorskip: the signature library is a hard requirement now. A build
# without it cannot check a licence at all, and a quiet skip here would let
# that ship looking green.
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.license_receipt import (
    AUDIENCE,
    BAD_SIGNATURE,
    BAD_WINDOW,
    CLOCK_SKEW,
    EXPECTED_VARIANT_ID,
    EXPIRED,
    MALFORMED,
    MAX_LIFETIME,
    NOT_YET_VALID,
    OK,
    RECEIPT_VERSION,
    SIGNED_FIELDS,
    UNKNOWN_KEY,
    UNSUPPORTED_VERSION,
    WRONG_AUDIENCE,
    WRONG_INSTALLATION,
    WRONG_VARIANT,
    CanonicalError,
    canonical_bytes,
    verify,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
INSTALL = "9f2c" * 16
KEY_ID = "k1"


def _signer():
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
        "license_id": "lic_1",
        "instance_id": "inst_1",
        "variant_id": EXPECTED_VARIANT_ID,
        "installation_hash": INSTALL,
        "issued_at": (NOW - timedelta(days=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=13)).isoformat(),
    }
    receipt.update(overrides)
    receipt["signature"] = base64.b64encode(private.sign(canonical_bytes(receipt))).decode()
    return receipt


def _judge(receipt, keys, *, installation_hash=INSTALL, now=NOW):
    return verify(receipt, public_keys=keys, installation_hash=installation_hash, now=now)


# ── the ordinary case ─────────────────────────────────────────────────
def test_a_genuine_receipt_is_believed() -> None:
    private, keys = _signer()

    verdict = _judge(_receipt(private), keys)

    assert verdict.ok is True
    assert verdict.reason == OK
    assert verdict.expires_at == NOW + timedelta(days=13)


# ── the signature ─────────────────────────────────────────────────────
TAMPERED = {
    "receipt_version": 7,
    "key_id": "k_other",
    "audience": "other-product",
    "license_id": "lic_other",
    "instance_id": "inst_other",
    "variant_id": "999",
    "installation_hash": "0" * 64,
    "issued_at": (NOW - timedelta(days=2)).isoformat(),
    "expires_at": (NOW + timedelta(days=400)).isoformat(),
}


def test_every_signed_field_really_changes_the_bytes() -> None:
    """The signature covers bytes, so what has to be shown is that each field
    reaches them.

    The earlier version of this test tried to prove it by tampering and
    watching the verdict, and quietly proved nothing for two of the fields: the
    values it substituted for the version and the audience were the values
    already there, so it skipped them and said so in a comment nobody would
    read twice. This asks the question directly.
    """
    private, _ = _signer()
    receipt = _receipt(private)
    original = canonical_bytes(receipt)

    for field in SIGNED_FIELDS:
        altered = dict(receipt)
        altered[field] = TAMPERED[field]
        assert altered[field] != receipt[field], f"the test did not change {field}"
        assert canonical_bytes(altered) != original, f"{field} is not covered by the signature"


def test_changing_any_signed_field_breaks_the_signature() -> None:
    """And the other half: bytes that differ are refused, one field at a time.

    A field that could be edited without breaking the signature is a field that
    is not really signed — and it would be found by whoever edits files, not by
    whoever wrote it.
    """
    private, keys = _signer()
    for field in SIGNED_FIELDS:
        receipt = _receipt(private)
        receipt[field] = TAMPERED[field]
        verdict = _judge(receipt, keys)
        assert verdict.ok is False, f"{field} could be edited freely"
        assert verdict.reason != OK


def test_a_signature_from_another_key_is_refused() -> None:
    """The key id says which key signed it; anyone can write any id. What
    decides is whether the named key actually verifies."""
    private, keys = _signer()
    other, _ = _signer()
    receipt = _receipt(private)
    receipt["signature"] = base64.b64encode(other.sign(canonical_bytes(receipt))).decode()

    assert _judge(receipt, keys).reason == BAD_SIGNATURE


def test_a_key_nobody_ships_is_refused_rather_than_trusted() -> None:
    private, keys = _signer()

    assert _judge(_receipt(private, key_id="k99"), keys).reason == UNKNOWN_KEY


def test_rubbish_where_a_signature_goes_is_not_a_crash() -> None:
    private, keys = _signer()
    for value in ("", "not base64!!", None, 42, "AAAA"):
        receipt = _receipt(private)
        receipt["signature"] = value
        verdict = _judge(receipt, keys)
        assert verdict.ok is False, value


# ── what the receipt is for ───────────────────────────────────────────
def test_a_receipt_for_something_else_is_refused() -> None:
    """A signature from the same key over another product's payload must not
    be usable here."""
    private, keys = _signer()

    assert _judge(_receipt(private, audience="other-product"), keys).reason == WRONG_AUDIENCE


def test_a_shape_this_build_does_not_know_is_refused() -> None:
    """Not guessed at optimistically. An older build meeting a newer receipt
    should ask for one it understands, not interpret the parts it recognises."""
    private, keys = _signer()

    assert _judge(_receipt(private, receipt_version=2), keys).reason == UNSUPPORTED_VERSION


def test_a_receipt_for_another_machine_is_refused() -> None:
    """The binding. Without it one activation would be a signature anybody
    could copy to any number of installations."""
    private, keys = _signer()

    verdict = _judge(_receipt(private), keys, installation_hash="1" * 64)

    assert verdict.reason == WRONG_INSTALLATION


def test_an_installation_that_answers_nothing_matches_nothing() -> None:
    """A missing protected blob must not become a wildcard.

    Two halves, and the second is the one that matters. A receipt carrying a
    real hash is refused simply because it differs. The dangerous shape is a
    receipt whose hash is *also* empty: then "they are equal" would be true,
    and a machine that had lost its identity would accept a receipt issued for
    no machine at all. Only a signer bug could produce such a receipt, which is
    exactly why refusing it belongs here rather than being assumed away.
    """
    private, keys = _signer()

    for empty in ("", "   ", None):
        assert _judge(_receipt(private), keys, installation_hash=empty).reason == (
            WRONG_INSTALLATION
        )

    anonymous = _receipt(private, installation_hash="")
    for empty in ("", "   ", None):
        assert _judge(anonymous, keys, installation_hash=empty).reason == WRONG_INSTALLATION


def test_the_installation_is_compared_in_one_spelling() -> None:
    private, keys = _signer()
    receipt = _receipt(private, installation_hash=INSTALL.upper())

    assert _judge(receipt, keys, installation_hash=INSTALL.lower()).ok is True


# ── time ──────────────────────────────────────────────────────────────
def test_an_expired_receipt_asks_to_be_refreshed_rather_than_complained_about() -> None:
    """The reason is the useful part: this one calls for a quiet refresh, not
    for telling somebody their licence is wrong."""
    private, keys = _signer()
    receipt = _receipt(private, expires_at=(NOW - timedelta(seconds=1)).isoformat())

    verdict = _judge(receipt, keys)

    assert verdict.ok is False
    assert verdict.reason == EXPIRED
    assert verdict.is_expired is True


def test_the_last_second_is_still_inside() -> None:
    private, keys = _signer()
    receipt = _receipt(private, expires_at=(NOW + timedelta(seconds=1)).isoformat())

    assert _judge(receipt, keys).ok is True


def test_a_receipt_from_the_future_is_refused_beyond_a_little_disagreement() -> None:
    """Machines disagree about the time by minutes, not by days."""
    private, keys = _signer()
    slightly = _receipt(private, issued_at=(NOW + CLOCK_SKEW - timedelta(seconds=30)).isoformat())
    wildly = _receipt(private, issued_at=(NOW + timedelta(days=2)).isoformat())

    assert _judge(slightly, keys).ok is True
    assert _judge(wildly, keys).reason == NOT_YET_VALID


def test_a_time_without_a_zone_is_read_as_utc() -> None:
    """The signer works in UTC. Reading a bare timestamp as local time would
    move every deadline by hours depending on where somebody is sitting."""
    private, keys = _signer()
    naive = (NOW + timedelta(days=13)).replace(tzinfo=None).isoformat()

    assert _judge(_receipt(private, expires_at=naive), keys).ok is True


def test_a_time_that_is_not_a_time_is_malformed() -> None:
    private, keys = _signer()

    assert _judge(_receipt(private, expires_at="soon"), keys).reason == MALFORMED
    assert _judge(_receipt(private, issued_at=""), keys).reason == MALFORMED


# ── the bytes the signature covers ────────────────────────────────────
def test_the_layout_is_fixed_and_does_not_follow_the_dictionary() -> None:
    """Two sides that disagree about field order disagree about every
    signature, and the signer here is written in another language."""
    private, _ = _signer()
    receipt = _receipt(private)
    shuffled = {field: receipt[field] for field in reversed(list(receipt))}

    assert canonical_bytes(receipt) == canonical_bytes(shuffled)
    assert canonical_bytes(receipt).decode().splitlines()[0].startswith("receipt_version=")


def test_a_value_that_could_forge_a_field_boundary_is_refused() -> None:
    """The separator is what tells one field from the next. A value allowed to
    contain it could spell out a second field inside itself, and two different
    receipts would sign the same bytes."""
    private, _ = _signer()
    receipt = _receipt(private)
    receipt["license_id"] = "lic_1\nvariant_id=999"

    with pytest.raises(CanonicalError):
        canonical_bytes(receipt)


def test_a_receipt_missing_a_field_is_not_signed_around_it() -> None:
    private, keys = _signer()
    receipt = _receipt(private)
    del receipt["variant_id"]

    with pytest.raises(CanonicalError):
        canonical_bytes(receipt)
    assert _judge(receipt, keys).reason == MALFORMED


def test_anything_that_is_not_a_receipt_is_refused_quietly() -> None:
    _, keys = _signer()

    for value in (None, "receipt", 7, []):
        assert _judge(value, keys).reason == MALFORMED


# ── what the receipt claims ───────────────────────────────────────────
def test_a_receipt_for_another_product_is_refused_here_too() -> None:
    """Checked on the client as well as on the server that signs it. A good
    signature over somebody's licence for a different product is still not a
    licence for this one."""
    private, keys = _signer()

    assert _judge(_receipt(private, variant_id="999"), keys).reason == WRONG_VARIANT
    assert _judge(_receipt(private, variant_id=""), keys).reason == WRONG_VARIANT


def test_a_window_longer_than_the_server_issues_is_refused() -> None:
    """A signed receipt good for a year would mean the signer had been changed
    or misconfigured. Honouring it turns one mistake into a permanent one."""
    private, keys = _signer()
    issued = (NOW - timedelta(hours=1)).isoformat()
    too_long = _receipt(
        private,
        issued_at=issued,
        expires_at=(NOW - timedelta(hours=1) + MAX_LIFETIME + timedelta(minutes=1)).isoformat(),
    )
    exactly = _receipt(
        private,
        issued_at=issued,
        expires_at=(NOW - timedelta(hours=1) + MAX_LIFETIME).isoformat(),
    )

    assert _judge(too_long, keys).reason == BAD_WINDOW
    assert _judge(exactly, keys).ok is True


def test_a_window_that_runs_backwards_is_refused() -> None:
    private, keys = _signer()
    backwards = _receipt(
        private,
        issued_at=NOW.isoformat(),
        expires_at=(NOW - timedelta(days=1)).isoformat(),
    )
    instant = _receipt(private, issued_at=NOW.isoformat(), expires_at=NOW.isoformat())

    assert _judge(backwards, keys).reason == BAD_WINDOW
    assert _judge(instant, keys).reason == BAD_WINDOW
