"""The seams between the licence model and the window, where the last four bugs were.

Each of these was passing before as a unit and wrong as a whole. The model said
a working licence shows nothing; the wiring showed "checking your licence" to
everybody once an hour anyway. The model was asked whether a licence had ended
before it was asked whether one was working, so a revocation outlived the
activation that replaced it. And a state worth mentioning once was written to
the log every hour for as long as it lasted.
"""

from __future__ import annotations

import ast

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app import feature_gate
from app.license_presenter import LicenseStatusPresenter
from app.license_refresh import LicenseRefresher
from app.license_status import CHECKING, ENDED, FREE, PRO, Facts, status


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


# ── a check nobody asked for stays quiet ──────────────────────────────
def test_the_hourly_check_says_nothing_about_starting(app, monkeypatch) -> None:
    """The first bug. Every wake-up announced itself, so a machine with no
    licence at all was told its licence was being checked, and a healthy Pro
    watched a banner appear and disappear once an hour — or sit there until the
    request timed out."""
    monkeypatch.setattr("app.license_refresh.is_pro", lambda: True)
    monkeypatch.setattr("app.license_refresh.refresh_pro_status", lambda: True)

    refresher = LicenseRefresher()
    announced: list[int] = []
    refresher.started.connect(lambda: announced.append(1))

    refresher.refresh()
    app.processEvents()

    assert announced == [], "a background check announced itself"


def test_starting_the_watch_is_just_as_quiet(app, monkeypatch) -> None:
    """The one at launch is the worst of them: it is the first thing anybody
    sees."""
    monkeypatch.setattr("app.license_refresh.is_pro", lambda: True)
    monkeypatch.setattr("app.license_refresh.refresh_pro_status", lambda: True)

    refresher = LicenseRefresher()
    announced: list[int] = []
    refresher.started.connect(lambda: announced.append(1))

    try:
        refresher.start_watching()
        app.processEvents()

        assert announced == []
    finally:
        refresher.stop_watching()


def test_a_check_somebody_pressed_does_announce_itself(app, monkeypatch) -> None:
    """Somebody who presses a button is owed an acknowledgement that something
    is happening. The difference is who asked."""
    monkeypatch.setattr("app.license_refresh.is_pro", lambda: False)
    monkeypatch.setattr("app.license_refresh.refresh_pro_status", lambda: False)

    refresher = LicenseRefresher()
    announced: list[int] = []
    refresher.started.connect(lambda: announced.append(1))

    refresher.refresh(announce=True)
    app.processEvents()

    assert announced == [1]


# ── an old refusal does not outlive a new licence ─────────────────────
def test_a_working_licence_is_never_described_as_ended() -> None:
    """The second bug, in the model. A revocation followed by activating a
    different key left the window saying Pro had ended while Pro was running."""
    answer = status(Facts(has_licence=True, pro=True, has_receipt=True, last_outcome="revoked"))

    assert answer.state == PRO
    assert answer.message == ""


def test_a_revocation_with_nothing_left_behind_it_is_still_explained() -> None:
    """The reordering must not lose the case it was written for: ending a
    licence clears it, so this is what a revoked machine actually looks like."""
    answer = status(Facts(has_licence=False, pro=False, last_outcome="revoked"))

    assert answer.state == ENDED


def test_asking_the_service_records_what_it_said(monkeypatch, tmp_path) -> None:
    """So that one place knows, and every place that changes a licence goes
    through it. The activation path used to ask for a receipt without recording
    the answer, which is how a stale refusal survived."""
    monkeypatch.setattr(feature_gate, "note_outcome", feature_gate.note_outcome)
    feature_gate.note_outcome("revoked")
    assert feature_gate.last_outcome() == "revoked"

    feature_gate.note_outcome("")
    assert feature_gate.last_outcome() == ""


def test_a_new_activation_clears_the_previous_refusal(monkeypatch) -> None:
    """Whatever the service said about the last licence is not about this one."""
    feature_gate.note_outcome("revoked")

    monkeypatch.setattr(feature_gate, "_local_state", lambda: (True, {}, None))
    feature_gate.invalidate_pro_cache()

    facts = Facts(has_licence=True, pro=True, has_receipt=True, last_outcome=feature_gate.last_outcome())
    assert status(facts).state == PRO, "the old refusal is still on screen"

    feature_gate.note_outcome("")


# ── the log is not a metronome ────────────────────────────────────────
def test_the_same_state_is_written_down_once(app) -> None:
    """The third bug. An expired confirmation or a wrong clock added an
    identical line every hour, for as long as it lasted, until the log was
    nothing else."""
    presenter = LicenseStatusPresenter()
    stuck = Facts(has_licence=True, pro=False, has_receipt=True)

    first, log_first = presenter.update(stuck)
    _second, log_second = presenter.update(stuck)
    _third, log_third = presenter.update(stuck)

    assert first.message
    assert log_first is True
    assert log_second is False
    assert log_third is False


def test_moving_to_a_different_state_is_worth_saying(app) -> None:
    presenter = LicenseStatusPresenter()

    presenter.update(Facts(has_licence=True, pro=False, has_receipt=True))
    _status, log_it = presenter.update(Facts(has_licence=True, pro=False, has_receipt=False))

    assert log_it is True


def test_coming_back_to_a_state_after_leaving_it_is_worth_saying_again(app) -> None:
    """It is news the second time too: something changed, and then changed
    back."""
    presenter = LicenseStatusPresenter()
    broken = Facts(has_licence=True, pro=False, has_receipt=True)
    working = Facts(has_licence=True, pro=True, has_receipt=True)

    presenter.update(broken)
    presenter.update(working)
    _status, log_it = presenter.update(broken)

    assert log_it is True


def test_states_with_nothing_to_say_are_never_written_down(app) -> None:
    presenter = LicenseStatusPresenter()

    for facts in (Facts(), Facts(has_licence=True, pro=True, has_receipt=True)):
        answer, log_it = presenter.update(facts)

        assert answer.state in (FREE, PRO)
        assert log_it is False


def test_checking_is_not_written_down_either(app) -> None:
    """It is a moment, not an event, and it happens on every manual press."""
    presenter = LicenseStatusPresenter()

    answer, log_it = presenter.update(Facts(checking=True))

    assert answer.state == CHECKING
    assert log_it is False


# ── the field nobody read ─────────────────────────────────────────────
def test_the_status_does_not_claim_to_decide_who_gets_pro() -> None:
    """It used to carry ends_pro, which nothing read, and which was set for a
    wrong clock and an expired confirmation — neither of which revokes or
    clears anything. Whether Pro holds is feature_gate's answer; this only
    explains it."""
    answer = status(Facts(has_licence=True, pro=False, has_receipt=True))

    assert not hasattr(answer, "ends_pro")


# ── the moments a licence changes without a check ─────────────────────
def _parsed(name: str):
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "app" / f"{name}.py").read_text(
        encoding="utf-8"
    )
    return source, ast.parse(source)


def _function(name: str, module: str):
    _source, tree = _parsed(module)
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _statements(function):
    """The body without the docstring.

    ``ast.dump`` includes it, so a test looking for a word in a function finds
    it in the prose explaining what the function does — and passes with the
    code removed. That has now happened three times in this repository, most
    recently on the word "announce".
    """
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return ast.dump(ast.Module(body=body, type_ignores=[]))


def test_activating_a_key_updates_the_line_at_once() -> None:
    """Not at the next hourly wake-up, which could be an hour of a window
    insisting Pro had ended.

    Checked for reachability, not presence: a call sitting after a return is
    still in the dump and does nothing at all.
    """
    function = _function("on_activated", "overlay_controller")
    reached = []
    for node in function.body:
        if isinstance(node, ast.Return):
            break
        reached.append(node)

    assert "_show_license_status" in ast.dump(ast.Module(body=reached, type_ignores=[]))


def test_handing_a_licence_back_updates_the_line_at_once() -> None:
    function = _function("show_license_transfer", "overlay_controller")

    assert "_show_license_status" in _statements(function)


def test_every_path_that_changes_a_licence_clears_what_the_service_said() -> None:
    """Activation, deactivation and transfer. Each makes the last answer about
    a licence that is no longer the one in front of the person."""
    source, _tree = _parsed("overlay_controller")

    for name in ("show_license_transfer", "deactivate"):
        assert "note_outcome" in _statements(_function(name, "overlay_controller"))

    # The activation closure clears it before asking, which is the only place
    # it can be done before the request rather than after it.
    assert source.count('note_outcome("")') >= 3


def test_the_window_writes_the_log_only_when_the_presenter_says_so() -> None:
    """The guard is the thing, not the word. An earlier version of this looked
    for "worth_saying" anywhere in the function and passed with the condition
    changed to something else entirely."""
    function = _function("_show_license_status", "main_window")

    guards = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.If) and "_log" in ast.dump(node)
    ]

    assert guards, "nothing guards the log line"
    for guard in guards:
        assert isinstance(guard.test, ast.Name)
        assert guard.test.id == "worth_saying"


def test_the_button_announces_and_nothing_else_does() -> None:
    """Read out of the code with the docstring removed, which is where the
    previous version of this found the word it was looking for."""
    pressed = _statements(_function("_recheck_license", "main_window"))

    assert "announce" in pressed

    _source, tree = _parsed("main_window")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name != "_recheck_license":
            assert "announce" not in _statements(node), f"{node.name} announces too"


# ── the service answer is recorded where it is heard ──────────────────
def test_obtaining_a_receipt_records_what_the_service_said(monkeypatch) -> None:
    """Inside obtain_receipt, because that is the single door to the service:
    the refresh goes through it and so does activation. Recording anywhere else
    means one of them is left out, which is how a stale refusal survived an
    activation in the first place.
    """
    from app import license_client

    class _Identity:
        installation_hash = "a" * 43

    settings = {"license": {"license_key": "LS-KEY", "instance_id": "inst-1"}}
    monkeypatch.setattr(feature_gate, "save_settings", lambda *_a, **_k: None)
    monkeypatch.setattr(feature_gate, "public_keys", lambda: {})

    for outcome in (
        license_client.UNAVAILABLE,
        license_client.RATE_LIMITED,
        license_client.INVALID,
    ):
        feature_gate.note_outcome("something stale")
        monkeypatch.setattr(
            feature_gate,
            "request_receipt",
            lambda _answer=outcome, **_kw: license_client.IssueResult(_answer),
        )

        feature_gate.obtain_receipt(dict(settings), _Identity(), now=_now())

        assert feature_gate.last_outcome() == outcome, outcome
    feature_gate.note_outcome("")


def test_a_receipt_that_arrives_is_recorded_as_success(monkeypatch) -> None:
    from app import license_client

    class _Identity:
        installation_hash = "a" * 43

    settings = {"license": {"license_key": "LS-KEY", "instance_id": "inst-1"}}
    monkeypatch.setattr(feature_gate, "save_settings", lambda *_a, **_k: None)
    monkeypatch.setattr(feature_gate, "public_keys", lambda: {})
    monkeypatch.setattr(feature_gate, "store_receipt", lambda *_a, **_k: None)
    monkeypatch.setattr(
        feature_gate,
        "request_receipt",
        lambda **_kw: license_client.IssueResult(license_client.ISSUED, receipt={"a": 1}),
    )
    feature_gate.note_outcome("revoked")

    feature_gate.obtain_receipt(settings, _Identity(), now=_now())

    assert feature_gate.last_outcome() == license_client.ISSUED
    feature_gate.note_outcome("")


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
