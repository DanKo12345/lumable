from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import play_or_complete
from app.widgets.liquid_button import LiquidButton
from app.widgets.profile_action_overlay import _ProfileActionPanel

_STAGE_W = 404
_STAGE_H = 268
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_LUCIDE_DIR = _ASSETS / "icons" / "lucide"
_ICON_PATH = _ASSETS / "icon.png"


class _Dots(QWidget):
    """Page indicator: a row of muted dots with an accent capsule that slides
    smoothly to the active step."""

    _SPACING = 20.0

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._count = max(1, count)
        self._pos = 0.0
        self.setFixedSize(int(self._count * self._SPACING), 14)
        self._anim = QPropertyAnimation(self, b"posValue", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def get_pos_value(self) -> float:
        return self._pos

    def set_pos_value(self, value: float) -> None:
        self._pos = float(value)
        self.update()

    posValue = Property(float, get_pos_value, set_pos_value)

    def set_current(self, index: int, *, animate: bool = True) -> None:
        index = max(0, min(self._count - 1, index))
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pos)
            self._anim.setEndValue(float(index))
            self._anim.start()
        else:
            self._pos = float(index)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = theme_manager.palette
        cy = self.height() / 2.0
        total = (self._count - 1) * self._SPACING
        start_x = (self.width() - total) / 2.0

        painter.setPen(Qt.NoPen)
        muted = qcolor_from_token(palette["muted"])
        muted.setAlpha(115)
        painter.setBrush(muted)
        for i in range(self._count):
            painter.drawEllipse(QPointF(start_x + i * self._SPACING, cy), 3.2, 3.2)

        painter.setBrush(qcolor_from_token(palette["accent_start"]))
        ax = start_x + self._pos * self._SPACING
        painter.drawRoundedRect(QRectF(ax - 8.0, cy - 3.6, 16.0, 7.2), 3.6, 3.6)


class OnboardingOverlay(QWidget):
    """First-run welcome carousel: centred slides (welcome → connect → sections →
    Pro → done) that slide horizontally between steps, with Back/Next/Skip and a
    dot indicator. The connect slide has a button that starts a controller scan.
    Reuses the app's overlay panel/backdrop so it matches the rest of the UI."""

    finished = Signal()
    scanRequested = Signal()

    def __init__(self, labels: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self._labels = labels
        self._steps: list[dict[str, Any]] = list(labels.get("steps", []))
        self._index = 0
        self._sliding = False
        self._icon_cache: dict[str, QPixmap] = {}
        self._fade_anim: QPropertyAnimation | None = None
        self._panel_anim: QPropertyAnimation | None = None
        self._slide_out: QParallelAnimationGroup | None = None
        self._slide_in: QParallelAnimationGroup | None = None
        if parent is not None:
            self.setGeometry(parent.rect())
        self._apply_style()

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._build_ui()
        self._apply_step_content()

    # ── build ─────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        self._panel = _ProfileActionPanel(self, height=452)
        layout.addWidget(self._panel, 0, Qt.AlignCenter)
        layout.addStretch(1)

        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(28, 16, 28, 20)
        pl.setSpacing(10)

        top = QHBoxLayout()
        top.addStretch(1)
        self._skip_button = LiquidButton(self._labels["skip"], "ghost", self._panel)
        self._skip_button.setFixedSize(108, 34)
        self._skip_button.clicked.connect(self._finish)
        top.addWidget(self._skip_button)
        pl.addLayout(top)

        # Stage clips the sliding content to its bounds (a child is clipped to its
        # parent), so slides move in/out cleanly like a carousel.
        self._stage = QWidget(self._panel)
        self._stage.setFixedSize(_STAGE_W, _STAGE_H)
        pl.addWidget(self._stage, 0, Qt.AlignHCenter)

        self._content = QWidget(self._stage)
        self._content.setFixedSize(_STAGE_W, _STAGE_H)
        self._content.move(0, 0)
        # The content's opacity effect is created only after the open fade (see
        # _drop_overlay_effect): applying it while the overlay's own effect is
        # active nests two QGraphicsEffects, which renders the first frame at a
        # stale position (the slide briefly appears outside the panel).
        self._content_effect: QGraphicsOpacityEffect | None = None
        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(0, 4, 0, 0)
        cl.setSpacing(10)
        self._icon = QLabel("", self._content)
        self._icon.setObjectName("onboardIcon")
        self._icon.setFixedSize(64, 64)
        self._icon.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self._title = QLabel("", self._content)
        self._title.setObjectName("onboardTitle")
        self._title.setAlignment(Qt.AlignHCenter)
        self._title.setWordWrap(True)
        self._body = QLabel("", self._content)
        self._body.setObjectName("onboardBody")
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._scan_button = LiquidButton(self._labels["scan"], "accent", self._content)
        self._scan_button.setMinimumHeight(44)
        self._scan_button.clicked.connect(self._on_scan)
        # Stretches above and below centre the icon/title/body group vertically in
        # the stage, so short and long slides both sit balanced (no top-clustering).
        cl.addStretch(1)
        cl.addWidget(self._icon, 0, Qt.AlignHCenter)
        cl.addWidget(self._title)
        cl.addWidget(self._body)
        cl.addWidget(self._scan_button)
        cl.addStretch(1)

        self._dots = _Dots(len(self._steps), self._panel)
        pl.addWidget(self._dots, 0, Qt.AlignHCenter)

        nav = QHBoxLayout()
        self._back_button = LiquidButton(self._labels["back"], "ghost", self._panel)
        self._back_button.setFixedSize(120, 42)
        self._back_button.clicked.connect(self._prev)
        self._next_button = LiquidButton(self._labels["next"], "accent", self._panel)
        self._next_button.setFixedSize(150, 42)
        self._next_button.clicked.connect(self._next)
        nav.addWidget(self._back_button)
        nav.addStretch(1)
        nav.addWidget(self._next_button)
        pl.addLayout(nav)

    # ── step content ──────────────────────────────────────────────────
    def _apply_step_content(self) -> None:
        if not self._steps:
            return
        step = self._steps[self._index]
        self._icon.setPixmap(self._icon_pixmap(str(step.get("icon", ""))))
        self._title.setText(str(step.get("title", "")))
        self._body.setText(str(step.get("body", "")))
        self._scan_button.setVisible(bool(step.get("scan")))
        self._back_button.setVisible(self._index > 0)
        last = self._index == len(self._steps) - 1
        self._next_button.setText(self._labels["finish"] if last else self._labels["next"])
        self._dots.set_current(self._index)

    # ── navigation with slide ─────────────────────────────────────────
    def _next(self) -> None:
        if self._index >= len(self._steps) - 1:
            self._finish()
            return
        self._go(self._index + 1, direction=1)

    def _prev(self) -> None:
        if self._index <= 0:
            return
        self._go(self._index - 1, direction=-1)

    def _on_scan(self) -> None:
        self.scanRequested.emit()
        self._next()

    def _ensure_content_effect(self) -> QGraphicsOpacityEffect:
        if self._content_effect is None:
            effect = QGraphicsOpacityEffect(self._content)
            effect.setOpacity(1.0)
            self._content.setGraphicsEffect(effect)
            self._content_effect = effect
        return self._content_effect

    def _go(self, new_index: int, *, direction: int) -> None:
        if self._sliding or not (0 <= new_index < len(self._steps)):
            return
        self._sliding = True
        self._ensure_content_effect()
        width = self._stage.width()

        move_out = QPropertyAnimation(self._content, b"pos", self)
        move_out.setDuration(150)
        move_out.setStartValue(QPoint(0, 0))
        move_out.setEndValue(QPoint(-direction * width, 0))
        move_out.setEasingCurve(QEasingCurve.InCubic)
        fade_out = QPropertyAnimation(self._content_effect, b"opacity", self)
        fade_out.setDuration(150)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        self._slide_out = QParallelAnimationGroup(self)
        self._slide_out.addAnimation(move_out)
        self._slide_out.addAnimation(fade_out)
        self._slide_out.finished.connect(lambda: self._slide_in_new(new_index, direction))
        # Reduced motion completes the group through the engine, so finished fires
        # and synchronously builds + completes the slide-in below.
        play_or_complete(self._slide_out)

    def _slide_in_new(self, new_index: int, direction: int) -> None:
        self._index = new_index
        self._apply_step_content()
        width = self._stage.width()
        self._content.move(direction * width, 0)
        self._content_effect.setOpacity(0.0)

        move_in = QPropertyAnimation(self._content, b"pos", self)
        move_in.setDuration(230)
        move_in.setStartValue(QPoint(direction * width, 0))
        move_in.setEndValue(QPoint(0, 0))
        move_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in = QPropertyAnimation(self._content_effect, b"opacity", self)
        fade_in.setDuration(230)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self._slide_in = QParallelAnimationGroup(self)
        self._slide_in.addAnimation(move_in)
        self._slide_in.addAnimation(fade_in)
        self._slide_in.finished.connect(self._on_slide_done)
        play_or_complete(self._slide_in)

    def _on_slide_done(self) -> None:
        self._sliding = False

    # ── lifecycle ─────────────────────────────────────────────────────
    def open(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            parent.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.PopupFocusReason)
        self._start_open_animation()

    def _start_open_animation(self) -> None:
        self.layout().activate()
        self._panel.layout().activate()  # position the stage before the first paint
        self._content.move(0, 0)
        end_pos = self._panel.pos()
        self._panel.move(end_pos + QPoint(0, 14))
        self._opacity_effect.setOpacity(0.0)
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._panel_anim = QPropertyAnimation(self._panel, b"pos", self)
        self._panel_anim.setDuration(220)
        self._panel_anim.setStartValue(end_pos + QPoint(0, 14))
        self._panel_anim.setEndValue(end_pos)
        self._panel_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_anim.finished.connect(self._drop_overlay_effect)
        # The panel move carries no cleanup — complete it first; the fade's
        # finished swaps the graphics effect, so complete it last.
        play_or_complete(self._panel_anim)
        play_or_complete(self._fade_anim)

    def _drop_overlay_effect(self) -> None:
        # Once the open fade is done, remove the overlay's own opacity effect and
        # only now attach the content effect — so the two never nest (nested
        # QGraphicsEffects render the first slide frame at a stale position).
        self.setGraphicsEffect(None)
        self._opacity_effect = None
        self._ensure_content_effect()

    def _finish(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._finish()
            return
        if event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right}:
            self._next()
            return
        if event.key() == Qt.Key_Left:
            self._prev()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}:
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 96 if theme_manager.is_dark else 60))
        painter.drawRect(self.rect())

    # ── icons (painted, on-brand — no emoji) ──────────────────────────
    def _icon_pixmap(self, kind: str) -> QPixmap:
        cached = self._icon_cache.get(kind)
        if cached is not None:
            return cached
        palette = theme_manager.palette
        accent = qcolor_from_token(palette["accent_start"])
        accent_end = qcolor_from_token(palette["accent_end"])
        size = 64
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = cy = size / 2.0

        # soft accent (or success, for the check) glow behind every icon
        glow_color = qcolor_from_token(palette["success_start"]) if kind == "check" else accent
        glow = QRadialGradient(cx, cy, 30.0)
        glow.setColorAt(0.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 120))
        glow.setColorAt(0.6, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 40))
        glow.setColorAt(1.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), 30.0, 30.0)

        if kind == "app":
            app_pm = QPixmap(str(_ICON_PATH))
            if not app_pm.isNull():
                scaled = app_pm.scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap(int(cx - scaled.width() / 2), int(cy - scaled.height() / 2), scaled)
        elif kind == "sparkle":
            fill = QLinearGradient(cx - 16.0, cy - 16.0, cx + 16.0, cy + 16.0)
            fill.setColorAt(0.0, accent)
            fill.setColorAt(1.0, accent_end)
            painter.setBrush(fill)
            # Nudge the pair left so the small companion sparkle doesn't pull the
            # visual centre to the right of the icon slot.
            self._draw_sparkle(painter, cx - 4.0, cy, 15.0)
            self._draw_sparkle(painter, cx + 11.0, cy - 11.0, 6.0)
        elif kind == "check":
            pen = QPen(qcolor_from_token(palette["success_start"]), 5.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(cx - 12.0, cy + 1.0)
            path.lineTo(cx - 3.0, cy + 10.0)
            path.lineTo(cx + 13.0, cy - 10.0)
            painter.drawPath(path)
        else:
            glyph = self._lucide_glyph(kind, 34, accent)
            if glyph is not None:
                painter.drawPixmap(int(cx - glyph.width() / 2), int(cy - glyph.height() / 2), glyph)
        painter.end()
        self._icon_cache[kind] = pm
        return pm

    @staticmethod
    def _draw_sparkle(painter: QPainter, cx: float, cy: float, size: float) -> None:
        waist = size * 0.32
        path = QPainterPath()
        path.moveTo(cx, cy - size)
        path.cubicTo(cx + waist, cy - waist, cx + waist, cy - waist, cx + size, cy)
        path.cubicTo(cx + waist, cy + waist, cx + waist, cy + waist, cx, cy + size)
        path.cubicTo(cx - waist, cy + waist, cx - waist, cy + waist, cx - size, cy)
        path.cubicTo(cx - waist, cy - waist, cx - waist, cy - waist, cx, cy - size)
        painter.drawPath(path)

    @staticmethod
    def _lucide_glyph(name: str, size: int, color: QColor) -> QPixmap | None:
        svg = _LUCIDE_DIR / f"{name}.svg"
        if not svg.exists():
            return None
        renderer = QSvgRenderer(str(svg))
        glyph = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        glyph.fill(Qt.transparent)
        gp = QPainter(glyph)
        gp.setRenderHint(QPainter.Antialiasing)
        renderer.render(gp, QRectF(0, 0, size, size))
        gp.end()
        tint = QImage(glyph.size(), QImage.Format_ARGB32_Premultiplied)
        tint.fill(Qt.transparent)
        tp = QPainter(tint)
        tp.fillRect(tint.rect(), color)
        tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        tp.drawImage(0, 0, glyph)
        tp.end()
        return QPixmap.fromImage(tint)

    def _apply_style(self) -> None:
        palette = theme_manager.palette
        self.setStyleSheet(
            f"""
            #onboardIcon {{
                font-size: 40px;
            }}
            #onboardTitle {{
                color: {palette["text"]};
                font-size: 21px;
                font-weight: 800;
            }}
            #onboardBody {{
                color: {palette["text_soft"]};
                font-size: 13.5px;
                font-weight: 500;
                line-height: 1.6em;
            }}
            #onboardDots {{
                color: {palette["muted"]};
                font-size: 13px;
                letter-spacing: 1px;
            }}
            """
        )
