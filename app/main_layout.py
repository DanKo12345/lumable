from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.constants import BODY_SPACING, ROOT_MARGINS, SECTION_SPACING, STATUS_MIN_WIDTH
from app.hero_header import build_brand, build_chrome_controls, build_mode_row
from app.panels import (
    build_ambient_section,
    build_color_section,
    build_configs_section,
    build_device_section,
    build_diagnostics_section,
    build_effects_section,
    build_schedule_section,
)
from app.widgets import AccentPreview, LiquidButton


def _build_settings_card(host):
    """App settings (language / FPS / theme / about) as a tidy labelled list."""
    card = host._card(host._tr("settings.title"), host._tr("settings.subtitle"))
    build_chrome_controls(host)  # creates host.language_combo / performance_combo / theme_button / about_button
    rows = [
        ("settings.language", host.language_combo),
        ("settings.fps", host.performance_combo),
        ("settings.theme", host.theme_button),
    ]
    host._settings_labels = []
    for label_key, widget in rows:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(host._sz(12))
        label = QLabel(host._tr(label_key))
        label.setObjectName("sliderLabel")
        label.setMinimumWidth(host._sz(140))
        host._settings_labels.append((label_key, label))
        row.addWidget(label, 0, Qt.AlignVCenter)
        row.addWidget(widget, 0, Qt.AlignVCenter)
        row.addStretch(1)
        card.content_layout.addLayout(row)

    # "About" stands alone (the button is self-describing).
    about_row = QHBoxLayout()
    about_row.setContentsMargins(0, host._sz(4), 0, 0)
    about_row.addWidget(host.about_button, 0, Qt.AlignVCenter)
    about_row.addStretch(1)
    card.content_layout.addLayout(about_row)
    return card


# Navigation sections: key, i18n label key, and the section builders shown on
# that page. Frequent tasks each get their own item; "settings" holds the
# rarely-touched setup (device, schedule, app settings, diagnostics).
_NAV_SECTIONS = (
    ("color", "nav.color", (build_color_section,)),
    ("effects", "nav.effects", (build_effects_section,)),
    ("ambient", "nav.ambient", (build_ambient_section,)),
    ("profiles", "nav.profiles", (build_configs_section,)),
    (
        "settings",
        "nav.settings",
        (
            build_device_section,
            _build_settings_card,
            build_schedule_section,
            build_diagnostics_section,
        ),
    ),
)


def build_main_layout(host) -> QWidget:
    """App shell: a full-height sidebar on the left, content filling the rest."""
    root = QWidget()
    root.setObjectName("rootWidget")
    root_layout = QHBoxLayout(root)
    root_layout.setContentsMargins(*(host._sz(m) for m in ROOT_MARGINS))
    root_layout.setSpacing(host._sz(BODY_SPACING))

    _build_sections(host)
    root_layout.addWidget(_build_sidebar(host), 0)

    separator = QFrame()
    separator.setObjectName("navSeparator")
    separator.setFrameShape(QFrame.VLine)
    separator.setFixedWidth(1)
    separator.setStyleSheet("background: rgba(255, 255, 255, 0.09); border: none;")
    root_layout.addWidget(separator)

    root_layout.addWidget(_build_main_area(host), 1)

    select_section(host, "color")
    return root


def select_section(host, key: str) -> None:
    """Switch the visible section page and update nav button states."""
    for nav_key, button in host._nav_buttons.items():
        # Flat nav item: active = subtle highlight + left accent bar; inactive =
        # near-transparent. No glossy pill.
        button.set_role("nav_active" if nav_key == key else "nav")
    page = host._nav_pages.get(key)
    if page is not None:
        host._section_stack.setCurrentWidget(page)


def _on_status_clicked(host) -> None:
    # Disconnected → start a controller search right away; connected → open the
    # device card so the user can manage/disconnect.
    if getattr(host, "_is_connected", False):
        select_section(host, "settings")
    else:
        host._ble_events.start_scan()


def _build_sections(host) -> None:
    host._section_stack = QStackedWidget()
    host._section_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    host._nav_buttons = {}
    host._nav_pages = {}

    for key, label_key, builders in _NAV_SECTIONS:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(host._sz(SECTION_SPACING))
        page_layout.setAlignment(Qt.AlignTop)
        for builder in builders:
            page_layout.addWidget(builder(host))
        page_layout.addStretch(1)
        host._section_stack.addWidget(page)
        host._nav_pages[key] = page

        button = LiquidButton(host._tr(label_key), role="nav")
        button.setMinimumHeight(host._sz(44))
        button.clicked.connect(lambda _checked=False, k=key: select_section(host, k))
        host._nav_buttons[key] = button


def _build_sidebar(host) -> QWidget:
    side = QWidget()
    side.setObjectName("sideBar")
    side.setFixedWidth(host._sz(216))
    column = QVBoxLayout(side)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(host._sz(8))

    column.addWidget(build_brand(host))
    column.addSpacing(host._sz(14))
    for button in host._nav_buttons.values():
        column.addWidget(button)
    column.addStretch(1)

    # Connection state always visible at the foot of the rail — a small card
    # with a coloured dot (green = connected, dim = not) plus the status text.
    # Clickable: jumps straight to the device section so connecting never
    # requires hunting through Settings.
    status_card = QPushButton()
    status_card.setObjectName("statusCard")
    status_card.setCursor(Qt.PointingHandCursor)
    status_card.setFlat(True)
    # A QPushButton sizes to its (empty) text, not to the child layout, so it
    # would clip the two-line content — pin a height that fits both lines.
    status_card.setMinimumHeight(host._sz(56))
    status_card.setToolTip(host._tr("device.find"))
    status_card.setStyleSheet(
        "QPushButton#statusCard { border: none; background: transparent; text-align: left; }"
        "QPushButton#statusCard:hover { background: rgba(255, 255, 255, 0.05); border-radius: 14px; }"
    )
    status_card.clicked.connect(lambda: _on_status_clicked(host))
    status_outer = QVBoxLayout(status_card)
    status_outer.setContentsMargins(host._sz(12), host._sz(8), host._sz(12), host._sz(8))
    status_outer.setSpacing(host._sz(2))
    status_row = QHBoxLayout()
    status_row.setContentsMargins(0, 0, 0, 0)
    status_row.setSpacing(host._sz(9))
    dot_size = host._sz(9)
    host.device_status_dot = QLabel()
    host.device_status_dot.setFixedSize(dot_size, dot_size)
    host.device_status_dot.setStyleSheet(
        f"background: rgba(255, 255, 255, 0.30); border-radius: {dot_size // 2}px;"
    )
    host.device_status = QLabel(host._tr("device.status.not_connected"))
    host.device_status.setObjectName("statusText")
    host.device_status.setStyleSheet("QLabel#statusText { font-size: 12px; font-weight: 600; }")
    host.device_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    host.device_status.setMinimumHeight(host._sz(20))  # avoid the text being clipped
    host.device_status.setMinimumWidth(STATUS_MIN_WIDTH)
    status_row.addWidget(host.device_status_dot, 0, Qt.AlignVCenter)
    status_row.addWidget(host.device_status, 1)
    status_outer.addLayout(status_row)
    # First-run hint: when disconnected, tell the user the card is the way to connect.
    host.device_status_hint = QLabel(host._tr("device.connect_hint"))
    host.device_status_hint.setObjectName("cardSubtitle")
    host.device_status_hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    # Indent so the second line aligns under the status text (past the dot).
    host.device_status_hint.setContentsMargins(dot_size + host._sz(9), 0, 0, 0)
    status_outer.addWidget(host.device_status_hint)
    column.addWidget(status_card)
    return side


def _build_main_area(host) -> QWidget:
    main = QWidget()
    main.setObjectName("mainArea")
    outer = QHBoxLayout(main)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    # A single capped column keeps the top bar, hero light and content cards at
    # exactly the same width so they line up — the live-light bar no longer
    # stretches wider than the section card below it.
    column = QWidget()
    column.setObjectName("contentColumn")
    column.setMaximumWidth(host._sz(1120))
    layout = QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(host._sz(10))

    # Hero "live light": the big bar that glows the current strip colour.
    host.preview = AccentPreview()
    host.preview.setMinimumHeight(host._sz(104))
    layout.addWidget(host.preview)

    # Quick actions under the light: presets on the left, power on the right —
    # so the power toggle sits in a populated row instead of floating alone.
    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(host._sz(10))
    actions.addLayout(build_mode_row(host))
    actions.addStretch(1)
    host.power_button = host._button(host._tr("color.power_on"), "ghost")
    host.power_button.setCheckable(True)
    host.power_button.setMaximumWidth(host._sz(190))
    host.power_button.setMinimumWidth(host._sz(150))
    actions.addWidget(host.power_button, 0, Qt.AlignVCenter)
    layout.addLayout(actions)

    layout.addWidget(_build_body_scroll(host), 1)

    outer.addStretch(1)
    outer.addWidget(column, 6)
    outer.addStretch(1)
    return main


def _build_body_scroll(host) -> QScrollArea:
    host.body_scroll = QScrollArea()
    host.body_scroll.setWidgetResizable(True)
    host.body_scroll.setFrameShape(QFrame.NoFrame)
    host.body_scroll.setObjectName("bodyScroll")

    host.body_canvas = QWidget()
    host.body_canvas.setObjectName("bodyCanvas")
    host.body_scroll.setWidget(host.body_canvas)

    canvas_layout = QVBoxLayout(host.body_canvas)
    canvas_layout.setContentsMargins(0, 0, 0, 0)
    canvas_layout.setSpacing(0)
    # Cap the section to the same width as the content column so it lines up with
    # the hero light and never overflows the scroll horizontally. Stretches
    # vertically centre short sections; taller ones (More) fill and scroll.
    host._section_stack.setMaximumWidth(host._sz(1120))
    canvas_layout.addStretch(1)
    canvas_layout.addWidget(host._section_stack)
    canvas_layout.addStretch(1)
    return host.body_scroll
