"""The capture-area picker: the picture has to match the crop.

A diagram that draws "roughly the middle" while the loop samples a precise
quarter teaches the wrong thing about the app's own behaviour, and it is the
kind of wrong that survives review because it looks right.
"""

from __future__ import annotations

import pathlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent

from app.ambient_controller import _region_for
from app.capture_regions import REGION_IDS, normalize_region, region_box
from app.widgets.capture_area_selector import CaptureAreaSelector

_MONITOR = {"left": 0, "top": 0, "width": 1920, "height": 1080}


def _selector() -> CaptureAreaSelector:
    return CaptureAreaSelector({region: region.title() for region in REGION_IDS})


def _widest_region_labels() -> dict[str, str]:
    """The longest label each region has in any language LumaBLE ships."""
    import json

    longest: dict[str, str] = dict.fromkeys(REGION_IDS, "")
    for path in pathlib.Path("app/i18n").glob("*.json"):
        translations = json.loads(path.read_text(encoding="utf-8"))["translations"]
        for region in REGION_IDS:
            label = str(translations.get(f"ambient.region.{region}", ""))
            if len(label) > len(longest[region]):
                longest[region] = label
    return longest


def _press(widget, key) -> None:
    widget.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, key, Qt.NoModifier))


# ── the shared geometry ───────────────────────────────────────────────
@pytest.mark.parametrize("region", REGION_IDS)
def test_the_drawing_and_the_crop_come_from_one_source(region: str) -> None:
    """Whatever the fractions are, both sides read them from the same place.
    Two copies of the numbers drift apart the first time either is retuned."""
    box = region_box(region)
    crop = _region_for(_MONITOR, region)

    assert crop["left"] == int(_MONITOR["width"] * box.left)
    assert crop["top"] == int(_MONITOR["height"] * box.top)
    assert crop["width"] == max(1, int(_MONITOR["width"] * box.width))
    assert crop["height"] == max(1, int(_MONITOR["height"] * box.height))


def test_the_centre_is_a_quarter_of_the_area_not_a_vague_middle() -> None:
    """Half of each side. Drawn as "most of the screen with margins" the picture
    would explain away the very complaint it exists to answer."""
    box = region_box("center")
    assert (box.width, box.height) == (0.5, 0.5)
    assert box.left == box.top == 0.25


def test_the_bands_are_a_third_of_the_height_each() -> None:
    top, bottom = region_box("top"), region_box("bottom")
    assert round(top.height, 4) == round(bottom.height, 4) == round(1 / 3, 4)
    assert top.top == 0.0
    assert round(bottom.top + bottom.height, 4) == 1.0


def test_a_crop_never_collapses_to_nothing() -> None:
    """A grab of zero height returns no bytes, so the frame is lost rather than
    merely small — a one-pixel monitor is not a reason to stop syncing."""
    crop = _region_for({"left": 0, "top": 0, "width": 1, "height": 1}, "center")
    assert crop["width"] >= 1 and crop["height"] >= 1


def test_stored_junk_falls_back_instead_of_raising() -> None:
    assert normalize_region("banana") == "full"
    assert normalize_region(None) == "full"
    assert region_box("banana") == region_box("full")


# ── the widget ────────────────────────────────────────────────────────
def test_choosing_a_region_moves_the_drawing_and_reports_it() -> None:
    selector = _selector()
    heard: list[str] = []
    selector.selected.connect(heard.append)

    selector.segments.set_current("center")
    selector.segments.selected.emit("center")

    assert heard == ["center"]
    assert selector.current_region() == "center"


def test_the_arrows_move_the_choice_without_a_mouse() -> None:
    """The control was reachable only by clicking. Arrow keys are what make it
    a real group rather than four pictures that happen to be adjacent."""
    selector = _selector()
    heard: list[str] = []
    selector.selected.connect(heard.append)
    selector.set_current_region("full", animate=False)

    _press(selector.segments, Qt.Key_Right)
    _press(selector.segments, Qt.Key_Right)

    assert heard == ["center", "top"]
    assert selector.current_region() == "top"

    _press(selector.segments, Qt.Key_Home)
    assert selector.current_region() == "full"
    _press(selector.segments, Qt.Key_End)
    assert selector.current_region() == REGION_IDS[-1]


def test_the_arrows_stop_at_the_ends_rather_than_wrapping() -> None:
    selector = _selector()
    selector.set_current_region("full", animate=False)

    _press(selector.segments, Qt.Key_Left)

    assert selector.current_region() == "full"


def test_setting_the_region_programmatically_says_nothing() -> None:
    """Restoring a saved choice must not read as the user making one, or the
    settings are written back on every start."""
    selector = _selector()
    heard: list[str] = []
    selector.selected.connect(heard.append)

    selector.set_current_region("top", animate=False)

    assert heard == []
    assert selector.current_region() == "top"


def test_the_explanation_is_reachable_without_costing_height() -> None:
    """The card had no room for a paragraph, so the sentence lives where a
    screen reader can still find it."""
    selector = _selector()
    selector.set_texts(
        title="Capture area",
        help_text="The highlighted part sets the colour.",
        labels={region: region for region in REGION_IDS},
    )

    assert selector.title.text() == "Capture area"
    assert "highlighted" in selector.toolTip()
    assert "highlighted" in selector.segments.accessibleDescription()
    # The position is spoken too: a painted widget cannot be a radio group, so
    # "2 / 4" is the only way the count and the current choice are heard at all.
    assert selector.segments.accessibleName() == "Capture area, full, 1 / 4"
    selector.set_current_region("top", animate=False)
    assert selector.segments.accessibleName() == "Capture area, top, 3 / 4"



def test_each_option_carries_a_drawing_of_its_own_crop() -> None:
    """The glyph is painted from the same fractions the loop crops with. Drawn
    by hand it would be an illustration that happens to resemble the setting,
    and would stop resembling it the first time either changed."""
    from PySide6.QtGui import QImage, QPainter

    from app.widgets.capture_area_selector import ICON_HEIGHT, ICON_WIDTH, paint_region_glyph

    filled: dict[str, set[int]] = {}
    for region in REGION_IDS:
        image = QImage(ICON_WIDTH, ICON_HEIGHT, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        paint_region_glyph(painter, QRectF(0, 0, ICON_WIDTH, ICON_HEIGHT), region, True)
        painter.end()
        rows = set()
        for y in range(1, ICON_HEIGHT - 1):
            for x in range(3, ICON_WIDTH - 3):
                pixel = QColor(image.pixel(x, y))
                # The accent fill, not the near-white outline: both are bright
                # in blue, only the fill is markedly less red.
                if pixel.alpha() and pixel.blue() - pixel.red() > 40:
                    rows.add(y)
                    break
        filled[region] = rows

    assert min(filled["top"]) < min(filled["center"]) < min(filled["bottom"]), (
        "the bands are not drawn where their names say"
    )
    assert len(filled["full"]) > len(filled["center"]), "the centre is not smaller than the whole"
    assert max(filled["top"]) < min(filled["bottom"]), "top and bottom overlap"


def test_every_option_explains_its_own_crop() -> None:
    """One tooltip for the whole control cannot say what "Centre" actually
    takes, which is the number a 24-pixel drawing cannot show."""
    selector = _selector()
    selector.set_texts(
        title="Capture area",
        help_text="general",
        labels={region: region for region in REGION_IDS},
        tooltips={region: f"tip-{region}" for region in REGION_IDS},
    )

    assert selector.segments._tooltips["center"] == "tip-center"
    assert selector.segments._tooltips["bottom"] == "tip-bottom"


def test_the_focus_ring_belongs_to_the_keyboard() -> None:
    """A ring after every click is noise beside the pill that already says what
    is selected. But the click must still hand over focus, or the arrows would
    do nothing until the control were tabbed to."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QFocusEvent, QMouseEvent

    selector = _selector()
    segments = selector.segments
    # Whether a widget really holds focus depends on an active window, which an
    # offscreen test has not got. The contract worth pinning is that the click
    # asks for focus at all — without that the arrows are dead until Tab.
    asked: list[object] = []
    segments.setFocus = lambda reason=None: asked.append(reason)

    segments.focusInEvent(QFocusEvent(QFocusEvent.FocusIn, Qt.TabFocusReason))
    assert segments._show_focus_ring, "tabbing in should show the ring"

    segments.mousePressEvent(
        QMouseEvent(
            QMouseEvent.MouseButtonPress,
            QPointF(5.0, 5.0),
            QPointF(5.0, 5.0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert not segments._show_focus_ring, "a click should not draw the ring"
    assert asked == [Qt.MouseFocusReason], "a click must still give the control focus"

    _press(segments, Qt.Key_Right)
    assert segments._show_focus_ring, "using the arrows after a click must show it again"

    segments.focusOutEvent(QFocusEvent(QFocusEvent.FocusOut, Qt.OtherFocusReason))
    assert not segments._show_focus_ring


def test_the_picker_fits_the_card_in_the_smallest_window() -> None:
    """Four options carrying a glyph and a word each multiply the default
    padding by four. In Russian that came to 774px, wider than the card once the
    sidebar is out, so the control was clipped or the card was pushed wider —
    and nothing caught it, because the narrow-width check went out with the
    monitor it belonged to."""
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.resize(860, 420)
        window.show()
        app.processEvents()

        selector = window.ambient_area_selector
        card = window.ambient_card
        # Measured against the widest labels any shipped language uses, not
        # whichever locale the test happens to run in — the 774px case was
        # Russian, and an English-only check would have missed it.
        selector.set_texts(
            title="X",
            help_text="X",
            labels=_widest_region_labels(),
            tooltips=dict.fromkeys(REGION_IDS, "X"),
        )
        app.processEvents()
        needed = selector.segments.sizeHint().width()
        available = card.contentsRect().width()

        assert needed <= available, (
            f"the picker needs {needed}px inside a {available}px card"
        )
        assert not window.body_scroll.horizontalScrollBar().isVisible(), (
            "the page scrolls sideways"
        )
    finally:
        overlay = getattr(window, "_onboarding_overlay", None)
        if overlay is not None:
            overlay.hide()
        window._ble.shutdown()
        window.close()


def test_the_option_explains_itself_to_a_screen_reader_too() -> None:
    """A tooltip needs a pointer. Without this, someone on a screen reader
    hears the general sentence and never "the central quarter of the screen" —
    the number the 24-pixel glyph cannot show."""
    selector = _selector()
    selector.set_texts(
        title="Capture area",
        help_text="general sentence",
        labels=dict.fromkeys(REGION_IDS, "x"),
        tooltips={region: f"crops the {region}" for region in REGION_IDS},
    )

    selector.set_current_region("center", animate=False)
    assert selector.segments.accessibleDescription() == "crops the center"

    _press(selector.segments, Qt.Key_Right)
    assert selector.segments.accessibleDescription() == "crops the top"


def test_without_per_option_hints_the_general_one_is_still_described() -> None:
    selector = _selector()
    selector.set_texts(
        title="Capture area",
        help_text="general sentence",
        labels=dict.fromkeys(REGION_IDS, "x"),
    )

    assert selector.segments.accessibleDescription() == "general sentence"
