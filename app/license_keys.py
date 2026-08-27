"""The public halves of the signing keys this build trusts.

Public on purpose and harmless to read: a public key checks a signature and
cannot produce one. The private halves live in the signing service and nowhere
else, which is what makes a receipt worth anything in an application whose
source anybody can open.

Keyed by the `key_id` a receipt names, so a key can be rotated without a flag
day: ship a build that knows both, start signing with the newer one, and drop
the older from a later build once no receipt can still be carrying it.

There is no fallback if a receipt cannot be verified, and there must never be
one: a build that trusts something else when a signature does not check out is
a build where the something else is the real check and the signature is
decoration. An empty mapping here means Pro is off for everybody, which is the
correct behaviour rather than a state to be worked around.

Running from source, `LUMABLE_FORCE_PRO=1` still works and is the intended way
to develop against Pro features. It is disabled in a frozen build.
"""

from __future__ import annotations

import base64

# key_id -> the raw 32-byte Ed25519 public key, base64 for legibility.
_ENCODED: dict[str, str] = {
    # Generated 26 August 2026 by worker/generate_key.py. Its private half was
    # written outside this repository, set as the Cloudflare secret
    # SIGNING_KEY, and has never been anywhere else.
    "k1": "/TYQaWKYb9rLACYUSnhmLrD9AuDS9Sl9/egnST1KNmw=",
}


def public_keys() -> dict[str, bytes]:
    """The keys a receipt may be signed with. Empty until one is deployed."""
    keys: dict[str, bytes] = {}
    for key_id, encoded in _ENCODED.items():
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
        # A key of the wrong size is a typo in this file rather than something
        # to hand to a verifier and hope about.
        if len(raw) == 32:
            keys[str(key_id)] = raw
    return keys
