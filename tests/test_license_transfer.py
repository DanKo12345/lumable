"""Handing a licence back so it can be used on another computer.

The rule underneath all of it: nothing stored locally may be cleared before the
server has confirmed. The stored key and instance are the only evidence of which
slot is ours, so clearing them on a request that never arrived leaves somebody
with no Pro and nothing left to name the slot they lost.

The cases that matter are the ones nobody can walk through by hand — a service
that is down at the moment the button is pressed, an instance that was revoked
while the machine was offline — which is why the network and the file are passed
in rather than reached for.
"""

from __future__ import annotations

from app.license_transfer import (
    FREED,
    NOT_FREED,
    NOTHING_TO_TRANSFER,
    can_transfer,
    key_to_carry,
    masked_key,
    transfer,
)


def _active() -> dict:
    return {"license": {"license_key": "LS-1234-ABCD", "instance_id": "inst-1", "receipt": {"a": 1}}}


class _Server:
    """A deactivation that answers as told and clears only when it succeeded,
    which is what the real one does."""

    def __init__(self, answer: bool) -> None:
        self._answer = answer
        self.calls = 0

    def __call__(self, settings) -> bool:
        self.calls += 1
        if self._answer:
            settings["license"] = {"license_key": "", "instance_id": "", "receipt": None}
        return self._answer


class _Save:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _settings) -> None:
        self.calls += 1


# ── is there anything to transfer ─────────────────────────────────────
def test_an_activated_machine_can_transfer() -> None:
    assert can_transfer(_active()) is True


def test_a_machine_with_half_an_activation_cannot() -> None:
    """Both halves are needed: a key to name the licence, an instance to name
    the slot. Offering the action without them offers something that cannot
    work."""
    for settings in (
        {},
        {"license": {}},
        {"license": {"license_key": "LS-KEY"}},
        {"license": {"instance_id": "inst-1"}},
        {"license": {"license_key": "   ", "instance_id": "inst-1"}},
        {"license": "rubbish"},
        "rubbish",
    ):
        assert can_transfer(settings) is False, settings


def test_a_lone_receipt_is_not_something_that_can_be_handed_back() -> None:
    """``has_licence`` counts one, on purpose, so a lost identity file can be
    told from a fresh installation. It is still not a slot anybody can
    release."""
    assert can_transfer({"license": {"receipt": {"a": 1}}}) is False


# ── the transfer ──────────────────────────────────────────────────────
def test_a_confirmed_transfer_is_written_down() -> None:
    server, save = _Server(True), _Save()

    outcome, key = transfer(_active(), server, save)

    assert outcome == FREED
    assert key == "LS-1234-ABCD"
    assert server.calls == 1
    assert save.calls == 1


def test_a_transfer_the_server_did_not_confirm_writes_nothing(
) -> None:
    """The rule the whole thing rests on, at the point where it would be broken.
    A service that cannot answer must never be able to cost somebody a
    licence."""
    settings = _active()
    before = {k: dict(v) if isinstance(v, dict) else v for k, v in settings.items()}
    server, save = _Server(False), _Save()

    outcome, key = transfer(settings, server, save)

    assert outcome == NOT_FREED
    assert save.calls == 0, "a failure was written down"
    assert settings == before, "a failure changed the stored licence"
    assert key == "LS-1234-ABCD", "the key vanished from a transfer that did not happen"


def test_the_key_is_read_before_anything_is_released() -> None:
    """A success removes it, so reading it afterwards would return nothing —
    and the whole point of the moment is to carry it to the other machine."""
    server, save = _Server(True), _Save()
    settings = _active()

    _outcome, key = transfer(settings, server, save)

    assert key == "LS-1234-ABCD"
    assert settings["license"]["license_key"] == "", "the stand-in did not clear, so this proves less"


def test_nothing_to_transfer_asks_nobody_anything() -> None:
    server, save = _Server(True), _Save()

    outcome, _key = transfer({}, server, save)

    assert outcome == NOTHING_TO_TRANSFER
    assert server.calls == 0, "an empty machine reached the network"
    assert save.calls == 0


def test_the_three_outcomes_are_distinct() -> None:
    """A caller has to say three different things to somebody, and collapsing
    any two would say the wrong one."""
    assert len({FREED, NOT_FREED, NOTHING_TO_TRANSFER}) == 3


# ── what is shown of the key ──────────────────────────────────────────
def test_the_key_is_masked_to_its_last_four() -> None:
    """Offered at a moment when a screen is quite often being shared with
    whoever is helping."""
    assert masked_key("LS-1234-ABCD") == "••••••••ABCD"
    assert "LS-1234" not in masked_key("LS-1234-ABCD")


def test_the_last_four_are_kept_so_two_keys_can_be_told_apart() -> None:
    assert masked_key("AAAA-AAAA-1111")[-4:] == "1111"
    assert masked_key("AAAA-AAAA-2222")[-4:] == "2222"


def test_a_key_too_short_to_mask_is_not_shown_at_all() -> None:
    """Four characters of a four-character secret is the secret."""
    assert masked_key("ABCD") == "••••"
    assert masked_key("AB") == "••"


def test_masking_survives_nothing_and_rubbish() -> None:
    assert masked_key("") == ""
    assert masked_key("   ") == ""
    assert masked_key(None) == ""


def test_key_to_carry_survives_rubbish() -> None:
    assert key_to_carry({}) == ""
    assert key_to_carry({"license": "rubbish"}) == ""
    assert key_to_carry("rubbish") == ""
    assert key_to_carry({"license": {"license_key": "  LS-KEY  "}}) == "LS-KEY"


def test_the_module_needs_neither_qt_nor_the_network() -> None:
    """It is the part every case above is written against, and either one in it
    would make those cases need a screen or a connection."""
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "app" / "license_transfer.py").read_text(
        encoding="utf-8"
    )

    assert "PySide6" not in source
    assert "urllib" not in source
    assert "import requests" not in source
