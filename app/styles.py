from __future__ import annotations

from app.theme import qcolor_from_token


def build_theme_stylesheet(tokens: dict[str, str]) -> str:
    T = tokens
    is_dark = qcolor_from_token(T["text"]).lightness() > 180
    language_background = (
        "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
        " stop:0 rgba(255,255,255,0.74),"
        " stop:0.46 rgba(236,244,255,0.66),"
        " stop:1 rgba(198,218,248,0.50))"
        if not is_dark
        else T["field_alt"]
    )
    language_border = "rgba(255, 255, 255, 0.56)" if not is_dark else T["field_border"]
    return f"""
        QMainWindow, #rootWidget, #bodyCanvas, #bodyScroll, QScrollArea {{
            background: transparent;
        }}
        QLabel {{
            background: transparent;
            color: {T["text"]};
        }}
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
        #heroSignature {{
            color: {T["muted"]};
            font-size: 10px;
            font-style: italic;
            font-weight: 500;
            padding-left: 10px;
            padding-right: 8px;
        }}
        #languageCombo {{
            background: {language_background};
            border: 1px solid {language_border};
            padding-left: 14px;
            padding-right: 14px;
            font-size: 12px;
            font-weight: 600;
        }}
        #themeButton {{
            background: transparent;
            border: none;
            color: {T["text"]};
            padding: 0;
            font-size: 12px;
            font-weight: 600;
        }}
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
            qproperty-alignment: 'AlignHCenter | AlignTop';
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
        QLineEdit, QComboBox, QListWidget, QTextEdit {{
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
        QLineEdit {{
            min-height: 44px;
        }}
        QComboBox {{
            min-height: 44px;
        }}
        QLineEdit:focus, QComboBox:focus, QListWidget:focus, QTextEdit:focus {{
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
        QListWidget::item {{
            padding: 12px 14px;
            border-radius: 12px;
            margin: 3px 0;
            font-size: 13px;
            font-weight: 500;
        }}
        QListWidget::item:selected {{
            background: {T["list_sel"]};
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
        #logOutput {{
            background: {T["field"]};
            border: 1px solid {T["field_border"]};
            color: {T["text_soft"]};
            font-size: 11px;
        }}
        QScrollBar:vertical {{
            width: 14px;
            margin: 8px 3px 8px 7px;
            background: rgba(255, 255, 255, 0.06);
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
