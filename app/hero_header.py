from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.constants import (
    HERO_BUTTON_HEIGHT,
    HERO_TITLE_SPACING,
    LANGUAGE_MIN_WIDTH,
    MODE_BUTTON_HEIGHT,
    MODE_BUTTON_MIN_WIDTH,
    MODE_ROW_SPACING,
)
from app.quick_modes import QUICK_MODES
from app.widgets import AuthorSignatureMark, LiquidButton, StaticPopupComboBox


def build_brand(host) -> QWidget:
    """Brand block (title + Pro badge + subtitle) for the sidebar top."""
    wrap = QWidget()
    wrap.setObjectName("brandBlock")
    column = QVBoxLayout(wrap)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(HERO_TITLE_SPACING)

    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(5)
    host.hero_title = QLabel(host._tr("hero.title"))
    host.hero_title.setObjectName("heroTitle")
    host.hero_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.hero_signature = AuthorSignatureMark(lambda: host._theme_tokens)
    host.hero_signature.clicked.connect(host._show_license_overlay)
    top.addWidget(host.hero_title, 0, Qt.AlignBottom)
    top.addWidget(host.hero_signature, 0, Qt.AlignTop)
    top.addStretch(1)
    column.addLayout(top)

    host.hero_subtitle = QLabel(host._tr("hero.subtitle"))
    host.hero_subtitle.setObjectName("heroSubtitle")
    host.hero_subtitle.setWordWrap(True)
    host.hero_subtitle.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    column.addWidget(host.hero_subtitle)
    return wrap


def build_mode_row(host) -> QHBoxLayout:
    mode_row = QHBoxLayout()
    mode_row.setContentsMargins(0, 7, 0, 0)
    mode_row.setSpacing(MODE_ROW_SPACING)
    mode_row.setAlignment(Qt.AlignHCenter)
    host._mode_buttons: dict[str, LiquidButton] = {}
    host._custom_mode_buttons: list[LiquidButton] = []
    for mode in QUICK_MODES:
        button = host._button(host._tr(f"mode.{mode.key}"), "mode")
        _prepare_mode_button(button)
        button.clicked.connect(lambda _checked=False, key=mode.key: host._activate_quick_mode(key))
        host._mode_buttons[mode.key] = button
        mode_row.addWidget(button)
    for index in range(4):
        button = host._button("", "mode")
        _prepare_mode_button(button)
        button.hide()
        button.clicked.connect(lambda _checked=False, slot=index: host._activate_custom_quick_mode(slot))
        button.set_embedded_action("x", lambda slot=index: host._delete_custom_quick_mode(slot))
        host._custom_mode_buttons.append(button)
        mode_row.addWidget(button)
    host.save_quick_mode_button = host._button("+", "ghost")
    host.save_quick_mode_button.setFixedSize(MODE_BUTTON_HEIGHT, MODE_BUTTON_HEIGHT)
    host.save_quick_mode_button.clicked.connect(host._save_custom_quick_mode)
    mode_row.addWidget(host.save_quick_mode_button)
    return mode_row


def _prepare_mode_button(button: LiquidButton) -> None:
    button.setMinimumHeight(MODE_BUTTON_HEIGHT)
    button.setMaximumHeight(MODE_BUTTON_HEIGHT)
    button.setMinimumWidth(MODE_BUTTON_MIN_WIDTH)
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    font = button.font()
    font.setPointSize(9)
    font.setWeight(QFont.Weight.DemiBold)
    button.setFont(font)


def build_chrome_controls(host) -> None:
    """Create the app-settings controls (language / FPS / theme / about).

    Widgets are stored on the host; the caller (Settings section) lays them out
    as a labelled list.
    """
    host.language_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.language_combo.setObjectName("languageCombo")
    host.language_combo.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.language_combo.setFixedWidth(LANGUAGE_MIN_WIDTH)
    language_font = host.language_combo.font()
    language_font.setPointSize(10)
    language_font.setWeight(QFont.Weight.DemiBold)
    host.language_combo.setFont(language_font)

    host.theme_button = host._button("", "ghost")
    host.theme_button.setObjectName("themeButton")
    host.theme_button.setCursor(Qt.PointingHandCursor)
    host.theme_button.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.theme_button.setFixedWidth(LANGUAGE_MIN_WIDTH)
    theme_font = host.theme_button.font()
    theme_font.setPointSize(10)
    theme_font.setWeight(QFont.Weight.DemiBold)
    host.theme_button.setFont(theme_font)

    host.performance_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.performance_combo.setObjectName("languageCombo")
    host.performance_combo.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.performance_combo.setFixedWidth(LANGUAGE_MIN_WIDTH)
    performance_font = host.performance_combo.font()
    performance_font.setPointSize(10)
    performance_font.setWeight(QFont.Weight.DemiBold)
    host.performance_combo.setFont(performance_font)

    host.motion_combo = StaticPopupComboBox(lambda: host._theme_tokens, lambda: host._is_dark)
    host.motion_combo.setObjectName("languageCombo")
    host.motion_combo.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.motion_combo.setFixedWidth(LANGUAGE_MIN_WIDTH)
    motion_font = host.motion_combo.font()
    motion_font.setPointSize(10)
    motion_font.setWeight(QFont.Weight.DemiBold)
    host.motion_combo.setFont(motion_font)

    host.about_button = host._button(host._tr("settings.about"), "ghost")
    host.about_button.setObjectName("aboutButton")
    host.about_button.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.about_button.setFixedWidth(LANGUAGE_MIN_WIDTH)
    about_font = host.about_button.font()
    about_font.setPointSize(10)
    about_font.setWeight(QFont.Weight.DemiBold)
    host.about_button.setFont(about_font)
    host.about_button.clicked.connect(host._show_about_overlay)

    # Moving a licence to another computer. A named action rather than a link
    # somebody finds afterwards: the slot is spent the moment a machine is wiped
    # without it, and nothing can hand it back after that.
    host.transfer_license_button = host._button(host._tr("transfer.action"), "ghost")
    host.transfer_license_button.setObjectName("transferLicenseButton")
    host.transfer_license_button.setFixedHeight(HERO_BUTTON_HEIGHT)
    host.transfer_license_button.setFixedWidth(LANGUAGE_MIN_WIDTH)
    transfer_font = host.transfer_license_button.font()
    transfer_font.setPointSize(10)
    transfer_font.setWeight(QFont.Weight.DemiBold)
    host.transfer_license_button.setFont(transfer_font)
    host.transfer_license_button.clicked.connect(host._show_license_transfer)
