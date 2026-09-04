from __future__ import annotations

import re

from app.theme import pro_badge_tokens, qcolor_from_token
from app.ui_metrics import CARD_RADIUS, FIELD_RADIUS

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


def context_menu_qss(tokens: dict[str, str]) -> str:
    """QMenu styling for the standard context menu inside self-styled overlays.

    Overlays set their own local stylesheet, which shadows the app-wide QMenu
    rules, so a QLineEdit's right-click menu (Cut/Copy/Paste…) falls back to the
    native light look. Append this to an overlay's stylesheet so that menu keeps
    the app theme while still offering paste (handy for license keys).
    """
    T = tokens
    return f"""
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
        QMenu::separator {{
            height: 1px;
            background: {T["field_border"]};
            margin: 4px 8px;
        }}
    """


def build_theme_stylesheet(tokens: dict[str, str], scale: float = 1.0) -> str:
    T = tokens
    is_dark = qcolor_from_token(T["text"]).lightness() > 180
    css = "".join([
        _base_styles(T, is_dark),
        _hero_styles(T, is_dark),
        _card_styles(T, is_dark),
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


def _base_styles(T: dict, is_dark: bool) -> str:
    pro = pro_badge_tokens(is_dark)
    return f"""
        QMainWindow, #rootWidget, #bodyCanvas, #bodyScroll, QScrollArea {{
            background: transparent;
        }}
        #contentShell {{
            background: transparent;
        }}
        #navSeparator {{
            background: {T["surface_line"]};
            border: none;
        }}
        QPushButton#statusCard {{
            background: transparent;
            border: none;
            color: {T["text"]};
            text-align: left;
        }}
        QPushButton#statusCard:hover {{
            background: {T["list_hover"]};
            border-radius: 14px;
        }}
        QLabel#statusText {{
            color: {T["text"]};
            font-size: 12px;
            font-weight: 600;
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
        #deviceSectionLabel {{
            color: {T["text_soft"]};
            font-size: 12px;
            font-weight: 700;
        }}
        #deviceStripRow {{
            background: {T["chip"]};
            border: 1px solid {T["chip_border"]};
            border-radius: 10px;
        }}
        #deviceStripTitle {{
            color: {T["text"]};
            font-size: 13px;
            font-weight: 700;
        }}
        #deviceStripMeta {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 600;
        }}
        #sceneFormHeading {{
            color: {T["text"]};
            font-size: 12px;
            font-weight: 700;
        }}
        #sceneDivider {{
            background: {T["chip_border"]};
            border: 0;
            max-height: 1px;
            min-height: 1px;
        }}
        #sceneHint {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 500;
        }}
        #sceneEmptyHint {{
            color: {T["muted"]};
            font-size: 12px;
            font-weight: 500;
            padding: 2px 0;
        }}
        #emptyState {{
            background: {T["field"]};
            border: none;
            border-radius: 14px;
        }}
        #emptyStateText {{
            background: transparent;
            border: none;
            color: {T["muted"]};
            font-size: 12px;
            font-weight: 600;
        }}
        #deviceOnboardingHint {{
            color: {T["text_soft"]};
            font-size: 12px;
            font-weight: 600;
            padding: 2px 2px 0 2px;
        }}
        #proBadge {{
            color: {pro["text"]};
            background: {pro["background"]};
            border: 1px solid {pro["border"]};
            border-radius: 7px;
            padding: 1px 6px;
            font-size: 10px;
            font-weight: 800;
        }}
        #proBadge:hover {{
            background: {pro["hover"]};
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
    # Light theme: the combo sits on a near-white card, so a white-on-white
    # gradient with a white border disappears entirely. Match the ghost
    # LiquidButton material instead: white top, faint grey bottom, grey border.
    lang_bg = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(255,255,255,0.92),"
        " stop:0.46 rgba(246,249,253,0.85),"
        " stop:1 rgba(228,233,241,0.78))"
        if not is_dark else
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(255,255,255,0.14),"
        " stop:0.48 rgba(255,255,255,0.08),"
        " stop:1 rgba(255,255,255,0.045))"
    )
    lang_border = "rgba(72, 79, 91, 0.36)" if not is_dark else "rgba(255, 255, 255, 0.13)"
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
            qproperty-alignment: 'AlignLeft | AlignBottom';
        }}
        #heroSubtitle {{
            color: {T["text_soft"]};
            font-size: 11px;
            font-weight: 500;
            qproperty-alignment: 'AlignLeft | AlignTop';
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
            padding: 0;
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

def _card_styles(T: dict, is_dark: bool) -> str:
    return f"""
        #glassCard {{
            background: transparent;
            border: none;
            border-radius: {CARD_RADIUS}px;
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
        QFrame#settingsList {{
            /* On light the card surface and the "field" token are nearly the
               same blue-white, so the list needs its own brighter panel to read
               as a group at all. */
            background: {T["field"] if is_dark else "rgba(255, 255, 255, 0.78)"};
            border: 1px solid {T["field_border"]};
            border-radius: {FIELD_RADIUS}px;
        }}
        #settingsRow {{
            background: transparent;
            border: 0;
            border-radius: {FIELD_RADIUS}px;
        }}
        /* A running timer keeps a soft highlight so the active row reads at a
           glance without shouting. */
        #settingsRow[active="true"] {{
            background: {T["list_hover"]};
        }}
        #settingsRowTitle {{
            color: {T["text"]};
            font-size: 14px;
            font-weight: 650;
            letter-spacing: 0.1px;
        }}
        #settingsRowCaption {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 500;
        }}
        #settingsRowStatus {{
            color: {T["muted"]};
            font-size: 11px;
            font-weight: 500;
        }}
        #settingsRowStatus[active="true"] {{
            color: {T["text_soft"]};
            font-weight: 650;
        }}
        #settingsIdentity, #settingsControls, #settingsDividerHolder {{
            background: transparent;
            border: 0;
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
            background: transparent;
            border: 0;
            border-radius: 0;
            padding: 0;
        }}
        #profileList:focus {{ border: 0; }}
        QLineEdit, QTimeEdit {{
            min-height: 44px;
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
