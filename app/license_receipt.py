"""Reading a signed receipt, and deciding whether to believe it.

A receipt says that at some moment a server checked a licence and found it
good, for this installation, until a stated time. The server signs it with a
private key nobody else has; this module holds only the public half, which can
check a signature but cannot make one. That asymmetry is the whole point: the
application is open source, so anything it *knows* is public, and a check that
depended on keeping a secret in it would be no check at all.

What this module deliberately does not do: read files, read the clock, or reach
the network. It is handed a receipt, a set of public keys, the installation it
expects, and what time it is, and it answers. Everything that can go wrong with
storage, clocks and connections belongs to the caller, and keeping it out of
here is what makes every rule below testable by writing down a case.

The answer is a reason, not a boolean. "This receipt is for another machine"
and "this receipt expired" and "this signature is forged" call for three
different things to happen — one is a re-issue, one is a refresh, one is a
person to be told something is wrong — and collapsing them into False the
moment the check succeeds throws that away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# The shape of a receipt this version understands. Present so a later shape can
# arrive without older builds guessing at it: an unknown version is refused,
# never interpreted optimistically.
RECEIPT_VERSION = 1

# Who the receipt is for. A signature from the same key over some other
# product's payload must not be accepted here, and an audience makes that a
# check rather than a hope.
AUDIENCE = "lumable-pro"

# The product this licence has to be for. Checked here as well as on the server
# that signs: a receipt is a statement about a licence, and a statement about
# somebody's licence for a different product is not one this build may accept
# just because the signature is good.
EXPECTED_VARIANT_ID = "1776109"

# The longest a receipt may claim to be good for. The server issues fourteen
# days; a signed receipt asking for a year would mean the signer had been
# changed or misconfigured, and honouring it would turn one mistake into a
# permanent one. Refusing costs a person a refresh they were going to do
# anyway.
MAX_LIFETIME = timedelta(days=14)

# The order the signed fields are laid out in. Fixed and written down, because
# the signature covers bytes and two sides that disagree about field order
# disagree about every signature. Not JSON: JSON leaves escaping and key order
# to whoever serialises, and the signer here is a different language.
SIGNED_FIELDS: tuple[str, ...] = (
    "receipt_version",
    "key_id",
    "audience",
    "license_id",
    "instance_id",
    "variant_id",
    "installation_hash",
    "issued_at",
    "expires_at",
)

# What separates the fields, and therefore what a value may never contain.
_FIELD_SEPARATOR = "\n"
_PAIR_SEPARATOR = "="

# A receipt issued slightly in the future is a clock that disagrees, not a
# forgery. Anything beyond this is refused rather than waited for.
CLOCK_SKEW = timedelta(minutes=5)

OK = "ok"
MALFORMED = "malformed"
UNSUPPORTED_VERSION = "unsupported_version"
UNKNOWN_KEY = "unknown_key"
WRONG_AUDIENCE = "wrong_audience"
BAD_SIGNATURE = "bad_signature"
WRONG_INSTALLATION = "wrong_installation"
NOT_YET_VALID = "not_yet_valid"
EXPIRED = "expired"
WRONG_VARIANT = "wrong_variant"
BAD_WINDOW = "bad_window"


@dataclass(frozen=True)
class Verdict:
    """Whether to believe a receipt, and if not, what is wrong with it."""

    ok: bool
    reason: str
    expires_at: datetime | None = None

    @property
    def is_expired(self) -> bool:
        """Worth refreshing rather than worth complaining about."""
        return self.reason == EXPIRED


class CanonicalError(ValueError):
    """A receipt that cannot be laid out as bytes at all."""


def canonical_bytes(receipt: Any) -> bytes:
    """The exact bytes a signature covers.

    Every signed field, in the fixed order above, as ``name=value`` lines. A
    value containing the separator is refused rather than escaped: escaping is
    a second thing for the signer to agree about, and the values here are ids,
    numbers and timestamps that have no business containing a newline.
    """
    if not isinstance(receipt, dict):
        raise CanonicalError("a receipt must be a mapping")
    lines = []
    for field in SIGNED_FIELDS:
        if field not in receipt:
            raise CanonicalError(f"missing field: {field}")
        value = str(receipt[field])
        if _FIELD_SEPARATOR in value:
            raise CanonicalError(f"field carries a separator: {field}")
        lines.append(f"{field}{_PAIR_SEPARATOR}{value}")
    return _FIELD_SEPARATOR.join(lines).encode("utf-8")


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    # A receipt without a zone is read as UTC rather than as local time: the
    # signer works in UTC, and guessing the reader's zone would move every
    # deadline by hours depending on where somebody happens to be.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _decode_signature(value: Any) -> bytes | None:
    import base64
    import binascii

    try:
        return base64.b64decode(str(value), validate=True)
    except (binascii.Error, TypeError, ValueError):
        return None


def verify(
    receipt: Any,
    *,
    public_keys: dict[str, bytes],
    installation_hash: str,
    now: datetime,
) -> Verdict:
    """Judge one receipt against one installation at one moment.

    ``public_keys`` maps a key id to its raw Ed25519 public key, so a key can be
    rotated by shipping a build that knows both and a server that signs with the
    newer one. An id nobody knows is refused: accepting the signature of an
    unknown key would make the id decorative.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(receipt, dict):
        return Verdict(False, MALFORMED)
    try:
        payload = canonical_bytes(receipt)
    except CanonicalError:
        return Verdict(False, MALFORMED)

    try:
        if int(receipt["receipt_version"]) != RECEIPT_VERSION:
            return Verdict(False, UNSUPPORTED_VERSION)
    except (TypeError, ValueError):
        return Verdict(False, MALFORMED)

    if str(receipt.get("audience", "")) != AUDIENCE:
        return Verdict(False, WRONG_AUDIENCE)

    key = public_keys.get(str(receipt.get("key_id", "")))
    if not key:
        return Verdict(False, UNKNOWN_KEY)

    signature = _decode_signature(receipt.get("signature"))
    if signature is None:
        return Verdict(False, MALFORMED)
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, payload)
    except (InvalidSignature, ValueError):
        return Verdict(False, BAD_SIGNATURE)

    # Everything below is checked only once the signature holds. A field from an
    # unverified receipt is whatever somebody typed, so acting on one — even to
    # refuse — would be reading an attacker's mind aloud.
    wanted = str(installation_hash or "").strip().lower()
    if not wanted or str(receipt.get("installation_hash", "")).strip().lower() != wanted:
        return Verdict(False, WRONG_INSTALLATION)

    if str(receipt.get("variant_id", "")).strip() != EXPECTED_VARIANT_ID:
        return Verdict(False, WRONG_VARIANT)

    issued_at = _parse_time(receipt.get("issued_at"))
    expires_at = _parse_time(receipt.get("expires_at"))
    if issued_at is None or expires_at is None:
        return Verdict(False, MALFORMED)
    # A window that runs backwards, or one longer than the server ever issues.
    # Both mean the thing that signed this was not behaving as designed, and a
    # good signature over a wrong statement is still a wrong statement.
    if expires_at <= issued_at or expires_at - issued_at > MAX_LIFETIME:
        return Verdict(False, BAD_WINDOW, expires_at)
    if issued_at - CLOCK_SKEW > now:
        return Verdict(False, NOT_YET_VALID, expires_at)
    if now >= expires_at:
        return Verdict(False, EXPIRED, expires_at)
    return Verdict(True, OK, expires_at)
