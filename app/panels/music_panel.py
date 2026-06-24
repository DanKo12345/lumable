from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.panels.types import PanelHost
from app.widgets import GlassCard
from app.widgets.ambient_preview import AmbientPreview
from app.widgets.clickable_label import ClickableLabel
from app.widgets.color_swatch import ColorSwatch

_BANDS = (("bass", "music.band_bass"), ("mid", "music.band_mid"), ("treble", "music.band_treble"))


def build_music_section(host: PanelHost) -> GlassCard:
    host.music_card = host._card(host._tr("music.title"), host._tr("music.subtitle"), icon="effects")
    host.music_card.setMinimumHeight(host._sz(196))

    # Pro badge shown when music sync isn't unlocked (toggled by the controller).
    host.music_lock_label = ClickableLabel(host._tr("music.pro_locked"))
    host.music_lock_label.setObjectName("proBadge")
    host.music_lock_label.setStyleSheet(
        "QLabel#proBadge { background: rgba(143, 191, 255, 0.16); color: #9fc0ff;"
        " padding: 5px 12px; border-radius: 11px; }"
        "QLabel#proBadge:hover { background: rgba(143, 191, 255, 0.26); }"
    )
    host.music_lock_label.setCursor(Qt.PointingHandCursor)
    host.music_lock_label.clicked.connect(host._show_license_overlay)
    host.music_lock_label.hide()
    host.music_card.content_layout.addWidget(host.music_lock_label, 0, Qt.AlignLeft)

    row = QHBoxLayout()
    row.setSpacing(10)
    row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.music_toggle_button = host._button(host._tr("music.toggle_off"), "ghost")
    host.music_toggle_button.setCheckable(True)
    host.music_toggle_button.setFixedSize(host._sz(104), host._sz(42))
    row.addWidget(host.music_toggle_button)
    row.addStretch(1)
    host.music_card.content_layout.addLayout(row)

    # Live status ("Слушаю звук…"), shown only while running.
    host.music_status_label = QLabel("")
    host.music_status_label.setObjectName("cardSubtitle")
    host.music_status_label.setVisible(False)
    host.music_card.content_layout.addWidget(host.music_status_label)

    # Live swatch showing the colour currently sent to the strip (same widget as
    # the ambient card, so the two reactive modes look consistent).
    host.music_preview = AmbientPreview()
    # Only shown while music is playing — an empty bar looks out of place idle.
    host.music_preview.setVisible(False)
    host.music_card.content_layout.addWidget(host.music_preview)

    # All tuning controls live in one container so the controller can grey the
    # whole group out (dim + disable) while music is off — like the Schedule card.
    host.music_controls = QWidget()
    controls = QVBoxLayout(host.music_controls)
    controls.setContentsMargins(0, 0, 0, 0)
    controls.setSpacing(host._sz(13))

    host.music_speed_slider = host._slider("red")
    host.music_speed_slider.setRange(0, 100)
    host.music_speed_value = host._pill("30%")
    controls.addLayout(
        host._slider_row(
            host._tr("music.speed"),
            host.music_speed_slider,
            host.music_speed_value,
            "music.speed",
        )
    )

    host.music_saturation_slider = host._slider("purple")
    host.music_saturation_slider.setRange(0, 100)
    host.music_saturation_value = host._pill("60%")
    controls.addLayout(
        host._slider_row(
            host._tr("music.saturation"),
            host.music_saturation_slider,
            host.music_saturation_value,
            "music.saturation",
        )
    )

    host.music_smoothing_slider = host._slider("blue")
    host.music_smoothing_slider.setRange(0, 100)
    host.music_smoothing_value = host._pill("50%")
    controls.addLayout(
        host._slider_row(
            host._tr("music.smoothing"),
            host.music_smoothing_slider,
            host.music_smoothing_value,
            "music.smoothing",
        )
    )

    # Per-band colours: a caption + swatch for bass / mids / treble. Clicking a
    # swatch opens the colour picker (wired in MusicUiController).
    colors_row = QHBoxLayout()
    colors_row.setSpacing(host._sz(18))
    colors_row.setContentsMargins(0, host._sz(6), 0, 0)
    colors_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.music_band_captions = {}
    for band, label_key in _BANDS:
        pair = QHBoxLayout()
        pair.setSpacing(host._sz(8))
        caption = QLabel(host._tr(label_key))
        caption.setObjectName("cardSubtitle")
        swatch = ColorSwatch(lambda: host._theme_tokens)
        setattr(host, f"music_{band}_swatch", swatch)
        host.music_band_captions[band] = caption
        pair.addWidget(caption, 0, Qt.AlignVCenter)
        pair.addWidget(swatch, 0, Qt.AlignVCenter)
        colors_row.addLayout(pair)
    colors_row.addStretch(1)
    controls.addLayout(colors_row)

    host.music_card.content_layout.addWidget(host.music_controls)
    return host.music_card
