from __future__ import annotations

import re

from app.theme import qcolor_from_token

_PX_RE = re.compile(r"(\d+)px")


def _scale_px(css: str, scale: float) -> str:
    """Scale every ``<n>px`` size in the stylesheet by ``scale`` (min 1px).

    This uniformly shrinks/grows fonts, paddings, radii and min/max sizes for the
    UI-density feature without parameterising each literal. Colours (rgba/#hex)
    and relative units (em) have no ``px`` suffix and are left untouched.
    """
    if abs(scale - 1.0) < 0.005:
        return css
    return _PX_RE.sub(lambda m: f"{max(1, round(int(m.group(1)) * scale))}px", css)


def build_theme_stylesheet(tokens: dict[str, str], scale: float = 1.0) -> str:
    T = tokens
    is_dark = qcolor_from_token(T["text"]).lightness() > 180
    css = "".join([
        _base_styles(T),
        _hero_styles(T, is_dark),
        _card_styles(T),
        _form_styles(T, is_dark),
        _scrollbar_styles(T, is_dark),
    ])
    return _scale_px(css, scale)


# ── base ──────────────────────────────────────────────────────────────

def build_tooltip_stylesheet(tokens: dict[str, str]) -> str:
    """QToolTip styling. Must be applied at the QApplication level: tooltips are
    top-level popups and do not inherit a widget/window stylesheet."""
    tip_bg = qcolor_from_token(tokens["surface_strong"])
    tip_bg.setAlpha(255)
    return f"""
        QToolTip {{
            background: {tip_bg.name()};
            color: {tokens["text"]};
            border: 1px solid {tokens["surface_border"]};
            border-radius: 9px;
            padding: 7px 11px;
            font-size: 12px;
            font-weight: 500;
        }}
    """


def _base_styles(T: dict) -> str:
    return f"""
        QMainWindow, #rootWidget, #bodyCanvas, #bodyScroll, QScrollArea {{
            background: transparent;
        }}
        #contentShell {{
            background: transparent;
        }}
        QLabel {{
            background: transparent;
            color: {T["text"]};
        }}
        #statusChip, #valueChip {{
            background: {T["chip"]};
            border: 1px solid {T["chip_border"]};
            border-radius: 14px;
            color: {T["text"]};
            font-size: 12px;
            font-weight: 600;
            padding: 0 12px;
        }}
        #sliderLabel {{
            color: {T["text_soft"]};
            font-size: 12px;
            font-weight: 600;
        }}
        #lastDeviceHint {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 600;
            padding-left: 2px;
        }}
        #deviceOnboardingHint {{
            color: {T["text_soft"]};
            font-size: 12px;
            font-weight: 600;
            padding: 2px 2px 0 2px;
        }}
        #scheduleNote {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 600;
            padding-left: 2px;
        }}
        #previewFrame {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(255,255,255,0.08),
                stop:1 {T["surface_soft"]});
            border: 1px solid {T["surface_border"]};
            border-radius: 24px;
        }}
        #previewInfo {{
            color: {T["text"]};
            font-size: 12px;
            font-weight: 600;
        }}
    """


# ── hero panel ────────────────────────────────────────────────────────

def _hero_styles(T: dict, is_dark: bool) -> str:
    lang_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(255,255,255,0.74),"
        " stop:0.46 rgba(236,244,255,0.66),"
        " stop:1 rgba(198,218,248,0.50))"
        if not is_dark else
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(255,255,255,0.14),"
        " stop:0.48 rgba(255,255,255,0.08),"
        " stop:1 rgba(255,255,255,0.045))"
    )
    lang_border = "rgba(255, 255, 255, 0.56)" if not is_dark else "rgba(255, 255, 255, 0.13)"
    return f"""
        #heroPanel {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {T["surface_soft"]},
                stop:1 {T["surface"]});
            border: 1px solid {T["surface_border"]};
            border-radius: 26px;
        }}
        #heroControlsWrap {{
            background: transparent;
        }}
        #heroTitle {{
            color: {T["text"]};
            font-size: 21px;
            font-weight: 700;
            qproperty-alignment: 'AlignHCenter | AlignVCenter';
        }}
        #heroSubtitle {{
            color: {T["text_soft"]};
            font-size: 11px;
            font-weight: 500;
            qproperty-alignment: 'AlignHCenter | AlignVCenter';
        }}
        #heroVersionText {{
            color: {T["muted"]};
            font-size: 10px;
            font-weight: 600;
            padding: 0 4px 2px 0;
        }}
        #authorEditionText {{
            background: transparent;
            border: none;
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 700;
            padding: 2px 0 0 0;
        }}
        #languageCombo {{
            background: {lang_bg};
            border: 1px solid {lang_border};
            min-height: 40px;
            max-height: 40px;
            padding-left: 14px;
            padding-right: 14px;
            padding-top: 0;
            padding-bottom: 0;
            font-size: 12px;
            font-weight: 600;
        }}
        #themeButton {{
            background: transparent;
            border: none;
            color: {T["text"]};
            min-height: 40px;
            max-height: 40px;
            padding: 0;
            font-size: 12px;
            font-weight: 600;
        }}
    """


# ── glass cards ───────────────────────────────────────────────────────

def _card_styles(T: dict) -> str:
    return f"""
        #glassCard {{
            background: transparent;
            border: none;
            border-radius: 26px;
        }}
        #cardTitle {{
            color: {T["text"]};
            font-size: 18px;
            font-weight: 700;
            margin: 0;
            padding: 0;
            qproperty-alignment: 'AlignHCenter | AlignVCenter';
        }}
        #cardSubtitle {{
            color: {T["text_soft"]};
            font-size: 11px;
            font-weight: 500;
            margin: 0;
            padding: 0;
            line-height: 1.25em;
            qproperty-alignment: 'AlignLeft | AlignTop';
        }}
    """


# ── form elements ─────────────────────────────────────────────────────

def _form_styles(T: dict, is_dark: bool) -> str:
    item_bg     = "rgba(255,255,255,0.07)" if is_dark else "rgba(100,130,210,0.07)"
    item_border = "rgba(255,255,255,0.09)" if is_dark else "rgba(100,130,210,0.18)"
    return f"""
        QLineEdit, QComboBox, QListWidget, QTextEdit, QTimeEdit {{
            background: {T["field"]};
            border: 1px solid {T["field_border"]};
            border-radius: 16px;
            color: {T["text"]};
            padding: 11px 16px;
            font-size: 13px;
            font-weight: 500;
            selection-background-color: {T["list_sel"]};
            outline: none;
        }}
        QListWidget {{
            font-size: 13px;
            font-weight: 500;
        }}
        #profileList {{
            background: {T["field_alt"]};
            border: 1px solid {T["field_border"]};
        }}
        QLineEdit, QTimeEdit {{
            min-height: 44px;
        }}
        QLineEdit#diyDurationInput {{
            min-height: 0px;
            max-height: 34px;
            padding: 0px 14px;
            border-radius: 17px;
            background: {T["chip"]};
            border: 1px solid {T["chip_border"]};
            color: {T["text"]};
            font-size: 13px;
            font-weight: 600;
        }}
        QLineEdit#diyDurationInput:focus {{
            border: 1px solid {T["accent_start"]};
        }}
        #diyList {{
            background: transparent;
            border: none;
            padding: 0px;
        }}
        #diyList::item {{
            margin: 4px 2px;
            padding: 0px;
            background: transparent;
            border: none;
        }}
        QComboBox {{
            min-height: 44px;
        }}
        QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTextEdit:focus, QTimeEdit:focus {{
            border: 1px solid rgba(94, 130, 210, 0.58);
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background: {T["field_alt"]};
            color: {T["text"]};
            border: 1px solid {T["field_border"]};
            selection-background-color: {T["list_sel"]};
            outline: none;
        }}
        QMenu {{
            background: {T["surface_strong"]};
            border: 1px solid {T["field_border"]};
            border-radius: 12px;
            padding: 6px;
            color: {T["text"]};
            font-size: 13px;
            font-weight: 500;
        }}
        QMenu::item {{
            padding: 8px 16px;
            border-radius: 8px;
        }}
        QMenu::item:selected {{
            background: {T["list_sel"]};
        }}
        QListWidget::item {{
            padding: 10px 14px;
            border-radius: 10px;
            margin: 2px 4px;
            background: {item_bg};
            border: 1px solid {item_border};
            font-size: 13px;
            font-weight: 500;
        }}
        QListWidget::item:selected {{
            background: {T["list_sel"]};
            border-left: 2px solid {T["accent_start"]};
            padding-left: 10px;
        }}
        QListWidget::item:hover {{
            background: {T["list_hover"]};
        }}
        QListWidget {{
            padding-top: 8px;
            padding-bottom: 8px;
            padding-left: 8px;
            padding-right: 16px;
        }}
        QTextEdit {{
            font-family: "Cascadia Code", "Consolas";
            font-size: 12px;
            font-weight: 500;
            padding: 14px 16px;
            line-height: 1.35em;
        }}
        #logOutput, #diagnosticsOutput {{
            background: {T["field"]};
            border: 1px solid {T["field_border"]};
            border-radius: 12px;
            color: {T["text"]};
            font-size: 12px;
            line-height: 1.6em;
            padding: 16px 18px;
        }}
        #diagnosticsSupportHint {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 600;
            padding: 0 2px;
        }}
    """


# ── scrollbars ────────────────────────────────────────────────────────

def _scrollbar_styles(T: dict, is_dark: bool) -> str:
    track = "rgba(0, 0, 0, 0.04)" if not is_dark else "rgba(255, 255, 255, 0.06)"
    return f"""
        QScrollBar:vertical {{
            width: 14px;
            margin: 8px 3px 8px 7px;
            background: {track};
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background: {T["scroll"]};
            border-radius: 5px;
            min-height: 28px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent;
            border: none;
        }}
    """
