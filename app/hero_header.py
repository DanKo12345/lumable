from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.constants import (
    HERO_BUTTON_HEIGHT,
    HERO_CONTROL_SPACING,
    HERO_CONTROLS_MIN_WIDTH,
    HERO_MARGINS,
    HERO_SPACING,
    HERO_TITLE_SPACING,
    LANGUAGE_MIN_WIDTH,
    MODE_BUTTON_HEIGHT,
    MODE_BUTTON_MIN_WIDTH,
    MODE_ROW_SPACING,
)
from app.quick_modes import QUICK_MODES
from app.widgets import AuthorSignatureMark, LiquidButton, StaticPopupComboBox


def build_hero_header(host) -> QFrame:
    hero = QFrame()
    hero.setObjectName("heroPanel")
    hero_layout = QHBoxLayout(hero)
    hero_layout.setContentsMargins(*HERO_MARGINS)
    hero_layout.setSpacing(HERO_SPACING)

    host.hero_signature = AuthorSignatureMark(lambda: host._theme_tokens)
    host.hero_signature.clicked.connect(host._show_license_overlay)

    title_stack = QVBoxLayout()
    title_stack.setSpacing(HERO_TITLE_SPACING)
    host.hero_title = QLabel(host._tr("hero.title"))
    host.hero_title.setObjectName("heroTitle")
    host.hero_subtitle = QLabel(host._tr("hero.subtitle"))
    host.hero_subtitle.setObjectName("heroSubtitle")
    host.hero_title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
    host.hero_subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
    title_stack.addWidget(host.hero_title)
    title_stack.addWidget(host.hero_subtitle)
    title_stack.addLayout(_build_mode_row(host))

    hero_layout.addWidget(host.hero_signature, 0, Qt.AlignVCenter | Qt.AlignLeft)
    hero_layout.addLayout(title_stack, 1)
    hero_layout.addWidget(_build_controls(host), 0, Qt.AlignRight | Qt.AlignVCenter)
    return hero


def _build_mode_row(host) -> QHBoxLayout:
    mode_row = QHBoxLayout()
    mode_row.setContentsMargins(0, 7, 0, 0)
    mode_row.setSpacing(MODE_ROW_SPACING)
    mode_row.setAlignment(Qt.AlignHCenter)
    host._mode_buttons: dict[str, LiquidButton] = {}
    for mode in QUICK_MODES:
        button = host._button(host._tr(f"mode.{mode.key}"), "mode")
        button.setMinimumHeight(MODE_BUTTON_HEIGHT)
        button.setMaximumHeight(MODE_BUTTON_HEIGHT)
        button.setMinimumWidth(MODE_BUTTON_MIN_WIDTH)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        font = button.font()
        font.setPointSize(9)
        font.setWeight(QFont.DemiBold)
        button.setFont(font)
        button.clicked.connect(lambda _checked=False, key=mode.key: host._activate_quick_mode(key))
        host._mode_buttons[mode.key] = button
        mode_row.addWidget(button)
    return mode_row


def _build_controls(host) -> QWidget:
    controls_row = QHBoxLayout()
    controls_row.setContentsMargins(0, 0, 0, 0)
    controls_row.setSpacing(HERO_CONTROL_SPACING)
    controls_row.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)

    host.language_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.language_combo.setObjectName("languageCombo")
    host.language_combo.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.language_combo.setFixedWidth(LANGUAGE_MIN_WIDTH)
    language_font = host.language_combo.font()
    language_font.setPointSize(10)
    language_font.setWeight(QFont.DemiBold)
    host.language_combo.setFont(language_font)

    host.theme_button = host._button("", "ghost")
    host.theme_button.setObjectName("themeButton")
    host.theme_button.setCursor(Qt.PointingHandCursor)
    host.theme_button.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.theme_button.setFixedWidth(LANGUAGE_MIN_WIDTH)
    theme_font = host.theme_button.font()
    theme_font.setPointSize(10)
    theme_font.setWeight(QFont.DemiBold)
    host.theme_button.setFont(theme_font)

    host.about_button = host._button("i", "ghost")
    host.about_button.setObjectName("aboutButton")
    host.about_button.setFixedSize(28, 24)
    about_font = host.about_button.font()
    about_font.setPointSize(10)
    about_font.setWeight(QFont.Bold)
    host.about_button.setFont(about_font)
    host.about_button.clicked.connect(host._show_about_overlay)

    controls_row.addWidget(host.language_combo, 0, Qt.AlignVCenter)
    controls_row.addWidget(host.theme_button, 0, Qt.AlignVCenter)
    controls_row.addWidget(host.about_button, 0, Qt.AlignVCenter)

    controls_wrap = QWidget()
    controls_wrap.setObjectName("heroControlsWrap")
    controls_wrap.setMinimumWidth(HERO_CONTROLS_MIN_WIDTH)
    controls_column = QVBoxLayout(controls_wrap)
    controls_column.setContentsMargins(0, 0, 0, 0)
    controls_column.setSpacing(0)
    controls_column.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    controls_column.addLayout(controls_row)
    return controls_wrap
