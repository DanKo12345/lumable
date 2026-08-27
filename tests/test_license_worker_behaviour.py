"""What the service actually does, run rather than read.

The other worker test compares constants; this one runs the code. Every case
here is a branch that cannot be produced against the live service on demand — a
refunded licence, an activation belonging to another machine, an API that
answers with a login page — and most of the rest would need a real licence key
to reach at all.

The receipt at the end is checked by the same verifier the application uses. If
the two sides ever stop agreeing about what is signed or how, that assertion is
where it shows, and it shows before a build goes out rather than after a
customer cannot activate.

Skipped where Node is not installed, which is most machines.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import license_receipt

RUNNER = Path(__file__).resolve().parent.parent / "worker" / "test" / "run.mjs"


@pytest.fixture(scope="module")
def ran() -> dict:
    node = shutil.which("node")
    if node is None or not RUNNER.exists():
        pytest.skip("node is not on this machine")
    finished = subprocess.run(
        [node, str(RUNNER)],
        cwd=str(RUNNER.parent.parent),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout)


def _outcome(ran: dict, name: str) -> tuple[int, str]:
    answer = ran[name]
    body = answer["body"] or {}
    return answer["status"], str(body.get("error", ""))


# ── the receipt it produces ───────────────────────────────────────────
def test_a_good_request_is_answered_with_a_receipt(ran) -> None:
    assert ran["issued"]["status"] == 200
    assert ran["issued"]["upstream_calls"] == 1


def test_the_receipt_is_one_the_application_accepts(ran) -> None:
    """The whole arrangement in one assertion. Two languages, two ideas about
    field order and escaping and how a date is written, and a signature that
    covers bytes — this is where a disagreement about any of it surfaces."""
    receipt = ran["issued"]["body"]
    keys = {"k1": base64.b64decode(ran["public_key"])}

    verdict = license_receipt.verify(
        receipt,
        public_keys=keys,
        installation_hash=receipt["installation_hash"],
        now=datetime.fromisoformat(receipt["issued_at"]),
    )

    assert verdict.ok, verdict.reason


def test_the_receipt_lasts_a_fortnight_and_not_a_day_longer(ran) -> None:
    receipt = ran["issued"]["body"]
    issued = datetime.fromisoformat(receipt["issued_at"])
    expires = datetime.fromisoformat(receipt["expires_at"])

    assert expires - issued == timedelta(days=14)
    assert issued.tzinfo is not None, "a moment without an offset is not a moment"
    assert issued.utcoffset() == timedelta(0)


def test_the_numbers_lemon_squeezy_returns_arrive_as_strings(ran) -> None:
    """It sends license_id and variant_id as integers, and the receipt says
    strings. Signing one and comparing the other is a mismatch that would only
    appear against the live API."""
    receipt = ran["issued"]["body"]

    assert receipt["license_id"] == "42"
    assert receipt["variant_id"] == "1776109"


def test_the_upstream_is_asked_about_the_key_that_was_sent(ran) -> None:
    assert ran["upstream_request"] == "license_key=TEST-KEY-0001&instance_id=inst-uuid-001"


def test_a_signature_over_something_else_is_not_accepted(ran) -> None:
    """A signature that verifies whatever it is put next to would pass every
    other test on this page."""
    receipt = dict(ran["issued"]["body"])
    receipt["installation_hash"] = "A" * 43
    keys = {"k1": base64.b64decode(ran["public_key"])}

    verdict = license_receipt.verify(
        receipt,
        public_keys=keys,
        installation_hash=receipt["installation_hash"],
        now=datetime.fromisoformat(ran["issued"]["body"]["issued_at"]),
    )

    assert not verdict.ok


# ── judged before anybody is asked ────────────────────────────────────
@pytest.mark.parametrize(
    ("case", "status", "error"),
    [
        ("wrong_path", 404, "not_found"),
        ("wrong_path_versioned", 404, "not_found"),
        ("get", 405, "method_not_allowed"),
        ("put", 405, "method_not_allowed"),
        ("no_content_type", 400, "malformed_request"),
        ("form_content_type", 400, "malformed_request"),
        ("not_json", 400, "malformed_request"),
        ("json_array", 400, "malformed_request"),
        ("json_string", 400, "malformed_request"),
        ("no_key", 400, "malformed_request"),
        ("empty_key", 400, "malformed_request"),
        ("key_too_long", 400, "malformed_request"),
        ("key_not_a_string", 400, "malformed_request"),
        ("no_instance", 400, "malformed_request"),
        ("hash_too_short", 400, "malformed_request"),
        ("hash_too_long", 400, "malformed_request"),
        ("hash_wrong_alphabet", 400, "malformed_request"),
        ("hash_with_padding", 400, "malformed_request"),
        ("hash_not_a_string", 400, "malformed_request"),
        ("oversized_body", 413, "request_too_large"),
        ("oversized_header", 413, "request_too_large"),
    ],
)
def test_a_request_that_was_never_going_to_work_is_refused(ran, case, status, error) -> None:
    assert _outcome(ran, case) == (status, error)


def test_none_of_those_cost_an_upstream_call(ran) -> None:
    """The upstream call is the expensive part and the part with a rate limit
    on it. Spending one on a request that was already wrong is how a service
    becomes somebody else denial of service."""
    refused = [name for name, answer in ran.items() if isinstance(answer, dict) and answer.get("status") in (400, 404, 405, 413)]

    assert len(refused) >= 20
    for name in refused:
        assert ran[name]["upstream_calls"] == 0, f"{name} reached Lemon Squeezy first"


def test_a_charset_on_the_content_type_is_not_a_malformed_request(ran) -> None:
    """Plenty of clients send one, and refusing them would be refusing
    everybody for no reason."""
    assert ran["charset_is_fine"]["status"] == 200


def test_nothing_refused_up_front_is_ever_a_403(ran) -> None:
    """400 and 403 mean different things to the client: one is a bug on the
    service side, the other is a statement about somebody licence, and only the
    second may take Pro away."""
    for name in ("no_key", "hash_too_short", "not_json", "get", "oversized_body"):
        assert ran[name]["status"] != 403


# ── what the upstream says ────────────────────────────────────────────
@pytest.mark.parametrize(
    ("case", "status", "error"),
    [
        ("not_valid", 403, "invalid"),
        ("expired", 403, "invalid"),
        ("not_valid_no_status", 403, "invalid"),
        ("unknown_key_404", 403, "invalid"),
        ("gone_410", 403, "invalid"),
        ("disabled", 403, "revoked"),
        ("forbidden_403", 403, "revoked"),
    ],
)
def test_lemon_squeezy_saying_no_is_the_only_thing_that_ends_a_licence(
    ran, case, status, error
) -> None:
    assert _outcome(ran, case) == (status, error)


def test_a_refund_is_told_apart_from_a_key_that_was_never_real(ran) -> None:
    """Both end Pro, and the client stores the reason. Collapsing them would
    make a refund indistinguishable from a typo in support."""
    assert _outcome(ran, "disabled")[1] == "revoked"
    assert _outcome(ran, "not_valid")[1] == "invalid"


@pytest.mark.parametrize(
    ("case", "status", "error"),
    [
        ("another_instance_described", 409, "instance_mismatch"),
        ("another_machine_name", 409, "instance_mismatch"),
        ("name_without_prefix", 409, "instance_mismatch"),
        ("name_with_prefix_only", 409, "instance_mismatch"),
        ("name_padded", 409, "instance_mismatch"),
        ("no_instance_at_all", 409, "instance_mismatch"),
    ],
)
def test_a_receipt_is_never_signed_for_an_installation_that_did_not_activate(
    ran, case, status, error
) -> None:
    """The binding, and the reason one licence cannot be spread across as many
    machines as somebody cares to type in. The name was fixed when the instance
    was activated; the hash in the request is only an input.

    ``name_padded`` is the one worth staring at: a trimming comparison would
    accept it, and a service that normalises before comparing has a binding
    that can be talked around.
    """
    assert _outcome(ran, case) == (status, error)


@pytest.mark.parametrize(
    ("case", "status", "error"),
    [
        ("wrong_variant", 403, "wrong_product"),
        ("no_variant", 403, "wrong_product"),
    ],
)
def test_a_licence_for_another_product_does_not_answer_invalid(ran, case, status, error) -> None:
    """The likeliest way to reach this branch is a new plan added to the store
    without the constant being updated, and invalid is the answer that switches
    Pro off. A misconfiguration should look like an outage, where the client
    keeps everything, rather than like a mass revocation."""
    assert _outcome(ran, case) == (status, error)


@pytest.mark.parametrize(
    "case",
    [
        "upstream_500",
        "upstream_503",
        "upstream_500_that_parses",
        "upstream_502_that_parses",
        "upstream_html",
        "upstream_no_valid_field",
        "upstream_valid_is_a_string",
        "upstream_refused",
        "no_license_id",
    ],
)
def test_an_upstream_that_cannot_answer_never_ends_a_licence(ran, case) -> None:
    """Including the cases where it answers with something that is not about a
    licence at all. Reaching for invalid when confused is how a service ends
    licences by accident — and a login page or an error page is exactly what an
    API in trouble returns."""
    status, error = _outcome(ran, case)

    assert (status, error) == (502, "upstream_unavailable")


def test_being_rate_limited_upstream_is_passed_on_as_such(ran) -> None:
    """Not translated into an outage. The client already knows to keep
    everything and come back later, and the distinction is worth keeping."""
    assert _outcome(ran, "upstream_429") == (429, "rate_limited")


def test_a_noisy_client_is_stopped_before_the_upstream(ran) -> None:
    assert _outcome(ran, "client_rate_limited") == (429, "rate_limited")
    assert ran["client_rate_limited"]["upstream_calls"] == 0


def test_every_failure_the_client_knows_about_is_reachable(ran) -> None:
    """The client maps statuses to outcomes, and a mapping for something the
    service never sends is a mapping nobody has checked."""
    from app import license_client

    seen = {a["status"] for a in ran.values() if isinstance(a, dict) and "status" in a}

    for status in (200, 400, 403, 405, 409, 413, 429, 502):
        assert status in seen, f"nothing here produces {status}"

    assert license_client._outcome_for_status(403, "invalid") == license_client.INVALID
    assert license_client._outcome_for_status(403, "revoked") == license_client.REVOKED
    assert license_client._outcome_for_status(403, "wrong_product") == license_client.UNAVAILABLE


def test_a_key_that_does_not_exist_is_answered_rather_than_deferred(ran) -> None:
    """Lemon Squeezy returns 404 for an unknown key, not the 400 the contract
    first assumed, and the first version of this service treated any status but
    200 and 400 as an outage. So somebody who mistyped their key was told to try
    again later, forever, and nothing in a stubbed test would ever have said so:
    the stub answered the way the document claimed.

    It took asking the deployed service to find, which is the argument for doing
    that before calling any of this finished.
    """
    assert _outcome(ran, "unknown_key_404") == (403, "invalid")


def test_a_server_error_stays_an_outage_however_readable_its_body(ran) -> None:
    """The other side of the same coin. Widening what counts as an answer must
    not widen it to a service that is simply broken."""
    for case in ("upstream_500_that_parses", "upstream_502_that_parses"):
        assert _outcome(ran, case) == (502, "upstream_unavailable")


def test_the_service_is_not_usable_without_encryption(ran) -> None:
    """workers.dev answers plain HTTP directly rather than redirecting to it,
    which the live check found by asking. A licence key in an unencrypted
    request is a licence key on the wire, and while LumaBLE cannot send one that
    way — its address is https and it refuses redirects — a service that accepts
    them is one somebody will eventually point something else at.

    Refused before Lemon Squeezy is asked, so a key sent in the clear is at
    least not also validated.
    """
    assert _outcome(ran, "plain_http") == (400, "https_required")
    assert ran["plain_http"]["upstream_calls"] == 0
