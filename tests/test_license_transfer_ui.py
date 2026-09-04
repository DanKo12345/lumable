"""What a person sees while moving a licence to another computer.

The window is where a true thing can quietly become a comforting one. Two of
these tests exist only to stop that: a transfer the server did not confirm must
not read as a success, and the key must not be legible until somebody asks.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from app.license_transfer import FREED, NOT_FREED, masked_key
from app.theme import theme_manager
from app.widgets.license_transfer_overlay import LicenseTransferDialog
from app.widgets.section_icon import LUCIDE_ICON_DIR

ROOT = Path(__file__).resolve().parent.parent
KEY = "LS-1234-ABCD"

_STRINGS = (
    "transfer.row",
    "transfer.action",
    "transfer.title",
    "transfer.headline",
    "transfer.body",
    "transfer.reveal",
    "transfer.hide",
    "transfer.copy",
    "transfer.confirm",
    "transfer.retry",
    "transfer.cancel",
    "transfer.done",
    "transfer.working",
    "transfer.freed_headline",
    "transfer.freed_body",
    "transfer.failed_headline",
    "transfer.failed_body",
    "transfer.unavailable",
)


def test_the_transfer_row_has_a_real_key_glyph() -> None:
    icon = LUCIDE_ICON_DIR / "key.svg"

    assert icon.is_file()
    assert QSvgRenderer(str(icon)).isValid()


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    made = LicenseTransferDialog(KEY, lambda: (FREED, KEY), lambda key: key)
    yield made
    made.deleteLater()


# ── the key ───────────────────────────────────────────────────────────
def test_the_key_is_masked_until_somebody_asks(dialog) -> None:
    """This window opens at exactly the sort of moment when a screen is being
    shared with whoever is helping."""
    assert dialog._key_label.text() == masked_key(KEY)
    assert KEY not in dialog._key_label.text()

    dialog._toggle_reveal()
    assert dialog._key_label.text() == KEY

    dialog._toggle_reveal()
    assert dialog._key_label.text() == masked_key(KEY), "it did not go back"


def test_copying_puts_the_whole_key_on_the_clipboard_not_the_dots(dialog, app) -> None:
    """Masking is for the screen. A masked key on the clipboard would be pasted
    into the new computer and rejected, with nothing to explain why."""
    dialog._copy_key()

    assert app.clipboard().text() == KEY


@pytest.mark.parametrize("is_dark", [False, True])
def test_the_separate_dialog_has_a_readable_surface_in_each_theme(app, is_dark) -> None:
    """A top-level QDialog does not inherit the main window's themed surface.

    The first transfer dialog therefore painted the light theme's dark text on
    the platform's dark dialog background. Render the actual top-level widget:
    checking only its stylesheet would miss the same integration error again.
    """
    previous = theme_manager.is_dark
    theme_manager.set_dark(is_dark)
    made = LicenseTransferDialog(KEY, lambda: (FREED, KEY), lambda key: key)
    try:
        made.show()
        app.processEvents()
        image = made.grab().toImage()
        surface = image.pixelColor(8, 8).lightness()
        headline_rect = made._headline.geometry()
        tones = [
            image.pixelColor(x, y).lightness()
            for y in range(headline_rect.top(), headline_rect.bottom() + 1)
            for x in range(headline_rect.left(), headline_rect.right() + 1)
        ]

        assert surface < 80 if is_dark else surface > 190
        assert max(tones) - min(tones) > 100, "headline disappears into the dialog surface"
    finally:
        made.close()
        made.deleteLater()
        theme_manager.set_dark(previous)


# ── how it ends ───────────────────────────────────────────────────────
def test_a_confirmed_transfer_says_so_and_still_offers_the_key(dialog) -> None:
    """The last place the key is on offer, and the one moment it is certainly
    wanted: it has to be typed into the other machine next."""
    dialog._finished(FREED, KEY)

    assert dialog.freed is True
    assert dialog._headline.text() == "transfer.freed_headline"
    assert dialog._key_label.text() == masked_key(KEY)
    assert dialog._copy.isEnabled(), "the key can no longer be copied"
    assert dialog._confirm.isHidden(), "it still offers to release an already-released licence"


def test_a_failed_transfer_is_never_dressed_up_as_a_success(dialog) -> None:
    """Nothing was released, so nothing may be said about anything having
    been."""
    dialog._finished(NOT_FREED, KEY)

    assert dialog.freed is False
    assert dialog._headline.text() == "transfer.failed_headline"
    assert not dialog._confirm.isHidden(), "the way back was taken away"
    assert dialog._confirm.isEnabled(), "there is no way to try again"
    assert dialog._confirm.text() == "transfer.retry"


def test_the_window_is_usable_again_after_either_ending(dialog) -> None:
    """It disables its own buttons while the request is out. Leaving one
    disabled afterwards would be a window somebody has to kill."""
    for outcome in (FREED, NOT_FREED):
        fresh = LicenseTransferDialog(
            KEY, lambda ending=outcome: (ending, KEY), lambda key: key
        )
        try:
            fresh._start()
            fresh._worker.wait(5000)
            fresh._finished(outcome, KEY)

            assert fresh._close.isEnabled(), f"{outcome} left the window shut in"
        finally:
            fresh.deleteLater()


def test_the_request_does_not_run_on_the_thread_drawing_the_window(dialog) -> None:
    """Handing a licence back is up to two calls to Lemon Squeezy at ten seconds
    each, and a window frozen for twenty looks like one that has crashed."""
    from PySide6.QtCore import QThread

    dialog._start()
    try:
        assert isinstance(dialog._worker, QThread)
    finally:
        dialog._worker.wait(5000)


def test_a_thrown_error_is_shown_as_a_failure_rather_than_vanishing(app) -> None:
    """An exception is an answer, not a crash. Without this the window would sit
    on "releasing the key..." for ever, with both buttons disabled, and the only
    way out would be killing it.

    The assertion is on the headline rather than on ``freed`` staying False,
    which it does anyway from never having been set — the first version of this
    would have passed on a thread that died silently.
    """
    def explode():
        raise RuntimeError("LS-SECRET-LEAK")

    made = LicenseTransferDialog(KEY, explode, lambda key: key)
    try:
        made._start()
        made._worker.wait(5000)
        app.processEvents()

        assert made._headline.text() == "transfer.failed_headline", "the window never came back"
        assert made.freed is False
        assert made._close.isEnabled(), "no way out of a window that failed"
        assert "LS-SECRET-LEAK" not in made._key_label.text()
        assert "LS-SECRET-LEAK" not in made._body.text()
    finally:
        made.deleteLater()


def _function(source: str, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


# ── where it is offered ───────────────────────────────────────────────
def test_the_action_is_a_row_in_settings() -> None:
    """Not a link in the corner of an overlay. The slot is spent the moment a
    machine is wiped without it, and nothing can hand it back afterwards, so it
    has to be somewhere a person would look before that happens."""
    layout = (ROOT / "app" / "main_layout.py").read_text(encoding="utf-8")

    assert '"transfer.row"' in layout
    assert "host.transfer_license_button" in layout


def test_the_button_is_wired_to_something_that_exists() -> None:
    header = (ROOT / "app" / "hero_header.py").read_text(encoding="utf-8")
    window = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
    controller = (ROOT / "app" / "overlay_controller.py").read_text(encoding="utf-8")

    assert "host._show_license_transfer" in header
    assert "def _show_license_transfer" in window
    assert "def show_license_transfer" in controller


def test_the_controller_asks_whether_there_is_anything_to_transfer_first() -> None:
    """Somebody with no licence gets told so, rather than a window that cannot
    do anything.

    Looks for the guard itself — a condition on can_transfer that returns —
    rather than for the name appearing somewhere in the function. The first
    version of this found it in the import line and passed with the guard
    deleted.
    """
    controller = (ROOT / "app" / "overlay_controller.py").read_text(encoding="utf-8")
    function = _function(controller, "show_license_transfer")

    guards = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.If)
        and "can_transfer" in ast.dump(node.test)
        and any(isinstance(inner, ast.Return) for inner in node.body)
    ]

    assert guards, "nothing stops the window opening on a machine with no licence"


def test_the_controller_clears_nothing_of_its_own() -> None:
    """Clearing belongs to deactivate_license, after the server has confirmed.
    A second place doing it is a second chance to get the order wrong."""
    controller = (ROOT / "app" / "overlay_controller.py").read_text(encoding="utf-8")
    function = _function(controller, "show_license_transfer")
    source = ast.get_source_segment(controller, function) or ""

    assert "clear_licence" not in source
    assert "license_key" not in source


def test_every_string_exists_in_every_language() -> None:
    """A missing key renders as its own name, and 'transfer.freed_headline' on
    screen after somebody released a licence would be alarming."""
    for locale in ("ru", "en", "es", "zh"):
        bundle = json.loads((ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        missing = set(_STRINGS) - set(bundle["translations"])
        assert not missing, f"{locale} is missing {sorted(missing)}"


def test_the_removed_uninstall_strings_are_gone_from_every_language() -> None:
    """The headless mode they belonged to was deleted. Strings for a window
    nothing opens are a translator's time spent on nothing."""
    for locale in ("ru", "en", "es", "zh"):
        bundle = json.loads((ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8"))
        left = [key for key in bundle["translations"] if key.startswith("uninstall.")]
        assert not left, f"{locale} still carries {left}"
