from __future__ import annotations

from typing import Protocol

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QLayout, QLineEdit, QMenu, QWidget

from app.widgets import (
    AccentPreview,
    EffectPreviewStrip,
    GlassCard,
    LiquidButton,
    LiquidSlider,
    SceneTileGrid,
    StaticPopupComboBox,
    TimeButton,
    ValueChip,
)
from app.widgets.capture_area_selector import CaptureAreaSelector


class PanelHost(Protocol):
    _control_height: int
    _chip_height: int
    _theme_tokens: dict[str, str]
    _is_dark: bool
    _effect_key_by_code: dict[int, str]

    device_card: GlassCard
    device_combo: StaticPopupComboBox
    scan_button: LiquidButton
    last_device_label: QLabel
    device_onboarding_label: QLabel
    device_status: QLabel
    device_primary_meta: QLabel
    scenes_create_heading: QLabel
    scenes_saved_heading: QLabel
    scenes_empty_label: QLabel
    scenes_empty_state: QWidget
    scenes_grid: SceneTileGrid
    groups_empty_state: QWidget
    connect_button: LiquidButton
    disconnect_button: LiquidButton
    logs_toggle_button: LiquidButton
    supported_controllers_button: LiquidButton
    rename_device_button: LiquidButton

    api_card: GlassCard
    api_enable_button: LiquidButton
    api_status_label: QLabel
    api_reveal_button: LiquidButton
    api_token_label: QLabel
    api_port_label: QLabel
    api_token_field: QLineEdit
    api_copy_token_button: LiquidButton
    api_regenerate_button: LiquidButton
    api_port_field: QLineEdit
    api_lan_button: LiquidButton
    api_lan_host_field: QLineEdit
    api_lan_warning: QLabel
    api_security_note: QLabel
    api_advanced_toggle: LiquidButton
    api_advanced_container: QWidget
    api_help_button: LiquidButton
    api_pair_button: LiquidButton

    color_card: GlassCard
    preview: AccentPreview
    red_slider: LiquidSlider
    green_slider: LiquidSlider
    blue_slider: LiquidSlider
    brightness_slider: LiquidSlider
    red_value: ValueChip
    green_value: ValueChip
    blue_value: ValueChip
    brightness_value: ValueChip
    color_history_label: QLabel
    color_history_buttons: list
    pick_color_button: LiquidButton
    power_button: LiquidButton

    effects_card: GlassCard
    effect_combo: StaticPopupComboBox
    effect_preview: EffectPreviewStrip
    speed_slider: LiquidSlider
    speed_value: ValueChip

    configs_card: GlassCard
    profile_name: object
    save_profile_button: LiquidButton
    profile_list: object
    import_profiles_button: LiquidButton
    export_profiles_button: LiquidButton
    configs_menu_button: LiquidButton
    configs_reset_menu: QMenu
    reset_profiles_action: QAction

    log_output: object
    check_update_button: LiquidButton

    diagnostics_card: GlassCard
    diagnostics_output: object
    diagnostics_support_label: QLabel
    diagnostics_report_label: QLabel
    diagnostics_logs_label: QLabel
    diagnostics_logs_hint: QLabel
    diagnostics_scan_label: QLabel
    diagnostics_scan_hint: QLabel
    diagnostics_update_label: QLabel
    diagnostics_update_hint: QLabel
    diagnostics_tools_list: QWidget
    copy_diagnostics_button: LiquidButton
    report_device_button: LiquidButton
    show_logs_button: LiquidButton
    export_diagnostics_button: LiquidButton
    export_scan_button: LiquidButton

    schedule_card: GlassCard
    schedule_runtime_note: QLabel
    schedule_toggle_button: LiquidButton
    schedule_startup_button: LiquidButton
    schedule_on_label: QLabel
    schedule_off_label: QLabel
    schedule_on_time: TimeButton
    schedule_off_time: TimeButton

    ambient_card: GlassCard
    ambient_toggle_button: LiquidButton
    ambient_area_selector: CaptureAreaSelector
    ambient_monitor_combo: object
    ambient_preview: object
    ambient_saturation_slider: LiquidSlider
    ambient_saturation_value: ValueChip
    ambient_smoothing_slider: LiquidSlider
    ambient_smoothing_value: ValueChip

    def _tr(self, key: str, **kwargs: object) -> str: ...

    def _card(self, title: str, subtitle: str | None = None, icon: str | None = None) -> GlassCard: ...

    def _button(self, text: str, role: str) -> LiquidButton: ...

    def _slider(self, accent: str) -> LiquidSlider: ...

    def _pill(self, text: str) -> ValueChip: ...

    def _slider_row(self, name: str, slider: LiquidSlider, value: ValueChip, key: str | None = None) -> QLayout: ...
