"""Every icon a card asks for has to exist.

A name with no file behind it renders as nothing at all — no error, no warning,
just an empty square where an icon should be. That is how the Windows lock and
unlock triggers shipped: the tile map named "lock", the loader found no file,
and the rule list showed a blank tile beside a working rule.

The maps are read as data rather than scanned as text, so this checks what the
app will actually ask for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from app.automation_ui_controller import (
    _FALLBACK_TILE,
    _JOURNAL_TILES,
    _PAUSE_TILES,
    _TRIGGER_TILES,
)

ICON_DIR = Path("app/assets/icons/lucide")


def _available() -> set[str]:
    return {path.stem for path in ICON_DIR.glob("*.svg")}


def test_the_icon_set_is_where_it_is_expected() -> None:
    assert ICON_DIR.is_dir()
    assert "moon" in _available(), "the set moved or the test is looking in the wrong place"


@pytest.mark.parametrize(
    ("label", "tiles"),
    (
        ("triggers", _TRIGGER_TILES),
        ("journal", _JOURNAL_TILES),
        ("pause", _PAUSE_TILES),
    ),
)
def test_every_tile_names_an_icon_that_exists(label: str, tiles: dict) -> None:
    available = _available()
    missing = {key: name for key, (name, _colour) in tiles.items() if name not in available}

    assert missing == {}, f"{label} tiles naming an icon with no file: {missing}"


def test_the_fallback_itself_is_not_missing() -> None:
    """It is the last thing standing when a kind is unknown; a blank fallback
    would turn one missing glyph into every missing glyph."""
    assert _FALLBACK_TILE[0] in _available()


def test_every_trigger_kind_has_a_tile_of_its_own() -> None:
    """Falling back for the four Windows events would make the rule list say
    less than its own words already do."""
    from app.automation.rules import TRIGGER_KINDS

    assert set(TRIGGER_KINDS) <= set(_TRIGGER_TILES)


def test_the_icons_actually_render() -> None:
    """A file that exists but will not parse is the same empty square."""
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for name, _colour in _TRIGGER_TILES.values():
        assert QSvgRenderer(str(ICON_DIR / f"{name}.svg")).isValid(), name
