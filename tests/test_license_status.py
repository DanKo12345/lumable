"""What a person is told about their licence, and what they are never told.

The case worth staring at is the one that must produce nothing: a service that
could not be reached while the licence is still good. No banner, no flicker, no
reassurance — Pro simply goes on working. Anything else teaches people that a
working licence sometimes looks broken, which is how they learn to ignore the
message that matters.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.license_status import (
    CHECKING,
    CLOCK_WRONG,
    ENDED,
    FREE,
    NEEDS_FIRST_CHECK,
    OFFLINE_PERIOD_ENDED,
    PRO,
    Facts,
    status,
)

ROOT = Path(__file__).resolve().parent.parent
_STATES = (PRO, FREE, CHECKING, NEEDS_FIRST_CHECK, OFFLINE_PERIOD_ENDED, CLOCK_WRONG, ENDED)


def _working() -> Facts:
    return Facts(has_licence=True, pro=True, has_receipt=True)


# ── the quiet ones ────────────────────────────────────────────────────
def test_a_working_licence_says_nothing() -> None:
    answer = status(_working())

    assert answer.state == PRO
    assert answer.message == ""
    assert answer.can_recheck is False


def test_a_machine_that_never_had_a_licence_is_not_a_problem_to_report() -> None:
    answer = status(Facts())

    assert answer.state == FREE
    assert answer.message == ""


# ── the one that must not show ────────────────────────────────────────
def test_a_service_that_could_not_be_reached_changes_nothing_while_pro_holds() -> None:
    """The whole reason a fortnight of offline life exists. Somebody on a train
    must not be shown a warning about their purchase.

    Every outcome that is not a statement about the licence is checked, because
    the temptation is to treat "something went wrong" as one kind of thing.
    """
    for outcome in ("unavailable", "rate_limited", "instance_mismatch", "", "something_new"):
        answer = status(Facts(has_licence=True, pro=True, has_receipt=True, last_outcome=outcome))

        assert answer.state == PRO, outcome
        assert answer.message == "", f"{outcome} put something on screen"


def test_only_the_service_saying_no_ends_a_licence() -> None:
    """Two outcomes out of all of them. A service that cannot answer must never
    be able to cancel a purchase."""
    ending = [
        outcome
        for outcome in (
            "invalid",
            "revoked",
            "unavailable",
            "rate_limited",
            "instance_mismatch",
            "issued",
            "",
        )
        if status(Facts(last_outcome=outcome)).state == ENDED
    ]

    assert ending == ["invalid", "revoked"]


# ── the ones with something to say ────────────────────────────────────
def test_an_activation_that_was_never_confirmed_asks_for_one_connection() -> None:
    answer = status(Facts(has_licence=True, pro=False, has_receipt=False))

    assert answer.state == NEEDS_FIRST_CHECK
    assert answer.can_recheck is True


def test_a_confirmation_that_has_run_out_says_so() -> None:
    """Told apart from never having been confirmed, because the two call for
    the same action but mean different things to somebody reading it."""
    answer = status(Facts(has_licence=True, pro=False, has_receipt=True))

    assert answer.state == OFFLINE_PERIOD_ENDED
    assert answer.can_recheck is True


def test_a_wound_back_clock_is_its_own_message() -> None:
    """The fix is different. Connecting does not help while the date is wrong,
    and saying it would send somebody to check a connection that was never the
    problem."""
    answer = status(Facts(has_licence=True, pro=False, clock_went_back=True, has_receipt=True))

    assert answer.state == CLOCK_WRONG
    assert answer.can_recheck is True


def test_the_clock_is_answered_before_anything_that_depends_on_dates() -> None:
    """Every other question here is about when something expires, and none of
    them can be trusted while the clock cannot."""
    for has_receipt in (True, False):
        answer = status(
            Facts(has_licence=True, pro=False, clock_went_back=True, has_receipt=has_receipt)
        )

        assert answer.state == CLOCK_WRONG, has_receipt


def test_a_wrong_clock_on_a_machine_with_no_licence_says_nothing() -> None:
    """There is nothing at stake, so there is nothing to warn about."""
    assert status(Facts(clock_went_back=True)).state == FREE


def test_a_revoked_licence_is_explained_rather_than_silently_becoming_free() -> None:
    """Ending a licence is what clears it, so by the time this is asked the key
    has already gone. Without answering ahead of that, somebody would find
    themselves on Free with no idea why."""
    answer = status(Facts(has_licence=False, pro=False, last_outcome="revoked"))

    assert answer.state == ENDED
    assert answer.can_recheck is False, "asking again only produces the same refusal"


# ── while asking ──────────────────────────────────────────────────────
def test_nothing_is_guessed_before_the_answer_arrives() -> None:
    """No "you appear to be offline" before a request has actually failed. A
    guess produces the worst kind of wrong message: one that names a cause the
    person goes off and tries to fix."""
    for facts in (
        Facts(checking=True),
        Facts(has_licence=True, checking=True),
        Facts(has_licence=True, pro=False, has_receipt=True, checking=True),
        Facts(has_licence=True, clock_went_back=True, checking=True),
        Facts(has_licence=True, last_outcome="revoked", checking=True),
    ):
        assert status(facts).state == CHECKING, facts


def test_checking_is_not_something_to_press_again() -> None:
    assert status(Facts(has_licence=True, checking=True)).can_recheck is False


# ── what the states are ───────────────────────────────────────────────
def test_every_state_has_an_answer_and_they_are_distinct() -> None:
    assert len(set(_STATES)) == len(_STATES)

    for state in _STATES:
        assert any(status(facts).state == state for facts in _every_case()), state


def _every_case():
    from itertools import product

    for licence, pro, clock, receipt, checking, outcome in product(
        (True, False), (True, False), (True, False), (True, False), (True, False),
        ("", "issued", "invalid", "revoked", "unavailable"),
    ):
        yield Facts(licence, pro, clock, receipt, checking, outcome)


def test_anything_other_than_working_or_free_has_something_to_say() -> None:
    """Every case, checked for the contradiction: a state that exists to explain
    something, explaining nothing.

    This used to be asked of an ``ends_pro`` field, which nothing read and which
    claimed a wrong clock revoked a licence. Whether Pro holds is feature_gate's
    answer; a status only explains it.
    """
    for facts in _every_case():
        answer = status(facts)

        if answer.state in (PRO, FREE):
            assert answer.message == "", f"{answer.state} said something"
        else:
            assert answer.message, f"{answer.state} explains nothing"


def test_a_working_licence_is_never_described_as_over() -> None:
    """The bug this ordering was rewritten for: a refusal about an earlier key
    outliving the activation that replaced it."""
    for outcome in ("revoked", "invalid"):
        answer = status(Facts(has_licence=True, pro=True, has_receipt=True, last_outcome=outcome))

        assert answer.state == PRO, outcome


def test_nothing_offers_a_button_it_cannot_honour() -> None:
    for facts in _every_case():
        answer = status(facts)

        if answer.can_recheck:
            assert answer.state != PRO
            assert answer.state != FREE
            assert answer.state != ENDED


# ── the words ─────────────────────────────────────────────────────────
def test_no_message_names_anything_internal() -> None:
    """A person who bought a licence is owed a sentence about their licence.
    Receipts, instances, signatures and the signing service are machinery they
    did not buy, and naming any of it invites a support conversation about it.
    """
    forbidden = {
        "ru": ("квитанц", "инстанс", "подпис", "worker", "воркер", "токен", "ключ подтвержд"),
        "en": ("receipt", "instance", "signature", "worker", "token", "payload"),
        "es": ("recibo", "instancia", "firma", "worker", "token"),
        "zh": ("收据", "签名", "实例", "worker", "令牌"),
    }
    for locale, words in forbidden.items():
        bundle = json.loads((ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        for key, text in bundle["translations"].items():
            if not key.startswith("license_status."):
                continue
            lowered = str(text).lower()
            for word in words:
                # Anchored to the start of a word, not any substring: the
                # Spanish for "confirm" contains the Spanish for "signature",
                # and a plain substring search fails on a perfectly good
                # sentence. Chinese has no such boundaries, so it stays a
                # substring search there.
                found = (
                    word in lowered
                    if locale == "zh"
                    else re.search(rf"(?<!\w){re.escape(word)}", lowered) is not None
                )
                assert not found, f"{locale} {key} says {word!r}"


def test_every_message_exists_in_every_language() -> None:
    wanted = {message for message in (status(f).message for f in _every_case()) if message}

    for locale in ("ru", "en", "es", "zh"):
        bundle = json.loads((ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        missing = wanted - set(bundle["translations"])
        assert not missing, f"{locale} is missing {sorted(missing)}"


def test_no_message_is_too_long_to_sit_in_a_panel() -> None:
    """These appear in a narrow strip above the licence controls. A paragraph
    there either wraps into the buttons or gets cut off mid-sentence, and a
    warning nobody can read is not a warning."""
    for locale in ("ru", "en", "es", "zh"):
        bundle = json.loads((ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        for key, text in bundle["translations"].items():
            if key.startswith("license_status."):
                assert len(str(text)) <= 120, f"{locale} {key} is {len(str(text))} characters"


def test_the_clock_message_does_not_promise_that_connecting_will_help() -> None:
    """It will not. A fresh confirmation is judged against the same wrong date,
    so the refusal simply happens again — and somebody sent to check their
    connection would be looking in the wrong place."""
    for locale, connection_words in (
        ("ru", ("интернет", "подключ", "сет")),
        ("en", ("internet", "connect", "network")),
        ("es", ("internet", "conex", "red")),
        ("zh", ("互联网", "联网", "网络")),
    ):
        bundle = json.loads((ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        text = str(bundle["translations"]["license_status.clock_wrong"]).lower()

        for word in connection_words:
            assert word not in text, f"{locale} clock message mentions {word!r}"


def test_the_module_is_pure() -> None:
    """It is the part every case above is written against."""
    source = (ROOT / "app" / "license_status.py").read_text(encoding="utf-8")

    for reached_for in ("PySide6", "urllib", "open(", "load_settings", "datetime"):
        assert reached_for not in source, f"the decision reaches for {reached_for}"
