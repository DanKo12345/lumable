"""The saved-scenes tile grid: adaptive columns, keyboard activation, rebuilds.

The grid replaces the old scenes dropdown, so what matters is that it degrades
to fewer columns instead of clipping, that a tile is fully keyboard-operable,
and that a rebuild after save/overwrite keeps the tiles (and the active mark)
consistent.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.widgets.scene_tile_grid import SceneTileData, SceneTileGrid


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _entries(count: int = 7) -> list[SceneTileData]:
    return [
        SceneTileData(scene_id=f"id-{i}", name=f"Scene {i}", color="#3fd2c7", target_label="All strips")
        for i in range(count)
    ]


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (120, 1),   # narrower than one tile — floor at a single column
        (360, 2),
        (540, 3),
        (720, 4),
        (1600, 4),  # capped, tiles stretch instead of a fifth column
    ],
)
def test_column_count_follows_width_including_spacing(width: int, expected: int) -> None:
    _app()
    grid = SceneTileGrid(1.0)
    grid.set_scenes(_entries())
    try:
        assert grid._column_count(width) == expected
    finally:
        grid.deleteLater()


def test_resize_relays_tiles_out() -> None:
    app = _app()
    grid = SceneTileGrid(1.0)
    grid.set_scenes(_entries())
    grid.show()
    try:
        grid.resize(720, 400)
        app.processEvents()
        assert grid._columns == 4
        assert grid._grid.itemAtPosition(0, 3) is not None

        grid.resize(360, 400)
        app.processEvents()
        assert grid._columns == 2
        assert grid._grid.itemAtPosition(0, 1) is not None
        assert grid._grid.itemAtPosition(0, 2) is None
    finally:
        grid.close()
        grid.deleteLater()
        app.processEvents()


def test_enter_and_space_apply_the_focused_tile() -> None:
    app = _app()
    grid = SceneTileGrid(1.0)
    grid.set_scenes(_entries(3))
    fired: list[str] = []
    grid.scene_activated.connect(fired.append)
    try:
        tile = grid.tiles()[1]
        QTest.keyClick(tile, Qt.Key_Space)
        QTest.keyClick(tile, Qt.Key_Return)
        assert fired == ["id-1", "id-1"]
    finally:
        grid.deleteLater()
        app.processEvents()


def test_set_scenes_rebuild_keeps_the_active_mark() -> None:
    app = _app()
    grid = SceneTileGrid(1.0)
    try:
        grid.set_scenes(_entries(2), active_id="id-1")
        assert [tile.is_active() for tile in grid.tiles()] == [False, True]

        # Overwrite/extend: same ids, one renamed, one new — active survives.
        rebuilt = [
            SceneTileData("id-0", "Renamed", "#ff9f6e", "Main strip"),
            SceneTileData("id-1", "Scene 1", "", "All strips"),
            SceneTileData("id-2", "New", "#7f5af0", "All strips"),
        ]
        grid.set_scenes(rebuilt, active_id="id-1")
        assert len(grid.tiles()) == 3
        assert [tile.is_active() for tile in grid.tiles()] == [False, True, False]

        grid.set_active(None)
        assert not any(tile.is_active() for tile in grid.tiles())
    finally:
        grid.deleteLater()
        app.processEvents()


def test_tiles_carry_accessible_names() -> None:
    app = _app()
    grid = SceneTileGrid(1.0)
    grid.set_scenes([SceneTileData("id-0", "Evening", "#ff9f6e", "All strips")])
    try:
        assert grid.tiles()[0].accessibleName() == "Evening — All strips"
    finally:
        grid.deleteLater()
        app.processEvents()
