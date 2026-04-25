from __future__ import annotations

from PySide6.QtGui import QColor


DARK = {
    "window_start": "#09112b",
    "window_end": "#0d1136",
    "surface": "rgba(22, 31, 63, 0.78)",
    "surface_soft": "rgba(56, 76, 132, 0.52)",
    "surface_strong": "rgba(14, 20, 42, 0.74)",
    "surface_border": "rgba(255, 255, 255, 0.22)",
    "surface_line": "rgba(255, 255, 255, 0.16)",
    "text": "#f6f8ff",
    "text_soft": "rgba(232, 238, 255, 0.82)",
    "muted": "rgba(214, 224, 255, 0.58)",
    "field": "rgba(255, 255, 255, 0.10)",
    "field_alt": "rgba(255, 255, 255, 0.16)",
    "field_border": "rgba(255, 255, 255, 0.16)",
    "accent_start": "#8fbfff",
    "accent_end": "#6f9eff",
    "danger_start": "#ff7a85",
    "danger_end": "#b64c66",
    "success_start": "#71d8c0",
    "success_end": "#4ca88f",
    "chip": "rgba(255, 255, 255, 0.10)",
    "chip_border": "rgba(255, 255, 255, 0.14)",
    "list_sel": "rgba(120, 182, 255, 0.22)",
    "list_hover": "rgba(255, 255, 255, 0.06)",
    "scroll": "rgba(255, 255, 255, 0.18)",
}

LIGHT = {
    "window_start": "#dce6f7",
    "window_end": "#cfd9f0",
    "surface": "rgba(255, 255, 255, 0.72)",
    "surface_soft": "rgba(240, 245, 255, 0.82)",
    "surface_strong": "rgba(255, 255, 255, 0.92)",
    "surface_border": "rgba(100, 130, 200, 0.28)",
    "surface_line": "rgba(100, 130, 200, 0.20)",
    "text": "#0f1a3a",
    "text_soft": "rgba(15, 30, 70, 0.78)",
    "muted": "rgba(15, 30, 70, 0.50)",
    "field": "rgba(220, 232, 255, 0.55)",
    "field_alt": "rgba(230, 240, 255, 0.70)",
    "field_border": "rgba(100, 130, 200, 0.30)",
    "accent_start": "#6fa4ff",
    "accent_end": "#4d82f5",
    "danger_start": "#ff7a85",
    "danger_end": "#c94d5f",
    "success_start": "#5ed4b8",
    "success_end": "#3aab8f",
    "chip": "rgba(180, 205, 255, 0.38)",
    "chip_border": "rgba(100, 140, 220, 0.32)",
    "list_sel": "rgba(72, 132, 255, 0.18)",
    "list_hover": "rgba(72, 132, 255, 0.08)",
    "scroll": "rgba(80, 120, 200, 0.35)",
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

    @property
    def is_dark(self) -> bool:
        return self._is_dark

    @property
    def palette(self) -> dict[str, str]:
        base = dict(DARK if self._is_dark else LIGHT)
        if self._accent_override is None:
            return base
        accent = QColor(self._accent_override)
        base["accent_start"] = self._mix_token(base["accent_start"], accent, 0.48, lift=1.1)
        base["accent_end"] = self._mix_token(base["accent_end"], accent, 0.42, lift=1.0)
        base["list_sel"] = self._mix_token(base["list_sel"], accent, 0.34)
        base["list_hover"] = self._mix_token(base["list_hover"], accent, 0.24)
        base["window_start"] = self._mix_token(base["window_start"], accent, 0.12)
        base["window_end"] = self._mix_token(base["window_end"], accent, 0.18)
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
