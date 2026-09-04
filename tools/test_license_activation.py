#!/usr/bin/env python3
"""Activate a real licence key on this machine, by hand.

For checking that the whole chain works against the live service: a key, this
installation's identity, the signing Worker, and a receipt this build will
verify. Nothing automated goes near it — it wants a real key and it writes to
the real settings file, which is exactly why it is a tool and not a test.

Activation alone stopped being enough in 0.4.2. A key buys an instance, and Pro
comes from a signed receipt about that instance, so this asks for one and says
which step failed when one does. The key is read with getpass and never
printed, logged, or written anywhere but where the application already keeps
it.

    python tools/test_license_activation.py
"""

from __future__ import annotations

import getpass
from datetime import UTC, datetime

from app.feature_gate import ISSUED, invalidate_pro_cache, is_pro, obtain_receipt
from app.install_identity import IDENTITY_LOST, load_identity
from app.license import activate_license_key, has_licence
from app.license_keys import public_keys
from app.storage import load_settings, save_settings

# What each answer from the service means for somebody standing at a terminal
# wondering what to do next.
_ADVICE = {
    "no_licence": "Nothing was stored to ask about - activation did not save a key.",
    "invalid": "The service reached Lemon Squeezy and was told this key is not valid.",
    "revoked": "The service reached Lemon Squeezy and was told this key is disabled.",
    "instance_mismatch": (
        "The activation on record belongs to another installation. Deactivate it "
        "first, or use a key that is free."
    ),
    "rate_limited": "Too many requests just now. Wait a minute and run this again.",
    "unavailable": (
        "The service could not answer. Nothing was changed - try again when it is back."
    ),
}


def main() -> int:
    if not public_keys():
        print("No public keys are built in, so no receipt could be verified.")
        print("Pro is off for everybody in this build. Nothing to test.")
        return 2

    settings = load_settings()
    outcome = load_identity(has_licence=has_licence(settings))
    if outcome.identity is None:
        why = (
            "the identity file could not be read"
            if outcome.state == IDENTITY_LOST
            else "this installation has no identity"
        )
        print(f"Cannot ask for anything: {why}.")
        return 2
    identity = outcome.identity

    key = getpass.getpass("Lemon Squeezy license key: ").strip()
    if not key:
        print("No key entered.")
        return 2

    if not activate_license_key(key, settings, installation_hash=identity.installation_hash):
        print("Activation failed. Check the key, the product variant, and test vs live mode.")
        return 1

    # Saved before the receipt is asked for, the same order the application
    # uses: an activation that succeeded is a slot spent, and losing the record
    # of it would mean spending another one on the next attempt.
    save_settings(settings)
    print("Activated. Asking the signing service for a receipt...")

    result = obtain_receipt(settings, identity, now=datetime.now(UTC))
    if result != ISSUED:
        print(f"No receipt: {result}")
        print(_ADVICE.get(result, "Unrecognised answer from the service."))
        print("The activation is kept, so running this again resumes rather than reactivates.")
        return 1

    invalidate_pro_cache()
    print("Receipt stored and verified. A normal launch should show Pro.")
    print(f"Pro now: {is_pro()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
