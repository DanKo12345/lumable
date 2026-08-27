"""Who this installation is, kept where a copied settings file cannot carry it.

A signed receipt is issued for one installation. That only means anything if
the installation can be told apart from a copy of itself: an identifier sitting
in ``settings.json`` beside the receipt would travel with it, and the binding
would be decoration. So the identifier lives in its own file, encrypted with
DPAPI — Windows ties the ciphertext to the user account, and the same bytes on
another machine simply do not decrypt.

Two things live here, and only two. The identifier itself, which is random and
says nothing about the machine: no host name, no serial numbers, no hardware
fingerprint. And the latest time this installation has seen, which makes
winding the clock back harder — *harder*, not impossible, and it is called
best effort throughout because restoring an older copy of this file walks past
it. It is a speed bump on the cheapest trick, not a lock.

The one thing this module refuses to do is guess. A file that is missing on a
fresh installation is a new identity. The same file missing next to a licence
that was working yesterday is a *loss* — the machine cannot prove who it is any
more — and quietly issuing a new identity there would spend a second activation
slot without anybody being asked.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The shape of the stored blob. Present from the first version so a later shape
# can arrive without this one guessing at it.
FORMAT_VERSION = 1

_FILE_NAME = "installation.dat"

# DPAPI may put a window on the screen. This application runs schedules and
# automations with nobody watching, and a prompt raised there would wait for a
# click that is never coming — a hang, not a refusal. Forbidding the interface
# turns that into an ordinary failure this module already knows how to report.
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

# What load_identity found.
NEW = "new"
LOADED = "loaded"
IDENTITY_LOST = "identity_lost"


@dataclass(frozen=True)
class Identity:
    """This installation, as far as it can prove."""

    installation_id: str = ""
    # The latest moment this installation has seen. Best effort against a clock
    # wound backwards; see the module docstring.
    highest_seen: datetime | None = None

    @property
    def installation_hash(self) -> str:
        return identity_hash(self.installation_id)


@dataclass(frozen=True)
class Outcome:
    """What was found, and what it means for what happens next."""

    state: str
    identity: Identity | None = None

    @property
    def is_lost(self) -> bool:
        """The machine had a licence and can no longer prove who it is.

        Not a thing to fix quietly: recovering costs an activation, so it is a
        question for the person rather than a decision for the program.
        """
        return self.state == IDENTITY_LOST


def new_installation_id() -> str:
    """A fresh identity: random, and about nothing.

    Deliberately not derived from the host name, a disk serial or anything else
    about the machine. Those are stable across reinstalls, which sounds useful
    until it means a licence file that follows somebody's hardware around, and
    they are somebody's data, which this does not need.
    """
    return secrets.token_bytes(32).hex()


def identity_hash(installation_id: Any) -> str:
    """What the server is told, and what a receipt is bound to.

    A hash rather than the identifier itself: the server never needs the value,
    only a stable name for it, and the shorter base64url form keeps the licence
    instance name it goes into to a sensible length.
    """
    text = str(installation_id or "").strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def identity_path() -> Path:
    """Where the blob lives, resolved now rather than at import.

    A module-level constant would be computed once, at whatever the data
    directory was when this module happened to be imported first — which in a
    test, or in a child process, is not the directory that was arranged for it.
    Resolving on each call is what keeps every writer inside LUMABLE_DATA_DIR.
    """
    from app import storage

    return Path(storage.DATA_DIR) / _FILE_NAME


# ── the Windows half ──────────────────────────────────────────────────
def _dpapi_call(function_name: str, payload: bytes, flags: int) -> bytes | None:
    """Run one DPAPI call, or answer None. Never raises.

    Wrapped rather than allowed to propagate because both directions have an
    ordinary failure: encrypting can fail on a machine in a strange state, and
    decrypting fails whenever the blob belongs to somebody else — which is
    exactly what it is for. Callers decide what a failure means; this only
    reports one.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buffer = ctypes.create_string_buffer(payload, len(payload))
        source = _Blob(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        result = _Blob()
        function = getattr(crypt32, function_name)
        ok = function(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(result),
        )
        if not ok:
            return None
        try:
            return ctypes.string_at(result.pbData, result.cbData)
        finally:
            kernel32.LocalFree(result.pbData)
    except Exception:
        return None


def protect(payload: bytes) -> bytes | None:
    return _dpapi_call("CryptProtectData", payload, _CRYPTPROTECT_UI_FORBIDDEN)


def unprotect(payload: bytes) -> bytes | None:
    return _dpapi_call("CryptUnprotectData", payload, _CRYPTPROTECT_UI_FORBIDDEN)


# ── what is in the blob ───────────────────────────────────────────────
def encode(identity: Identity) -> bytes:
    body = {
        "format_version": FORMAT_VERSION,
        "installation_id": identity.installation_id,
        "highest_seen": identity.highest_seen.isoformat() if identity.highest_seen else "",
    }
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def decode(payload: bytes) -> Identity | None:
    """The identity in a decrypted blob, or None if it is not one.

    A blob this build does not understand is refused rather than partly read:
    an identifier taken out of a shape whose meaning has changed is a plausible
    wrong answer, which is worse here than no answer.
    """
    try:
        body = json.loads(bytes(payload).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or body.get("format_version") != FORMAT_VERSION:
        return None
    installation_id = str(body.get("installation_id", "")).strip()
    if not installation_id:
        return None
    seen = None
    raw_seen = str(body.get("highest_seen", "")).strip()
    if raw_seen:
        try:
            parsed = datetime.fromisoformat(raw_seen)
            seen = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            seen = None
    return Identity(installation_id=installation_id, highest_seen=seen)


# ── reading and writing ───────────────────────────────────────────────
def save_identity(identity: Identity) -> bool:
    """Write the blob, or leave whatever was there untouched.

    Atomic on purpose, and in that order: a half-written identity is a machine
    that cannot prove who it is, which costs an activation to repair. Encrypting
    first means a refusal from DPAPI ends the attempt before the old file has
    been touched at all.
    """
    payload = protect(encode(identity))
    if payload is None:
        return False
    path = identity_path()
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_identity(*, has_licence: bool) -> Outcome:
    """Who this installation is, or why it cannot say.

    ``has_licence`` is the question that decides what a missing file means, and
    it is asked of the caller because this module has no business reading
    settings. It is true whenever there is anything to lose::

        has_licence = bool(license_key or instance_id or receipt)

    A receipt on its own counts. It was issued for an installation, so its
    presence is proof that this one was not fresh — whatever else is missing.

    Nothing here is fixed automatically: an identity that was there yesterday
    and is gone today costs an activation slot to replace, and spending one
    without asking is exactly the surprise this avoids.
    """
    path = identity_path()
    try:
        stored = path.read_bytes()
    except FileNotFoundError:
        # Genuinely absent, which is the only reading that may lead to a new
        # identity.
        stored = b""
    except OSError:
        # A refused permission or a failing disk. The file may well be there
        # and readable tomorrow, so calling this a fresh installation would
        # spend an activation slot on a problem that was going to pass.
        return Outcome(IDENTITY_LOST)
    if stored:
        decrypted = unprotect(stored)
        identity = decode(decrypted) if decrypted is not None else None
        if identity is not None:
            return Outcome(LOADED, identity)
        # Unreadable: another user's blob, a corrupted file, a shape from a
        # newer build. The file is left exactly where it is — overwriting it
        # would destroy the one copy of an identity that may still be readable
        # by whoever it belongs to.
        return Outcome(IDENTITY_LOST) if has_licence else Outcome(NEW, Identity(new_installation_id()))
    if has_licence:
        return Outcome(IDENTITY_LOST)
    return Outcome(NEW, Identity(new_installation_id()))


def advance_high_water(identity: Identity, now: datetime) -> Identity:
    """Move the latest-seen time forward, never back.

    Best effort, and named that way everywhere: somebody who restores an older
    copy of the blob restores an older mark with it. What it stops is the
    cheapest version — winding the clock back while the file stays where it is.
    """
    if identity.highest_seen is not None and now <= identity.highest_seen:
        return identity
    return Identity(installation_id=identity.installation_id, highest_seen=now)
