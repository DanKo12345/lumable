from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel

from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.clickable_label import ClickableLabel
from app.widgets.diy_preview_strip import DiyPreviewStrip
from app.widgets.drag_reorder_list import DragReorderList
from app.widgets.segmented_control import SegmentedControl


def build_diy_section(host: PanelHost) -> GlassCard:
    host.diy_card = host._card(host._tr("diy.title"), host._tr("diy.subtitle"), icon="effects")
    host.diy_card.setMinimumHeight(host._sz(300))

    # Pro badge — clickable, opens the Pro window (feature is Pro-gated).
    host.diy_lock_label = ClickableLabel(host._tr("diy.pro_locked"))
    host.diy_lock_label.setObjectName("proBadge")
    host.diy_lock_label.setStyleSheet(
        "QLabel#proBadge { background: rgba(143, 191, 255, 0.16); color: #9fc0ff;"
        " padding: 5px 12px; border-radius: 11px; }"
        "QLabel#proBadge:hover { background: rgba(143, 191, 255, 0.26); }"
    )
    host.diy_lock_label.setCursor(Qt.PointingHandCursor)
    host.diy_lock_label.clicked.connect(host._show_license_overlay)
    host.diy_lock_label.hide()
    host.diy_card.content_layout.addWidget(host.diy_lock_label, 0, Qt.AlignLeft)

    # Saved-effects library: pick one to load, then save / delete / share / import.
    saved_row = QHBoxLayout()
    saved_row.setSpacing(10)
    host.diy_saved_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.diy_saved_combo.setMinimumHeight(host._control_height)
    host.diy_saved_combo.setMinimumWidth(host._sz(180))
    saved_row.addWidget(host.diy_saved_combo, 1)
    host.diy_card.content_layout.addLayout(saved_row)

    actions_row = QHBoxLayout()
    actions_row.setSpacing(10)
    host.diy_save_button = host._button(host._tr("diy.save"), "ghost")
    host.diy_delete_button = host._button(host._tr("diy.delete"), "ghost")
    host.diy_share_button = host._button(host._tr("diy.share"), "ghost")
    host.diy_import_button = host._button(host._tr("diy.import"), "ghost")
    actions_row.addWidget(host.diy_save_button)
    actions_row.addWidget(host.diy_delete_button)
    actions_row.addStretch(1)
    actions_row.addWidget(host.diy_share_button)
    actions_row.addWidget(host.diy_import_button)
    host.diy_card.content_layout.addLayout(actions_row)

    # Live preview of the colour sequence.
    host.diy_preview = DiyPreviewStrip()
    host.diy_preview.setMinimumHeight(host._sz(26))
    host.diy_card.content_layout.addWidget(host.diy_preview)

    # Colour steps — drag a row to reorder (clean snapshot drag, see DragReorderList).
    host.diy_list = DragReorderList()
    host.diy_card.content_layout.addWidget(host.diy_list)

    host.diy_add_button = host._button(host._tr("diy.add_step"), "ghost")
    add_row = QHBoxLayout()
    add_row.addWidget(host.diy_add_button)
    add_row.addStretch(1)
    host.diy_card.content_layout.addLayout(add_row)

    # Transition (smooth / cut) + speed.
    options = QHBoxLayout()
    options.setSpacing(10)
    options.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.diy_transition_label = QLabel(host._tr("diy.transition"))
    host.diy_transition_label.setObjectName("sliderLabel")
    options.addWidget(host.diy_transition_label)
    host.diy_transition_segment = SegmentedControl([
        ("smooth", host._tr("diy.transition_smooth")),
        ("cut", host._tr("diy.transition_cut")),
    ])
    options.addWidget(host.diy_transition_segment)
    options.addStretch(1)
    host.diy_card.content_layout.addLayout(options)

    host.diy_speed_slider = host._slider("red")
    host.diy_speed_slider.setRange(0, 100)
    host.diy_speed_value = host._pill("50%")
    host.diy_card.content_layout.addLayout(
        host._slider_row(host._tr("diy.speed"), host.diy_speed_slider, host.diy_speed_value, "diy.speed")
    )

    # Run / stop.
    run_row = QHBoxLayout()
    host.diy_run_button = host._button(host._tr("diy.run"), "accent_soft")
    host.diy_run_button.setCheckable(True)
    host.diy_run_button.setMinimumWidth(host._sz(168))
    host.diy_run_button.setMinimumHeight(host._sz(46))
    run_row.addWidget(host.diy_run_button)
    run_row.addStretch(1)
    host.diy_card.content_layout.addLayout(run_row)
    return host.diy_card
