from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QSizePolicy

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import ButtonAnimationMixin, make_property_animation, restart_animation

LUCIDE_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "lucide"


class LiquidButton(ButtonAnimationMixin, QPushButton):
    def __init__(self, text: str = "", role: str = "ghost", parent=None):
        super().__init__(text, parent)
        self._role = role
        self._hover = 0.0
        self._scale = 1.0
        self._ripple = 0.0
        self._ripple_opacity = 0.0
        self._ripple_x = 0.0
        self._ripple_y = 0.0
        self._pointer_x = 0.5
        self._pointer_y = 0.5
        self._icon_kind = ""
        self._icon_renderer: QSvgRenderer | None = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setMinimumHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = make_property_animation(self, b"hoverValue", 180, QEasingCurve.OutCubic)
        self._init_button_motion()

    def set_icon_kind(self, kind: str) -> None:
        self._icon_kind = kind
        self._icon_renderer = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{kind}.svg"), self) if kind else None
        self.update()

    def setIconSize(self, size) -> None:
        super().setIconSize(size)
        self.update()

    def set_role(self, role: str) -> None:
        if role == self._role:
            return
        self._role = role
        self.update()

    def enterEvent(self, event):
        restart_animation(self._anim, self._hover, 1.0)
        self._handle_button_enter()
        super().enterEvent(event)

    def leaveEvent(self, event):
        restart_animation(self._anim, self._hover, 0.0)
        self._pointer_x = 0.5
        self._pointer_y = 0.5
        self._handle_button_leave()
        super().leaveEvent(event)

    def get_hover_value(self):
        return self._hover

    def set_hover_value(self, value):
        self._hover = float(value)
        self.update()

    hoverValue = Property(float, get_hover_value, set_hover_value)

    def get_scale(self):
        return self._scale

    def set_scale(self, value):
        self._scale = float(value)
        self.update()

    scaleValue = Property(float, get_scale, set_scale)

    def get_ripple(self):
        return self._ripple

    def set_ripple(self, value):
        self._ripple = float(value)
        self._ripple_opacity = max(0.0, 1.0 - self._ripple)
        self.update()

    rippleValue = Property(float, get_ripple, set_ripple)

    def mousePressEvent(self, event):
        pos = event.position()
        self._handle_button_press(pos.x(), pos.y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()
        width = max(1.0, float(self.width()))
        height = max(1.0, float(self.height()))
        self._pointer_x = min(1.0, max(0.0, pos.x() / width))
        self._pointer_y = min(1.0, max(0.0, pos.y() / height))
        if self._role in {"primary_warm", "ghost"}:
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._handle_button_release()
        super().mouseReleaseEvent(event)

    # ── shared light-mode palette ──────────────────────────────────────
    @staticmethod
    def _light_palette() -> dict:
        return {
            "fill_top":    QColor(255, 255, 255, 188),
            "fill_mid":    QColor(236, 244, 255, 154),
            "fill_bottom": QColor(198, 218, 248, 138),
            "body_mid":    QColor(166, 192, 232, 12),
            "body_bottom": QColor(92,  120, 168, 14),
            "border_top":  QColor(255, 255, 255, 144),
            "border_bot":  QColor(164, 192, 236, 64),
            "text":        QColor("#18243d"),
        }

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        grow = max(0.0, self._scale - 1.0)
        inset = max(0.8, 4.0 - grow * 75.0)
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        is_ghost = self._role == "ghost"
        radius = rect.height() / 2.0 if is_ghost else 17.0
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        lc = self._light_palette()

        if is_ghost:
            self._paint_ghost(painter, path, rect, radius, lc)
            return

        top, bottom = self._role_base_colors(lc)
        self._paint_glow(painter, path, rect, radius, top)
        painter.setClipPath(path)
        if self._role == "primary_warm":
            self._paint_warm_fill(painter, path, rect)
        elif self._role == "accent_soft":
            self._paint_accent_soft_fill(painter, path, rect, lc)
        else:
            self._paint_standard_fill(painter, path, rect, top, bottom)

        if self._ripple_opacity > 0.01:
            rr = 8 + self._ripple * max(rect.width(), rect.height()) * 0.9
            ripple = QRadialGradient(self._ripple_x, self._ripple_y, rr)
            ripple.setColorAt(0.0, QColor(255, 255, 255, int(72 * self._ripple_opacity)))
            ripple.setColorAt(0.45, QColor(210, 228, 255, int(32 * self._ripple_opacity)))
            ripple.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), ripple)

        painter.setClipping(False)
        self._paint_border(painter, rect, radius, lc)
        self._paint_label(painter, rect, lc)

    # ── ghost (Liquid Glass) ───────────────────────────────────────────
    def _paint_ghost(self, painter: QPainter, path: QPainterPath, rect: QRectF, radius: float, lc: dict) -> None:
        painter.setClipPath(path)
        enabled = self.isEnabled()

        # 1. quiet neutral material
        base_a = 5 + int(3 * self._hover)
        base = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if theme_manager.is_dark:
            base.setColorAt(0.0,  QColor(255, 255, 255, base_a + 1))
            base.setColorAt(0.34, QColor(240, 246, 255, base_a))
            base.setColorAt(0.68, QColor(226, 236, 248, max(0, base_a - 1)))
            base.setColorAt(1.0,  QColor(214, 226, 242, max(0, base_a - 2)))
        else:
            ft, fm, fb = lc["fill_top"], lc["fill_mid"], lc["fill_bottom"]
            base.setColorAt(0.0,  QColor(ft.red(), ft.green(), ft.blue(), ft.alpha()))
            base.setColorAt(0.34, QColor(fm.red(), fm.green(), fm.blue(), fm.alpha()))
            base.setColorAt(0.68, QColor(220, 232, 248, 146))
            base.setColorAt(1.0,  QColor(fb.red(), fb.green(), fb.blue(), 126))
        painter.fillPath(path, base)

        body = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bm, bb = lc["body_mid"], lc["body_bottom"]
        if theme_manager.is_dark:
            body.setColorAt(0.0,  QColor(255, 255, 255, 2))
            body.setColorAt(0.42, QColor(156, 174, 204, 4 if enabled else 2))
            body.setColorAt(1.0,  QColor(14, 20, 36,   6 if enabled else 3))
        else:
            body.setColorAt(0.0,  QColor(255, 255, 255, 8 if enabled else 4))
            body.setColorAt(0.42, QColor(bm.red(), bm.green(), bm.blue(), 12 if enabled else 5))
            body.setColorAt(1.0,  QColor(bb.red(), bb.green(), bb.blue(), 12 if enabled else 5))
        painter.fillPath(path, body)

        # 2. soft top fresnel
        fresnel = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.14)
        fresnel.setColorAt(0.0,  QColor(255, 255, 255, 26 if enabled else 10))
        fresnel.setColorAt(0.22, QColor(255, 255, 255,  6 if enabled else  2))
        fresnel.setColorAt(1.0,  QColor(255, 255, 255,  0))
        painter.fillPath(path, fresnel)

        # 3. bottom refraction
        bot = QLinearGradient(0, rect.bottom() - rect.height() * 0.30, 0, rect.bottom())
        bot.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot.setColorAt(1.0, QColor(0, 0, 0, 6 if theme_manager.is_dark else 10))
        painter.fillPath(path, bot)

        # 4. cursor specular
        if self._hover > 0.01 and enabled:
            sa = int(9 * self._hover)
            spec = QRadialGradient(
                rect.left() + rect.width() * self._pointer_x,
                rect.top() + rect.height() * self._pointer_y * 0.80,
                rect.width() * 0.74,
            )
            spec.setColorAt(0.0,  QColor(255, 255, 255, sa))
            spec.setColorAt(0.22, QColor(255, 255, 255, max(0, sa // 8)))
            spec.setColorAt(1.0,  QColor(255, 255, 255, 0))
            painter.fillPath(path, spec)

        # 5. ripple
        if self._ripple_opacity > 0.01:
            rr = 8 + self._ripple * max(rect.width(), rect.height()) * 0.9
            ripple = QRadialGradient(self._ripple_x, self._ripple_y, rr)
            ripple.setColorAt(0.0,  QColor(255, 255, 255, int(24 * self._ripple_opacity)))
            ripple.setColorAt(0.45, QColor(255, 255, 255, int( 6 * self._ripple_opacity)))
            ripple.setColorAt(1.0,  QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), ripple)

        painter.setClipping(False)

        # 6. glass border
        bt, bb2 = lc["border_top"], lc["border_bot"]
        border_g = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if theme_manager.is_dark:
            border_g.setColorAt(0.0, QColor(255, 255, 255, 36 if enabled else 18))
            border_g.setColorAt(1.0, QColor(218, 224, 236, 20 if enabled else  9))
        else:
            border_g.setColorAt(0.0, QColor(bt.red(),  bt.green(),  bt.blue(),  132 if enabled else 48))
            border_g.setColorAt(1.0, QColor(bb2.red(), bb2.green(), bb2.blue(),  54 if enabled else 20))
        painter.setPen(QPen(QBrush(border_g), 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        # 7. text
        font = self.font()
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        text_color = QColor("#ffffff") if theme_manager.is_dark else QColor(lc["text"])
        if not enabled:
            text_color.setAlpha(110)
        elif not theme_manager.is_dark:
            text_color.setAlpha(232)
        painter.setPen(text_color)
        self._draw_content(painter, rect, text_color)

    # ── base fill colours per role ────────────────────────────────────
    def _role_base_colors(self, lc: dict) -> tuple[QColor, QColor]:
        palette = theme_manager.palette
        ft, fb = lc["fill_top"], lc["fill_bottom"]
        role = self._role
        if role == "mode":
            return (QColor(255, 255, 255, 17), QColor(95, 110, 160, 10)) if theme_manager.is_dark else (QColor(ft), QColor(fb))
        if role == "mode_active":
            return (QColor(251, 191, 146, 138), QColor(114, 73, 54, 94)) if theme_manager.is_dark else (QColor(ft), QColor(fb))
        if role == "primary_warm":
            return (QColor(255, 218, 198, 58), QColor(118, 72, 66, 44)) if theme_manager.is_dark else (QColor(ft), QColor(fb))
        if role == "accent_soft":
            return (QColor(255, 255, 255, 18), QColor(220, 232, 250, 10)) if theme_manager.is_dark else (QColor(ft), QColor(fb))
        if role == "accent":
            top = qcolor_from_token(palette["accent_start"])
            top.setAlpha(118 if theme_manager.is_dark else ft.alpha())
            bot = qcolor_from_token(palette["accent_end"])
            bot.setAlpha(78 if theme_manager.is_dark else fb.alpha())
            return top, bot
        # primary / fallback
        top = qcolor_from_token(palette["accent_start"])
        top.setAlpha(126 if role == "primary" and theme_manager.is_dark else 108 if theme_manager.is_dark else ft.alpha())
        bot = qcolor_from_token(palette["accent_end"])
        bot.setAlpha(88 if role == "primary" and theme_manager.is_dark else 72 if theme_manager.is_dark else fb.alpha())
        return top, bot

    # ── outer glow (non-ghost roles that need it) ──────────────────────
    def _paint_glow(self, painter: QPainter, path: QPainterPath, rect: QRectF, radius: float, top: QColor) -> None:
        role = self._role
        is_mode = role in {"mode", "mode_active"}
        is_warm = role == "primary_warm"
        is_soft = role == "accent_soft"
        if role not in {"accent", "primary"} and not is_mode and not is_warm and not is_soft:
            return
        palette = theme_manager.palette
        glow_rect = rect.adjusted(-1.0, -1.0, 1.0, 1.0)
        glow_path = QPainterPath()
        glow_path.addRoundedRect(glow_rect, radius + 1.0, radius + 1.0)
        if is_warm or role == "mode_active":
            glow_color = QColor(255, 187, 140)
        elif is_soft:
            glow_color = QColor(150, 188, 255) if not theme_manager.is_dark else QColor(255, 255, 255)
        else:
            glow_color = qcolor_from_token(palette["accent_start"])
        if not theme_manager.is_dark:
            glow_color = QColor(120, 160, 255) if is_warm else QColor(168, 198, 244)
        if role == "mode":
            glow_alpha = 8
        elif role == "mode_active":
            glow_alpha = 38
        elif is_soft:
            glow_alpha = 8 if theme_manager.is_dark else 14
        elif role == "accent":
            glow_alpha = 18
        else:
            glow_alpha = 36
        if self._hover > 0.0:
            glow_alpha += int(14 * self._hover)
        glow_color.setAlpha(glow_alpha if self.isEnabled() else 10)
        painter.fillPath(glow_path, glow_color)

    # ── primary_warm fill ──────────────────────────────────────────────
    def _paint_warm_fill(self, painter: QPainter, path: QPainterPath, rect: QRectF) -> None:
        enabled = self.isEnabled()
        base = QLinearGradient(0, rect.top(), 0, rect.bottom())
        base_alpha = (34 if theme_manager.is_dark else 44) + int(12 * self._hover)
        if theme_manager.is_dark:
            base.setColorAt(0.0, QColor(255, 255, 255, base_alpha + 16))
            base.setColorAt(0.5, QColor(255, 250, 246, base_alpha))
            base.setColorAt(1.0, QColor(208, 188, 182, max(0, base_alpha - 10)))
        else:
            base.setColorAt(0.0, QColor(255, 255, 255, 156))
            base.setColorAt(0.42, QColor(255, 226, 205, 132))
            base.setColorAt(1.0, QColor(236, 171, 126, 104))
        painter.fillPath(path, base)

        shine = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.44)
        shine.setColorAt(0.0,  QColor(255, 255, 255, 116 if enabled else 28))
        shine.setColorAt(0.18, QColor(255, 255, 255,  38 if enabled else 10))
        shine.setColorAt(1.0,  QColor(255, 255, 255,   0))
        painter.fillPath(path, shine)

        bot_r = QLinearGradient(0, rect.bottom() - rect.height() * 0.32, 0, rect.bottom())
        bot_r.setColorAt(0.0, QColor(0, 0, 0,  0))
        bot_r.setColorAt(1.0, QColor(0, 0, 0, 26 if theme_manager.is_dark else 18))
        painter.fillPath(path, bot_r)

        if self._hover > 0.01:
            sa = int(52 * self._hover) if enabled else 12
            spec = QRadialGradient(
                rect.left() + rect.width() * self._pointer_x,
                rect.top() + rect.height() * self._pointer_y * 0.82,
                rect.width() * 0.52,
            )
            spec.setColorAt(0.0, QColor(255, 255, 255, sa))
            spec.setColorAt(0.3, QColor(255, 246, 240, sa // 4))
            spec.setColorAt(1.0, QColor(255, 255, 255,  0))
            painter.fillPath(path, spec)

        if not theme_manager.is_dark:
            unify = QLinearGradient(0, rect.top(), 0, rect.bottom())
            unify.setColorAt(0.0,  QColor(180, 200, 255, 70))
            unify.setColorAt(0.48, QColor(140, 170, 255, 50))
            unify.setColorAt(1.0,  QColor(100, 140, 240, 32))
            painter.fillPath(path, unify)

    # ── accent_soft fill ───────────────────────────────────────────────
    def _paint_accent_soft_fill(self, painter: QPainter, path: QPainterPath, rect: QRectF, lc: dict) -> None:
        enabled = self.isEnabled()
        ft, fm, fb = lc["fill_top"], lc["fill_mid"], lc["fill_bottom"]
        bm, bb = lc["body_mid"], lc["body_bottom"]
        base = QLinearGradient(0, rect.top(), 0, rect.bottom())
        base_alpha = (16 if theme_manager.is_dark else 46) + int(8 * self._hover)
        if theme_manager.is_dark:
            base.setColorAt(0.0,  QColor(255, 255, 255, base_alpha + 3))
            base.setColorAt(0.38, QColor(238, 244, 252, base_alpha))
            base.setColorAt(1.0,  QColor(214, 224, 240, max(0, base_alpha - 4)))
        else:
            base.setColorAt(0.0,  QColor(ft.red(), ft.green(), ft.blue(), ft.alpha()))
            base.setColorAt(0.38, QColor(fm.red(), fm.green(), fm.blue(), fm.alpha()))
            base.setColorAt(1.0,  QColor(fb.red(), fb.green(), fb.blue(), fb.alpha()))
        painter.fillPath(path, base)

        body = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if theme_manager.is_dark:
            body.setColorAt(0.0,  QColor(255, 255, 255,  1))
            body.setColorAt(0.46, QColor(154, 174, 204,  4 if enabled else 2))
            body.setColorAt(1.0,  QColor( 14,  20,  36,  6 if enabled else 3))
        else:
            body.setColorAt(0.0,  QColor(255, 255, 255,  8))
            body.setColorAt(0.46, QColor(bm.red(), bm.green(), bm.blue(), 12 if enabled else 5))
            body.setColorAt(1.0,  QColor(bb.red(), bb.green(), bb.blue(), 14 if enabled else 6))
        painter.fillPath(path, body)

        fresnel = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.15)
        fresnel.setColorAt(0.0,  QColor(255, 255, 255, 24 if enabled else 10))
        fresnel.setColorAt(0.26, QColor(255, 255, 255,  6 if enabled else  2))
        fresnel.setColorAt(1.0,  QColor(255, 255, 255,  0))
        painter.fillPath(path, fresnel)

        bot_r = QLinearGradient(0, rect.bottom() - rect.height() * 0.30, 0, rect.bottom())
        bot_r.setColorAt(0.0, QColor(0, 0, 0,  0))
        bot_r.setColorAt(1.0, QColor(0, 0, 0,  8 if theme_manager.is_dark else 10))
        painter.fillPath(path, bot_r)

        if self._hover > 0.01 and enabled:
            sa = int(10 * self._hover)
            spec = QRadialGradient(
                rect.left() + rect.width() * self._pointer_x,
                rect.top() + rect.height() * self._pointer_y * 0.82,
                rect.width() * 0.76,
            )
            spec.setColorAt(0.0,  QColor(255, 255, 255, sa))
            spec.setColorAt(0.28, QColor(255, 255, 255, max(0, sa // 8)))
            spec.setColorAt(1.0,  QColor(255, 255, 255,  0))
            painter.fillPath(path, spec)

    # ── standard fill (mode / mode_active / accent / primary) ─────────
    def _paint_standard_fill(self, painter: QPainter, path: QPainterPath, rect: QRectF, top: QColor, bottom: QColor) -> None:
        role = self._role
        is_mode = role in {"mode", "mode_active"}
        enabled = self.isEnabled()
        fill = QLinearGradient(0, 0, 0, self.height())
        if role == "mode":
            fill.setColorAt(0.0, top)
            fill.setColorAt(1.0, bottom)
        else:
            lift = 108 if role == "mode_active" else 106 if role == "primary" else 101
            fill.setColorAt(0.0, top.lighter(lift + int(self._hover * 5)))
            fill.setColorAt(1.0, bottom)
        painter.fillPath(path, fill)

        if not theme_manager.is_dark and role in {"mode", "mode_active", "accent", "primary"}:
            cool = QLinearGradient(0, rect.top(), 0, rect.bottom())
            cool.setColorAt(0.0,  QColor(226, 238, 255, 84))
            cool.setColorAt(0.46, QColor(200, 222, 252, 64))
            cool.setColorAt(1.0,  QColor(166, 196, 244, 40))
            painter.fillPath(path, cool)

        base_haze = 26 if role == "mode_active" else 22 if role == "primary" else 16 if not is_mode else 12
        haze = QRadialGradient(
            rect.left() + rect.width() * 0.50,
            rect.top() - rect.height() * 0.06,
            rect.width() * 0.76,
        )
        haze.setColorAt(0.0,  QColor(255, 255, 255, base_haze if enabled else 10))
        haze.setColorAt(0.35, QColor(255, 255, 255, 10 if role in {"primary", "mode_active"} and enabled else 6 if enabled else 3))
        haze.setColorAt(1.0,  QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), haze)

        shine_alpha = 82 if role == "mode_active" else 80 if role == "primary" else 64 if not is_mode else 44
        shine = QLinearGradient(0, 0, 0, self.height() * 0.52)
        shine.setColorAt(0.0, QColor(255, 255, 255, shine_alpha if enabled else 26))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

    # ── border ─────────────────────────────────────────────────────────
    def _paint_border(self, painter: QPainter, rect: QRectF, radius: float, lc: dict) -> None:
        role = self._role
        enabled = self.isEnabled()
        bt, bb = lc["border_top"], lc["border_bot"]

        if role == "primary_warm":
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                g.setColorAt(0.0,  QColor(255, 255, 255, 170 if enabled else 66))
                g.setColorAt(0.42, QColor(255, 255, 255,  54 if enabled else 22))
                g.setColorAt(1.0,  QColor(208, 186, 180,  82 if enabled else 34))
            else:
                g.setColorAt(0.0,  QColor(255, 255, 255, 144 if enabled else 52))
                g.setColorAt(0.42, QColor(255, 226, 205,  92 if enabled else 30))
                g.setColorAt(1.0,  QColor(232, 150,  96,  64 if enabled else 22))
            painter.setPen(QPen(g, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
            inner = rect.adjusted(0.8, 0.8, -0.8, -0.8)
            inner_path = QPainterPath()
            inner_path.addRoundedRect(inner, radius - 0.8, radius - 0.8)
            painter.setPen(QPen(QColor(255, 255, 255, 62 if enabled else 20), 0.7))
            painter.setClipRect(QRectF(inner.left(), inner.top(), inner.width(), inner.height() * 0.44))
            painter.drawPath(inner_path)
            painter.setClipping(False)
        elif role == "mode":
            c = QColor(255, 255, 255, 36) if theme_manager.is_dark else QColor(bb.red(), bb.green(), bb.blue(), bb.alpha())
            painter.setPen(QPen(c, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif role == "mode_active":
            c = QColor(255, 205, 170, 132) if theme_manager.is_dark else QColor(bb.red(), bb.green(), bb.blue(), bb.alpha())
            painter.setPen(QPen(c, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif role == "accent_soft":
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                g.setColorAt(0.0, QColor(255, 255, 255, 46 if enabled else 20))
                g.setColorAt(1.0, QColor(214, 222, 236, 20 if enabled else  8))
            else:
                g.setColorAt(0.0, QColor(bt.red(), bt.green(), bt.blue(), bt.alpha()))
                g.setColorAt(1.0, QColor(bb.red(), bb.green(), bb.blue(), bb.alpha()))
            painter.setPen(QPen(g, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif role == "accent":
            c = QColor(255, 255, 255, 54 if theme_manager.is_dark else bt.alpha())
            painter.setPen(QPen(c, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        else:
            a = 70 if role == "primary" and theme_manager.is_dark else 46 if theme_manager.is_dark else bt.alpha()
            painter.setPen(QPen(QColor(255, 255, 255, a), 1.0))
            painter.drawRoundedRect(rect, radius, radius)

    # ── label / text ───────────────────────────────────────────────────
    def _paint_label(self, painter: QPainter, rect: QRectF, lc: dict) -> None:
        role = self._role
        enabled = self.isEnabled()
        if role == "mode" and not theme_manager.is_dark:
            text_color = QColor(lc["text"])
        elif role in {"mode", "mode_active"} and theme_manager.is_dark:
            text_color = QColor("#fff8f4") if role == "mode_active" else QColor("#ecf1ff")
        else:
            text_color = QColor("#ffffff") if theme_manager.is_dark else QColor(lc["text"])
        if not enabled:
            text_color.setAlpha(132 if not theme_manager.is_dark else 110)
        font = self.font()
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        if role == "primary_warm" and enabled:
            painter.setPen(QColor(0, 0, 0, 52 if theme_manager.is_dark else 18))
            painter.drawText(rect.adjusted(0.0, 1.0, 0.0, 1.0), Qt.AlignCenter, self.text())
        painter.setPen(text_color)
        self._draw_content(painter, rect, text_color)

    def _draw_content(self, painter: QPainter, rect: QRectF, text_color: QColor) -> None:
        text = self.text()
        if self._icon_renderer is None or not self._icon_renderer.isValid():
            painter.drawText(rect, Qt.AlignCenter, text)
            return

        metrics = painter.fontMetrics()
        requested_icon_size = self.iconSize()
        icon_size = float(requested_icon_size.width() or 0)
        if icon_size <= 0:
            icon_size = min(17.0, max(14.0, rect.height() * 0.43))
        if not text:
            icon_rect = QRectF(rect.center().x() - icon_size / 2.0, rect.center().y() - icon_size / 2.0, icon_size, icon_size)
            self._draw_svg_icon(painter, icon_rect, text_color)
            return

        gap = 7.0
        text_width = metrics.horizontalAdvance(text)
        total_width = icon_size + gap + text_width
        start_x = rect.center().x() - total_width / 2.0
        icon_rect = QRectF(start_x, rect.center().y() - icon_size / 2.0, icon_size, icon_size)
        text_rect = QRectF(icon_rect.right() + gap, rect.top(), text_width + 2.0, rect.height())

        self._draw_svg_icon(painter, icon_rect, text_color)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)

    def _draw_svg_icon(self, target_painter: QPainter, rect: QRectF, color: QColor) -> None:
        if self._icon_renderer is None or not self._icon_renderer.isValid():
            return
        image = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        self._icon_renderer.render(painter, rect)
        painter.end()

        tint = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
        tint.fill(Qt.transparent)
        painter = QPainter(tint)
        icon_color = QColor(color)
        icon_color.setAlpha(230 if self.isEnabled() else 120)
        painter.fillRect(tint.rect(), icon_color)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, image)
        painter.end()

        target_painter.drawImage(0, 0, tint)
