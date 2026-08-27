"""Make a signing key pair, once.

The private half is written to a folder outside this repository and is never
printed, never committed and never sent anywhere. The public half is printed,
because a public key checks a signature and cannot produce one, and it has to
be pasted into app/license_keys.py to be of any use.

Run it again and it refuses rather than overwrites. Replacing a live signing
key is a deliberate act with a build behind it, not something a stray command
should be able to do by accident.

    python worker/generate_key.py

Afterwards:

  1. Back the private key up somewhere safe. Losing it means no new receipts
     can be issued, which is repaired only by shipping a build carrying a new
     public key.
  2. `wrangler secret put SIGNING_KEY` and paste the contents of the private
     file, or paste it into the Worker settings page. Cloudflare keeps it
     write-only from then on.
  3. Put the printed public key into app/license_keys.py under its key_id.
"""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY_ID = "k1"


def key_folder() -> Path:
    """Outside the repository on purpose.

    A private key inside a working tree is one `git add -A` away from being
    public, and the whole arrangement rests on this half staying secret.
    """
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "LumaBLE-signing-key"


def main() -> int:
    folder = key_folder()
    private_path = folder / f"{KEY_ID}-private-pkcs8.b64"
    public_path = folder / f"{KEY_ID}-public.b64"

    if private_path.exists():
        print(f"A key is already here: {private_path}")
        print("Refusing to overwrite it. Delete it deliberately if you mean to replace it.")
        return 1

    private = Ed25519PrivateKey.generate()
    der = private.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    folder.mkdir(parents=True, exist_ok=True)
    # Written before anything is printed, so a failure to save cannot leave
    # somebody holding a public key whose private half no longer exists.
    private_path.write_text(base64.b64encode(der).decode("ascii") + "\n", encoding="ascii")
    public_path.write_text(base64.b64encode(raw_public).decode("ascii") + "\n", encoding="ascii")
    os.chmod(private_path, 0o600)

    print(f"key_id: {KEY_ID}")
    print(f"public key (paste into app/license_keys.py):\n    {base64.b64encode(raw_public).decode('ascii')}")
    print()
    print(f"private key written to: {private_path}")
    print("It has not been printed and must not be. Back it up, then set it as the")
    print("Cloudflare secret SIGNING_KEY.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
