"""Asking for a receipt, and what each answer is allowed to change.

One outcome ends somebody's Pro. Every other one — a service that is down, a
rate limit, a reply that will not parse, a redirect — has to leave the stored
key, instance and receipt exactly as they were, because a service that cannot
answer must never be able to cancel a licence.

The stand-in service here answers with whatever a test needs, but the receipts
it signs are real: a genuine key pair, real Ed25519 signatures, and the same
verifier the application uses. A test that hand-wrote a "receipt" would prove
only that some dictionary is not one.
"""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.install_identity import identity_hash
from app.license_client import (
    INSTANCE_MISMATCH,
    INVALID,
    ISSUE_URL,
    ISSUED,
    MALFORMED_RESPONSE,
    MAX_RESPONSE_BYTES,
    RATE_LIMITED,
    REFRESH_SPREAD_SECONDS,
    REVOKED,
    UNAVAILABLE,
    _NoRedirects,
    refresh_delay_seconds,
    request_receipt,
)
from app.license_receipt import AUDIENCE, EXPECTED_VARIANT_ID, MAX_LIFETIME, RECEIPT_VERSION
from app.license_receipt import canonical_bytes as receipt_bytes

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
INSTALLATION = identity_hash("a" * 64)
KEY_ID = "k1"


def _keys():
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
        "installation_hash": INSTALLATION,
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + MAX_LIFETIME).isoformat(),
    }
    receipt.update(overrides)
    receipt["signature"] = base64.b64encode(private.sign(receipt_bytes(receipt))).decode()
    return receipt


class _Answer(io.BytesIO):
    """A response object shaped like the one urllib hands back."""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        super().__init__(payload)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


class _Service:
    """Stands in for the Worker, and records what it was asked."""

    def __init__(self, answer) -> None:
        self._answer = answer
        self.requests: list = []

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _ask(service, keys, *, now=NOW, installation_hash=INSTALLATION):
    return request_receipt(
        license_key="LS-KEY",
        instance_id="inst-uuid-001",
        installation_hash=installation_hash,
        public_keys=keys,
        now=now,
        opener=service,
    )


# ── the ordinary answer ───────────────────────────────────────────────
def test_a_signed_receipt_is_accepted_and_handed_back() -> None:
    private, keys = _keys()
    service = _Service(_Answer(json.dumps(_receipt(private)).encode()))

    result = _ask(service, keys)

    assert result.outcome == ISSUED
    assert result.ok is True
    assert result.receipt["installation_hash"] == INSTALLATION
    assert result.ends_pro is False


def test_the_request_goes_to_the_one_address_as_a_post() -> None:
    private, keys = _keys()
    service = _Service(_Answer(json.dumps(_receipt(private)).encode()))

    _ask(service, keys)

    request, timeout = service.requests[0]
    assert request.full_url == ISSUE_URL
    assert request.full_url.startswith("https://")
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert timeout is not None, "a request with no deadline can wait forever"
    sent = json.loads(request.data.decode())
    assert sent == {
        "license_key": "LS-KEY",
        "instance_id": "inst-uuid-001",
        "installation_hash": INSTALLATION,
    }


# ── a 200 is not enough ───────────────────────────────────────────────
def test_a_two_hundred_that_does_not_verify_is_not_a_receipt() -> None:
    """Whatever the service meant by it. Storing it would replace a working
    receipt with one refused on every launch afterwards, and the reason would
    be nowhere near the symptom."""
    _private, keys = _keys()
    stranger, _ = _keys()
    service = _Service(_Answer(json.dumps(_receipt(stranger)).encode()))

    result = _ask(service, keys)

    assert result.outcome == MALFORMED_RESPONSE
    assert result.receipt is None
    assert result.ends_pro is False


def test_a_two_hundred_for_another_installation_is_not_a_receipt() -> None:
    private, keys = _keys()
    service = _Service(_Answer(json.dumps(_receipt(private)).encode()))

    result = _ask(service, keys, installation_hash=identity_hash("b" * 64))

    assert result.outcome == MALFORMED_RESPONSE


def test_a_two_hundred_that_has_already_expired_is_not_a_receipt() -> None:
    private, keys = _keys()
    service = _Service(_Answer(json.dumps(_receipt(private)).encode()))

    result = _ask(service, keys, now=NOW + MAX_LIFETIME + timedelta(seconds=1))

    assert result.outcome == MALFORMED_RESPONSE


@pytest.mark.parametrize(
    "payload", [b"", b"not json", b'"a string"', b"[]", b"{}", b'{"error": "invalid"}']
)
def test_a_two_hundred_carrying_something_else_is_malformed(payload: bytes) -> None:
    """Including a body that says "invalid" with a 200 on it. What ends a
    licence is the status the service chose, not a word in a body that failed
    every other check."""
    _private, keys = _keys()
    service = _Service(_Answer(payload))

    result = _ask(service, keys)

    assert result.outcome == MALFORMED_RESPONSE
    assert result.ends_pro is False


# ── the size of the answer ────────────────────────────────────────────
def test_an_answer_larger_than_allowed_is_refused() -> None:
    _private, keys = _keys()
    service = _Service(_Answer(b"x" * (MAX_RESPONSE_BYTES + 1)))

    assert _ask(service, keys).outcome == MALFORMED_RESPONSE


def test_an_oversized_answer_that_would_otherwise_be_perfect_is_still_refused() -> None:
    """The version of this that matters.

    The first oversize test pads with rubbish, so it is refused for being
    unreadable and the size limit is never what decides. This one is a genuine,
    correctly signed receipt with a large field added: the signature still
    holds, because the extra field is not one of the signed ones, so removing
    the limit would let it straight through.
    """
    private, keys = _keys()
    receipt = _receipt(private)
    receipt["note"] = "x" * MAX_RESPONSE_BYTES
    payload = json.dumps(receipt).encode()
    assert len(payload) > MAX_RESPONSE_BYTES

    result = _ask(_Service(_Answer(payload)), keys)

    assert result.outcome == MALFORMED_RESPONSE
    assert result.receipt is None


def test_a_body_one_byte_over_the_limit_is_refused_by_the_limit_itself() -> None:
    """The only size the length check actually decides, and therefore the only
    one worth testing it with.

    Reading is already capped, so anything comfortably over the limit arrives
    truncated and fails to parse — refused, but by the parser, and the check
    could be deleted without any of those tests noticing. A body of exactly one
    byte over arrives whole, parses, and verifies. Then the check is the only
    thing standing between it and being stored.
    """
    private, keys = _keys()
    receipt = _receipt(private)
    without_note = len(json.dumps(receipt).encode())
    # Grow the padding until the encoded body lands exactly on the boundary.
    padding = MAX_RESPONSE_BYTES + 1 - without_note - len('"note":"",')
    receipt["note"] = "x" * padding
    payload = json.dumps(receipt, separators=(",", ":")).encode()
    while len(payload) != MAX_RESPONSE_BYTES + 1:
        step = MAX_RESPONSE_BYTES + 1 - len(payload)
        receipt["note"] = "x" * (len(receipt["note"]) + step)
        payload = json.dumps(receipt, separators=(",", ":")).encode()

    assert len(payload) == MAX_RESPONSE_BYTES + 1
    assert json.loads(payload), "the body has to be readable, or the parser refuses it instead"

    result = _ask(_Service(_Answer(payload)), keys)

    assert result.outcome == MALFORMED_RESPONSE, "an oversized answer was accepted"


def test_the_opener_this_module_builds_refuses_redirects() -> None:
    """The tests hand in their own opener, so the one built for real use is the
    piece nothing else looks at — and it is the piece that runs."""
    from app.license_client import _opener

    handlers = _opener().handlers

    assert any(isinstance(handler, _NoRedirects) for handler in handlers), handlers
    assert all(
        type(handler).__name__ != "HTTPRedirectHandler" for handler in handlers
    ), "the ordinary redirect handler is still installed"


def test_the_limit_is_read_rather_than_believed() -> None:
    """A body that claims to be small and is not.

    Trusting the declared length is how a few hundred bytes turn out to be all
    the memory there is; this reads one byte past what is allowed and decides
    from that.
    """

    class _Lying(_Answer):
        def __init__(self) -> None:
            super().__init__(b"x" * (MAX_RESPONSE_BYTES * 4))
            self.headers = {"Content-Length": "12"}

        def read(self, size=-1):
            assert size == MAX_RESPONSE_BYTES + 1, "the whole body was read into memory"
            return super().read(size)

    _private, keys = _keys()

    assert _ask(_Service(_Lying()), keys).outcome == MALFORMED_RESPONSE


# ── redirects ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_a_redirect_is_refused_rather_than_followed(status: int) -> None:
    """A redirect is how a licence key ends up posted to an address nobody
    chose. Which address does not matter: the client was told one place."""
    _private, keys = _keys()
    failure = HTTPError(
        ISSUE_URL, status, "Moved", {"Location": "https://elsewhere.example/steal"}, None
    )

    result = _ask(_Service(failure), keys)

    assert result.outcome == UNAVAILABLE
    assert result.ends_pro is False


@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_the_handler_itself_builds_no_second_request(status: int) -> None:
    """Below the outcome: urllib is told not to construct the follow-up at all,
    so the key is never put in it."""
    handler = _NoRedirects()

    assert handler.redirect_request(None, None, status, "Moved", {}, "https://elsewhere.example") is None


# ── what the service says about the licence ───────────────────────────
@pytest.mark.parametrize(
    "status, error, expected",
    [
        (403, "invalid", INVALID),
        (403, "revoked", REVOKED),
        (403, "", UNAVAILABLE),
        (409, "instance_mismatch", INSTANCE_MISMATCH),
        (429, "rate_limited", RATE_LIMITED),
        (400, "malformed_request", UNAVAILABLE),
        (405, "method_not_allowed", UNAVAILABLE),
        (413, "request_too_large", UNAVAILABLE),
        (502, "upstream_unavailable", UNAVAILABLE),
        (500, "", UNAVAILABLE),
    ],
)
def test_each_status_is_understood_as_itself(status: int, error: str, expected: str) -> None:
    _private, keys = _keys()
    body = json.dumps({"error": error}).encode()
    failure = HTTPError(ISSUE_URL, status, error, {}, io.BytesIO(body))

    result = _ask(_Service(failure), keys)

    assert result.outcome == expected
    assert result.receipt is None


def test_a_forbidden_that_says_nothing_about_a_licence_ends_nothing() -> None:
    """The gap that mattered most, and the one a test had locked in.

    A 403 is not by itself a statement about anybody's licence. A protection
    page in front of the service answers 403 with HTML; a proxy answers it with
    an empty body; a future version of the service might answer it with a word
    this build has never heard of. Reading any of those as "your licence was
    cancelled" cancels licences on a day when nothing is wrong with them — and
    the earlier table asserted exactly that for an empty body.
    """
    _private, keys = _keys()
    bodies = [
        b"",
        b"<!DOCTYPE html><html><body>Attention Required! | Cloudflare</body></html>",
        b'{"error": "forbidden"}',
        b'{"error": "Invalid"}',
        b'{"error": ""}',
        b"not json at all",
        b'{"message": "no"}',
        b"x" * (MAX_RESPONSE_BYTES + 1),
    ]

    for body in bodies:
        failure = HTTPError(ISSUE_URL, 403, "Forbidden", {}, io.BytesIO(body))
        result = _ask(_Service(failure), keys)

        assert result.outcome == UNAVAILABLE, body[:40]
        assert result.ends_pro is False, body[:40]
        assert result.receipt is None


def test_the_two_words_that_do_end_pro_still_do() -> None:
    """The other half: being careful about 403 must not make a real revocation
    unenforceable."""
    _private, keys = _keys()

    for word, expected in (("invalid", INVALID), ("revoked", REVOKED)):
        failure = HTTPError(
            ISSUE_URL, 403, word, {}, io.BytesIO(json.dumps({"error": word}).encode())
        )
        result = _ask(_Service(failure), keys)

        assert result.outcome == expected
        assert result.ends_pro is True


def test_only_lemon_squeezys_verdict_ends_pro() -> None:
    """The line the whole design rests on. Everything that is not the service
    reporting what Lemon Squeezy said leaves the licence alone."""
    _private, keys = _keys()
    ending, keeping = [], []

    for status, error in [
        (403, "invalid"),
        (403, "revoked"),
        (403, "forbidden"),
        (409, "instance_mismatch"),
        (429, "rate_limited"),
        (400, "malformed_request"),
        (405, "method_not_allowed"),
        (413, "request_too_large"),
        (502, "upstream_unavailable"),
        (503, ""),
    ]:
        failure = HTTPError(
            ISSUE_URL, status, error, {}, io.BytesIO(json.dumps({"error": error}).encode())
        )
        result = _ask(_Service(failure), keys)
        (ending if result.ends_pro else keeping).append(status)

    assert ending == [403, 403], "something other than a verdict ended a licence"
    assert keeping == [403, 409, 429, 400, 405, 413, 502, 503]


# ── nothing to answer at all ──────────────────────────────────────────
@pytest.mark.parametrize(
    "failure", [URLError("no route"), TimeoutError("took too long"), OSError("adapter gone")]
)
def test_a_service_that_cannot_be_reached_changes_nothing(failure: Exception) -> None:
    _private, keys = _keys()

    result = _ask(_Service(failure), keys)

    assert result.outcome == UNAVAILABLE
    assert result.ends_pro is False
    assert result.receipt is None


# ── when to ask ───────────────────────────────────────────────────────
def test_the_daily_offset_belongs_to_the_installation() -> None:
    """A fresh random number each launch would move the deadline on every
    restart — somebody who restarts often would either never reach it or ask
    far more than daily."""
    first = refresh_delay_seconds(INSTALLATION)

    assert refresh_delay_seconds(INSTALLATION) == first
    assert 0 <= first < REFRESH_SPREAD_SECONDS


def test_two_installations_do_not_arrive_in_the_same_minute() -> None:
    """A fixed offset would have every machine ask at once, which is the thing
    a rate limit is measured against."""
    offsets = {refresh_delay_seconds(identity_hash(str(index) * 64)) for index in range(50)}

    assert len(offsets) > 40, "the offsets are barely spread at all"


def test_an_installation_with_no_identity_asks_without_delay() -> None:
    assert refresh_delay_seconds("") == 0.0
    assert refresh_delay_seconds(None) == 0.0


# ── what this module is not ───────────────────────────────────────────
def test_the_network_layer_knows_nothing_about_the_interface() -> None:
    """It must be callable from a background thread, which means it cannot be
    tangled with the toolkit that owns the main one — and it must not reach
    settings or storage, so that what to *do* about each answer stays with the
    caller who is allowed to decide it."""
    import ast
    import inspect

    import app.license_client as client

    # Read as code, not as text: a substring search finds the word in a comment
    # explaining why the thing is absent, which is the opposite of a check.
    tree = ast.parse(inspect.getsource(client))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)

    assert "PySide6" not in imported, "the network layer cannot be tied to the interface thread"
    assert "logging" not in imported, "nothing here may write a key or a body anywhere"
    assert not any(name.startswith("app.storage") for name in imported), imported
    assert "app.license_receipt" in imported, "it must verify with the same code as everything else"
    assert "print" not in called


# ── who is asking ─────────────────────────────────────────────────────
def test_the_request_says_which_application_is_asking() -> None:
    """Cloudflare refuses the default Python-urllib signature outright — a 403
    and an error page, from in front of the service, which never sees the
    request. Every activation would have failed that way, and only against the
    deployed service does it show: a local stand-in answers whoever asks.
    """
    from app.app_info import APP_VERSION
    from app.license_client import USER_AGENT

    seen = {}

    class _Opener:
        def open(self, request, timeout=None):
            seen.update(dict(request.header_items()))
            raise OSError("far enough")

    request_receipt(
        license_key="LS-KEY",
        instance_id="inst-1",
        installation_hash="a" * 43,
        public_keys={},
        now=datetime.now(UTC),
        url="https://example.invalid/v1/issue",
        opener=_Opener(),
    )

    agent = seen.get("User-agent") or seen.get("User-Agent") or ""

    assert agent == USER_AGENT
    assert APP_VERSION in agent
    assert "urllib" not in agent.lower(), "the signature Cloudflare refuses"
