"""What to tell somebody about their Pro licence, decided in one place.

Several windows can find themselves explaining the same situation — the licence
panel, a feature that refused to open, a line in the log — and left to
themselves they explain it differently, or explain the same thing twice in
words that disagree. So none of them decides anything. They are handed a state
and they show it.

Two rules about what may be said.

Nothing internal is ever named. Not receipts, not instances, not signatures, not
the signing service, not which check failed. A person who bought a licence is
owed a sentence about their licence and what to do next, and every one of those
words invites a support conversation about machinery they did not buy.

And nothing is guessed ahead of the answer. There is no "you appear to be
offline" before a request has actually failed: the state while asking is
*asking*, and a specific complaint only exists once something specific went
wrong. Guessing produces the worst kind of wrong message — one that names a
cause the person then tries to fix, when their connection was fine all along.

The trickiest case is the one nobody sees. A service that cannot be reached
while a licence is still good must change nothing at all: no banner, no flicker,
no reassurance. Pro simply goes on working, and the detail belongs in the log
for whoever is diagnosing it later. Anything else teaches people that a working
licence sometimes looks broken, which is how they learn to ignore the message
that matters.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── the states ────────────────────────────────────────────────────────
# Pro holds. Nothing is shown, including when the last attempt to check failed:
# what is on screen should describe the licence, not the weather.
PRO = "pro"

# No licence here, and none expected. Not a problem to report.
FREE = "free"

# A request is out. What is known is that nothing is known yet.
CHECKING = "checking"

# Activated, never confirmed. One connection finishes what activation started.
NEEDS_FIRST_CHECK = "needs_first_check"

# It was confirmed once, and that confirmation has run out.
OFFLINE_PERIOD_ENDED = "offline_period_ended"

# The clock reads earlier than a moment this installation has already seen.
# Kept apart from every other state because the fix is different: connecting
# will not help while the date is wrong, and saying it would send somebody to
# check a connection that was never the problem.
CLOCK_WRONG = "clock_wrong"

# The service was reached and said no. The only state that ends a licence.
ENDED = "ended"

# What the outcome of a refresh has to be for a licence to be over. Anything
# else — a service that is down, a rate limit, a reply that will not parse —
# leaves everything as it was, which is the whole point of the distinction.
_ENDING_OUTCOMES = frozenset({"invalid", "revoked"})

_MESSAGES = {
    PRO: "",
    FREE: "",
    CHECKING: "license_status.checking",
    NEEDS_FIRST_CHECK: "license_status.needs_first_check",
    OFFLINE_PERIOD_ENDED: "license_status.offline_period_ended",
    CLOCK_WRONG: "license_status.clock_wrong",
    ENDED: "license_status.ended",
}

# States a person can do something about by asking again. Not ENDED: asking
# again about a licence the service has refused only produces the same refusal,
# and offering the button would suggest otherwise.
_RECHECKABLE = frozenset({NEEDS_FIRST_CHECK, OFFLINE_PERIOD_ENDED, CLOCK_WRONG})


@dataclass(frozen=True)
class Facts:
    """Everything the answer depends on, and nothing else.

    Gathered by a caller that may read files and clocks. Kept out of here so
    that every case below is a case somebody can write down, including the ones
    that need a service to be down at a particular moment.
    """

    has_licence: bool = False
    pro: bool = False
    clock_went_back: bool = False
    has_receipt: bool = False
    checking: bool = False
    last_outcome: str = ""


@dataclass(frozen=True)
class Status:
    """What to show. Not who gets Pro — that is feature_gate's answer, and this
    only explains it. A field here claiming otherwise was read by nothing and
    was set for a wrong clock and an expired confirmation, neither of which
    revokes or clears anything."""

    state: str
    message: str
    can_recheck: bool


def status(facts: Facts) -> Status:
    """The one decision. Order matters, and each step says why it is where it is."""
    if facts.checking:
        # Before anything else. While a request is out, the honest answer is
        # that it is out — not a guess about what it will come back with.
        return _made(CHECKING)

    if facts.pro:
        # Ahead of everything except the question of whether an answer has
        # arrived. A working licence says nothing — including when the last
        # attempt to reach the service failed, and including when the service
        # refused some *earlier* licence. Asking about endings first meant a
        # revocation outlived the activation that replaced it: somebody who
        # bought a second key was told Pro had ended while Pro was running.
        return _made(PRO)

    if facts.has_licence and facts.clock_went_back:
        # Ahead of the receipt questions, since every one of them is about
        # dates and the dates cannot be trusted.
        return _made(CLOCK_WRONG)

    if facts.last_outcome in _ENDING_OUTCOMES:
        # Ahead of the licence being gone, because ending it is what clears it:
        # by the time this is asked the key has already been removed, and
        # without this the person would simply find themselves on Free with no
        # idea why.
        return _made(ENDED)

    if not facts.has_licence:
        return _made(FREE)

    if not facts.has_receipt:
        return _made(NEEDS_FIRST_CHECK)

    return _made(OFFLINE_PERIOD_ENDED)


def _made(state: str) -> Status:
    return Status(
        state=state,
        message=_MESSAGES[state],
        can_recheck=state in _RECHECKABLE,
    )
