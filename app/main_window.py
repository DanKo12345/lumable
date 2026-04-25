from __future__ import annotations

import ctypes
import sys
from dataclasses import asdict, dataclass
from datetime import datetime

from PySide6.QtCore import QCoreApplication, QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ble import BleController, EFFECTS
from app.constants import (
    ACTION_SPACING,
    BODY_SPACING,
    CHIP_HEIGHT,
    CONTROL_HEIGHT,
    DEVICE_ACTION_MIN_WIDTH,
    DEVICE_CONTENT_TOP_MARGIN,
    EFFECTS_CONTENT_TOP_MARGIN,
    HERO_CONTROLS_MIN_WIDTH,
    HERO_CONTROL_SPACING,
    HERO_BUTTON_HEIGHT,
    HERO_MARGINS,
    MODE_BUTTON_HEIGHT,
    MODE_BUTTON_MIN_WIDTH,
    MODE_ROW_SPACING,
    HERO_SPACING,
    HERO_TITLE_SPACING,
    LANGUAGE_MIN_WIDTH,
    ROOT_MARGINS,
    ROOT_SPACING,
    ROW_SPACING,
    ROW_SPACING_TIGHT,
    ROW_TOP_MARGIN,
    SAVE_BUTTON_MIN_WIDTH,
    SCAN_BUTTON_MIN_WIDTH,
    SECTION_SPACING,
    SLIDER_ROW_MARGINS,
    SLIDER_ROW_SPACING,
    STATUS_MIN_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from app.localization import localization_manager
from app.profile_controller import ProfileController
from app.quick_modes import QUICK_MODE_MAP, QUICK_MODES
from app.styles import build_theme_stylesheet
from app.storage import load_profiles, load_settings, save_settings
from app.theme import theme_manager
from app.ui_feedback import UiFeedback
from app.widgets import (
    AccentPreview,
    AuroraBackground,
    EffectPreviewStrip,
    GlassCard,
    LiquidButton,
    LiquidSlider,
    SmoothScrollFilter,
    StaticPopupComboBox,
)


@dataclass
class ProfileState:
    name: str
    power: bool
    brightness: int
    speed: int
    effect_code: int
    color: dict


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(localization_manager.t("dialog.title"))
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self._control_height = CONTROL_HEIGHT
        self._chip_height = CHIP_HEIGHT
        self._settings = load_settings()
        self._theme_mode = self._settings.get("theme_mode") or self._settings.get("theme", "dark")
        self._language = self._settings.get("language", "ru")
        localization_manager.set_language(self._language)
        if self._theme_mode not in {"dark", "light", "auto"}:
            self._theme_mode = "auto"
        self._is_dark = self._resolve_dark_from_mode(self._theme_mode)
        self._theme_tokens = theme_manager.set_dark(self._is_dark)
        self._profiles = load_profiles()
        self._profile_controller = ProfileController(self._profiles)
        self._devices = []
        self._is_connected = False
        self._ble = BleController()
        self._initializing = True
        self._scan_in_progress = False
        self._active_mode_key: str | None = None
        self._theme_transition = None
        self._theme_transition_overlay = None
        self._auto_theme_timer = QTimer(self)
        self._auto_theme_timer.setInterval(60_000)
        self._auto_theme_timer.timeout.connect(self._refresh_auto_theme)
        self._auto_theme_timer.start()
        self._aurora = AuroraBackground(self)
        self._aurora.lower()
        self._buttons: list[LiquidButton] = []
        self._slider_labels: dict[str, QLabel] = {}
        self._build_ui()
        self._apply_theme()
        self._wire_events()
        self._load_initial_state()
        self._apply_windows_backdrop()

    def _tr(self, key: str, **kwargs) -> str:
        return localization_manager.t(key, **kwargs)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("rootWidget")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(*ROOT_MARGINS)
        root_layout.setSpacing(ROOT_SPACING)

        hero = QFrame()
        hero.setObjectName("heroPanel")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(*HERO_MARGINS)
        hero_layout.setSpacing(HERO_SPACING)
        self.hero_signature = QLabel("by dollza")
        self.hero_signature.setObjectName("heroSignature")
        self.hero_signature.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.hero_signature.setMinimumWidth(220)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(HERO_TITLE_SPACING)
        self.hero_title = QLabel(self._tr("hero.title"))
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel(self._tr("hero.subtitle"))
        self.hero_subtitle.setObjectName("heroSubtitle")
        self.hero_title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.hero_subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        title_stack.addWidget(self.hero_title)
        title_stack.addWidget(self.hero_subtitle)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 7, 0, 0)
        mode_row.setSpacing(MODE_ROW_SPACING)
        mode_row.setAlignment(Qt.AlignHCenter)
        self._mode_buttons: dict[str, LiquidButton] = {}
        for mode in QUICK_MODES:
            button = self._button(self._tr(f"mode.{mode.key}"), "mode")
            button.setMinimumHeight(MODE_BUTTON_HEIGHT)
            button.setMaximumHeight(MODE_BUTTON_HEIGHT)
            button.setMinimumWidth(MODE_BUTTON_MIN_WIDTH)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            font = button.font()
            font.setPointSize(9)
            font.setWeight(QFont.DemiBold)
            button.setFont(font)
            button.clicked.connect(lambda _checked=False, key=mode.key: self._activate_quick_mode(key))
            self._mode_buttons[mode.key] = button
            mode_row.addWidget(button)
        title_stack.addLayout(mode_row)
        hero_layout.addWidget(self.hero_signature, 0, Qt.AlignVCenter | Qt.AlignLeft)
        hero_layout.addLayout(title_stack, 1)
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(HERO_CONTROL_SPACING)
        self.language_combo = StaticPopupComboBox(lambda: self._theme_tokens, lambda: self._is_dark)
        self.language_combo.setObjectName("languageCombo")
        self.language_combo.setMinimumHeight(HERO_BUTTON_HEIGHT)
        self.language_combo.setMaximumHeight(HERO_BUTTON_HEIGHT)
        self.language_combo.setMinimumWidth(LANGUAGE_MIN_WIDTH)
        language_font = self.language_combo.font()
        language_font.setPointSize(10)
        language_font.setWeight(QFont.DemiBold)
        self.language_combo.setFont(language_font)
        self.theme_button = self._button("", "ghost")
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.setMinimumHeight(HERO_BUTTON_HEIGHT)
        self.theme_button.setMaximumHeight(HERO_BUTTON_HEIGHT)
        theme_font = self.theme_button.font()
        theme_font.setPointSize(10)
        theme_font.setWeight(QFont.DemiBold)
        self.theme_button.setFont(theme_font)
        controls_row.addWidget(self.language_combo, 0, Qt.AlignVCenter)
        controls_row.addWidget(self.theme_button, 0, Qt.AlignVCenter)
        controls_wrap = QWidget()
        controls_wrap.setObjectName("heroControlsWrap")
        controls_wrap.setLayout(controls_row)
        controls_wrap.setMinimumWidth(HERO_CONTROLS_MIN_WIDTH)
        hero_layout.addWidget(controls_wrap, 0, Qt.AlignVCenter | Qt.AlignRight)
        root_layout.addWidget(hero)

        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.NoFrame)
        self.body_scroll.setObjectName("bodyScroll")
        root_layout.addWidget(self.body_scroll, 1)
        self.body_canvas = QWidget()
        self.body_canvas.setObjectName("bodyCanvas")
        self.body_scroll.setWidget(self.body_canvas)

        body_layout = QHBoxLayout(self.body_canvas)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(BODY_SPACING)
        body_layout.setAlignment(Qt.AlignTop)
        left = QVBoxLayout()
        right = QVBoxLayout()
        left.setSpacing(SECTION_SPACING)
        right.setSpacing(SECTION_SPACING)
        left.setAlignment(Qt.AlignTop)
        right.setAlignment(Qt.AlignTop)
        body_layout.addLayout(left, 3)
        body_layout.addLayout(right, 2)

        left.addWidget(self._build_device_section())
        left.addWidget(self._build_color_section())
        left.addWidget(self._build_effects_section())

        right.addWidget(self._build_configs_section())
        right.addWidget(self._build_logs_section())
        right.addStretch(1)
        left.addStretch(1)

        self._apply_localized_texts()
        self._install_smooth_scroll(self.profile_list, step=54, duration=185)
        self._install_smooth_scroll(self.log_output, step=54, duration=185)
        self._install_smooth_scroll(self.body_scroll, step=72, duration=210)
        self._ui_feedback = UiFeedback(self, self.log_output, lambda: self._theme_tokens, self._tr)
        self.setCentralWidget(root)

    def _build_device_section(self) -> GlassCard:
        self.device_card = self._card(self._tr("device.title"), self._tr("device.subtitle"))
        self.device_card.setMinimumHeight(162)
        self.device_card.content_layout.setContentsMargins(0, DEVICE_CONTENT_TOP_MARGIN, 0, 0)

        row = QHBoxLayout()
        row.setSpacing(ROW_SPACING)
        row.setContentsMargins(0, ROW_TOP_MARGIN, 0, 0)
        self.device_combo = StaticPopupComboBox(lambda: self._theme_tokens, lambda: self._is_dark)
        self.device_combo.setMinimumHeight(self._control_height)
        self.scan_button = self._button(self._tr("device.find"), "accent_soft")
        self.scan_button.setMinimumWidth(SCAN_BUTTON_MIN_WIDTH)
        row.addWidget(self.device_combo, 1)
        row.addWidget(self.scan_button)
        self.device_card.content_layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(ROW_SPACING_TIGHT)
        row2.setContentsMargins(0, ROW_TOP_MARGIN, 0, 0)
        self.device_status = QLabel(self._tr("device.status.not_connected"))
        self.device_status.setObjectName("statusChip")
        self.device_status.setAlignment(Qt.AlignCenter)
        self.device_status.setMinimumHeight(self._chip_height)
        self.device_status.setMinimumWidth(STATUS_MIN_WIDTH)
        self.connect_button = self._button(self._tr("device.connect"), "ghost")
        self.disconnect_button = self._button(self._tr("device.disconnect"), "ghost")
        self.logs_toggle_button = self._button(self._tr("device.show_logs"), "ghost")
        for button in (self.connect_button, self.disconnect_button, self.logs_toggle_button):
            button.setMinimumWidth(DEVICE_ACTION_MIN_WIDTH)
        row2.addWidget(self.device_status, 0)
        row2.addStretch(1)
        row2.addWidget(self.connect_button)
        row2.addWidget(self.disconnect_button)
        row2.addWidget(self.logs_toggle_button)
        self.device_card.content_layout.addLayout(row2)
        return self.device_card

    def _build_color_section(self) -> GlassCard:
        self.color_card = self._card(self._tr("color.title"), self._tr("color.subtitle"))
        self.color_card.setMinimumHeight(468)
        self.preview = AccentPreview()
        self.color_card.content_layout.addWidget(self.preview)

        self.red_slider = self._slider("red")
        self.green_slider = self._slider("green")
        self.blue_slider = self._slider("blue")
        self.red_slider.setRange(0, 255)
        self.green_slider.setRange(0, 255)
        self.blue_slider.setRange(0, 255)
        self.brightness_slider = self._slider("yellow")
        self.brightness_slider.setRange(0, 100)
        self.red_value = self._pill("0")
        self.green_value = self._pill("0")
        self.blue_value = self._pill("0")
        self.brightness_value = self._pill("100%")
        self.color_card.content_layout.addLayout(self._slider_row(self._tr("slider.red"), self.red_slider, self.red_value, "slider.red"))
        self.color_card.content_layout.addLayout(self._slider_row(self._tr("slider.green"), self.green_slider, self.green_value, "slider.green"))
        self.color_card.content_layout.addLayout(self._slider_row(self._tr("slider.blue"), self.blue_slider, self.blue_value, "slider.blue"))
        self.color_card.content_layout.addLayout(self._slider_row(self._tr("slider.brightness"), self.brightness_slider, self.brightness_value, "slider.brightness"))

        color_actions = QHBoxLayout()
        color_actions.setSpacing(ACTION_SPACING)
        self.pick_color_button = self._button(self._tr("color.pick"), "ghost")
        self.apply_color_button = self._button(self._tr("color.apply"), "primary_warm")
        self.power_button = self._button(self._tr("power.on"), "ghost")
        self.power_button.setCheckable(True)
        color_actions.addWidget(self.pick_color_button, 9)
        color_actions.addWidget(self.apply_color_button, 10)
        color_actions.addWidget(self.power_button, 9)
        self.color_card.content_layout.addLayout(color_actions)
        return self.color_card

    def _build_effects_section(self) -> GlassCard:
        self.effects_card = self._card(self._tr("effects.title"), self._tr("effects.subtitle"))
        self.effects_card.setMinimumHeight(260)
        self.effects_card.content_layout.setContentsMargins(0, EFFECTS_CONTENT_TOP_MARGIN, 0, 0)
        self.effect_combo = StaticPopupComboBox(lambda: self._theme_tokens, lambda: self._is_dark)
        self.effect_combo.setMinimumHeight(self._control_height)
        self._effect_key_by_code = {effect.code: effect.key for effect in EFFECTS}
        for effect in EFFECTS:
            self.effect_combo.addItem(localization_manager.effect_name(effect.key), effect.code)
        self.effect_preview = EffectPreviewStrip()
        self.speed_slider = self._slider("purple")
        self.speed_slider.setRange(0, 100)
        self.speed_value = self._pill("60%")
        self.effects_card.content_layout.addWidget(self.effect_combo)
        self.effects_card.content_layout.addWidget(self.effect_preview)
        self.effects_card.content_layout.addLayout(self._slider_row(self._tr("effects.speed"), self.speed_slider, self.speed_value, "effects.speed"))
        return self.effects_card

    def _build_configs_section(self) -> GlassCard:
        self.configs_card = self._card(self._tr("configs.title"), self._tr("configs.subtitle"))
        self.configs_card.setMinimumHeight(404)
        config_top = QHBoxLayout()
        config_top.setSpacing(ROW_SPACING_TIGHT)
        config_top.setContentsMargins(0, ROW_TOP_MARGIN, 0, 0)
        self.profile_name = QLineEdit()
        self.profile_name.setMinimumHeight(self._control_height)
        self.profile_name.setPlaceholderText(self._tr("configs.placeholder"))
        self.save_profile_button = self._button(self._tr("configs.save"), "accent_soft")
        self.save_profile_button.setMinimumWidth(SAVE_BUTTON_MIN_WIDTH)
        config_top.addWidget(self.profile_name, 1)
        config_top.addWidget(self.save_profile_button)
        self.configs_card.content_layout.addLayout(config_top)

        self.profile_list = QListWidget()
        self.profile_list.setObjectName("profileList")
        self.profile_list.setMinimumHeight(250)
        self.profile_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.profile_list.verticalScrollBar().setSingleStep(18)
        self.configs_card.content_layout.addWidget(self.profile_list)

        config_bottom = QHBoxLayout()
        config_bottom.setSpacing(ACTION_SPACING)
        self.load_profile_button = self._button(self._tr("configs.load"), "ghost")
        self.delete_profile_button = self._button(self._tr("configs.delete"), "ghost")
        self.reset_profiles_button = self._button(self._tr("configs.reset"), "ghost")
        for button in (self.load_profile_button, self.delete_profile_button, self.reset_profiles_button):
            button.setMinimumWidth(138)
        config_bottom.addWidget(self.load_profile_button)
        config_bottom.addWidget(self.delete_profile_button)
        config_bottom.addWidget(self.reset_profiles_button)
        self.configs_card.content_layout.addLayout(config_bottom)
        return self.configs_card

    def _build_logs_section(self) -> GlassCard:
        self.info_card = self._card(self._tr("logs.title"), self._tr("logs.subtitle"))
        self.info_card.setMinimumHeight(214)
        self.log_output = QTextEdit()
        self.log_output.setObjectName("logOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(156)
        self.log_output.verticalScrollBar().setSingleStep(18)
        self.info_card.content_layout.addWidget(self.log_output)
        return self.info_card

    def _apply_localized_texts(self):
        self.hero_title.setText(self._tr("hero.title"))
        self.hero_subtitle.setText(self._tr("hero.subtitle"))
        self._refresh_language_options()
        self._refresh_quick_mode_buttons()

        self.device_card.title_label.setText(self._tr("device.title"))
        if self.device_card.subtitle_label is not None:
            self.device_card.subtitle_label.setText(self._tr("device.subtitle"))
        self.scan_button.setText(self._tr("device.find"))
        self.connect_button.setText(self._tr("device.connect"))
        self.disconnect_button.setText(self._tr("device.disconnect"))
        self.device_status.setText(self._tr("device.status.connected") if self._is_connected else self._tr("device.status.not_connected"))
        self.logs_toggle_button.setText(self._tr("device.hide_logs") if self.info_card.isVisible() else self._tr("device.show_logs"))

        self.color_card.title_label.setText(self._tr("color.title"))
        if self.color_card.subtitle_label is not None:
            self.color_card.subtitle_label.setText(self._tr("color.subtitle"))
        self.pick_color_button.setText(self._tr("color.pick"))
        self.apply_color_button.setText(self._tr("color.apply"))
        self._sync_power_button()
        self._set_slider_label_text("slider.red", self._tr("slider.red"))
        self._set_slider_label_text("slider.green", self._tr("slider.green"))
        self._set_slider_label_text("slider.blue", self._tr("slider.blue"))
        self._set_slider_label_text("slider.brightness", self._tr("slider.brightness"))

        self.effects_card.title_label.setText(self._tr("effects.title"))
        if self.effects_card.subtitle_label is not None:
            self.effects_card.subtitle_label.setText(self._tr("effects.subtitle"))
        self._set_slider_label_text("effects.speed", self._tr("effects.speed"))

        self.configs_card.title_label.setText(self._tr("configs.title"))
        if self.configs_card.subtitle_label is not None:
            self.configs_card.subtitle_label.setText(self._tr("configs.subtitle"))
        self.profile_name.setPlaceholderText(self._tr("configs.placeholder"))
        self.save_profile_button.setText(self._tr("configs.save"))
        self.load_profile_button.setText(self._tr("configs.load"))
        self.delete_profile_button.setText(self._tr("configs.delete"))
        self.reset_profiles_button.setText(self._tr("configs.reset"))

        self.info_card.title_label.setText(self._tr("logs.title"))
        if self.info_card.subtitle_label is not None:
            self.info_card.subtitle_label.setText(self._tr("logs.subtitle"))
        self._refresh_effect_names()
        self._refresh_profiles()

    def _refresh_effect_names(self):
        current_code = self.effect_combo.currentData()
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for effect in EFFECTS:
            self.effect_combo.addItem(localization_manager.effect_name(effect.key), effect.code)
        idx = self.effect_combo.findData(current_code)
        self.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.effect_combo.blockSignals(False)

    def _refresh_language_options(self):
        current_language = self._language
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        for language in localization_manager.available_languages():
            self.language_combo.addItem(localization_manager.language_name(language), language)
        index = self.language_combo.findData(current_language)
        self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        self.language_combo.blockSignals(False)

    def _refresh_localized_log_lines(self):
        self._ui_feedback.refresh_logs()

    def _set_slider_label_text(self, key: str, text: str):
        label = self._slider_labels.get(key)
        if label is not None:
            label.setText(text)

    def _card(self, title: str, subtitle: str | None = None) -> GlassCard:
        return GlassCard(title, subtitle)

    def _button(self, text: str, role: str) -> LiquidButton:
        button = LiquidButton(text, role)
        font = button.font()
        font.setPointSize(11)
        font.setWeight(QFont.DemiBold)
        button.setFont(font)
        self._buttons.append(button)
        return button

    def _slider(self, accent: str) -> LiquidSlider:
        return LiquidSlider(accent)

    def _pill(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("valueChip")
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumWidth(68)
        label.setMinimumHeight(CHIP_HEIGHT)
        return label

    def _slider_row(self, name: str, slider: LiquidSlider, value: QLabel, key: str | None = None):
        layout = QHBoxLayout()
        layout.setSpacing(SLIDER_ROW_SPACING)
        layout.setContentsMargins(*SLIDER_ROW_MARGINS)
        label = QLabel(name)
        label.setObjectName("sliderLabel")
        label.setMinimumWidth(84)
        if key is not None:
            self._slider_labels[key] = label
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value, 0)
        return layout

    def _install_smooth_scroll(self, widget, step: int = 58, duration: int = 180):
        viewport = widget.viewport() if hasattr(widget, "viewport") else widget
        scroll_filter = SmoothScrollFilter(widget, step=step, duration=duration)
        viewport.installEventFilter(scroll_filter)
        if not hasattr(self, "_scroll_filters"):
            self._scroll_filters = []
        self._scroll_filters.append(scroll_filter)

    def _theme_stylesheet(self) -> str:
        return build_theme_stylesheet(self._theme_tokens)

    def _apply_slider_theme(self):
        slider_accents = {
            self.red_slider: "red",
            self.green_slider: "green",
            self.blue_slider: "blue",
            self.brightness_slider: "yellow",
            self.speed_slider: "purple",
        }
        for slider, accent in slider_accents.items():
            slider.set_accent_color(accent)
            slider.update()

    def _refresh_theme_widgets(self):
        if hasattr(self.language_combo, "_apply_popup_style"):
            self.language_combo._apply_popup_style()
        if hasattr(self.device_combo, "_apply_popup_style"):
            self.device_combo._apply_popup_style()
        if hasattr(self.effect_combo, "_apply_popup_style"):
            self.effect_combo._apply_popup_style()
        self.body_scroll.viewport().setStyleSheet("background: transparent;")
        self._sync_theme_button()
        self.preview.set_theme("dark" if self._is_dark else "light")
        self.effect_preview.update()
        for button in self._buttons:
            button.update()
        for slider in (self.red_slider, self.green_slider, self.blue_slider, self.brightness_slider, self.speed_slider):
            slider.update()

    def _apply_theme(self):
        theme_manager.set_dark(self._is_dark)
        mode = QUICK_MODE_MAP.get(self._active_mode_key or "")
        self._theme_tokens = theme_manager.set_accent_override(None if mode is None else QColor(mode.accent))
        self._aurora.set_dark(self._is_dark)
        app = QApplication.instance()
        if app:
            app.setFont(QFont("Segoe UI Variable Text", 10))
        self.setStyleSheet(self._theme_stylesheet())
        self._apply_slider_theme()
        self._refresh_theme_widgets()

    def _wire_events(self):
        self._wire_device_events()
        self._wire_theme_events()
        self._wire_color_events()
        self._wire_profile_events()
        self._wire_ble_events()

    def _wire_device_events(self):
        self.scan_button.clicked.connect(self._start_scan)
        self.connect_button.clicked.connect(self._handle_connect)
        self.disconnect_button.clicked.connect(self._ble.disconnect)
        self.logs_toggle_button.clicked.connect(self._toggle_logs)

    def _wire_theme_events(self):
        self.theme_button.clicked.connect(self._toggle_theme)
        self.language_combo.currentIndexChanged.connect(self._change_language)

    def _wire_color_events(self):
        self.pick_color_button.clicked.connect(self._pick_color)
        self.apply_color_button.clicked.connect(self._apply_current_color)
        self.power_button.clicked.connect(self._toggle_power)
        self.effect_combo.currentIndexChanged.connect(self._apply_selected_effect)
        self.speed_slider.valueChanged.connect(lambda v: self.speed_value.setText(f"{v}%"))
        self.speed_slider.valueChanged.connect(self.effect_preview.set_speed)
        self.speed_slider.valueChanged.connect(lambda _v: self._sync_quick_mode_from_state())
        self.speed_slider.sliderReleased.connect(self._apply_speed)
        self._wire_rgb_slider_events()
        self.brightness_slider.valueChanged.connect(lambda v: self.brightness_value.setText(f"{v}%"))
        self.brightness_slider.valueChanged.connect(self.preview.set_brightness)
        self.brightness_slider.valueChanged.connect(lambda _v: self._sync_quick_mode_from_state())

    def _wire_rgb_slider_events(self):
        for slider, label in (
            (self.red_slider, self.red_value),
            (self.green_slider, self.green_value),
            (self.blue_slider, self.blue_value),
        ):
            slider.valueChanged.connect(lambda v, t=label: t.setText(str(v)))
            slider.valueChanged.connect(self._update_preview)
            slider.valueChanged.connect(lambda _v: self._sync_quick_mode_from_state())

    def _wire_profile_events(self):
        self.save_profile_button.clicked.connect(self._save_profile)
        self.load_profile_button.clicked.connect(self._load_selected_profile)
        self.delete_profile_button.clicked.connect(self._delete_selected_profile)
        self.reset_profiles_button.clicked.connect(self._reset_profiles)

    def _wire_ble_events(self):
        self._ble.status_changed.connect(self._log)
        self._ble.devices_discovered.connect(self._populate_devices)
        self._ble.connected_changed.connect(self._on_connected_changed)
        self._ble.error_occurred.connect(self._show_error)

    def _load_initial_state(self):
        self.resize(self._settings.get("window_width", 1320), self._settings.get("window_height", 860))
        last = self._settings.get("last_state", {})
        color = last.get("color", {"r": 88, "g": 182, "b": 255})
        self.red_slider.setValue(int(color.get("r", 88)))
        self.green_slider.setValue(int(color.get("g", 182)))
        self.blue_slider.setValue(int(color.get("b", 255)))
        self.brightness_slider.setValue(int(last.get("brightness", 100)))
        self.speed_slider.setValue(int(last.get("speed", 60)))
        idx = self.effect_combo.findData(int(last.get("effect_code", 0)))
        self.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.power_button.setChecked(bool(last.get("power", True)))
        self._sync_power_button()
        self._refresh_profiles()
        self._update_preview()
        self.preview.set_brightness(self.brightness_slider.value())
        self._sync_effect_preview()
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.info_card.hide()
        self._log(self._tr("status.ready_find"))
        self._initializing = False
        self._sync_quick_mode_from_state(preferred=self._settings.get("quick_mode"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._aurora.setGeometry(0, 0, self.width(), self.height())

    def _apply_windows_backdrop(self):
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        value = ctypes.c_int(2)
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    def _start_scan(self):
        self._scan_in_progress = True
        self._devices = []
        self.device_combo.clear()
        self.device_combo.addItem(self._tr("device.choice.scan_placeholder"))
        self.device_status.setText(self._tr("device.status.scanning"))
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self._ble.scan()

    def _handle_connect(self):
        if self._scan_in_progress:
            self._show_error(self._tr("error.wait_scan"))
            return
        index = self.device_combo.currentIndex()
        if index < 0 or index >= len(self._devices):
            self._show_error(self._tr("error.find_first"))
            return
        self._ble.connect_to_address(self._devices[index]["address"])

    def _populate_devices(self, devices):
        self._scan_in_progress = False
        self._devices = devices
        self.device_combo.clear()
        if not devices:
            self.device_combo.addItem(self._tr("device.choice.not_found"))
            self.device_status.setText(self._tr("device.status.not_found"))
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(False)
            return
        for device in devices:
            self.device_combo.addItem(f"{device['name']}  |  {device['address']}  |  RSSI {device['rssi']}", device["address"])
        preferred = self._settings.get("last_device_address", "")
        preferred_index = self.device_combo.findData(preferred) if preferred else -1
        self.device_combo.setCurrentIndex(preferred_index if preferred_index >= 0 else 0)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        if len(devices) == 1:
            device = devices[0]
            self.device_status.setText(self._tr("device.status.found_one", name=device["name"]))
            self._log(self._tr("status.autofound_connecting", name=device["name"], address=device["address"]))
            self._ble.connect_to_address(device["address"])
        else:
            self.device_status.setText(self._tr("device.status.found_many", count=len(devices)))

    def _on_connected_changed(self, connected, address):
        self._is_connected = connected
        self.device_status.setText(self._tr("device.status.connected") if connected else self._tr("device.status.not_connected"))
        self.connect_button.setEnabled(not connected and bool(self._devices))
        self.disconnect_button.setEnabled(connected)
        self._refresh_quick_mode_buttons()
        if connected:
            self._settings["last_device_address"] = address
            save_settings(self._settings)

    def _current_color(self):
        return QColor(self.red_slider.value(), self.green_slider.value(), self.blue_slider.value())

    def _update_preview(self):
        self.preview.set_color(self._current_color())

    def _sync_effect_preview(self, *, reset_phase: bool = False):
        code = int(self.effect_combo.currentData() or 0)
        self.effect_preview.set_effect(self._effect_key_by_code.get(code, "static_color"), code, reset_phase=reset_phase)
        self.effect_preview.set_speed(self.speed_slider.value())

    def _pick_color(self):
        color = QColorDialog.getColor(self._current_color(), self, self._tr("dialog.pick_color"))
        if not color.isValid():
            return
        self.red_slider.setValue(color.red())
        self.green_slider.setValue(color.green())
        self.blue_slider.setValue(color.blue())
        self._apply_current_color()

    def _apply_current_color(self):
        if self._initializing:
            return
        color = self._current_color()
        self._ble.set_brightness(self.brightness_slider.value())
        self._ble.set_color(color.red(), color.green(), color.blue())
        if self.effect_combo.currentData() != 0:
            self._initializing = True
            self.effect_combo.setCurrentIndex(0)
            self._initializing = False
        self._sync_quick_mode_from_state()

    def _toggle_power(self):
        self._sync_power_button()
        if self._initializing:
            return
        self._ble.set_power(self.power_button.isChecked())
        self._sync_quick_mode_from_state()

    def _sync_power_button(self):
        self.power_button.setText(self._tr("power.off") if self.power_button.isChecked() else self._tr("power.on"))

    def _apply_speed(self):
        if self._initializing:
            return
        self._ble.set_effect_speed(self.speed_slider.value())
        self._sync_quick_mode_from_state()

    def _apply_selected_effect(self):
        if self._initializing:
            return
        code = int(self.effect_combo.currentData())
        if code == 0:
            self._ble.set_brightness(self.brightness_slider.value())
            self._ble.set_color(self.red_slider.value(), self.green_slider.value(), self.blue_slider.value())
            self._log(self._tr("status.static_color_mode"))
            self._sync_effect_preview(reset_phase=True)
            self._sync_quick_mode_from_state()
            return
        self._ble.set_effect_with_speed(code, self.speed_slider.value())
        self._sync_effect_preview(reset_phase=True)
        self._sync_quick_mode_from_state()

    def _toggle_logs(self):
        visible = not self.info_card.isVisible()
        self.info_card.setVisible(visible)
        self.logs_toggle_button.setText(self._tr("device.hide_logs") if visible else self._tr("device.show_logs"))

    def _sync_theme_button(self):
        labels = {
            "dark": self._tr("theme.dark"),
            "light": self._tr("theme.light"),
            "auto": self._tr("theme.auto"),
        }
        self.theme_button.setText(labels.get(self._theme_mode, self._tr("theme.auto")))

    def _change_language(self):
        language = self.language_combo.currentData()
        if not isinstance(language, str) or language == self._language:
            return
        snapshot = self.grab()
        self._language = language
        localization_manager.set_language(language)
        self._settings["language"] = language
        save_settings(self._settings)
        self.setWindowTitle(self._tr("dialog.title"))
        self._apply_localized_texts()
        self._refresh_localized_log_lines()
        self._sync_theme_button()
        self.preview.refresh_text()
        self._animate_overlay_fade(snapshot, duration=210)

    def _toggle_theme(self):
        snapshot = self.grab()
        order = ("dark", "light", "auto")
        current_index = order.index(self._theme_mode) if self._theme_mode in order else 0
        self._theme_mode = order[(current_index + 1) % len(order)]
        self._is_dark = self._resolve_dark_from_mode(self._theme_mode)
        self._settings["theme_mode"] = self._theme_mode
        self._settings["theme"] = "dark" if self._is_dark else "light"
        save_settings(self._settings)
        self._apply_theme()
        self._animate_overlay_fade(snapshot, duration=260)

    def _refresh_quick_mode_buttons(self):
        for key, button in self._mode_buttons.items():
            button.setText(self._tr(f"mode.{key}"))
            mode = QUICK_MODE_MAP.get(key)
            is_supported = True if mode is None else self._ble.supports_effect_code(mode.effect_code)
            button.setEnabled(is_supported or key == self._active_mode_key)
            button.set_role("mode_active" if key == self._active_mode_key else "mode")

    def _set_active_mode(self, mode_key: str | None):
        normalized = mode_key if mode_key in QUICK_MODE_MAP else None
        if normalized == self._active_mode_key:
            return
        self._active_mode_key = normalized
        self._settings["quick_mode"] = normalized or ""
        self._refresh_quick_mode_buttons()
        self._apply_theme()

    def _current_state_dict(self) -> dict:
        color = self._current_color()
        return {
            "power": self.power_button.isChecked(),
            "brightness": self.brightness_slider.value(),
            "speed": self.speed_slider.value(),
            "effect_code": int(self.effect_combo.currentData()),
            "color": {"r": color.red(), "g": color.green(), "b": color.blue()},
        }

    def _sync_quick_mode_from_state(self, preferred: str | None = None):
        if self._initializing:
            return
        state = self._current_state_dict()
        preferred_mode = QUICK_MODE_MAP.get(preferred or "")
        if preferred_mode is not None and preferred_mode.matches(state):
            self._set_active_mode(preferred_mode.key)
            return
        for mode in QUICK_MODES:
            if mode.matches(state):
                self._set_active_mode(mode.key)
                return
        self._set_active_mode(None)

    def _apply_profile_payload(self, profile: dict, *, announce_load: bool = False):
        previous_power = self.power_button.isChecked()
        self._initializing = True
        color = profile["color"]
        self.red_slider.setValue(int(color["r"]))
        self.green_slider.setValue(int(color["g"]))
        self.blue_slider.setValue(int(color["b"]))
        self.brightness_slider.setValue(int(profile["brightness"]))
        self.speed_slider.setValue(int(profile["speed"]))
        idx = self.effect_combo.findData(int(profile["effect_code"]))
        self.effect_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.power_button.setChecked(bool(profile["power"]))
        self._sync_power_button()
        self._initializing = False
        self._update_preview()
        self.preview.set_brightness(self.brightness_slider.value())
        self._sync_effect_preview(reset_phase=True)
        if announce_load:
            self._log(localization_manager.status_config_event("loaded", profile))
        self._sync_quick_mode_from_state()
        if not self._is_connected:
            if announce_load:
                self._log(self._tr("status.profile_loaded_local"))
                self._show_error(self._tr("error.connect_strip_to_apply_profile"))
            else:
                self._show_error(self._tr("error.connect_strip_first"))
            return
        target_power = self.power_button.isChecked()
        if previous_power != target_power:
            self._ble.set_power(target_power, restore_state=False)
        if not target_power:
            return
        if int(profile["effect_code"]) == 0:
            color_obj = self._current_color()
            self._ble.set_brightness(self.brightness_slider.value())
            self._ble.set_color(color_obj.red(), color_obj.green(), color_obj.blue())
        else:
            self._ble.set_effect_with_speed(int(profile["effect_code"]), self.speed_slider.value())

    def _activate_quick_mode(self, mode_key: str):
        mode = QUICK_MODE_MAP.get(mode_key)
        if mode is None:
            return
        if self._is_connected and not self._ble.supports_effect_code(mode.effect_code):
            self._show_error("Built-in effects are not supported by this controller yet.")
            return
        self._set_active_mode(mode.key)
        self._apply_profile_payload(mode.as_profile(), announce_load=False)

    def _resolve_dark_from_mode(self, mode: str) -> bool:
        if mode == "dark":
            return True
        if mode == "light":
            return False
        hour = datetime.now().hour
        return hour >= 19 or hour < 7

    def _refresh_auto_theme(self):
        if self._theme_mode != "auto":
            return
        desired_dark = self._resolve_dark_from_mode("auto")
        if desired_dark == self._is_dark:
            return
        self._is_dark = desired_dark
        self._settings["theme_mode"] = "auto"
        self._settings["theme"] = "dark" if self._is_dark else "light"
        save_settings(self._settings)
        self._apply_theme()

    def _animate_overlay_fade(self, snapshot, duration: int = 260):
        if snapshot.isNull():
            return

        if self._theme_transition is not None:
            self._theme_transition.stop()
        if self._theme_transition_overlay is not None:
            self._theme_transition_overlay.deleteLater()

        overlay = QLabel(self)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setPixmap(snapshot)
        overlay.setScaledContents(True)
        overlay.setGeometry(self.rect())
        overlay.raise_()

        effect = QGraphicsOpacityEffect(overlay)
        effect.setOpacity(1.0)
        overlay.setGraphicsEffect(effect)
        overlay.show()

        anim = QPropertyAnimation(effect, b"opacity", overlay)
        anim.setDuration(duration)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _cleanup():
            overlay.deleteLater()
            if self._theme_transition is anim:
                self._theme_transition = None
                self._theme_transition_overlay = None

        anim.finished.connect(_cleanup)
        self._theme_transition = anim
        self._theme_transition_overlay = overlay
        anim.start()

    def _collect_state(self, name):
        color = self._current_color()
        return ProfileState(
            name=name,
            power=self.power_button.isChecked(),
            brightness=self.brightness_slider.value(),
            speed=self.speed_slider.value(),
            effect_code=int(self.effect_combo.currentData()),
            color={"r": color.red(), "g": color.green(), "b": color.blue()},
        )

    def _refresh_profiles(self):
        self._profile_controller.refresh_list(self.profile_list)

    def _save_profile(self):
        self._profile_controller.save_profile(
            self.profile_name.text(),
            self._collect_state,
            self._show_error,
            self._log,
            self._tr,
            self.profile_list,
        )

    def _selected_profile(self):
        return self._profile_controller.selected_profile(self.profile_list)

    def _load_selected_profile(self):
        profile = self._selected_profile()
        if profile is None:
            self._show_error(self._tr("error.select_profile_first"))
            return
        self._apply_profile_payload(profile, announce_load=True)

    def _delete_selected_profile(self):
        self._profile_controller.delete_selected_profile(
            self.profile_list,
            self._show_error,
            self._log,
            self._tr,
        )

    def _reset_profiles(self):
        self._profile_controller.reset_profiles(
            self.profile_list,
            self._log,
            self._tr,
        )

    def _show_error(self, message):
        self._ui_feedback.show_error(message)

    def _log(self, message):
        self._ui_feedback.log(message)

    def closeEvent(self, event):
        self._settings["window_width"] = self.width()
        self._settings["window_height"] = self.height()
        self._settings["language"] = self._language
        self._settings["theme_mode"] = self._theme_mode
        self._settings["theme"] = "dark" if self._is_dark else "light"
        self._settings["quick_mode"] = self._active_mode_key or ""
        self._settings["last_state"] = asdict(self._collect_state("last"))
        save_settings(self._settings)
        self._ble.shutdown()
        super().closeEvent(event)


def run():
    QCoreApplication.setApplicationName(localization_manager.t("dialog.title"))
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
