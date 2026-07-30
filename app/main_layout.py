from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.constants import BODY_SPACING, ROOT_MARGINS, SECTION_SPACING, STATUS_MIN_WIDTH
from app.hero_header import build_brand, build_chrome_controls, build_mode_row
from app.panels import (
    build_ambient_section,
    build_app_triggers_section,
    build_automation_bridge_section,
    build_automation_journal_section,
    build_automation_rules_section,
    build_automations_section,
    build_color_section,
    build_configs_section,
    build_device_section,
    build_diagnostics_section,
    build_diy_section,
    build_effects_section,
    build_groups_section,
    build_hotkeys_section,
    build_local_api_section,
    build_music_section,
    build_scenes_section,
    build_schedule_section,
    build_software_effects_section,
    build_timers_section,
)
from app.panels.list_rows import divider, list_container, list_row
from app.widgets import AccentPreview, LiquidButton


def _build_settings_card(host):
    """App settings as one compact grouped list."""
    card = host._card(host._tr("settings.title"), host._tr("settings.subtitle"), icon="settings")
    build_chrome_controls(host)  # creates host.language_combo / performance_combo / theme_button / about_button
    for control in (host.language_combo, host.performance_combo, host.motion_combo, host.theme_button, host.about_button):
        control.setFixedWidth(host._sz(170))
    rows = (
        ("settings.language", "globe", "#78a7ff", host.language_combo),
        ("settings.fps", "diagnostics", "#72c7b7", host.performance_combo),
        ("settings.motion", "orbit", "#b58fff", host.motion_combo),
        ("settings.theme", "sun", "#ffb066", host.theme_button),
        ("settings.about", "settings", "#a9b0bd", host.about_button),
    )
    settings_list, settings_layout = list_container(host)
    host._settings_labels = []
    for index, (label_key, icon, tint, control) in enumerate(rows):
        row, controls, title, _, _ = list_row(
            host,
            icon,
            tint,
            host._tr(label_key),
            with_status=False,
        )
        host._settings_labels.append((label_key, title, control))
        # The row label is a separate QLabel, so a screen reader reaching the
        # control alone would just hear its value ("Auto") with no idea what it
        # sets. Buddy + accessible name carry the row's meaning onto the control.
        title.setBuddy(control)
        control.setAccessibleName(host._tr(label_key))
        controls.addWidget(control, 0, Qt.AlignVCenter)
        settings_layout.addWidget(row)
        if index < len(rows) - 1:
            settings_layout.addWidget(divider(host))
    card.content_layout.addWidget(settings_list)
    return card


# Navigation sections: key, i18n label key, and the section builders shown on
# that page. Frequent tasks each get their own item; "settings" holds the
# rarely-touched setup (device, schedule, app settings, diagnostics).
_NAV_SECTIONS = (
    ("color", "nav.color", (build_color_section,)),
    ("scenes", "nav.scenes", (build_scenes_section, build_groups_section)),
    ("effects", "nav.effects", (build_effects_section, build_software_effects_section, build_diy_section)),
    ("ambient", "nav.ambient", (build_ambient_section,)),
    ("music", "nav.music", (build_music_section,)),
    ("profiles", "nav.profiles", (build_configs_section,)),
    ("schedule", "nav.schedule", (build_schedule_section, build_timers_section, build_app_triggers_section)),
    (
        "automations",
        "nav.automations",
        (
            build_automations_section,
            build_automation_rules_section,
            build_automation_journal_section,
            build_automation_bridge_section,
        ),
    ),
    (
        "settings",
        "nav.settings",
        (
            build_device_section,
            _build_settings_card,
            build_hotkeys_section,
            build_local_api_section,
            build_diagnostics_section,
        ),
    ),
)

_LIVE_LIGHT_SECTIONS = frozenset({"color", "effects", "ambient", "music"})

_NAV_ICONS = {
    "color": "color",
    "scenes": "layers-3",
    "effects": "effects",
    "ambient": "monitor",
    "music": "audio-lines",
    "profiles": "configs",
    "schedule": "calendar",
    "automations": "workflow",
    "settings": "settings",
}


class _CurrentPageStack(QStackedWidget):
    """Size the stack from the visible page, never from a wider hidden page."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        if page is None:
            return QSize(0, 0)
        hint = page.sizeHint()
        return QSize(0, hint.height())

    def minimumSizeHint(self) -> QSize:
        page = self.currentWidget()
        if page is None:
            return QSize(0, 0)
        return QSize(0, page.minimumSizeHint().height())


class _CenteredContent(QWidget):
    """Fill the available width up to a cap, then centre the content."""

    def __init__(self, content: QWidget, maximum_width: int) -> None:
        super().__init__()
        self._content = content
        self._maximum_width = maximum_width
        content.setParent(self)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = min(self.width(), self._maximum_width)
        left = max(0, (self.width() - width) // 2)
        self._content.setGeometry(left, 0, width, self.height())


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
    body_scroll = getattr(host, "body_scroll", None)
    if body_scroll is not None:
        body_scroll.verticalScrollBar().setValue(0)
    preview = getattr(host, "preview", None)
    if preview is not None:
        preview.set_compact(key not in _LIVE_LIGHT_SECTIONS)
    _reveal_nav_item(host, key)


def _reveal_nav_item(host, key: str) -> None:
    """Scroll the rail so the item that is now current can be seen.

    The rail scrolls on a short window, so a section opened from anywhere other than
    its own button — restoring the last section on start-up, the status card jumping
    to Settings — can leave the highlight above or below the visible part of the list.
    The page would then be the right one while the sidebar showed a different item as
    current.

    Deferred by a zero timer because on the first pass the rail has not been laid out
    yet, and scrolling against geometry that is still all zeroes does nothing. The
    scroll area is passed as the timer's context object, so a window closed in that
    one turn of the event loop cancels this instead of reaching a deleted widget.
    """
    button = host._nav_buttons.get(key)
    nav_scroll = getattr(host, "nav_scroll", None)
    if button is None or nav_scroll is None:
        return
    QTimer.singleShot(0, nav_scroll, lambda: nav_scroll.ensureWidgetVisible(button))


def _on_status_clicked(host) -> None:
    # Disconnected → start a controller search right away; connected → open the
    # device card so the user can manage/disconnect.
    if getattr(host, "_is_connected", False):
        select_section(host, "settings")
    else:
        host._ble_events.start_scan()


def _build_sections(host) -> None:
    host._section_stack = _CurrentPageStack()
    # A stacked widget's size hint is the largest of *all* its pages. Keeping
    # the default horizontal policy made a hidden wide page force the scroll
    # canvas wider than its viewport, clipping the visible card on laptops.
    host._section_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
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
        button.set_icon_kind(_NAV_ICONS[key])
        button.setIconSize(QSize(host._sz(18), host._sz(18)))
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

    # The nav items live in their own scroll area so a short window (e.g.
    # 1366×768 at 150%) never clips the lower items or pushes the status card off
    # the bottom. Brand stays pinned above, status pinned below; only the nav
    # list scrolls, and only when it doesn't fit. Nothing is ever hidden.
    nav_container = QWidget()
    nav_container.setObjectName("navList")
    nav_layout = QVBoxLayout(nav_container)
    nav_layout.setContentsMargins(0, 0, 0, 0)
    nav_layout.setSpacing(host._sz(8))
    for button in host._nav_buttons.values():
        nav_layout.addWidget(button)
    nav_layout.addStretch(1)

    host.nav_scroll = QScrollArea()
    host.nav_scroll.setObjectName("navScroll")
    host.nav_scroll.setWidgetResizable(True)
    host.nav_scroll.setFrameShape(QFrame.NoFrame)
    host.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    host.nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    host.nav_scroll.setAttribute(Qt.WA_TranslucentBackground)
    host.nav_scroll.setStyleSheet("#navScroll, #navScroll > QWidget > QWidget { background: transparent; }")
    host.nav_scroll.setWidget(nav_container)
    host.nav_scroll.viewport().setAutoFillBackground(False)
    column.addWidget(host.nav_scroll, 1)

    # Connection state always visible at the foot of the rail — a small card
    # with a coloured dot (green = connected, dim = not) plus the status text.
    # Clickable: jumps straight to the device section so connecting never
    # requires hunting through Settings.
    status_card = QPushButton()
    host.device_status_card = status_card
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
    host.device_status_dot.setStyleSheet(f"background: rgba(255, 255, 255, 0.30); border-radius: {dot_size // 2}px;")
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
    column.setMinimumWidth(0)
    column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout = QVBoxLayout(column)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(host._sz(10))

    # Hero "live light": the big bar that glows the current strip colour.
    host.preview = AccentPreview()
    host.preview.set_compact(False, animate=False)
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

    # The wrapper gives the column all available room up to its cap. A plain
    # AlignHCenter made Qt use only the content's sizeHint, producing a narrow
    # card and a large empty area on wide windows.
    outer.addWidget(_CenteredContent(column, host._sz(1120)), 1)
    return main


def _build_body_scroll(host) -> QScrollArea:
    host.body_scroll = QScrollArea()
    host.body_scroll.setWidgetResizable(True)
    host.body_scroll.setFrameShape(QFrame.NoFrame)
    host.body_scroll.setObjectName("bodyScroll")
    host.body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    host.body_canvas = QWidget()
    host.body_canvas.setObjectName("bodyCanvas")
    host.body_canvas.setMinimumWidth(0)
    host.body_scroll.setWidget(host.body_canvas)

    canvas_layout = QVBoxLayout(host.body_canvas)
    # Keep the cards clear of the actual styled scrollbar, rather than relying
    # on a magic pixel value. This remains balanced across Windows DPI scales
    # and screen sizes.
    scrollbar_width = host.body_scroll.style().pixelMetric(
        QStyle.PixelMetric.PM_ScrollBarExtent,
        None,
        host.body_scroll.verticalScrollBar(),
    )
    # QScrollArea already reserves the native scrollbar extent. Keep only a
    # small visual breath here; the old double reservation made every card look
    # clipped and shorter than the live-light header above it.
    right_gutter = max(host._sz(8), scrollbar_width // 3)
    canvas_layout.setContentsMargins(0, 0, right_gutter, 0)
    canvas_layout.setSpacing(0)
    # Cap the section to the same width as the content column so it lines up with
    # the hero light and never overflows the scroll horizontally. Stretches
    # vertically centre short sections; taller ones (More) fill and scroll.
    host._section_stack.setMaximumWidth(host._sz(1120))
    host._section_stack.setMinimumWidth(0)
    canvas_layout.addStretch(1)
    canvas_layout.addWidget(host._section_stack)
    canvas_layout.addStretch(1)
    return host.body_scroll
