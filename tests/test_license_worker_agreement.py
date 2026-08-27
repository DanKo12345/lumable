"""The two halves have to agree, and nothing makes them.

`worker/src/worker.js` and `app/license_receipt.py` are written in different
languages, live in different places and are deployed at different times. Every
constant they share is a chance for one to be changed and the other forgotten —
and the failure would be silent in the worst way: receipts that verify nowhere,
or a binding that no longer binds.

So the constants are read out of the JavaScript and compared. Not by running it
— there is no runtime here — but the values are what drift, not the syntax.

The key round-trip at the bottom is the other half of the same worry: a public
key pasted into a build has to be the public half of the key the service signs
with, and a typo in either produces a build that refuses every real receipt.
"""

from __future__ import annotations

import base64
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import license_keys, license_receipt

WORKER = Path(__file__).resolve().parent.parent / "worker" / "src" / "worker.js"


def _source() -> str:
    if not WORKER.exists():  # pragma: no cover - the file is committed
        pytest.skip("the worker source is not here")
    return WORKER.read_text(encoding="utf-8")


def _const(name: str) -> str:
    match = re.search(rf"^const {name} = (.+);$", _source(), re.MULTILINE)
    assert match, f"{name} is not declared in worker.js the way this test reads it"
    return match.group(1).strip()


def _string(name: str) -> str:
    raw = _const(name)
    assert raw.startswith('"') and raw.endswith('"'), f"{name} is not a plain string"
    return raw[1:-1]


# ── the constants both sides use ──────────────────────────────────────
def test_the_receipt_version_matches() -> None:
    assert _const("RECEIPT_VERSION") == str(license_receipt.RECEIPT_VERSION)


def test_the_audience_matches() -> None:
    """A signature from this key over another product payload must not be
    accepted here, which only works while both sides spell the audience the
    same way."""
    assert _string("AUDIENCE") == license_receipt.AUDIENCE


def test_the_variant_matches() -> None:
    assert _string("EXPECTED_VARIANT_ID") == license_receipt.EXPECTED_VARIANT_ID


def test_the_instance_name_prefix_matches() -> None:
    """The binding. If the service builds a name the application would not
    build, a correct activation is refused; if the application builds one the
    service would not, every activation is."""
    from app.license import INSTANCE_NAME_PREFIX

    assert _string("INSTANCE_NAME_PREFIX") == INSTANCE_NAME_PREFIX


def test_the_signed_fields_match_in_order() -> None:
    """Order and all. The signature covers bytes, and two sides that disagree
    about field order disagree about every signature ever made."""
    match = re.search(r"const SIGNED_FIELDS = \[(.*?)\];", _source(), re.DOTALL)
    assert match
    fields = tuple(re.findall(r'"([^"]+)"', match.group(1)))

    assert fields == license_receipt.SIGNED_FIELDS


def test_the_key_id_the_service_signs_with_is_one_this_build_knows() -> None:
    """Otherwise every receipt is refused on arrival: an unknown key_id is not
    trusted, which is right, and would make the service useless, which is not."""
    assert _string("KEY_ID") in license_keys.public_keys()


def test_the_receipt_lifetime_is_not_longer_than_the_application_accepts() -> None:
    """A service issuing more than the client will take signs receipts that are
    dead on arrival."""
    raw = _const("LIFETIME_MS")
    # A product of integers, which is how it is written and all it may be.
    parts = [int(piece.strip()) for piece in raw.split("*")]
    milliseconds = 1
    for part in parts:
        milliseconds *= part
    lifetime = timedelta(milliseconds=milliseconds)

    assert lifetime <= license_receipt.MAX_LIFETIME


def test_the_body_limit_is_not_smaller_than_a_request_the_client_sends() -> None:
    """A limit below a real request would refuse everybody with 413."""
    from app.license_client import MAX_RESPONSE_BYTES

    limit = int(_const("MAX_BODY_BYTES"))

    assert limit >= 1024
    assert limit <= MAX_RESPONSE_BYTES


def test_the_hash_shape_is_the_one_the_application_produces() -> None:
    """43 characters of base64url, which is what SHA-256 comes to unpadded. A
    looser pattern here would be a looser binding, since the hash is what the
    instance name is built from."""
    pattern = _const("INSTALLATION_HASH")
    assert pattern == "/^[A-Za-z0-9_-]{43}$/"

    digest = base64.urlsafe_b64encode(b"\x00" * 32).rstrip(b"=").decode("ascii")
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", digest)


def test_the_service_never_answers_invalid_when_it_is_merely_confused() -> None:
    """The one answer that ends a licence, and it may only follow Lemon Squeezy
    saying so. Everything else in there must reach for something the client
    treats as an outage."""
    source = _source()
    invalid = re.findall(r'fail\(403, ([^)]+)\)', source)

    assert invalid, "the refusal path has been renamed and this test has stopped reading it"
    for expression in invalid:
        assert 'status === "disabled" ? "revoked" : "invalid"' in expression or (
            '"invalid"' not in expression
        ), f"403 invalid is reachable from {expression}"


def test_nothing_is_logged() -> None:
    """A licence key, a request body or a full response in a log is the one way
    this service could leak what it is trusted with. It has no reason to write
    anything at all, so the absence is the check."""
    source = _source()

    assert "console." not in source


# ── the key that was generated ────────────────────────────────────────
def _private_key_path() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "LumaBLE-signing-key" / "k1-private-pkcs8.b64"


def test_the_shipped_public_key_verifies_what_the_private_key_signs() -> None:
    """The round trip, on the real pair.

    A public key pasted in by hand is a place for a typo that no other test
    would catch: everything would look right and every receipt from the live
    service would be refused. Skipped where the private half is not kept, which
    is everywhere except the machine that made it.
    """
    path = _private_key_path()
    if not path.exists():
        pytest.skip("the private key is not on this machine, which is the normal case")

    from cryptography.hazmat.primitives.serialization import load_der_private_key

    private = load_der_private_key(base64.b64decode(path.read_text(encoding="ascii")), password=None)

    now = datetime.now(UTC)
    receipt = {
        "receipt_version": license_receipt.RECEIPT_VERSION,
        "key_id": "k1",
        "audience": license_receipt.AUDIENCE,
        "license_id": "42",
        "instance_id": "inst-1",
        "variant_id": license_receipt.EXPECTED_VARIANT_ID,
        "installation_hash": "6gMgc3K5w-RS6E8LZVKT6_HcWsMEA7UepSyCrmhaT4k",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(days=14)).isoformat(),
    }
    signed = "\n".join(f"{f}={receipt[f]}" for f in license_receipt.SIGNED_FIELDS)
    receipt["signature"] = base64.b64encode(private.sign(signed.encode("utf-8"))).decode("ascii")

    verdict = license_receipt.verify(
        receipt,
        public_keys=license_keys.public_keys(),
        installation_hash=receipt["installation_hash"],
        now=now,
    )

    assert verdict.ok, verdict.reason


def test_the_private_key_is_not_in_the_repository() -> None:
    """It has one home, outside the working tree, because a private key inside
    one is a single `git add -A` away from being public.

    Asked of what git tracks rather than what is on disk. Tracked is what would
    be published, and the tree also holds node_modules, whose binaries contain
    the words this looks for without containing a key.
    """
    import subprocess

    root = Path(__file__).resolve().parent.parent
    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(root),
        capture_output=True,
        timeout=60,
    )
    if listed.returncode != 0:  # pragma: no cover - not a checkout
        pytest.skip("not a git checkout")
    tracked = [root / name for name in listed.stdout.decode("utf-8").split(chr(0)) if name]
    assert len(tracked) > 100, "git listed almost nothing and this test would prove nothing"

    # Spelled in pieces so this file does not find itself, which it did.
    header = "PRIVATE" + " KEY"

    secret = None
    path = _private_key_path()
    if path.exists():
        secret = path.read_text(encoding="ascii").strip()

    for entry in tracked:
        assert entry.suffix != ".b64", f"a key file is tracked: {entry}"
        if not entry.is_file():
            continue
        text = entry.read_text(encoding="utf-8", errors="ignore")
        assert header not in text, f"a private key is written into {entry}"
        if secret:
            # The exact bytes of the real one, in case it were ever pasted in
            # without the header that would have given it away.
            assert secret not in text, f"the signing key is inside {entry}"


def test_a_key_file_could_not_be_committed_by_accident() -> None:
    """The belt to the previous braces. Everything generate_key.py writes is
    ignored by name, so `git add -A` in a hurry cannot pick one up."""
    root = Path(__file__).resolve().parent.parent
    ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "*.b64" in [line.strip() for line in ignored]
