from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.motion_policy import motion_policy
from app.theme import (
    overlay_panel_colors,
    pro_badge_tokens,
    qcolor_from_token,
    theme_manager,
)
from app.widgets.animation_helpers import play_or_complete
from app.widgets.celebration_overlay import CelebrationOverlay
from app.widgets.clickable_label import ClickableLabel
from app.widgets.icon_tile import IconTile
from app.widgets.liquid_button import LiquidButton
from app.widgets.themed_line_edit import ThemedLineEdit

# Panel heights: value-first (all benefits shown) collapses to the buy CTA; the
# key field is revealed on request, growing the panel.
_FREE_COLLAPSED_H = 620
_FREE_EXPANDED_H = 688

# The six headline Pro benefits, in display order. Icon + tint live in code (a
# visual concern); the name/description come from i18n via these label keys, so
# a missing key just hides that tile instead of crashing (minimal-labels tests).
# Kept in step with feature_gate.PRO_FEATURES — note scenes are Free, so they are
# deliberately absent here.
_PRO_FEATURES = (
    ("audio-lines", "#ff8fb0", "feat_music", "feat_music_desc"),
    ("monitor", "#78a7ff", "feat_screen", "feat_screen_desc"),
    ("effects", "#b58fff", "feat_diy", "feat_diy_desc"),
    ("calendar", "#ffb066", "feat_schedule", "feat_schedule_desc"),
    ("layers-3", "#72c7b7", "feat_effects", "feat_effects_desc"),
    ("configs", "#8fd3ff", "feat_profiles", "feat_profiles_desc"),
)

# Animated "checking…" suffix cycled in the activate button while a key is verified.
_SPINNER_FRAMES = ("", ".", "..", "...")


class _ActivateWorker(QThread):
    """Runs the (network) license activation off the UI thread so the window
    never freezes while the Lemon Squeezy request is in flight.
    """

    done = Signal(bool, str)

    def __init__(self, callback: Callable[[str], tuple[bool, str]], key: str, parent=None) -> None:
        super().__init__(parent)
        self._callback = callback
        self._key = key

    def run(self) -> None:
        try:
            ok, message = self._callback(self._key)
        except Exception as exc:  # network/parse failure -> a failed activation
            ok, message = False, str(exc)
        self.done.emit(bool(ok), str(message))


class _LicensePanel(QFrame):
    RADIUS = 24.0

    def __init__(self, width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Fixed width; the owner controls height (min/max) so the panel can fit a
        # short window with its centre scrolling.
        self.setFixedWidth(width)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        panel_top, panel_bottom = overlay_panel_colors()
        fill.setColorAt(0.0, panel_top)
        fill.setColorAt(1.0, panel_bottom)
        painter.fillPath(path, fill)

        shine = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        shine.setColorAt(0.0, QColor(255, 255, 255, 30 if theme_manager.is_dark else 62))
        shine.setColorAt(0.48, QColor(255, 255, 255, 6 if theme_manager.is_dark else 16))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        # Soft accent halo behind the title for a more premium, branded feel.
        halo = QRadialGradient(rect.center().x(), rect.top() + rect.height() * 0.16, rect.width() * 0.6)
        accent = qcolor_from_token(theme_manager.palette["accent_start"])
        halo.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 60 if theme_manager.is_dark else 46))
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.fillPath(path, halo)

        border = qcolor_from_token(theme_manager.palette["surface_border"])
        border.setAlpha(98 if theme_manager.is_dark else 110)
        painter.setPen(QPen(border, 1.0))
        painter.drawPath(path)


class _ProEmblem(QWidget):
    """A small painted sparkle badge shown above the title."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # Fixed width too, and tall enough that the glow fades inside the bounds
        # (so the round halo is never clipped into a square).
        self.setFixedSize(132, 60)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        accent_start = qcolor_from_token(theme_manager.palette["accent_start"])
        accent_end = qcolor_from_token(theme_manager.palette["accent_end"])

        glow_radius = 26.0
        glow = QRadialGradient(cx, cy, glow_radius)
        glow.setColorAt(0.0, QColor(accent_start.red(), accent_start.green(), accent_start.blue(), 150))
        glow.setColorAt(0.6, QColor(accent_start.red(), accent_start.green(), accent_start.blue(), 60))
        glow.setColorAt(1.0, QColor(accent_start.red(), accent_start.green(), accent_start.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        fill = QLinearGradient(cx - 16.0, cy - 16.0, cx + 16.0, cy + 16.0)
        fill.setColorAt(0.0, accent_start)
        fill.setColorAt(1.0, accent_end)
        painter.setBrush(fill)
        self._draw_sparkle(painter, cx, cy, 15.0)
        self._draw_sparkle(painter, cx + 16.0, cy - 11.0, 6.0)

    def _draw_sparkle(self, painter: QPainter, cx: float, cy: float, size: float) -> None:
        waist = size * 0.32
        path = QPainterPath()
        path.moveTo(cx, cy - size)
        path.cubicTo(cx + waist, cy - waist, cx + waist, cy - waist, cx + size, cy)
        path.cubicTo(cx + waist, cy + waist, cx + waist, cy + waist, cx, cy + size)
        path.cubicTo(cx - waist, cy + waist, cx - waist, cy + waist, cx - size, cy)
        path.cubicTo(cx - waist, cy - waist, cx - waist, cy - waist, cx, cy - size)
        painter.drawPath(path)


class _ProStatusBadge(QWidget):
    """A green checkmark crest with a slow breathing glow for the active state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        # The widget must be larger than the glow so the soft halo fades to zero
        # *inside* the bounds — otherwise the rect clips it into a square.
        self.setFixedSize(132, 116)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self) -> None:
        self._phase += 0.06
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        radius = 31.0
        pulse = (math.sin(self._phase) + 1.0) * 0.5

        start = qcolor_from_token(theme_manager.palette["success_start"])
        end = qcolor_from_token(theme_manager.palette["success_end"])

        # Fixed radius (< half the widget height) keeps the halo perfectly round;
        # the breathing is driven by alpha only, never by the radius.
        glow_radius = 52.0
        glow = QRadialGradient(cx, cy, glow_radius)
        glow.setColorAt(0.0, QColor(start.red(), start.green(), start.blue(), int(60 + 60 * pulse)))
        glow.setColorAt(0.55, QColor(start.red(), start.green(), start.blue(), int(24 + 26 * pulse)))
        glow.setColorAt(1.0, QColor(start.red(), start.green(), start.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

        fill = QRadialGradient(cx, cy - radius * 0.3, radius * 1.7)
        fill.setColorAt(0.0, start)
        fill.setColorAt(1.0, end)
        painter.setBrush(fill)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 80), 1.4))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        pen = QPen(QColor(255, 255, 255), 5.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        check = QPainterPath()
        check.moveTo(cx - 14.0, cy + 1.0)
        check.lineTo(cx - 3.5, cy + 11.0)
        check.lineTo(cx + 15.0, cy - 11.0)
        painter.drawPath(check)


class LicenseOverlay(QWidget):
    activated = Signal()
    deactivated = Signal()
    closed = Signal()

    def __init__(
        self,
        labels: dict[str, str],
        activate_callback: Callable[[str], tuple[bool, str]],
        parent: QWidget | None = None,
        *,
        mode: str = "free",
        buy_callback: Callable[[], bool] | None = None,
        deactivate_callback: Callable[[], tuple[bool, str]] | None = None,
        license_key: str = "",
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._activate_callback = activate_callback
        self._activate_worker: _ActivateWorker | None = None
        self._buy_callback = buy_callback
        self._deactivate_callback = deactivate_callback
        self._mode = mode
        self._license_key = str(license_key or "").strip()
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        self._panel_opacity: QGraphicsOpacityEffect | None = None
        self._celebration: CelebrationOverlay | None = None
        self._deactivate_armed = False
        self._disarm_timer = QTimer(self)
        self._disarm_timer.setSingleShot(True)
        self._disarm_timer.setInterval(4000)
        self._disarm_timer.timeout.connect(self._disarm_deactivate)
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        active = self._is_active_mode()
        self._key_revealed = False
        self._spinner_frame = 0
        self._activating = False
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(280)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        motion_policy.changed.connect(self._on_spinner_motion_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _LicensePanel(560 if active else 640, self)
        self._panel.setMinimumHeight(300)
        self._panel.setMaximumHeight(self._preferred_height())
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(34, 20, 34, 24)
        panel_layout.setSpacing(12)

        # --- Pinned header: a compact title + the × close. Nothing tall lives
        # here, so on a short window (860×420) the title and close stay visible
        # while the value content below scrolls. Esc also closes via keyPressEvent.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        if active:
            title = QLabel(labels["active_title"], self._panel)
            title.setObjectName("licenseTitle")
            title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.addWidget(title, 1, Qt.AlignVCenter)
            self._title_label = title
            self._title_pro_label = None
        else:
            title_row = QWidget(self._panel)
            title_layout = QHBoxLayout(title_row)
            title_layout.setContentsMargins(0, 0, 0, 0)
            title_layout.setSpacing(6)
            title_text = str(labels["title"]).strip()
            brand_text = title_text[:-4].rstrip() if title_text.lower().endswith(" pro") else title_text
            title = QLabel(brand_text, title_row)
            title.setObjectName("licenseTitle")
            title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            title_layout.addWidget(title, 0, Qt.AlignVCenter)
            pro_title = QLabel("Pro", title_row)
            pro_title.setObjectName("licenseTitlePro")
            pro_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            title_layout.addWidget(pro_title, 0, Qt.AlignVCenter)
            title_layout.addStretch(1)
            header.addWidget(title_row, 1, Qt.AlignVCenter)
            self._title_label = title
            self._title_pro_label = pro_title
        self._close_button = ClickableLabel("✕", self._panel)
        self._close_button.setObjectName("licenseClose")
        self._close_button.setFixedSize(32, 32)
        self._close_button.setAlignment(Qt.AlignCenter)
        self._close_button.setCursor(Qt.PointingHandCursor)
        self._close_button.setToolTip(labels.get("close", ""))
        self._close_button.setAccessibleName(labels.get("close", "Close"))
        self._close_button.clicked.connect(self.close_overlay)
        header.addWidget(self._close_button, 0, Qt.AlignTop | Qt.AlignRight)
        panel_layout.addLayout(header)

        # --- Scrollable centre: emblem/status, benefits, key field, message.
        # Only this area gives up height on a short window; header and footer stay.
        self._scroll = QScrollArea(self._panel)
        self._scroll.setObjectName("licenseScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setAttribute(Qt.WA_TranslucentBackground)
        self._scroll.viewport().setAutoFillBackground(False)
        centre = QWidget()
        centre.setObjectName("licenseScrollContent")
        centre_layout = QVBoxLayout(centre)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(10)

        badge = _ProStatusBadge(centre) if active else _ProEmblem(centre)
        centre_layout.addWidget(badge, 0, Qt.AlignHCenter)

        self._hero_title: QLabel | None = None
        self._features_grid: QWidget | None = None
        if not active and labels.get("hero_title"):
            hero_title = QLabel(labels["hero_title"], centre)
            hero_title.setObjectName("licenseHeroTitle")
            hero_title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            hero_title.setWordWrap(True)
            centre_layout.addWidget(hero_title)
            self._hero_title = hero_title

        subtitle = QLabel(self._active_message() if active else labels["subtitle"], centre)
        subtitle.setObjectName("licenseSubtitle")
        subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        subtitle.setWordWrap(True)

        if active:
            status_card = QFrame(centre)
            status_card.setObjectName("licenseStatusCard")
            status_layout = QVBoxLayout(status_card)
            status_layout.setContentsMargins(18, 14, 18, 16)
            status_layout.setSpacing(12)
            status_layout.addWidget(subtitle)
            masked = self._masked_key()
            if masked:
                key_chip = QLabel(masked, status_card)
                key_chip.setObjectName("licenseKeyChip")
                key_chip.setAlignment(Qt.AlignHCenter)
                status_layout.addWidget(key_chip, 0, Qt.AlignHCenter)
            centre_layout.addWidget(status_card)
        else:
            centre_layout.addWidget(subtitle)
            centre_layout.addSpacing(10)
            features_grid = self._build_features_grid()
            if features_grid is not None:
                centre_layout.addWidget(features_grid)
                self._features_grid = features_grid

        # The key field belongs with the footer actions, not with the benefits.
        # This flexible gap pushes it down on a tall window and collapses to zero
        # when the centre has to scroll at the minimum window height.
        centre_layout.addStretch(1)

        # The key field: always built, but hidden until the user asks for it in
        # free mode (and always hidden in the active/licensed state).
        field_box = QFrame(centre)
        self._field_box = field_box
        field_box.setObjectName("licenseFieldBox")
        field_layout = QVBoxLayout(field_box)
        field_layout.setContentsMargins(18, 10, 18, 10)
        field_layout.setSpacing(6)
        field_label = QLabel(labels["key_label"], field_box)
        field_label.setObjectName("licenseFieldLabel")
        self.key_input = ThemedLineEdit(field_box)
        self.key_input.setObjectName("licenseKeyInput")
        self.key_input.setPlaceholderText(labels["placeholder"])
        self.key_input.returnPressed.connect(self._activate)
        self.key_input.installEventFilter(self)
        field_layout.addWidget(field_label)
        field_layout.addWidget(self.key_input)
        centre_layout.addWidget(field_box)
        field_box.setVisible(False)

        self.message_label = QLabel("", centre)
        self.message_label.setObjectName("licenseMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumHeight(24)
        self.message_label.hide()
        centre_layout.addWidget(self.message_label)
        centre_layout.addStretch(1)

        self._scroll.setWidget(centre)
        panel_layout.addWidget(self._scroll, 1)

        # --- Pinned footer: the primary CTA / OK, Back, and deactivate stay put.
        # Active: a single OK. Free default: one primary "Buy Pro" plus a quiet
        # "I already have a key" link. Revealing the key swaps in Back + Activate.
        self.buy_button = LiquidButton(labels.get("buy", ""), "premium", self._panel)
        self.buy_button.set_icon_kind("crown")
        self.buy_button.clicked.connect(self._show_buy_message)
        self._activate_button = LiquidButton(labels.get("activate", ""), "accent", self._panel)
        self._activate_button.clicked.connect(self._activate)

        if active:
            ok_button = LiquidButton(labels.get("ok", ""), "ghost", self._panel)
            self._cancel_button = ok_button
            ok_button.setMinimumSize(140, 40)
            ok_button.clicked.connect(self.close_overlay)
            self.buy_button.setVisible(False)
            self._activate_button.setVisible(False)
            ok_row = QHBoxLayout()
            ok_row.addStretch(1)
            ok_row.addWidget(ok_button)
            ok_row.addStretch(1)
            panel_layout.addLayout(ok_row)
        else:
            divider = QFrame(self._panel)
            divider.setObjectName("licenseFooterDivider")
            divider.setFrameShape(QFrame.HLine)
            divider.setFixedHeight(1)
            panel_layout.addWidget(divider)

            # Default: buy hero + quiet "have key" link.
            self._buy_row = QWidget(self._panel)
            buy_layout = QVBoxLayout(self._buy_row)
            buy_layout.setContentsMargins(0, 0, 0, 0)
            buy_layout.setSpacing(8)
            self.buy_button.setFixedSize(400, 52)
            buy_inner = QHBoxLayout()
            buy_inner.addStretch(1)
            buy_inner.addWidget(self.buy_button)
            buy_inner.addStretch(1)
            buy_layout.addLayout(buy_inner)
            have_key_text = labels.get("have_key", "")
            self._have_key_link = ClickableLabel(f"{have_key_text}  →", self._buy_row)
            self._have_key_link.setObjectName("licenseHaveKey")
            self._have_key_link.setAlignment(Qt.AlignHCenter)
            self._have_key_link.setCursor(Qt.PointingHandCursor)
            self._have_key_link.setAccessibleName(have_key_text)
            self._have_key_link.clicked.connect(self._reveal_key)
            buy_layout.addWidget(self._have_key_link, 0, Qt.AlignHCenter)
            panel_layout.addWidget(self._buy_row)

            # Revealed: Back + Activate.
            self._reveal_row = QWidget(self._panel)
            reveal_layout = QHBoxLayout(self._reveal_row)
            reveal_layout.setContentsMargins(0, 0, 0, 0)
            reveal_layout.setSpacing(10)
            self._back_button = LiquidButton(labels.get("back", ""), "ghost", self._panel)
            self._cancel_button = self._back_button
            self._back_button.setMinimumSize(120, 40)
            self._back_button.clicked.connect(self._hide_key)
            self._activate_button.setMinimumSize(160, 40)
            reveal_layout.addStretch(1)
            reveal_layout.addWidget(self._back_button)
            reveal_layout.addWidget(self._activate_button)
            reveal_layout.addStretch(1)
            self._reveal_row.setVisible(False)
            panel_layout.addWidget(self._reveal_row)

        # Deactivation is a rare, destructive action: keep it as a quiet link
        # under the primary button and require a second click to confirm.
        self.deactivate_link: ClickableLabel | None = None
        if self._mode == "license":
            link = ClickableLabel(labels.get("deactivate", ""), self._panel)
            link.setObjectName("licenseDeactivateLink")
            link.setAlignment(Qt.AlignHCenter)
            link.setCursor(Qt.PointingHandCursor)
            link_font = link.font()
            link_font.setUnderline(True)
            link.setFont(link_font)
            link.clicked.connect(self._on_deactivate_link)
            self.deactivate_link = link
            panel_layout.addSpacing(2)
            panel_layout.addWidget(link, 0, Qt.AlignHCenter)

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        # Fit the panel to the window BEFORE the animation reads its geometry.
        self._fit_to_parent()
        self._prepare_open_animation()
        self.show()
        self.raise_()
        # Free mode opens on the value screen with the key hidden, so focus the
        # overlay itself (Esc/close work); the key field grabs focus on reveal.
        self.setFocus(Qt.PopupFocusReason)
        QTimer.singleShot(0, self._start_open_animation)

    def _is_active_mode(self) -> bool:
        return self._mode in {"dev", "license"}

    def _preferred_height(self) -> int:
        if self._is_active_mode():
            return 460
        return _FREE_EXPANDED_H if self._key_revealed else _FREE_COLLAPSED_H

    def _fitted_height(self) -> int:
        # Explicit: min(preferred, available). Growing the window back restores
        # the full preferred height because it is recomputed every time.
        parent = self.parentWidget()
        if parent is None:
            return self._preferred_height()
        return max(300, min(self._preferred_height(), parent.height() - 24))

    def _fit_to_parent(self) -> None:
        height = self._fitted_height()
        self._panel.setMinimumHeight(height)
        self._panel.setMaximumHeight(height)

    def _active_message(self) -> str:
        return self._labels["active_dev"] if self._mode == "dev" else self._labels["active_license"]

    def _masked_key(self) -> str:
        """A privacy-preserving preview of the saved key, e.g. ``ABCD ···· WXYZ``."""
        key = self._license_key
        if len(key) < 8:
            return ""
        return f"{key[:4]} ···· {key[-4:]}"

    def _build_features_grid(self) -> QWidget | None:
        """The six headline Pro benefits as a 2x3 icon-tile grid — value shown
        up front, all at once. Returns None if no feature strings were supplied
        (minimal-labels tests), so the panel simply omits the block."""
        tiles = [
            (icon, tint, str(self._labels.get(name_key, "")).strip(), str(self._labels.get(desc_key, "")).strip())
            for icon, tint, name_key, desc_key in _PRO_FEATURES
        ]
        tiles = [t for t in tiles if t[2]]
        if not tiles:
            return None

        container = QWidget(self._panel)
        grid = QGridLayout(container)
        grid.setContentsMargins(8, 0, 8, 0)
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(18)
        for index, (icon, tint, name, desc) in enumerate(tiles):
            grid.addWidget(self._feature_tile(icon, tint, name, desc), index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return container

    def _feature_tile(self, icon: str, tint: str, name: str, desc: str) -> QWidget:
        cell = QWidget(self._panel)
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(IconTile(icon, tint, tile_size=42, glyph_size=24), 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 1, 0, 0)
        text.setSpacing(1)
        text.setAlignment(Qt.AlignTop)
        name_label = QLabel(name, cell)
        name_label.setObjectName("licenseFeatureName")
        text.addWidget(name_label)
        if desc:
            desc_label = QLabel(desc, cell)
            desc_label.setObjectName("licenseFeatureDesc")
            desc_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            # Two lines max, never elided: a purchase screen must not truncate
            # the meaning it is selling.
            desc_label.setWordWrap(True)
            text.addWidget(desc_label)
        row.addLayout(text, 1)
        return cell

    def _reveal_key(self) -> None:
        """Swap the buy CTA for the key field on request (progressive disclosure)."""
        if self._key_revealed:
            return
        self._key_revealed = True
        self._buy_row.setVisible(False)
        self._field_box.setVisible(True)
        self._reveal_row.setVisible(True)
        self._set_message("")
        self._animate_panel_height(self._fitted_height())
        self.key_input.setFocus(Qt.OtherFocusReason)
        # Defer to the next tick so the field has its final geometry before we
        # scroll it into view (it was just made visible / the panel resized).
        QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self.key_input, 0, 40))

    def _hide_key(self) -> None:
        """Back out of the key field to the buy CTA."""
        if not self._key_revealed:
            return
        self._key_revealed = False
        self._field_box.setVisible(False)
        self._reveal_row.setVisible(False)
        self._buy_row.setVisible(True)
        self._set_message("")
        self._animate_panel_height(self._fitted_height())

    def _animate_panel_height(self, end: int) -> None:
        start = self._panel.height()
        self._height_anims = []
        for prop in (b"minimumHeight", b"maximumHeight"):
            anim = QPropertyAnimation(self._panel, prop, self)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.setStartValue(start)
            anim.setEndValue(end)
            self._height_anims.append(anim)
            anim.start()

    def _set_message(self, text: str, state: str = "") -> None:
        text = str(text)
        self.message_label.setText(text)
        self.message_label.setVisible(bool(text))
        self.message_label.setProperty("state", state)
        self.message_label.style().unpolish(self.message_label)
        self.message_label.style().polish(self.message_label)

    def _activate(self) -> None:
        if self._activate_worker is not None:
            return  # an activation is already in flight
        self._set_activating(True)
        self._set_message("")
        worker = _ActivateWorker(self._activate_callback, self.key_input.text(), self)
        self._activate_worker = worker
        worker.done.connect(self._on_activate_done)
        # Clear the reference on the thread's real ``finished`` (after run() has
        # returned and the OS thread has stopped), not on ``done`` — ``done`` is
        # emitted from inside run() while the thread is still technically
        # running, which would let close_overlay's guard race a live thread.
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_worker_finished(self) -> None:
        self._activate_worker = None

    def _set_activating(self, busy: bool) -> None:
        self.key_input.setEnabled(not busy)
        self._activate_button.setEnabled(not busy)
        self._cancel_button.setEnabled(not busy)
        self.buy_button.setEnabled(not busy)
        # Dim the close affordance while checking — close is refused anyway
        # (close_overlay guards on the running worker), but the dim signals it.
        self._close_button.setEnabled(not busy)
        self._activating = busy
        if busy:
            self._sync_spinner()
        else:
            self._spinner_timer.stop()
            self._activate_button.setText(self._labels.get("activate", ""))

    def _sync_spinner(self) -> None:
        """Under reduced motion the worker keeps checking the key — only the
        cycling dots stop. The label itself carries no suffix ("Checking"), so a
        single static ellipsis is appended to still read as work in progress."""
        if not self._activating:
            self._spinner_timer.stop()
            return
        base = self._labels.get("activating", "")
        if motion_policy.reduced:
            self._spinner_timer.stop()
            self._activate_button.setText(f"{base.rstrip('.…')}…")
            return
        self._spinner_frame = 0
        self._activate_button.setText(base or "…")
        if not self._spinner_timer.isActive():
            self._spinner_timer.start()

    def _on_spinner_motion_changed(self, _reduced: bool) -> None:
        self._sync_spinner()

    def _tick_spinner(self) -> None:
        """Animate a trailing '…' in the activate button while a key is checked —
        an in-button progress indicator so the wait never looks frozen."""
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        base = self._labels.get("activating", "…")
        self._activate_button.setText(f"{base}{_SPINNER_FRAMES[self._spinner_frame]}")

    def _on_activate_done(self, ok: bool, message: str) -> None:
        # Note: the worker reference is cleared by _on_worker_finished (the
        # thread's ``finished`` signal), not here — ``done`` runs before the
        # thread has actually stopped.
        self._set_activating(False)
        self._set_message("" if ok else message, "success" if ok else "error")
        if ok:
            self.activated.emit()
            self._play_success(message)

    def _play_success(self, message: str) -> None:
        """Celebrate a successful activation, then close the overlay."""
        # Lock further input and gently fade the panel away so the confetti and
        # the checkmark badge own the moment.
        self.key_input.setEnabled(False)
        self._activate_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self.buy_button.setEnabled(False)

        self._panel_opacity = QGraphicsOpacityEffect(self._panel)
        self._panel.setGraphicsEffect(self._panel_opacity)
        self._panel_anim = QPropertyAnimation(self._panel_opacity, b"opacity", self)
        self._panel_anim.setDuration(260)
        self._panel_anim.setStartValue(1.0)
        self._panel_anim.setEndValue(0.0)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim.start()

        self._celebration = CelebrationOverlay(self, message=message)
        self._celebration.finished.connect(self.close_overlay)
        self._celebration.start()

    def _show_buy_message(self) -> None:
        if self._buy_callback is not None and self._buy_callback():
            return
        self._set_message(self._labels["buy_unavailable"], "info")

    def _on_deactivate_link(self) -> None:
        if self._deactivate_callback is None or self.deactivate_link is None:
            return
        if not self._deactivate_armed:
            # First click only arms the action; a second click confirms it.
            self._deactivate_armed = True
            self.deactivate_link.setText(self._labels.get("deactivate_confirm", self._labels.get("deactivate", "")))
            self.deactivate_link.setProperty("armed", True)
            self.deactivate_link.style().unpolish(self.deactivate_link)
            self.deactivate_link.style().polish(self.deactivate_link)
            self._disarm_timer.start()
            return
        self._disarm_timer.stop()
        self._deactivate()
        self._disarm_deactivate()

    def _disarm_deactivate(self) -> None:
        self._deactivate_armed = False
        if self.deactivate_link is None:
            return
        self.deactivate_link.setText(self._labels.get("deactivate", ""))
        self.deactivate_link.setProperty("armed", False)
        self.deactivate_link.style().unpolish(self.deactivate_link)
        self.deactivate_link.style().polish(self.deactivate_link)

    def _deactivate(self) -> None:
        if self._deactivate_callback is None:
            return
        ok, message = self._deactivate_callback()
        self._set_message(message, "success" if ok else "error")
        if ok:
            self.deactivated.emit()
            self.close_overlay()

    def _prepare_open_animation(self) -> None:
        self.layout().activate()
        self._opacity_effect.setOpacity(0.0)

    def _start_open_animation(self) -> None:
        if not self.isVisible():
            return
        self.layout().activate()
        self._panel.raise_()

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(210)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        play_or_complete(self._fade_anim)

        # Let the panel rise into place for a softer, more polished entrance.
        target = self._panel.geometry()
        self._panel_anim = QPropertyAnimation(self._panel, b"geometry", self)
        self._panel_anim.setDuration(300)
        self._panel_anim.setStartValue(target.translated(0, 26))
        self._panel_anim.setEndValue(target)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        play_or_complete(self._panel_anim)

    def close_overlay(self) -> None:
        # Never tear the overlay down while a key check is in flight: the
        # activation worker is a child QThread, so deleteLater() here would
        # destroy a still-running thread ("QThread: Destroyed while thread is
        # still running", up to a crash). Both the × button and Esc route
        # through here, so this one guard covers both. Check the real thread
        # state, not just the reference: ``done`` fires before the thread stops.
        if self._activate_worker is not None and self._activate_worker.isRunning():
            return
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 44 if theme_manager.is_dark else 26))
        painter.drawRect(self.rect())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
                self._fit_to_parent()
        elif watched is self.key_input and event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
            self._field_box.setProperty("focused", event.type() == QEvent.Type.FocusIn)
            self._field_box.style().unpolish(self._field_box)
            self._field_box.style().polish(self._field_box)
        return super().eventFilter(watched, event)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        pro = pro_badge_tokens(theme_manager.is_dark)
        self.setStyleSheet(
            f"""
            #licenseScroll, #licenseScroll > QWidget, #licenseScrollContent {{
                background: transparent;
                border: none;
            }}
            #licenseTitle {{
                color: {palette["text"]};
                font-size: 24px;
                font-weight: 800;
            }}
            #licenseTitlePro {{
                color: {pro["text"]};
                font-size: 24px;
                font-weight: 800;
            }}
            #licenseHeroTitle {{
                color: {palette["text"]};
                font-size: 18px;
                font-weight: 800;
            }}
            #licenseSubtitle {{
                color: {palette["muted"]};
                font-size: 13px;
                font-weight: 500;
                line-height: 1.35em;
            }}
            #licenseStatusCard {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 18px;
            }}
            #licenseFeatureName {{
                color: {palette["text"]};
                font-size: 14px;
                font-weight: 800;
            }}
            #licenseFeatureDesc {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 500;
            }}
            #licenseHaveKey {{
                color: {palette["accent_start"]};
                font-size: 13px;
                font-weight: 800;
                padding: 4px 8px;
            }}
            #licenseHaveKey:hover {{
                color: {palette["text"]};
            }}
            #licenseFooterDivider {{
                background: {palette["surface_line"]};
                border: none;
                min-height: 1px;
                max-height: 1px;
            }}
            #licenseClose {{
                color: {palette["muted"]};
                font-size: 15px;
                font-weight: 700;
                border-radius: 10px;
            }}
            #licenseClose:hover {{
                color: {palette["text"]};
                background: {palette["field"]};
            }}
            #licenseKeyChip {{
                color: {palette["text"]};
                font-size: 14px;
                font-weight: 800;
            }}
            #licenseFieldBox {{
                background: {palette["field"]};
                border: 1px solid {palette["field_border"]};
                border-radius: 16px;
            }}
            #licenseFieldBox[focused="true"] {{
                border: 1px solid {palette["accent_start"]};
                background: {palette["field_alt"]};
            }}
            #licenseFieldLabel {{
                color: {palette["text"]};
                font-size: 12px;
                font-weight: 800;
            }}
            #licenseKeyInput {{
                background: transparent;
                border: none;
                color: {palette["text"]};
                padding: 0 4px;
                min-height: 40px;
                font-size: 13px;
                font-weight: 700;
            }}
            #licenseMessage {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 600;
            }}
            #licenseDeactivateLink {{
                color: {palette["muted"]};
                font-size: 12px;
                font-weight: 700;
                padding: 4px 8px;
            }}
            #licenseDeactivateLink:hover {{
                color: {palette["text_soft"]};
            }}
            #licenseDeactivateLink[armed="true"] {{
                color: #ff9aa9;
            }}
            #licenseMessage[state="error"] {{
                color: #ff9aa9;
            }}
            #licenseMessage[state="success"] {{
                color: #83f0c9;
            }}
            """
        )
