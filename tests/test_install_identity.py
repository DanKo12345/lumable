"""The identity a receipt is bound to, and what happens when it goes.

Everything here turns on one distinction. A file that is not there on a fresh
installation is a new identity. The same file not there beside a licence that
worked yesterday is a *loss*, and the difference matters because replacing an
identity costs an activation slot — so it is a question to put to somebody,
never a decision to take quietly.

The three failures at the end are the ones that would be easy to get wrong in
the direction that destroys data: encrypting refuses, decrypting refuses, or
the write does not land. None of them may take the previous good blob with
them, and none may hand back a new identity as though nothing had happened.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app import install_identity, storage
from app.install_identity import (
    IDENTITY_LOST,
    LOADED,
    NEW,
    Identity,
    advance_high_water,
    decode,
    encode,
    identity_hash,
    identity_path,
    load_identity,
    new_installation_id,
    save_identity,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _own_directory(tmp_path, monkeypatch):
    """Every test writes into its own directory, and none into the real one."""
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    return tmp_path


def _stored_identity() -> Identity:
    identity = load_identity(has_licence=False).identity
    assert save_identity(identity) is True
    return identity


# ── what an identity is ───────────────────────────────────────────────
def test_an_identity_says_nothing_about_the_machine() -> None:
    """Not the host name, not a serial. Those are stable across reinstalls,
    which sounds useful until it means a licence that follows somebody's
    hardware around — and they are somebody's data, which this does not need.
    """
    first = new_installation_id()
    second = new_installation_id()

    assert first != second
    assert len(first) == 64, "32 random bytes, as hex"
    assert int(first, 16) >= 0, "hex, so it can go in a file and a hash"


def test_the_hash_is_short_stable_and_unpadded() -> None:
    """It goes into the licence instance name, which has to be compared whole
    and has no documented length to spend freely."""
    identity = Identity(installation_id="a" * 64)

    assert identity.installation_hash == identity_hash("a" * 64)
    assert len(identity.installation_hash) == 43
    assert "=" not in identity.installation_hash
    assert identity_hash("") == "" and identity_hash(None) == ""


# ── the ordinary life of the file ─────────────────────────────────────
def test_a_fresh_installation_gets_an_identity() -> None:
    outcome = load_identity(has_licence=False)

    assert outcome.state == NEW
    assert outcome.is_lost is False
    assert len(outcome.identity.installation_id) == 64


def test_an_identity_survives_being_written_and_read_back() -> None:
    """Through real DPAPI, because the point of the whole file is that the
    bytes on disk are not the identity."""
    identity = _stored_identity()

    assert identity_path().read_bytes() != encode(identity), "it was stored in the clear"

    outcome = load_identity(has_licence=True)

    assert outcome.state == LOADED
    assert outcome.identity.installation_id == identity.installation_id


def test_the_directory_is_read_at_the_moment_it_is_used(tmp_path, monkeypatch) -> None:
    """A path worked out once at import is the path of whatever directory
    happened to be current when this module was first imported — which in a
    test, or in a child process, is not the one arranged for it."""
    first = identity_path()
    elsewhere = tmp_path / "somewhere-else"
    monkeypatch.setattr(storage, "DATA_DIR", elsewhere)

    assert identity_path() != first
    assert identity_path().parent == elsewhere


# ── losing it ─────────────────────────────────────────────────────────
def test_a_missing_file_beside_a_licence_is_a_loss_not_a_fresh_start() -> None:
    """Replacing an identity costs an activation slot. Spending one without
    asking is the surprise this exists to avoid."""
    outcome = load_identity(has_licence=True)

    assert outcome.state == IDENTITY_LOST
    assert outcome.is_lost is True
    assert outcome.identity is None, "a replacement was invented"


def test_an_unreadable_file_beside_a_licence_is_a_loss_too() -> None:
    _stored_identity()
    identity_path().write_bytes(b"not a dpapi blob")

    outcome = load_identity(has_licence=True)

    assert outcome.state == IDENTITY_LOST


def test_an_unreadable_file_is_left_exactly_where_it_is() -> None:
    """It may still be readable by whoever it belongs to. Overwriting it would
    destroy the only copy of an identity this machine cannot read but another
    account can."""
    _stored_identity()
    rubbish = b"not a dpapi blob"
    identity_path().write_bytes(rubbish)

    load_identity(has_licence=True)
    load_identity(has_licence=False)

    assert identity_path().read_bytes() == rubbish


def test_without_a_licence_an_unreadable_file_simply_starts_again() -> None:
    """Nothing is at stake: there is no activation to lose."""
    _stored_identity()
    identity_path().write_bytes(b"not a dpapi blob")

    outcome = load_identity(has_licence=False)

    assert outcome.state == NEW
    assert outcome.identity is not None


def test_a_shape_this_build_does_not_know_is_refused_rather_than_half_read() -> None:
    """An identifier taken out of a shape whose meaning has changed is a
    plausible wrong answer, which is worse here than no answer."""
    import json

    payload = json.dumps({"format_version": 99, "installation_id": "a" * 64}).encode()

    assert decode(payload) is None
    assert decode(b"{}") is None
    assert decode(b"not json") is None
    assert decode(json.dumps({"format_version": 1, "installation_id": ""}).encode()) is None


def test_a_file_that_cannot_be_read_is_never_a_fresh_start(monkeypatch) -> None:
    """A refused permission and a failing disk are not "no file".

    Collapsing them into absence is how a temporary problem becomes a spent
    activation slot: the file is very likely still there, and readable again
    tomorrow. Only a genuine FileNotFoundError may lead to a new identity, and
    that holds whether or not there is a licence — because with the directory
    unreadable, "fresh installation" is not something anybody can know.
    """
    _stored_identity()

    for failure in (PermissionError("denied"), OSError("the disk is unwell")):
        with monkeypatch.context() as refusing:
            refusing.setattr(
                install_identity.Path,
                "read_bytes",
                lambda _self, _exc=failure: (_ for _ in ()).throw(_exc),
            )

            for has_licence in (True, False):
                outcome = load_identity(has_licence=has_licence)
                assert outcome.state == IDENTITY_LOST, failure
                assert outcome.identity is None, "a replacement was invented"


def test_the_prompt_is_forbidden_so_a_background_run_cannot_hang(monkeypatch) -> None:
    """This application runs schedules with nobody watching. A DPAPI window
    raised there waits for a click that is never coming, which is a hang rather
    than a refusal — and a refusal is something this module can report.

    What is checked is that the flag reaches the call, not merely that the
    constant has the right value. The last hop into Win32 itself is not
    intercepted: this catches a call site that stopped passing it, not a change
    made inside the wrapper.
    """
    seen = []

    with monkeypatch.context() as watching:
        watching.setattr(
            install_identity,
            "_dpapi_call",
            lambda name, payload, flags: seen.append((name, flags)) or b"",
        )
        install_identity.protect(b"payload")
        install_identity.unprotect(b"payload")

    assert seen == [
        ("CryptProtectData", 0x1),
        ("CryptUnprotectData", 0x1),
    ], "the flag never reached the call"

    # And the real thing still works with it set, which is the other half: a
    # flag that forbade everything would also pass the check above.
    blob = install_identity.protect(b"payload")
    assert blob is not None
    assert install_identity.unprotect(blob) == b"payload"


# ── the three failures ────────────────────────────────────────────────
def test_a_refusal_to_encrypt_leaves_the_previous_identity_alone(monkeypatch) -> None:
    """The first of the three. Encrypting happens before the file is touched,
    so a refusal ends the attempt with the old blob still in place."""
    identity = _stored_identity()
    before = identity_path().read_bytes()
    # A nested context, not undo(): undo() rolls back *every* patch, including
    # the one pointing the data directory at this test's own folder — and the
    # next line would then read the real one.
    with monkeypatch.context() as refusing:
        refusing.setattr(install_identity, "protect", lambda _payload: None)

        assert save_identity(Identity(installation_id="b" * 64)) is False
        assert identity_path().read_bytes() == before

    assert load_identity(has_licence=True).identity.installation_id == identity.installation_id


def test_a_refusal_to_decrypt_is_a_loss_and_not_a_deletion(monkeypatch) -> None:
    """The second. This is what a blob belonging to another account looks like,
    and the file is that account's to keep."""
    _stored_identity()
    before = identity_path().read_bytes()
    monkeypatch.setattr(install_identity, "unprotect", lambda _payload: None)

    outcome = load_identity(has_licence=True)

    assert outcome.state == IDENTITY_LOST
    assert identity_path().read_bytes() == before


def test_a_write_that_does_not_land_changes_nothing(monkeypatch) -> None:
    """The third. A half-written identity is a machine that cannot prove who it
    is, and repairing that costs an activation."""
    identity = _stored_identity()
    before = identity_path().read_bytes()

    def _refuse(_source, _destination):
        raise OSError("the disk said no")

    with monkeypatch.context() as refusing:
        refusing.setattr(install_identity.os, "replace", _refuse)

        assert save_identity(Identity(installation_id="c" * 64)) is False
        assert identity_path().read_bytes() == before

    assert load_identity(has_licence=True).identity.installation_id == identity.installation_id


def test_a_failed_write_leaves_no_half_file_behind(monkeypatch) -> None:
    """The temporary is the whole point of writing this way; leaving it lying
    around turns one failure into a directory nobody can explain."""
    _stored_identity()

    def _refuse(_source, _destination):
        raise OSError("the disk said no")

    monkeypatch.setattr(install_identity.os, "replace", _refuse)
    save_identity(Identity(installation_id="d" * 64))

    leftovers = [name for name in os.listdir(identity_path().parent) if name.endswith(".tmp")]
    assert leftovers == []


# ── the clock mark ────────────────────────────────────────────────────
def test_the_latest_seen_time_only_moves_forward() -> None:
    """Best effort against a clock wound backwards. Restoring an older copy of
    the file restores an older mark with it, which is why it is called that."""
    identity = Identity(installation_id="a" * 64)

    advanced = advance_high_water(identity, NOW)
    later = advance_high_water(advanced, NOW + timedelta(hours=1))
    backwards = advance_high_water(later, NOW - timedelta(days=30))

    assert advanced.highest_seen == NOW
    assert later.highest_seen == NOW + timedelta(hours=1)
    assert backwards.highest_seen == NOW + timedelta(hours=1)


def test_the_mark_survives_a_round_trip() -> None:
    identity = advance_high_water(Identity(installation_id="a" * 64), NOW)

    assert decode(encode(identity)).highest_seen == NOW


def test_a_mark_written_without_a_zone_is_read_as_utc() -> None:
    import json

    payload = json.dumps(
        {
            "format_version": 1,
            "installation_id": "a" * 64,
            "highest_seen": NOW.replace(tzinfo=None).isoformat(),
        }
    ).encode()

    assert decode(payload).highest_seen == NOW
