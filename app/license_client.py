"""Asking the signing service for a receipt.

The one piece of this that talks to the network, and it is deliberately dull:
synchronous, free of Qt, and knowing nothing about settings or storage. It is
handed what to ask, it asks, it checks the answer with the same verifier the
rest of the application uses, and it reports one of a small number of outcomes.
What to *do* about each outcome belongs to the caller, because only one of them
is allowed to take somebody's Pro away and that decision should not be buried
in a function that also parses JSON.

Being synchronous is a property, not an oversight: it must be called from a
background thread. A licence check on the thread drawing the window is a window
that stops drawing whenever somebody's connection is slow.

Two things it will not do. It does not follow redirects — a redirect is how a
licence key ends up posted to an address nobody chose — and it does not read an
answer of unbounded size, because a service that has been replaced by something
else should cost a few kilobytes rather than all the memory there is. The size
is enforced by reading one byte more than is allowed rather than by believing
the length the other end claims.

Nothing here writes the licence key, the request body or a whole response
anywhere. There is no logging in this module at all, which is the only version
of that promise that cannot drift.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from app.app_info import APP_VERSION
from app.license_receipt import OK, verify

ISSUE_URL = "https://lumable-license.lumable.workers.dev/v1/issue"
# What this build calls itself when asking. Not decoration: Cloudflare refuses
# the default Python-urllib signature outright, with a 403 and an error page,
# and every activation would have failed on a service that had never seen the
# request. Found by asking the deployed service rather than a local stand-in,
# which is the only place it could have been found.
USER_AGENT = f"LumaBLE/{APP_VERSION}"


# A receipt is a few hundred bytes. Anything approaching this is not one.
MAX_RESPONSE_BYTES = 8192
TIMEOUT_SECONDS = 10.0

# How long a receipt is asked to last, and therefore how often it is worth
# asking. Daily, so the usual case has most of its fourteen days left when a
# service goes down.
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
# Spread over an hour so every installation does not arrive at once.
REFRESH_SPREAD_SECONDS = 60 * 60

ISSUED = "issued"
INVALID = "invalid"
REVOKED = "revoked"
INSTANCE_MISMATCH = "instance_mismatch"
RATE_LIMITED = "rate_limited"
UNAVAILABLE = "unavailable"
MALFORMED_RESPONSE = "malformed_response"

# The only two answers that end somebody's Pro, and only because the service
# reached Lemon Squeezy and was told so. Everything else leaves the stored key,
# instance and receipt exactly as they were: a service that cannot answer must
# never be able to cancel a licence.
_ENDS_PRO = frozenset({INVALID, REVOKED})


@dataclass(frozen=True)
class IssueResult:
    """What came back, in terms the caller can act on."""

    outcome: str
    receipt: dict | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == ISSUED and self.receipt is not None

    @property
    def ends_pro(self) -> bool:
        return self.outcome in _ENDS_PRO


class _NoRedirects(urllib_request.HTTPRedirectHandler):
    """Refuses every redirect.

    Returning None here stops urllib building the second request, so the
    licence key is never sent to the new address. Which address that would have
    been does not matter: the client was told one place to go.
    """

    def redirect_request(self, *_args, **_kwargs):
        return None


def _opener():
    return urllib_request.build_opener(_NoRedirects)


def refresh_delay_seconds(installation_hash: Any) -> float:
    """How long after the interval this installation should ask.

    Derived from the installation rather than drawn fresh each time. A random
    number per launch would move the deadline on every restart — somebody who
    restarts often would either never reach it or ask far more than daily —
    while a fixed offset would have every installation arrive in the same
    minute.
    """
    text = str(installation_hash or "")
    if not text:
        return 0.0
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % REFRESH_SPREAD_SECONDS


def is_refresh_due(receipt: Any, *, installation_hash: Any, now: datetime) -> bool:
    """Whether it is time to ask for a new receipt.

    Counted from the ``issued_at`` the service signed, not from when this
    process started. Anchoring it to a launch would let anybody put the next
    check off forever by restarting often enough, which is a way of never being
    told a licence was revoked.

    A receipt with no readable ``issued_at`` is due now: something is wrong
    with it, and asking is how that gets repaired.
    """
    if not isinstance(receipt, dict):
        return True
    try:
        issued = datetime.fromisoformat(str(receipt.get("issued_at", "")))
    except (TypeError, ValueError):
        return True
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=UTC)
    due = issued + timedelta(
        seconds=REFRESH_INTERVAL_SECONDS + refresh_delay_seconds(installation_hash)
    )
    return now >= due


def _outcome_for_status(status: int, error: str) -> str:
    # Two exact pairs, and nothing else, may end somebody's Pro. A 403 is not
    # by itself a statement about a licence: a protection page in front of the
    # service answers 403 with HTML, a proxy answers it with nothing at all,
    # and reading either as "your licence was cancelled" would cancel licences
    # by accident on a day when nothing was wrong with them.
    if status == 403 and error == "invalid":
        return INVALID
    if status == 403 and error == "revoked":
        return REVOKED
    if status == 403:
        return UNAVAILABLE
    if status == 409:
        return INSTANCE_MISMATCH
    if status == 429:
        return RATE_LIMITED
    # 400, 405, 413 and anything else: the service answered, and the answer was
    # not about this licence. Treated as unavailable because the effect is the
    # same — keep everything, try later — though the first three mean this
    # client is asking wrongly and will go on doing so until it is fixed.
    return UNAVAILABLE


def request_receipt(
    *,
    license_key: str,
    instance_id: str,
    installation_hash: str,
    public_keys: dict[str, bytes],
    now: datetime,
    url: str = ISSUE_URL,
    opener: Any = None,
) -> IssueResult:
    """Ask for a receipt, and believe it only if it checks out here.

    A ``200`` whose body does not verify against the keys this build ships is
    not a receipt — whatever the service meant by it — and is reported as a
    malformed response rather than stored. Otherwise a broken or substituted
    answer would replace a working receipt with one that is refused on every
    launch afterwards, and the reason would be nowhere near the symptom.
    """
    body = json.dumps(
        {
            "license_key": str(license_key or ""),
            "instance_id": str(instance_id or ""),
            "installation_hash": str(installation_hash or ""),
        }
    ).encode("utf-8")
    request = urllib_request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        response = (opener or _opener()).open(request, timeout=TIMEOUT_SECONDS)
    except HTTPError as failure:
        # An error response is still a response, and the status is the useful
        # part. A redirect arrives here too, because following one was refused.
        payload = _read_capped(failure)
        error = ""
        if payload is not None:
            error = str(_as_object(payload).get("error", ""))
        return IssueResult(_outcome_for_status(int(getattr(failure, "status", 0) or 0), error))
    except (URLError, OSError, ValueError):
        return IssueResult(UNAVAILABLE)

    with response:
        payload = _read_capped(response)
    if payload is None:
        return IssueResult(MALFORMED_RESPONSE)
    receipt = _as_object(payload)
    if not receipt:
        return IssueResult(MALFORMED_RESPONSE)

    verdict = verify(
        receipt, public_keys=public_keys, installation_hash=installation_hash, now=now
    )
    if verdict.reason != OK:
        return IssueResult(MALFORMED_RESPONSE)
    return IssueResult(ISSUED, receipt)


def _read_capped(response: Any) -> bytes | None:
    """At most the allowed size, decided by reading one byte more.

    Not by the length the other end declares: that is a number somebody else
    chose, and believing it is how a small answer turns out to be a large one.
    """
    try:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, ValueError):
        return None
    if payload is None or len(payload) > MAX_RESPONSE_BYTES:
        return None
    return payload


def _as_object(payload: bytes) -> dict:
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
