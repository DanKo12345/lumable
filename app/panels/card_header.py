from __future__ import annotations

from PySide6.QtCore import Qt

from app.panels.types import PanelHost
from app.widgets import GlassCard
from app.widgets.clickable_label import ClickableLabel


def add_pro_badge(host: PanelHost, card: GlassCard, tooltip_key: str) -> ClickableLabel:
    """Add the shared compact Pro badge beside a card title."""
    badge = ClickableLabel("Pro")
    badge.setObjectName("proBadge")
    badge.setCursor(Qt.PointingHandCursor)
    badge.setToolTip(host._tr(tooltip_key))
    badge.clicked.connect(host._show_license_overlay)
    badge.hide()
    index = max(0, card.header_layout.count() - 1)
    card.header_layout.insertSpacing(index, host._sz(10))
    card.header_layout.insertWidget(index + 1, badge, 0, Qt.AlignVCenter)
    return badge
