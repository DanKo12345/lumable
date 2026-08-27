"""The contract in docs/license-worker.md, made executable.

The signing service is a few dozen lines of JavaScript that nobody here runs.
What can be checked is the agreement between the two halves: a receipt built
exactly the way that page describes has to be one this application accepts, and
the binding the page rests on has to be a rule the stand-in actually applies.

So the stand-in below is not a mock that returns whatever the test wants. It
does what the Worker is specified to do — validates, checks the variant,
rebuilds the expected instance name from the hash it was given, refuses if it
does not match, and only then signs. Writing it that way is the point: a rule
this stand-in leaves out is a rule the real one can leave out too, and the
tests would still pass.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.install_identity import identity_hash
from app.license import canonical_instance_name
from app.license_receipt import (
    AUDIENCE,
    EXPECTED_VARIANT_ID,
    MAX_LIFETIME,
    OK,
    RECEIPT_VERSION,
    WRONG_INSTALLATION,
    canonical_bytes,
    verify,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
KEY_ID = "k1"
INSTALLATION = identity_hash("a" * 64)
OTHER_INSTALLATION = identity_hash("b" * 64)


class _Unavailable(Exception):
    """Lemon Squeezy could not be reached."""


class _RateLimited(Exception):
    """Lemon Squeezy refused for asking too often."""


class _Lemon:
    """Lemon Squeezy, as far as the Worker is concerned.

    Holds one activated instance: the name it was activated under, which is the
    thing the Worker compares against and cannot be talked out of.
    """

    def __init__(
        self,
        *,
        instance_name: str,
        valid: bool = True,
        variant_id: str | None = None,
        instance_id: str = "inst-uuid-001",
        raises: Exception | None = None,
    ):
        self.instance_name = instance_name
        self.valid = valid
        self.variant_id = EXPECTED_VARIANT_ID if variant_id is None else variant_id
        self.instance_id = instance_id
        self.raises = raises

    def validate(self, _license_key: str, _instance_id: str) -> dict:
        if self.raises is not None:
            raise self.raises
        return {
            "valid": self.valid,
            "meta": {"variant_id": int(self.variant_id) if self.variant_id else 0},
            "license_key": {"id": 42},
            "instance": {"id": self.instance_id, "name": self.instance_name},
        }


MAX_BODY = 4096
MAX_FIELD = 200
HASH_SHAPE = re.compile(r"^[A-Za-z0-9_-]{43}$")


@dataclass(frozen=True)
class _Request:
    """A request as it arrives, not as somebody has already understood it."""

    method: str = "POST"
    content_type: str = "application/json"
    body: bytes = b"{}"


def _request(**fields) -> _Request:
    return _Request(body=json.dumps(fields).encode("utf-8"))


class _Worker:
    """What the service is specified to do, in the language the tests are in."""

    def __init__(self, lemon: _Lemon, private_key) -> None:
        self._lemon = lemon
        self._private = private_key
        self.upstream_calls = 0

    def issue(self, request: _Request, *, now: datetime):
        # Judged on its own first. An upstream call is the expensive part and
        # the one with a limit on it; spending one on a request that was never
        # going to work is how a service becomes somebody else's denial of
        # service.
        if request.method != "POST":
            return 405, {"error": "method_not_allowed"}
        if len(request.body) > MAX_BODY:
            return 413, {"error": "request_too_large"}
        if request.content_type != "application/json":
            return 400, {"error": "malformed_request"}
        try:
            fields = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return 400, {"error": "malformed_request"}
        if not isinstance(fields, dict):
            return 400, {"error": "malformed_request"}

        license_key = str(fields.get("license_key", ""))
        instance_id = str(fields.get("instance_id", ""))
        installation_hash = str(fields.get("installation_hash", ""))
        if not HASH_SHAPE.match(installation_hash):
            return 400, {"error": "malformed_request"}
        for field in (license_key, instance_id):
            if not field or len(field) > MAX_FIELD:
                return 400, {"error": "malformed_request"}

        self.upstream_calls += 1
        try:
            answer = self._lemon.validate(license_key, instance_id)
        except _Unavailable:
            # Lemon Squeezy being down is not a statement about anybody's
            # licence, so it must not arrive as one.
            return 502, {"error": "upstream_unavailable"}
        except _RateLimited:
            return 429, {"error": "rate_limited"}
        if not answer.get("valid"):
            return 403, {"error": "invalid"}
        if str(answer.get("meta", {}).get("variant_id", "")) != EXPECTED_VARIANT_ID:
            return 403, {"error": "invalid"}
        # About the activation that was actually asked about. Without this the
        # answer could describe a different one — and its name would match,
        # because it is that instance's name.
        if str(answer["instance"]["id"]) != instance_id:
            return 409, {"error": "instance_mismatch"}
        # The binding. Rebuilt from the hash that arrived, compared whole with
        # what Lemon Squeezy has on file for the activation.
        expected = canonical_instance_name(installation_hash)
        if not expected or answer["instance"]["name"] != expected:
            return 409, {"error": "instance_mismatch"}

        receipt = {
            "receipt_version": RECEIPT_VERSION,
            "key_id": KEY_ID,
            "audience": AUDIENCE,
            "license_id": str(answer["license_key"]["id"]),
            "instance_id": str(answer["instance"]["id"]),
            "variant_id": EXPECTED_VARIANT_ID,
            "installation_hash": installation_hash,
            "issued_at": now.isoformat(),
            "expires_at": (now + MAX_LIFETIME).isoformat(),
        }
        receipt["signature"] = base64.b64encode(
            self._private.sign(canonical_bytes(receipt))
        ).decode()
        return 200, receipt


def _good_request(**overrides) -> _Request:
    fields = {
        "license_key": "LS-KEY",
        "instance_id": "inst-uuid-001",
        "installation_hash": INSTALLATION,
    }
    fields.update(overrides)
    return _request(**fields)


def _service(*, instance_name: str | None = None, **lemon):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    name = canonical_instance_name(INSTALLATION) if instance_name is None else instance_name
    return _Worker(_Lemon(instance_name=name, **lemon), private), {KEY_ID: public}


# ── the two halves agree ──────────────────────────────────────────────
def test_a_receipt_built_the_documented_way_is_accepted() -> None:
    """The whole point of writing the contract down: an implementation that
    follows the page produces something this application believes."""
    worker, keys = _service()

    status, receipt = worker.issue(_good_request(), now=NOW)

    assert status == 200
    verdict = verify(receipt, public_keys=keys, installation_hash=INSTALLATION, now=NOW)
    assert verdict.reason == OK
    assert verdict.ok is True


def test_the_receipt_lasts_exactly_as_long_as_the_page_says() -> None:
    """Fourteen days, which is also the longest the client will accept — the
    two numbers are the same number, and a service that drifted past it would
    be refused by every installation at once."""
    worker, keys = _service()

    _status, receipt = worker.issue(_good_request(), now=NOW)

    issued = datetime.fromisoformat(receipt["issued_at"])
    expires = datetime.fromisoformat(receipt["expires_at"])
    assert expires - issued == MAX_LIFETIME
    assert verify(receipt, public_keys=keys, installation_hash=INSTALLATION, now=NOW).ok is True

    just_before = NOW + MAX_LIFETIME - timedelta(seconds=1)
    assert verify(
        receipt, public_keys=keys, installation_hash=INSTALLATION, now=just_before
    ).ok is True


# ── the binding, which is what the service is for ─────────────────────
def test_a_receipt_cannot_be_had_for_an_installation_that_did_not_activate() -> None:
    """The rule the whole design rests on.

    Without it a valid key and instance would be enough to obtain a receipt for
    any hash somebody cared to type — one activation, spread across as many
    machines as they liked.
    """
    worker, _keys = _service()

    status, body = worker.issue(_good_request(installation_hash=OTHER_INSTALLATION), now=NOW)

    assert status == 409
    assert body == {"error": "instance_mismatch"}


def test_the_name_is_compared_whole_and_not_by_its_beginning() -> None:
    """A prefix comparison would accept a name with anything appended, which is
    a name anybody can arrange."""
    worker, _keys = _service(
        instance_name=canonical_instance_name(INSTALLATION) + "-extra"
    )

    status, body = worker.issue(_good_request(), now=NOW)

    assert status == 409
    assert body == {"error": "instance_mismatch"}


def test_an_installation_with_no_identity_is_refused_rather_than_matched() -> None:
    """An empty hash builds an empty expected name. Comparing two empty strings
    would succeed, which would make a lost identity a master key."""
    worker, _keys = _service(instance_name="")

    status, body = worker.issue(_good_request(installation_hash="x" * 43), now=NOW)

    assert status == 409
    assert body == {"error": "instance_mismatch"}


# ── what Lemon Squeezy says still decides ─────────────────────────────
def test_a_licence_lemon_calls_invalid_is_refused() -> None:
    worker, _keys = _service(valid=False)

    status, body = worker.issue(_good_request(), now=NOW)

    assert status == 403
    assert body == {"error": "invalid"}


def test_a_licence_for_another_product_is_refused_at_the_server_too() -> None:
    """Checked in both places. The client checks it because a good signature
    over the wrong statement is still wrong; the server checks it so the wrong
    statement is never signed."""
    worker, _keys = _service(variant_id="999")

    status, body = worker.issue(_good_request(), now=NOW)

    assert status == 403
    assert body == {"error": "invalid"}


# ── a receipt is for one installation and one product ─────────────────
def test_a_receipt_issued_here_is_no_use_on_another_installation() -> None:
    """Copying the file to another machine is the case this answers: the
    signature is fine, and it is a signature about somebody else."""
    worker, keys = _service()

    _status, receipt = worker.issue(_good_request(), now=NOW)

    verdict = verify(
        receipt, public_keys=keys, installation_hash=OTHER_INSTALLATION, now=NOW
    )

    assert verdict.reason == WRONG_INSTALLATION


def test_a_receipt_from_another_service_is_no_use_here() -> None:
    """Two services, two keys. The one this build ships cannot check the
    other's signature, however well formed it is."""
    ours, our_keys = _service()
    theirs, _their_keys = _service()

    _status, receipt = theirs.issue(_good_request(), now=NOW)

    assert verify(receipt, public_keys=our_keys, installation_hash=INSTALLATION, now=NOW).ok is (
        False
    )
    _status, mine = ours.issue(_good_request(), now=NOW)
    assert verify(mine, public_keys=our_keys, installation_hash=INSTALLATION, now=NOW).ok is True


# ── the request, judged before anything is asked upstream ─────────────
def test_a_request_that_cannot_work_never_reaches_lemon_squeezy() -> None:
    """The upstream call is the expensive part and the one with a limit on it.

    Spending one on a request that was never going to work is how a service
    becomes somebody else's denial of service — and the counter here is what
    makes "checked first" a fact rather than an ordering in the source.
    """
    worker, _keys = _service()

    refusals = [
        worker.issue(_Request(method="GET"), now=NOW),
        worker.issue(_Request(content_type="text/plain"), now=NOW),
        worker.issue(_Request(body=b"not json"), now=NOW),
        worker.issue(_Request(body=b'"a string, not an object"'), now=NOW),
        worker.issue(_good_request(installation_hash="short"), now=NOW),
        worker.issue(_good_request(license_key=""), now=NOW),
    ]

    assert all(status in (400, 405, 413) for status, _body in refusals), refusals
    assert worker.upstream_calls == 0, "a doomed request was passed upstream"


def test_a_wrong_method_is_not_a_wrong_licence() -> None:
    worker, _keys = _service()

    for method in ("GET", "PUT", "DELETE", "OPTIONS"):
        status, body = worker.issue(_Request(method=method), now=NOW)
        assert (status, body) == (405, {"error": "method_not_allowed"}), method


def test_an_oversized_body_is_refused_by_its_size_alone() -> None:
    """Refused for being too large, before anything tries to understand it."""
    worker, _keys = _service()
    padding = "x" * (MAX_BODY + 1)

    status, body = worker.issue(_good_request(license_key=padding), now=NOW)

    assert (status, body) == (413, {"error": "request_too_large"})
    assert worker.upstream_calls == 0


def test_the_hash_has_one_shape_and_anything_else_is_a_mistake() -> None:
    """Not "starts with", not "at least". A hash of the wrong length or with a
    character outside the alphabet is a bug on the client or an attempt, and
    either way it is not something to ask Lemon Squeezy about."""
    worker, _keys = _service()
    wrong = [
        "",
        "x" * 42,
        "x" * 44,
        "x" * 43 + "=",
        "+" + "x" * 42,
        "/" + "x" * 42,
        "x" * 21 + " " + "x" * 21,
    ]

    for candidate in wrong:
        status, body = worker.issue(_good_request(installation_hash=candidate), now=NOW)
        assert (status, body) == (400, {"error": "malformed_request"}), repr(candidate)

    assert worker.upstream_calls == 0


def test_a_malformed_request_is_never_reported_as_an_invalid_licence() -> None:
    """The two mean different things to the client. One is a fault on this side;
    the other is a statement about somebody's licence, and only the second is
    allowed to switch their Pro off. A service that reaches for "invalid" when
    it is confused ends licences by accident."""
    worker, _keys = _service()

    for request in (_Request(method="GET"), _Request(body=b"{"), _good_request(instance_id="")):
        _status, body = worker.issue(request, now=NOW)
        assert body["error"] != "invalid", body


# ── the answer has to be about the activation that was asked about ────
def test_an_answer_about_a_different_activation_is_refused() -> None:
    """Its name would match — it is that instance's name. What would not match
    is which activation it was, and without checking that, a receipt could be
    issued on the strength of somebody else's instance entirely."""
    worker, _keys = _service(instance_id="inst-somebody-else")

    status, body = worker.issue(_good_request(), now=NOW)

    assert (status, body) == (409, {"error": "instance_mismatch"})


def test_the_receipt_names_the_activation_that_was_asked_about() -> None:
    worker, keys = _service()

    _status, receipt = worker.issue(_good_request(), now=NOW)

    assert receipt["instance_id"] == "inst-uuid-001"
    assert verify(receipt, public_keys=keys, installation_hash=INSTALLATION, now=NOW).ok is True


# ── an upstream that cannot answer is not an answer ───────────────────
def test_lemon_squeezy_being_down_does_not_end_a_licence() -> None:
    """The most important thing this service must never do. A dependency that
    is unreachable has said nothing about anybody's licence, and reporting it
    as "invalid" would turn an outage into cancelled Pro for everyone at once.
    """
    worker, _keys = _service(raises=_Unavailable())

    status, body = worker.issue(_good_request(), now=NOW)

    assert (status, body) == (502, {"error": "upstream_unavailable"})
    assert body["error"] not in ("invalid", "revoked")


def test_lemon_squeezy_rate_limiting_is_passed_on_as_itself() -> None:
    """Asking too often is a reason to wait, not a reason to stop being Pro."""
    worker, _keys = _service(raises=_RateLimited())

    status, body = worker.issue(_good_request(), now=NOW)

    assert (status, body) == (429, {"error": "rate_limited"})
