"""Handing a licence back, so it can be used on another computer.

An activation is bound to one installation. The name it was activated under is
built from an identifier kept in ``%APPDATA%\\LumaBLE``, so deleting that folder
does not free the slot — it destroys the only thing that could have said which
slot was ours. Lemon Squeezy goes on counting the machine as active, and nobody
can tell it otherwise.

Before 0.4.2 the binding was a stored timestamp and moving to a new computer
cost nothing. Now it costs a purchase unless the licence is handed back first,
which is why that has to be something a person can find and do, rather than
something they discover the need for afterwards.

Not a second way to deactivate: ``deactivate_license`` already talks to Lemon
Squeezy and already holds the rule everything rests on — it clears what is
stored here only once the server has confirmed, and on a failure it changes
nothing and says so. What lives here is the part around it, with no network and
no window in it: whether there is anything to hand back, what to show of the
key, and the order in which a success may be written down.
"""

from __future__ import annotations

from typing import Any

# How it ended, for a caller that has to say something to somebody.
FREED = "freed"
# The server did not confirm. Everything is exactly as it was, Pro included.
NOT_FREED = "not_freed"
# There was nothing bound here to begin with.
NOTHING_TO_TRANSFER = "nothing_to_transfer"


def can_transfer(settings: dict[str, Any] | Any) -> bool:
    """Whether there is an activation here that could be handed back.

    Both halves are needed: a key to name the licence and an instance to name
    the slot. Without them there is nothing Lemon Squeezy can be told, so
    offering the action would be offering something that cannot work.

    Deliberately narrower than ``has_licence``, which counts a lone receipt so
    that a lost identity file can be told from a fresh installation. A leftover
    receipt with no key behind it is not a slot anybody can release.
    """
    licence = settings.get("license", {}) if isinstance(settings, dict) else {}
    if not isinstance(licence, dict):
        return False
    key = str(licence.get("license_key", "")).strip()
    instance_id = str(licence.get("instance_id", "")).strip()
    return bool(key and instance_id)


def key_to_carry(settings: dict[str, Any] | Any) -> str:
    """The key, so it can be copied before it stops being on this machine.

    It is needed on the new computer, and a successful transfer removes it from
    here. Bought a year ago and buried in an email is exactly the sort of thing
    that is not to hand at the moment it is wanted.
    """
    licence = settings.get("license", {}) if isinstance(settings, dict) else {}
    if not isinstance(licence, dict):
        return ""
    return str(licence.get("license_key", "")).strip()


def masked_key(key: str) -> str:
    """The key, shown as little as it can be while still being recognisable.

    A licence key is a credential: it is what somebody types to claim a
    purchase. It has no business being legible on a screen that may be shared,
    recorded or photographed, and this is offered at a moment when people are
    quite often on a call with whoever is helping them.

    The last four characters stay, the way a card number does, so a person with
    two keys can tell which one this machine holds. The whole key is available,
    but only because somebody asked for it.
    """
    text = str(key or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        # Too short to show any of: four characters of a four-character secret
        # is the secret.
        return "•" * len(text)
    return "•" * (len(text) - 4) + text[-4:]


def transfer(settings: dict[str, Any], deactivate, save) -> tuple[str, str]:
    """Hand the licence back, and say how it went along with the key to carry.

    ``deactivate`` and ``save`` are passed in so every path — including the one
    that only happens while a service is down — can be written as a case rather
    than reproduced by unplugging something.

    The key is read *before* anything is released, because a success removes it,
    and it is returned either way: somebody whose transfer failed still wants it
    in front of them, and somebody whose transfer worked needs it on the other
    machine.

    Saving happens only after the server has confirmed. Writing a cleared
    licence out on a request that never arrived would leave a person with no Pro
    and nothing left to name the slot they had lost.
    """
    if not can_transfer(settings):
        return NOTHING_TO_TRANSFER, key_to_carry(settings)

    carried = key_to_carry(settings)
    if not deactivate(settings):
        # Nothing was cleared, so there is nothing to write down and nothing to
        # undo. The licence is still here, and so is Pro.
        return NOT_FREED, carried

    save(settings)
    return FREED, carried
