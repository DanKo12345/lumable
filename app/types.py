from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QListWidget, QScrollArea

from app.ble import BleController
from app.ui_feedback import UiFeedback
from app.widgets import (
    AccentPreview,
    AuroraBackground,
    EffectPreviewStrip,
    LiquidButton,
    LiquidSlider,
    StaticPopupComboBox,
)


class BleEventHost(Protocol):
    _ble: BleController
    _devices: list[dict[str, Any]]
    _is_connected: bool
    _scan_in_progress: bool
    _connect_in_progress: bool
    _settings: dict[str, Any]
    _ui_feedback: UiFeedback

    device_combo: StaticPopupComboBox
    device_status: QLabel
    connect_button: LiquidButton
    disconnect_button: LiquidButton
    logs_toggle_button: LiquidButton

    def _tr(self, key: str, **kwargs: object) -> str: ...

    def _sync_connect_buttons(self) -> None: ...

    def _refresh_effect_names(self) -> None: ...

    def _refresh_quick_mode_buttons(self) -> None: ...


class ThemeHost(Protocol):
    _active_mode_key: str | None
    _aurora: AuroraBackground
    _buttons: list[LiquidButton]
    _is_dark: bool
    _settings: dict[str, Any]
    _theme_mode: str
    _theme_tokens: dict[str, str]
    _theme_transition: Any | None
    _theme_transition_overlay: QLabel | None

    body_scroll: QScrollArea
    language_combo: StaticPopupComboBox
    device_combo: StaticPopupComboBox
    effect_combo: StaticPopupComboBox
    theme_button: LiquidButton
    preview: AccentPreview
    effect_preview: EffectPreviewStrip
    profile_list: QListWidget
    red_slider: LiquidSlider
    green_slider: LiquidSlider
    blue_slider: LiquidSlider
    brightness_slider: LiquidSlider
    speed_slider: LiquidSlider

    def _tr(self, key: str, **kwargs: object) -> str: ...

    def grab(self) -> QPixmap: ...

    def rect(self) -> QRect: ...

    def setStyleSheet(self, style_sheet: str) -> None: ...
