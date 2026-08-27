"""A window left open, and a key that is not the one already here.

Two gaps that only appear over time or over a second attempt, which is why
neither showed up in the tests written alongside the code. An application
running for a fortnight kept a cached yes long after the receipt behind it had
expired, and a second key typed into a machine that already had one was ignored
in favour of the first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app import feature_gate
from app.license_refresh import LicenseRefresher
from app.overlay_controller import ACTIVATE, RESUME, WRONG_KEY, activation_plan


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ── a window that stays open ──────────────────────────────────────────
def test_the_refresher_keeps_asking_rather_than_asking_once(app) -> None:
    """The gap: it was called a second after starting and never again.

    So a licence revoked on Tuesday stayed Pro until somebody happened to
    restart, and a receipt's fortnight could pass with the answer cached from
    before it began.
    """
    refresher = LicenseRefresher()
    asked: list[int] = []
    refresher.refresh = lambda: asked.append(1)  # type: ignore[method-assign]
    refresher._timer.timeout.disconnect()
    refresher._timer.timeout.connect(refresher.refresh)

    try:
        refresher.start_watching()
        assert asked == [1], "the first check did not happen"
        assert refresher._timer.isActive(), "nothing will ever ask again"

        # Wind the timer on rather than waiting an hour for it.
        for _ in range(3):
            refresher._timer.timeout.emit()

        assert len(asked) == 4
    finally:
        refresher.stop_watching()


def test_the_wake_up_is_often_enough_to_notice_a_fortnight_passing(app) -> None:
    """It does not have to be frequent, only frequent enough that a receipt's
    life cannot end between two of them unnoticed."""
    refresher = LicenseRefresher()

    assert refresher.WAKE_INTERVAL_MS <= 24 * 60 * 60 * 1000
    assert refresher._timer.interval() == refresher.WAKE_INTERVAL_MS


def test_a_receipt_expiring_while_the_window_is_open_ends_pro(monkeypatch) -> None:
    """The whole point of asking again: the answer has to be allowed to change
    without the application being restarted."""
    answers = iter([True, False])
    monkeypatch.setattr(feature_gate, "_local_state", lambda: (next(answers), {}, None))

    feature_gate.invalidate_pro_cache()
    assert feature_gate.is_pro() is True

    # A cached yes is what a long-running window holds. Only a refresh may
    # replace it, which is why nothing else is allowed to write the cache.
    assert feature_gate.is_pro() is True, "the cache stopped working"
    assert feature_gate.refresh_pro_status() is False
    assert feature_gate.is_pro() is False


# ── a second key ──────────────────────────────────────────────────────
def test_a_machine_with_nothing_on_it_activates() -> None:
    assert activation_plan({}, "LS-KEY") == ACTIVATE
    assert activation_plan({"license": {}}, "LS-KEY") == ACTIVATE
    assert activation_plan({"license": {"license_key": "LS-KEY"}}, "LS-KEY") == ACTIVATE


def test_the_same_key_typed_again_resumes_rather_than_activating_twice() -> None:
    """Somebody whose activation succeeded and whose receipt did not can type
    the same key again. That has to finish what it started, not spend a second
    slot on the same licence."""
    settings = {"license": {"license_key": "LS-KEY", "instance_id": "inst-1"}}

    assert activation_plan(settings, "LS-KEY") == RESUME
    assert activation_plan(settings, " ls-key ") == RESUME, "case and spaces are not a new key"


def test_a_different_key_is_refused_rather_than_quietly_ignored() -> None:
    """The gap this closes.

    Any stored instance used to mean "do not activate", so a second key was
    accepted, never used, and the service was asked about the first one — while
    the person was told their new key had worked.
    """
    settings = {"license": {"license_key": "OLD-KEY", "instance_id": "inst-old"}}

    assert activation_plan(settings, "NEW-KEY") == WRONG_KEY


def test_an_activation_with_no_key_recorded_is_not_resumed_by_anything() -> None:
    """An instance with no key beside it cannot be matched, so nothing may
    claim to be continuing it."""
    settings = {"license": {"license_key": "", "instance_id": "inst-old"}}

    assert activation_plan(settings, "ANY-KEY") == WRONG_KEY


def test_rubbish_where_a_licence_goes_does_not_become_an_activation() -> None:
    assert activation_plan({"license": "broken"}, "LS-KEY") == ACTIVATE
    assert activation_plan("broken", "LS-KEY") == ACTIVATE


def test_the_daily_check_is_not_reset_by_restarting(monkeypatch) -> None:
    """Anchored to the signature, so closing and reopening the application does
    not push the next check into the future."""
    from app.license_client import is_refresh_due, refresh_delay_seconds

    issued = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    receipt = {"issued_at": issued.isoformat()}
    install = "9f2c" * 10 + "abc"
    offset = timedelta(seconds=refresh_delay_seconds(install))

    later = issued + timedelta(days=1) + offset + timedelta(minutes=1)

    assert is_refresh_due(receipt, installation_hash=install, now=later) is True
    # A restart changes nothing about the receipt, so it is still due.
    assert is_refresh_due(receipt, installation_hash=install, now=later) is True
