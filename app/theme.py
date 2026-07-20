from __future__ import annotations

from PySide6.QtGui import QColor

DARK = {
    "window_start": "#090a0c",
    "window_end": "#07080a",
    "surface": "rgba(28, 29, 32, 0.94)",
    "surface_soft": "rgba(38, 39, 43, 0.66)",
    "surface_strong": "rgba(17, 18, 21, 0.94)",
    "surface_border": "rgba(255, 255, 255, 0.10)",
    "surface_line": "rgba(255, 255, 255, 0.12)",
    "text": "#f7f7f8",
    "text_soft": "rgba(236, 237, 240, 0.82)",
    "muted": "rgba(220, 222, 226, 0.58)",
    "field": "rgba(255, 255, 255, 0.085)",
    "field_alt": "rgba(255, 255, 255, 0.13)",
    "field_border": "rgba(255, 255, 255, 0.16)",
    "accent_start": "#8fbfff",
    "accent_end": "#6f9eff",
    "danger_start": "#ff7a85",
    "danger_end": "#b64c66",
    "success_start": "#71d8c0",
    "success_end": "#4ca88f",
    "chip": "rgba(255, 255, 255, 0.10)",
    "chip_border": "rgba(255, 255, 255, 0.14)",
    "list_sel": "rgba(255, 255, 255, 0.12)",
    "list_hover": "rgba(255, 255, 255, 0.06)",
    "scroll": "rgba(255, 255, 255, 0.18)",
}

LIGHT = {
    "window_start": "#f2f3f5",
    "window_end": "#e7e9ed",
    "surface": "rgba(255, 255, 255, 0.84)",
    "surface_soft": "rgba(249, 250, 252, 0.92)",
    "surface_strong": "rgba(255, 255, 255, 0.96)",
    "surface_border": "rgba(34, 38, 46, 0.20)",
    "surface_line": "rgba(34, 38, 46, 0.13)",
    "text": "#17181b",
    "text_soft": "rgba(28, 30, 35, 0.82)",
    "muted": "rgba(38, 41, 48, 0.60)",
    "field": "rgba(22, 25, 31, 0.045)",
    "field_alt": "rgba(22, 25, 31, 0.075)",
    "field_border": "rgba(34, 38, 46, 0.16)",
    "accent_start": "#5f8ee6",
    "accent_end": "#3f70cf",
    "danger_start": "#ff7a85",
    "danger_end": "#c94d5f",
    "success_start": "#5ed4b8",
    "success_end": "#3aab8f",
    "chip": "rgba(22, 25, 31, 0.06)",
    "chip_border": "rgba(34, 38, 46, 0.14)",
    "list_sel": "rgba(63, 112, 207, 0.17)",
    "list_hover": "rgba(22, 25, 31, 0.045)",
    "scroll": "rgba(34, 38, 46, 0.24)",
}


def qcolor_from_token(value: str) -> QColor:
    value = value.strip()
    if value.startswith("#"):
        return QColor(value)
    if value.startswith("rgba(") and value.endswith(")"):
        parts = [part.strip() for part in value[5:-1].split(",")]
        if len(parts) == 4:
            red = int(float(parts[0]))
            green = int(float(parts[1]))
            blue = int(float(parts[2]))
            alpha = float(parts[3])
            if alpha <= 1.0:
                alpha = round(alpha * 255)
            else:
                alpha = round(alpha)
            return QColor(red, green, blue, max(0, min(255, alpha)))
    if value.startswith("rgb(") and value.endswith(")"):
        parts = [part.strip() for part in value[4:-1].split(",")]
        if len(parts) == 3:
            return QColor(int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
    return QColor(value)


class ThemeManager:
    def __init__(self) -> None:
        self._is_dark = True
        self._accent_override: QColor | None = None
        # Current LED strip colour, shared so widgets (e.g. the power button)
        # can tint themselves to "the light you control". None = no colour yet.
        self.led_glow: QColor | None = None

    @property
    def is_dark(self) -> bool:
        return self._is_dark

    @property
    def palette(self) -> dict[str, str]:
        base = dict(DARK if self._is_dark else LIGHT)
        if self._accent_override is None:
            return base
        accent = QColor(self._accent_override)
        # The quick-mode accent only dyes small UI elements (active buttons,
        # chips, selection). It must NOT touch window_start/window_end — the
        # window background's only source of colour is the live strip colour,
        # applied as a glow in AuroraBackground. Tinting the window here is what
        # leaked a blue cast when "Спокойно" (accent #7fb7ff) was active.
        base["accent_start"] = self._mix_token(base["accent_start"], accent, 0.48, lift=1.1)
        base["accent_end"] = self._mix_token(base["accent_end"], accent, 0.42, lift=1.0)
        base["list_sel"] = self._mix_token(base["list_sel"], accent, 0.34)
        base["list_hover"] = self._mix_token(base["list_hover"], accent, 0.24)
        return base

    def set_dark(self, is_dark: bool) -> dict[str, str]:
        self._is_dark = bool(is_dark)
        return self.palette

    def set_accent_override(self, color: QColor | str | None) -> dict[str, str]:
        if color in (None, ""):
            self._accent_override = None
        else:
            self._accent_override = color if isinstance(color, QColor) else QColor(str(color))
        return self.palette

    @staticmethod
    def _mix_token(value: str, accent: QColor, amount: float, *, lift: float = 1.0) -> str:
        source = qcolor_from_token(value)
        mixed = QColor(
            round(source.red() * (1.0 - amount) + accent.red() * amount),
            round(source.green() * (1.0 - amount) + accent.green() * amount),
            round(source.blue() * (1.0 - amount) + accent.blue() * amount),
            source.alpha(),
        )
        if lift != 1.0:
            if lift > 1.0:
                mixed = mixed.lighter(round(lift * 100))
            else:
                mixed = mixed.darker(round((1.0 / max(lift, 0.01)) * 100))
        alpha = round(mixed.alpha() / 255, 3)
        return f"rgba({mixed.red()}, {mixed.green()}, {mixed.blue()}, {alpha})"


theme_manager = ThemeManager()


def overlay_panel_colors() -> tuple[QColor, QColor]:
    """Top and bottom stops of the floating panel gradient (dialogs, popovers).

    One source of truth on purpose: the same pair used to be copy-pasted into
    nine overlays, so the dark panels drifted blue while the app's cards stayed
    graphite — and fixing one window left the other eight wrong.
    """
    if theme_manager.is_dark:
        return QColor(36, 37, 41, 250), QColor(20, 21, 24, 252)
    return QColor(250, 252, 255, 252), QColor(234, 241, 251, 252)
