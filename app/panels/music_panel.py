from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.panels.card_header import add_pro_badge
from app.panels.list_rows import Hairline, divider, list_container, list_row
from app.panels.types import PanelHost
from app.widgets import GlassCard, StaticPopupComboBox
from app.widgets.ambient_preview import AmbientPreview
from app.widgets.color_swatch import ColorSwatch
from app.widgets.segmented_control import SegmentedControl

_BANDS = (("bass", "music.band_bass"), ("mid", "music.band_mid"), ("treble", "music.band_treble"))
_MODE_TINT = "#ff8ca6"
_SOURCE_TINT = "#72d9b7"


def build_music_section(host: PanelHost) -> GlassCard:
    host.music_card = host._card(host._tr("music.title"), host._tr("music.subtitle"), icon="audio-lines")
    host.music_card.setMinimumHeight(host._sz(196))
    host.music_card.subtitle_label.setMinimumHeight(0)
    host.music_card.subtitle_label.setContentsMargins(0, 0, 0, 0)
    host.music_card.content_layout.setContentsMargins(0, host._sz(8), 0, 0)
    host.music_card.content_layout.setSpacing(host._sz(12))

    # Pro badge shown when music sync isn't unlocked (toggled by the controller).
    host.music_lock_label = add_pro_badge(host, host.music_card, "music.pro_locked")
    host.music_toggle_button = host._button(host._tr("music.toggle_off"), "ghost")
    host.music_toggle_button.setCheckable(True)
    host.music_toggle_button.setFixedSize(host._sz(104), host._sz(42))

    # Listen to the PC's own audio (speaker loopback) or a real microphone (sound
    # in the room). Toggling this repopulates the device list below.
    host.music_source_segment = SegmentedControl([
        ("system", host._tr("music.source_system")),
        ("mic", host._tr("music.source_mic")),
    ])
    host.music_source_segment.set_metrics(pad=host._sz(12))

    # Which device to capture. Populated by the controller based on the source;
    # the first item is always that source's system default.
    host.music_source_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.music_source_combo.setMinimumHeight(host._control_height)
    host.music_source_combo.setMinimumWidth(host._sz(180))
    host.music_source_combo.setToolTip(host._tr("music.source_hint"))

    source_list, source_list_layout = list_container(host)
    mode_row, mode_layout, host.music_mode_label, host.music_status_label, _ = list_row(
        host, "audio-lines", _MODE_TINT, host._tr("music.mode_title")
    )
    assert host.music_status_label is not None
    host.music_status_label.setText(host._tr("music.status_off"))
    mode_layout.addWidget(host.music_toggle_button, 0, Qt.AlignVCenter)
    source_list_layout.addWidget(mode_row)
    source_list_layout.addWidget(divider(host))

    source_row, source_layout, host.music_source_label, host.music_source_description, _ = list_row(
        host, "circle-dot", _SOURCE_TINT, host._tr("music.source_title")
    )
    assert host.music_source_description is not None
    host.music_source_description.setText(host._tr("music.source_system_desc"))
    source_controls = QWidget()
    source_controls_layout = QHBoxLayout(source_controls)
    source_controls_layout.setContentsMargins(0, 0, 0, 0)
    source_controls_layout.setSpacing(host._sz(8))
    source_controls_layout.addWidget(host.music_source_segment)
    source_controls_layout.addWidget(host.music_source_combo, 1)
    source_layout.addWidget(source_controls, 0, Qt.AlignVCenter)
    source_list_layout.addWidget(source_row)
    host.music_card.content_layout.addWidget(source_list)

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
    controls.setSpacing(host._sz(8))

    reaction, reaction_layout, host.music_reaction_label = _section(
        host, host._tr("music.reaction_title")
    )

    host.music_speed_slider = host._slider("red")
    host.music_speed_slider.setRange(0, 100)
    host.music_speed_value = host._pill("30%")
    reaction_layout.addLayout(
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
    reaction_layout.addLayout(
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
    reaction_layout.addWidget(host.music_gate_row)

    host.music_saturation_slider = host._slider("purple")
    host.music_saturation_slider.setRange(0, 100)
    host.music_saturation_value = host._pill("60%")
    reaction_layout.addLayout(
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
    reaction_layout.addLayout(
        host._slider_row(
            host._tr("music.smoothing"),
            host.music_smoothing_slider,
            host.music_smoothing_value,
            "music.smoothing",
        )
    )

    controls.addWidget(reaction)
    controls.addWidget(Hairline())

    # Per-band colours are three equal compact items. Clicking a swatch opens
    # the colour picker (wired in MusicUiController).
    colors, colors_layout, host.music_colors_label = _section(
        host, host._tr("music.colors_title")
    )
    colors_row = QHBoxLayout()
    colors_row.setSpacing(host._sz(8))
    colors_row.setContentsMargins(0, 0, 0, 0)
    host.music_band_captions = {}
    for band, label_key in _BANDS:
        item = QWidget()
        item.setObjectName("settingsRow")
        item.setAttribute(Qt.WA_StyledBackground, True)
        pair = QHBoxLayout(item)
        pair.setContentsMargins(host._sz(10), host._sz(4), host._sz(10), host._sz(4))
        pair.setSpacing(host._sz(8))
        caption = QLabel(host._tr(label_key))
        caption.setObjectName("settingsRowTitle")
        swatch = ColorSwatch(lambda: host._theme_tokens)
        swatch.setFixedSize(host._sz(32), host._sz(32))
        setattr(host, f"music_{band}_swatch", swatch)
        host.music_band_captions[band] = caption
        pair.addStretch(1)
        pair.addWidget(caption, 0, Qt.AlignVCenter)
        pair.addWidget(swatch, 0, Qt.AlignVCenter)
        pair.addStretch(1)
        colors_row.addWidget(item, 1)
    colors_layout.addLayout(colors_row)
    controls.addWidget(colors)

    host.music_card.content_layout.addWidget(host.music_controls)
    return host.music_card


def _section(host: PanelHost, title: str) -> tuple[QWidget, QVBoxLayout, QLabel]:
    section = QWidget()
    section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    layout = QVBoxLayout(section)
    layout.setContentsMargins(host._sz(2), 0, host._sz(2), 0)
    layout.setSpacing(host._sz(5))
    heading = QLabel(title)
    heading.setObjectName("sceneFormHeading")
    layout.addWidget(heading)
    return section, layout, heading
