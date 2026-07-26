from __future__ import annotations

from datetime import datetime
from typing import cast

import darkdetect
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget

from app.storage import save_settings
from app.styles import build_theme_stylesheet, build_tooltip_stylesheet
from app.theme import qcolor_from_token, theme_manager
from app.types import ThemeHost
from app.widgets.animation_helpers import play_or_complete


class ThemeController:
    def __init__(self, host: ThemeHost) -> None:
        self._host = host

    @staticmethod
    def resolve_dark_from_mode(mode: str) -> bool:
        if mode == "dark":
            return True
        if mode == "light":
            return False
        try:
            system_is_dark = darkdetect.isDark()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            system_is_dark = None
        if system_is_dark is not None:
            return bool(system_is_dark)
        hour = datetime.now().hour
        return hour >= 19 or hour < 7

    def theme_stylesheet(self) -> str:
        return build_theme_stylesheet(self._host._theme_tokens, getattr(self._host, "_ui_scale", 1.0))

    def sync_theme_button(self) -> None:
        labels = {
            "dark": self._host._tr("theme.dark"),
            "light": self._host._tr("theme.light"),
            "auto": self._host._tr("theme.auto"),
        }
        self._host.theme_button.setText(labels.get(self._host._theme_mode, self._host._tr("theme.auto")))

    def apply_slider_theme(self) -> None:
        slider_accents = {
            self._host.red_slider: "red",
            self._host.green_slider: "green",
            self._host.blue_slider: "blue",
            self._host.brightness_slider: "white",
            self._host.speed_slider: "purple",
        }
        for slider, accent in slider_accents.items():
            slider.set_accent_color(accent)
            slider.update()

    def refresh_theme_widgets(self) -> None:
        for combo in (self._host.language_combo, self._host.device_combo, self._host.effect_combo):
            if hasattr(combo, "_apply_popup_style"):
                combo._apply_popup_style()
        self._host.body_scroll.viewport().setStyleSheet("background: transparent;")
        self.sync_theme_button()
        self._host.preview.set_theme("dark" if self._host._is_dark else "light")
        self._host.hero_signature.refresh_theme()
        self._host.effect_preview.update()
        self._host.profile_list.viewport().update()
        for button in self._host._buttons:
            button.update()
        for slider in (
            self._host.red_slider,
            self._host.green_slider,
            self._host.blue_slider,
            self._host.brightness_slider,
            self._host.speed_slider,
        ):
            slider.update()

    def apply_theme(self) -> None:
        theme_manager.set_dark(self._host._is_dark)
        mode = self._host._quick_mode_by_key(self._host._active_mode_key or "")
        accent = None
        if mode is not None:
            accent = mode.accent if hasattr(mode, "accent") else str(mode.get("accent", "#7fb7ff"))
        self._host._theme_tokens = theme_manager.set_accent_override(None if accent is None else QColor(accent))
        self._host._aurora.set_dark(self._host._is_dark)
        if hasattr(self._host._aurora, "set_capture_compatibility"):
            self._host._aurora.set_capture_compatibility(bool(self._host._settings.get("capture_compatibility", True)))
        app = QApplication.instance()
        if app:
            base_font = QFont("Segoe UI Variable Text")
            base_font.setPointSizeF(10.0 * getattr(self._host, "_ui_scale", 1.0))
            # setFont is application-wide: Qt re-polishes every living widget in
            # the process. It only depends on the UI scale, so applying it when
            # nothing changed is pure cost on every theme/accent refresh.
            if app.font() != base_font:
                app.setFont(base_font)
            # Tooltips are top-level popups, so their style must live on the app,
            # not the main window — otherwise they fall back to the OS default.
            # Both writes below re-polish every widget in the process, so each is
            # compared against Qt's *actual* state rather than a remembered value:
            # a cache would drift if anything else touched the stylesheet or the
            # palette, or if the QApplication were replaced.
            tooltip_qss = build_tooltip_stylesheet(self._host._theme_tokens)
            if tooltip_qss != app.styleSheet():
                app.setStyleSheet(tooltip_qss)
            # Stylesheet alone doesn't always reach tooltip popups (Windows may
            # keep the system tooltip colours), so also drive the colours through
            # the application palette, which Qt always honours. Checked
            # separately: the palette can be right while the stylesheet is not.
            tip_bg = qcolor_from_token(self._host._theme_tokens["surface_strong"])
            tip_bg.setAlpha(255)
            tip_text = qcolor_from_token(self._host._theme_tokens["text"])
            pal = app.palette()
            if (
                pal.color(QPalette.ColorRole.ToolTipBase) != tip_bg
                or pal.color(QPalette.ColorRole.ToolTipText) != tip_text
            ):
                pal.setColor(QPalette.ColorRole.ToolTipBase, tip_bg)
                pal.setColor(QPalette.ColorRole.ToolTipText, tip_text)
                app.setPalette(pal)
        self._host.setStyleSheet(self.theme_stylesheet())
        self.apply_slider_theme()
        self.refresh_theme_widgets()

    def toggle_theme(self) -> None:
        snapshot = self._host.grab()
        # auto → light → dark → auto: from the default "auto" a single click shows
        # the light theme (clicking to "dark" first looked like nothing happened
        # when the system was already dark).
        order = ("auto", "light", "dark")
        current_index = order.index(self._host._theme_mode) if self._host._theme_mode in order else 0
        self._host._theme_mode = order[(current_index + 1) % len(order)]
        self._host._is_dark = self.resolve_dark_from_mode(self._host._theme_mode)
        self._host._settings["theme_mode"] = self._host._theme_mode
        self._host._settings["theme"] = "dark" if self._host._is_dark else "light"
        save_settings(self._host._settings)
        self.apply_theme()
        self.animate_overlay_fade(snapshot, duration=260)

    def refresh_auto_theme(self) -> None:
        if self._host._theme_mode != "auto":
            return
        desired_dark = self.resolve_dark_from_mode("auto")
        if desired_dark == self._host._is_dark:
            return
        self._host._is_dark = desired_dark
        self._host._settings["theme_mode"] = "auto"
        self._host._settings["theme"] = "dark" if self._host._is_dark else "light"
        save_settings(self._host._settings)
        self.apply_theme()

    def animate_overlay_fade(self, snapshot, duration: int = 260) -> None:
        if snapshot.isNull():
            return

        if self._host._theme_transition is not None:
            self._host._theme_transition.stop()
        if self._host._theme_transition_overlay is not None:
            self._host._theme_transition_overlay.deleteLater()

        host_widget = cast(QWidget, self._host)
        overlay = QLabel(host_widget)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setPixmap(snapshot)
        overlay.setScaledContents(True)
        overlay.setGeometry(self._host.rect())
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

        def _cleanup() -> None:
            overlay.deleteLater()
            if self._host._theme_transition is anim:
                self._host._theme_transition = None
                self._host._theme_transition_overlay = None

        anim.finished.connect(_cleanup)
        self._host._theme_transition = anim
        self._host._theme_transition_overlay = overlay
        # Reduced motion jumps the crossfade to its end THROUGH the engine, so
        # finished fires and _cleanup removes the snapshot overlay + clears the
        # host references — the transition never lingers as a frozen snapshot.
        play_or_complete(anim)
