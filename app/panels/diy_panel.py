from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.panels.card_header import add_pro_badge
from app.panels.list_rows import Hairline
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.diy_preview_strip import DiyPreviewStrip
from app.widgets.drag_reorder_list import DragReorderList
from app.widgets.segmented_control import SegmentedControl


def build_diy_section(host: PanelHost) -> GlassCard:
    host.diy_card = host._card(host._tr("diy.title"), host._tr("diy.subtitle"), icon="pen-tool")
    host.diy_card.setMinimumHeight(host._sz(340))
    host.diy_card.content_layout.setSpacing(host._sz(12))

    host.diy_lock_label = add_pro_badge(host, host.diy_card, "diy.pro_locked")

    library, library_layout, host.diy_library_label, host.diy_library_hint = _section(
        host, "diy.library"
    )
    library_row = QHBoxLayout()
    library_row.setContentsMargins(0, 0, 0, 0)
    library_row.setSpacing(host._sz(8))
    host.diy_saved_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.diy_saved_combo.setMinimumHeight(host._control_height)
    host.diy_saved_combo.setMinimumWidth(host._sz(180))
    library_row.addWidget(host.diy_saved_combo, 1)

    host.diy_save_button = host._button(host._tr("diy.save"), "accent_soft")
    host.diy_save_button.setMinimumWidth(host._sz(104))
    host.diy_delete_button = _icon_action(host, "trash-2", "diy.delete")
    # Sharing copies a portable effect code; importing brings one into the app.
    # These familiar symbols describe those concrete actions more clearly than
    # a paper plane and an outward-facing upload arrow.
    host.diy_share_button = _icon_action(host, "copy", "diy.share")
    host.diy_import_button = _icon_action(host, "download", "diy.import")
    library_row.addWidget(host.diy_save_button, 0, Qt.AlignVCenter)
    library_row.addWidget(host.diy_delete_button, 0, Qt.AlignVCenter)
    library_row.addWidget(host.diy_share_button, 0, Qt.AlignVCenter)
    library_row.addWidget(host.diy_import_button, 0, Qt.AlignVCenter)
    library_layout.addLayout(library_row)
    host.diy_card.content_layout.addWidget(library)
    host.diy_card.content_layout.addWidget(Hairline())

    timeline, timeline_layout, host.diy_timeline_label, host.diy_timeline_hint = _section(
        host, "diy.timeline", "diy.timeline_hint"
    )
    timeline_layout.setSpacing(host._sz(8))
    host.diy_preview = DiyPreviewStrip()
    host.diy_preview.setMinimumHeight(host._sz(44))
    timeline_layout.addWidget(host.diy_preview)

    host.diy_list = DragReorderList(spacing=host._sz(8))
    timeline_layout.addWidget(host.diy_list)

    add_row = QHBoxLayout()
    add_row.setContentsMargins(0, 0, 0, 0)
    host.diy_add_button = host._button(host._tr("diy.add_step"), "accent_soft")
    add_row.addWidget(host.diy_add_button)
    add_row.addStretch(1)
    timeline_layout.addLayout(add_row)
    host.diy_card.content_layout.addWidget(timeline)
    host.diy_card.content_layout.addWidget(Hairline())

    playback, playback_layout, host.diy_playback_label, host.diy_playback_hint = _section(
        host, "diy.playback"
    )
    options = QHBoxLayout()
    options.setContentsMargins(0, 0, 0, 0)
    options.setSpacing(host._sz(10))
    options.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.diy_transition_label = QLabel(host._tr("diy.transition"))
    host.diy_transition_label.setObjectName("settingsRowTitle")
    options.addWidget(host.diy_transition_label)
    host.diy_transition_segment = SegmentedControl(
        [
            ("smooth", host._tr("diy.transition_smooth")),
            ("cut", host._tr("diy.transition_cut")),
        ]
    )
    options.addWidget(host.diy_transition_segment)
    options.addStretch(1)
    playback_layout.addLayout(options)

    host.diy_speed_slider = host._slider("red")
    host.diy_speed_slider.setRange(0, 100)
    host.diy_speed_value = host._pill("50%")
    playback_layout.addLayout(
        host._slider_row(host._tr("diy.speed"), host.diy_speed_slider, host.diy_speed_value, "diy.speed")
    )

    run_row = QHBoxLayout()
    run_row.setContentsMargins(0, 0, 0, 0)
    run_row.addStretch(1)
    host.diy_run_button = host._button(host._tr("diy.run"), "accent")
    host.diy_run_button.set_icon_kind("circle-play")
    host.diy_run_button.setCheckable(True)
    host.diy_run_button.setMinimumWidth(host._sz(168))
    host.diy_run_button.setMinimumHeight(host._sz(42))
    run_row.addWidget(host.diy_run_button)
    playback_layout.addLayout(run_row)
    host.diy_card.content_layout.addWidget(playback)
    return host.diy_card


def _section(host: PanelHost, title_key: str, hint_key: str | None = None):
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(host._sz(2), host._sz(2), host._sz(2), host._sz(2))
    layout.setSpacing(host._sz(6))

    title = QLabel(host._tr(title_key))
    title.setObjectName("sceneFormHeading")
    layout.addWidget(title)
    hint = QLabel(host._tr(hint_key)) if hint_key else QLabel("")
    hint.setObjectName("cardSubtitle")
    hint.setWordWrap(True)
    hint.setVisible(hint_key is not None)
    if hint_key is not None:
        layout.addWidget(hint)
    return section, layout, title, hint


def _icon_action(host: PanelHost, icon: str, text_key: str):
    label = host._tr(text_key)
    button = host._button("", "ghost")
    button.set_icon_kind(icon)
    button.setIconSize(QSize(17, 17))
    button.setAccessibleName(label)
    button.setToolTip(label)
    button.setFixedSize(host._sz(38), host._sz(38))
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return button
