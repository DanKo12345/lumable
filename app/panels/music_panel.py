from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.panels.card_header import add_pro_badge
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.ambient_preview import AmbientPreview
from app.widgets.color_swatch import ColorSwatch
from app.widgets.segmented_control import SegmentedControl

_BANDS = (("bass", "music.band_bass"), ("mid", "music.band_mid"), ("treble", "music.band_treble"))


def build_music_section(host: PanelHost) -> GlassCard:
    host.music_card = host._card(host._tr("music.title"), host._tr("music.subtitle"), icon="audio-lines")
    host.music_card.setMinimumHeight(host._sz(196))

    # Pro badge shown when music sync isn't unlocked (toggled by the controller).
    host.music_lock_label = add_pro_badge(host, host.music_card, "music.pro_locked")
    row = QHBoxLayout()
    row.setSpacing(10)
    row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.music_toggle_button = host._button(host._tr("music.toggle_off"), "ghost")
    host.music_toggle_button.setCheckable(True)
    host.music_toggle_button.setFixedSize(host._sz(104), host._sz(42))
    row.addWidget(host.music_toggle_button)

    # Listen to the PC's own audio (speaker loopback) or a real microphone (sound
    # in the room). Toggling this repopulates the device list below.
    host.music_source_segment = SegmentedControl([
        ("system", host._tr("music.source_system")),
        ("mic", host._tr("music.source_mic")),
    ])
    row.addWidget(host.music_source_segment)

    # Which device to capture. Populated by the controller based on the source;
    # the first item is always that source's system default.
    host.music_source_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.music_source_combo.setMinimumHeight(host._control_height)
    host.music_source_combo.setMinimumWidth(host._sz(180))
    host.music_source_combo.setToolTip(host._tr("music.source_hint"))
    row.addWidget(host.music_source_combo)
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

    host.music_beat_slider = host._slider("green")
    host.music_beat_slider.setRange(0, 100)
    host.music_beat_value = host._pill("40%")
    controls.addLayout(
        host._slider_row(
            host._tr("music.beat"),
            host.music_beat_slider,
            host.music_beat_value,
            "music.beat",
        )
    )

    # Noise gate — only meaningful for the microphone (ignores room noise), so it
    # lives in its own container the controller collapses/reveals with the source.
    host.music_gate_slider = host._slider("green")
    host.music_gate_slider.setRange(0, 100)
    host.music_gate_value = host._pill("16%")
    host.music_gate_row = QWidget()
    gate_layout = QVBoxLayout(host.music_gate_row)
    gate_layout.setContentsMargins(0, 0, 0, 0)
    gate_layout.addLayout(
        host._slider_row(
            host._tr("music.gate"),
            host.music_gate_slider,
            host.music_gate_value,
            "music.gate",
        )
    )
    controls.addWidget(host.music_gate_row)

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
