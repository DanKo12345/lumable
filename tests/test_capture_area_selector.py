"""The capture-area picker: the picture has to match the crop.

A diagram that draws "roughly the middle" while the loop samples a precise
quarter teaches the wrong thing about the app's own behaviour, and it is the
kind of wrong that survives review because it looks right.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest

from app.ambient_controller import _region_for
from app.capture_regions import REGION_IDS, normalize_region, region_box
from app.widgets.capture_area_selector import CaptureAreaSelector

_MONITOR = {"left": 0, "top": 0, "width": 1920, "height": 1080}


def _selector() -> CaptureAreaSelector:
    return CaptureAreaSelector({region: region.title() for region in REGION_IDS})


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
    assert selector.diagram._region == "center"


@pytest.mark.parametrize("region", REGION_IDS)
def test_the_rectangle_it_draws_is_the_one_it_will_capture(region: str) -> None:
    """The claim of the whole widget. Rectangles of its own — even plausible
    ones — make the picture an illustration rather than a statement about what
    the app is about to do."""
    selector = _selector()
    selector.set_current_region(region, animate=False)

    box = region_box(region)
    assert selector.diagram._box == (box.left, box.top, box.width, box.height)


def test_the_drawing_actually_travels_to_the_new_area() -> None:
    """The path every user takes, and the one the other tests skipped by asking
    for no animation. Animating the rectangle as a QVariant tuple looked right
    and moved nothing: Qt cannot interpolate a Python tuple, so the setter got
    None, the box stayed put, and the picture showed the old area while the
    capture had already switched — the widget's one claim, quietly false."""
    selector = _selector()
    selector.set_current_region("full", animate=False)
    assert selector.diagram._box == (0.0, 0.0, 1.0, 1.0)

    selector.set_current_region("center", animate=True)

    QTest.qWait(90)
    midway = selector.diagram._box
    assert midway != (0.0, 0.0, 1.0, 1.0), "the rectangle never left the full screen"
    assert midway != (0.25, 0.25, 0.5, 0.5), "it jumped instead of travelling"
    assert 0.0 < midway[0] < 0.25, f"left edge outside the move: {midway}"
    assert 0.5 < midway[2] < 1.0, f"width outside the move: {midway}"

    QTest.qWait(180)
    assert selector.diagram._box == (0.25, 0.25, 0.5, 0.5), "it never arrived"


def test_an_interrupted_move_continues_from_what_is_on_screen() -> None:
    """Restarting from the target instead would snap the rectangle backwards
    before setting off again."""
    selector = _selector()
    selector.set_current_region("full", animate=False)
    selector.set_current_region("center", animate=True)
    QTest.qWait(60)
    caught = selector.diagram._box

    selector.set_current_region("top", animate=True)

    assert selector.diagram._from == caught
    QTest.qWait(260)
    box = region_box("top")
    assert selector.diagram._box == (box.left, box.top, box.width, box.height)


def test_reduced_motion_puts_the_rectangle_straight_where_it_belongs() -> None:
    from app.motion_policy import motion_policy

    selector = _selector()
    selector.set_current_region("full", animate=False)
    motion_policy.set_mode("reduced")
    try:
        selector.set_current_region("bottom", animate=True)
        box = region_box("bottom")
        assert selector.diagram._box == (box.left, box.top, box.width, box.height)
    finally:
        motion_policy.set_mode("system")


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


def test_the_wash_is_dropped_when_nothing_is_running() -> None:
    """Left glowing, it would claim the strip is showing a colour it stopped
    showing — a picture that lies about the present."""
    selector = _selector()
    selector.set_result_color((234, 173, 17))
    assert selector.diagram._result == (234, 173, 17)

    selector.set_result_color(None)

    assert selector.diagram._result is None


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


def test_the_row_stays_one_line_and_within_its_height_budget() -> None:
    """Stacking is what put this block over the card's budget, so a narrow card
    shrinks the monitor instead — and never below the size where a third of the
    height stops being tellable from a half."""
    selector = _selector()

    selector.resize(520, selector.sizeHint().height())
    wide = selector.diagram.width()
    selector.resize(240, selector.sizeHint().height())
    narrow = selector.diagram.width()

    assert wide >= narrow >= 96
    assert selector.sizeHint().height() <= 80, "the row outgrew the card's spare height"
