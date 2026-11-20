from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSizePolicy, QVBoxLayout, QWidget

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


class QuickModeRow(QWidget):
    def __init__(self, host) -> None:
        super().__init__()
        self._host = host
        self._folded: set[LiquidButton] = set()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(MODE_BUTTON_HEIGHT + 7)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 7, 0, 0)
        self.row.setSpacing(MODE_ROW_SPACING)
        self.menu = QMenu(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh()

    def refresh(self) -> None:
        host = self._host
        if not hasattr(host, "save_quick_mode_button"):
            return
        built_in = list(host._mode_buttons.values())
        custom = host._custom_mode_buttons[:len(host._custom_quick_modes)]
        buttons = [*built_in, *custom]
        widths = []
        for button in buttons:
            padding = 34 if button in custom else 20
            width = max(MODE_BUTTON_MIN_WIDTH, button.fontMetrics().horizontalAdvance(button.text()) + padding)
            button.setFixedWidth(width)
            widths.append(width)

        remaining = self.width() - host.save_quick_mode_button.width()
        visible_count = len(buttons)
        required = sum(widths) + MODE_ROW_SPACING * visible_count
        if required > remaining:
            remaining -= self.more_button.width() + MODE_ROW_SPACING
            while visible_count and required > remaining:
                visible_count -= 1
                required -= widths[visible_count] + MODE_ROW_SPACING

        visible = set(buttons[:visible_count])
        self._folded = set(buttons[visible_count:])
        for button in [*built_in, *host._custom_mode_buttons]:
            button.setVisible(button in visible)
        more = host._tr("mode.more")
        self.more_button.setToolTip(more)
        self.more_button.setAccessibleName(more)
        self.more_button.setVisible(bool(self._folded))

    def show_more(self) -> None:
        host = self._host
        self.menu.clear()
        for key, button in host._mode_buttons.items():
            if button in self._folded:
                action = self.menu.addAction(button.text().replace("&", "&&"))
                action.setEnabled(button.isEnabled())
                action.setCheckable(True)
                action.setChecked(key == host._active_mode_key)
                action.triggered.connect(lambda _checked=False, key=key: host._activate_quick_mode(key))
        removable = []
        for index, button in enumerate(host._custom_mode_buttons):
            if button not in self._folded:
                continue
            name = button.toolTip().replace("&", "&&")
            action = self.menu.addAction(name)
            action.setEnabled(button.isEnabled())
            action.setCheckable(True)
            action.setChecked(host._custom_quick_modes[index].get("key") == host._active_mode_key)
            action.triggered.connect(lambda _checked=False, slot=index: host._activate_custom_quick_mode(slot))
            removable.append((index, name))
        if removable:
            self.menu.addSeparator()
            remove = self.menu.addMenu(host._tr("mode.remove_shortcut"))
            for index, name in removable:
                action = remove.addAction(name)
                action.triggered.connect(lambda _checked=False, slot=index: host._delete_custom_quick_mode(slot))
        if not self.menu.isEmpty():
            self.menu.popup(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))


def build_mode_row(host) -> QuickModeRow:
    host.quick_modes_row = QuickModeRow(host)
    mode_row = host.quick_modes_row.row
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
    more_button = host._button("", "ghost")
    more_button.set_icon_kind("more-horizontal")
    more_button.setFixedSize(MODE_BUTTON_HEIGHT, MODE_BUTTON_HEIGHT)
    more_button.clicked.connect(host.quick_modes_row.show_more)
    more_button.hide()
    host.quick_modes_row.more_button = more_button
    mode_row.addWidget(more_button)
    host.save_quick_mode_button = host._button("", "ghost")
    host.save_quick_mode_button.set_icon_kind("plus")
    host.save_quick_mode_button.setFixedSize(MODE_BUTTON_HEIGHT, MODE_BUTTON_HEIGHT)
    host.save_quick_mode_button.clicked.connect(host._save_custom_quick_mode)
    mode_row.addWidget(host.save_quick_mode_button)
    mode_row.addStretch(1)
    return host.quick_modes_row


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
