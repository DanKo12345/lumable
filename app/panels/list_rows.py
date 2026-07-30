"""Shared building blocks for grouped setting lists.

Both the timers card and the schedule card are lists of "one setting per row":
an icon tile that carries the meaning, a title (with an optional status line
under it), and the controls pinned to the right. Keeping the construction in one
place is what makes the two cards look like the same product rather than two
takes on the same idea.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.panels.types import PanelHost
from app.theme import qcolor_from_token, theme_manager
from app.ui_metrics import (
    ACTION_HEIGHT,
    ACTION_WIDTH,
    ROW_INSET,
    SPACE_MD,
    SPACE_SM,
    SPACE_XS,
)
from app.widgets import IconTile


class Hairline(QWidget):
    """A 1px separator that paints itself.

    Drawn rather than styled on purpose: a QSS-backed frame inside a layout kept
    collapsing to nothing, so the separators silently disappeared. Painting also
    means the colour follows the palette on a theme switch without a restyle.
    """

    def __init__(self, vertical: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        color = qcolor_from_token(theme_manager.palette["field_border"])
        painter.fillRect(self.rect(), color)


ROW_PAD = ROW_INSET
TILE_GAP = SPACE_MD
CHIP_H = 32       # every chip in a row shares one height
BTN_W = ACTION_WIDTH       # right-most action column
BTN_H = ACTION_HEIGHT


def list_container(host: PanelHost) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("settingsList")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, host._sz(4), 0, host._sz(4))
    layout.setSpacing(0)
    return frame, layout


def list_row(
    host: PanelHost,
    kind: str,
    tint: str,
    title: str,
    *,
    with_status: bool = True,
) -> tuple[QWidget, QHBoxLayout, QLabel, QLabel | None, IconTile]:
    """One row: icon tile, title (+ status), then whatever the caller adds."""
    row = QWidget()
    row.setObjectName("settingsRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    row.setProperty("active", False)
    controls = QHBoxLayout(row)
    controls.setContentsMargins(
        host._sz(ROW_PAD), host._sz(SPACE_SM), host._sz(ROW_PAD), host._sz(SPACE_SM)
    )
    controls.setSpacing(host._sz(SPACE_MD))

    tile = IconTile(kind, tint)
    controls.addWidget(tile, 0, Qt.AlignVCenter)
    controls.addSpacing(host._sz(TILE_GAP - 10))

    info_widget = QWidget()
    info_widget.setObjectName("settingsIdentity")
    info_widget.setMinimumWidth(host._sz(150))
    info = QVBoxLayout(info_widget)
    info.setContentsMargins(0, 0, 0, 0)
    info.setSpacing(host._sz(1))
    title_label = QLabel(title)
    title_label.setObjectName("settingsRowTitle")
    info.addWidget(title_label)
    status: QLabel | None = None
    if with_status:
        status = QLabel("")
        status.setObjectName("settingsRowStatus")
        # A long hint (and the German/Spanish translations are longer still) must
        # wrap instead of setting the column's minimum width — otherwise at 150%
        # Windows scaling it pushes straight into the action button.
        status.setWordWrap(True)
        status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info.addWidget(status)
    controls.addWidget(info_widget, 1, Qt.AlignVCenter)
    return row, controls, title_label, status, tile


def plain_row(host: PanelHost, title: str) -> tuple[QWidget, QHBoxLayout, QLabel]:
    """A secondary setting row aligned with the text of an icon-led row."""
    row = QWidget()
    row.setObjectName("settingsRow")
    row.setAttribute(Qt.WA_StyledBackground, True)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(
        host._sz(ROW_PAD + IconTile.TILE + TILE_GAP),
        host._sz(SPACE_SM),
        host._sz(ROW_PAD),
        host._sz(SPACE_SM),
    )
    layout.setSpacing(host._sz(SPACE_MD))
    label = QLabel(title)
    label.setObjectName("settingsRowTitle")
    layout.addWidget(label, 0, Qt.AlignVCenter)
    layout.addStretch(1)
    return row, layout, label


def caption(text: str) -> QLabel:
    """The quiet lead-in that the chips next to it answer."""
    label = QLabel(text)
    label.setObjectName("settingsRowCaption")
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


def control_group(host: PanelHost, width: int, lead: QLabel | None = None) -> tuple[QWidget, QHBoxLayout]:
    """Fixed-width, right-aligned control cluster.

    The width is shared by every row of a card so the chips end on one vertical.
    An optional lead-in label rides inside the cluster: on a wide window it stays
    glued to the chips it describes instead of drifting into empty space.
    """
    box = QWidget()
    box.setObjectName("settingsControls")
    box.setFixedWidth(host._sz(width))
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(host._sz(SPACE_SM))
    layout.addStretch(1)
    if lead is not None:
        layout.addWidget(lead, 0, Qt.AlignVCenter)
        layout.addSpacing(host._sz(SPACE_XS))
    return box, layout


def half_cell(host: PanelHost, kind: str, tint: str, title: str) -> tuple[QWidget, QHBoxLayout, QLabel]:
    """Half of a paired row — two of these split one row into equal columns.

    Used when two settings are the same kind of thing (an on-time and an
    off-time): side by side they read as a pair, and together they fill a wide
    card instead of leaving a hole in the middle.
    """
    cell = QWidget()
    cell.setObjectName("settingsHalfCell")
    layout = QHBoxLayout(cell)
    layout.setContentsMargins(
        host._sz(ROW_PAD), host._sz(SPACE_SM), host._sz(ROW_PAD), host._sz(SPACE_SM)
    )
    layout.setSpacing(host._sz(SPACE_MD))
    tile = IconTile(kind, tint)
    layout.addWidget(tile, 0, Qt.AlignVCenter)
    layout.addSpacing(host._sz(TILE_GAP - 10))
    label = QLabel(title)
    label.setObjectName("settingsRowTitle")
    # Deliberately no stretch on the title: the value belongs next to its name,
    # not pushed to the far edge of the column.
    layout.addWidget(label, 0, Qt.AlignVCenter)
    return cell, layout, label


def v_divider(host: PanelHost) -> QWidget:
    """Vertical hairline between two half cells."""
    return Hairline(vertical=True)


def divider(host: PanelHost) -> QWidget:
    """Hairline inset to the text column, the way grouped lists separate rows."""
    holder = QWidget()
    holder.setObjectName("settingsDividerHolder")
    holder.setFixedHeight(1)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(host._sz(ROW_PAD + IconTile.TILE + TILE_GAP), 0, host._sz(ROW_PAD), 0)
    layout.setSpacing(0)
    layout.addWidget(Hairline())
    return holder
