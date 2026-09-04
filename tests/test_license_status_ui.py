"""The status line, and the wiring that keeps it honest.

Two things are guarded here that no amount of care in the model would give on
its own: the widget must have no opinions of its own, and a licence that is
working must never flicker into a warning because a background check happened to
fail.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from app.license_status import Facts, status
from app.widgets.license_status_banner import LicenseStatusBanner

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def banner(app):
    presses: list[int] = []
    made = LicenseStatusBanner(lambda key: key, lambda: presses.append(1))
    made.presses = presses
    yield made
    made.deleteLater()


def _shown(banner) -> bool:
    return not banner.isHidden()


# ── what it shows ─────────────────────────────────────────────────────
def test_a_working_licence_shows_nothing_at_all(banner) -> None:
    """A strip that is always there saying everything is fine is a strip people
    stop seeing — and then they miss the one time it says something else."""
    banner.show_status(status(Facts(has_licence=True, pro=True, has_receipt=True)))

    assert not _shown(banner)


def test_a_service_outage_does_not_make_a_working_licence_flicker(banner) -> None:
    """The case this whole page exists for. Somebody on a train, with a licence
    that has days left, must see no change of any kind."""
    banner.show_status(status(Facts(has_licence=True, pro=True, has_receipt=True)))
    assert not _shown(banner)

    banner.show_status(
        status(Facts(has_licence=True, pro=True, has_receipt=True, last_outcome="unavailable"))
    )

    assert not _shown(banner), "a failed check put a warning over a working licence"


def test_something_to_say_is_said_with_a_way_to_act(banner) -> None:
    banner.show_status(status(Facts(has_licence=True, pro=False, has_receipt=False)))

    assert _shown(banner)
    assert banner._label.text() == "license_status.needs_first_check"
    assert not banner._button.isHidden()


def test_a_refusal_is_shown_without_a_button_that_cannot_help(banner) -> None:
    """Asking again about a licence the service has refused produces the same
    refusal, and offering the button would suggest otherwise."""
    banner.show_status(status(Facts(last_outcome="revoked")))

    assert _shown(banner)
    assert banner._label.text() == "license_status.ended"
    assert banner._button.isHidden()


def test_pressing_it_asks_once_and_stops_asking(banner) -> None:
    """The request runs in the background, so a button that stays live invites
    somebody to press it four more times while they wait."""
    banner.show_status(status(Facts(has_licence=True, pro=False, has_receipt=True)))
    banner._pressed()

    assert banner.presses == [1]
    assert not banner._button.isEnabled()


def test_the_button_works_again_once_an_answer_arrives(banner) -> None:
    """Otherwise a failed check ends with a message telling somebody to try
    again, beside a button that cannot be pressed."""
    banner.show_status(status(Facts(has_licence=True, pro=False, has_receipt=True)))
    banner._pressed()
    assert not banner._button.isEnabled()

    banner.show_status(status(Facts(has_licence=True, pro=False, has_receipt=True)))

    assert banner._button.isEnabled()


def test_the_widget_decides_nothing_for_itself() -> None:
    """The same situation is reachable from several places, and a widget that
    reasons for itself is a second answer waiting to disagree with the first."""
    source = (ROOT / "app" / "widgets" / "license_status_banner.py").read_text(encoding="utf-8")

    for reached_for in ("is_pro", "current_facts", "load_settings", "urllib", "datetime", "Facts("):
        assert reached_for not in source, f"the banner works out {reached_for} on its own"


# ── the wiring ────────────────────────────────────────────────────────
def _method(name: str) -> ast.FunctionDef:
    source = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_the_line_is_refreshed_even_when_pro_itself_did_not_change() -> None:
    """Plenty of what a person needs to be told does not move Pro: a licence
    that was already unconfirmed and still is, a clock that is still wrong. An
    early return before the refresh would leave a stale sentence on screen."""
    function = _method("_on_license_refreshed")
    body = function.body

    statements = [node for node in body if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant)]
    first = statements[0]
    dumped = ast.dump(first)

    assert "_show_license_status" in dumped, "the status is refreshed after the early return"


def test_asking_begins_with_saying_that_it_is_asking() -> None:
    """Not with a guess about what the answer will be. A specific complaint
    invented before anything specific went wrong sends somebody off to fix a
    connection that was working."""
    started = _method("_on_license_check_started")
    dumped = ast.dump(started)

    assert "checking" in dumped

    refresher = (ROOT / "app" / "license_refresh.py").read_text(encoding="utf-8")
    assert "started = Signal()" in refresher
    assert "self.started.emit()" in refresher


def test_the_button_uses_the_same_path_as_the_hourly_check() -> None:
    """One route to the service, so there is one place it can go wrong."""
    function = _method("_recheck_license")
    dumped = ast.dump(function)

    assert "_license_refresher" in dumped
    assert "refresh" in dumped


def test_the_window_asks_the_model_rather_than_working_it_out() -> None:
    function = _method("_show_license_status")
    dumped = ast.dump(function)

    assert "current_facts" in dumped
    assert "status" in dumped
    assert "is_pro" not in dumped, "the window is deciding for itself"


def test_the_banner_is_built_where_a_person_would_look() -> None:
    layout = (ROOT / "app" / "main_layout.py").read_text(encoding="utf-8")

    assert "LicenseStatusBanner" in layout
    assert "host._recheck_license" in layout
