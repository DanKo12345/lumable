from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QSizePolicy

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import (
    ButtonAnimationMixin,
    make_property_animation,
    play_or_complete,
    restart_animation,
)

LUCIDE_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons" / "lucide"


class LiquidButton(ButtonAnimationMixin, QPushButton):
    def __init__(self, text: str = "", role: str = "ghost", parent=None):
        super().__init__(text, parent)
        self._role = role
        self._hover = 0.0
        self._scale = 1.0
        self._ripple = 0.0
        self._ripple_opacity = 0.0
        self._impact = 0.0
        self._ripple_x = 0.0
        self._ripple_y = 0.0
        self._pointer_x = 0.5
        self._pointer_y = 0.5
        self._icon_kind = ""
        self._icon_renderer: QSvgRenderer | None = None
        self._icon_pixmap_cache: dict[tuple, QPixmap] = {}
        self._embedded_action_text = ""
        self._embedded_action_callback = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setMinimumHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = make_property_animation(self, b"hoverValue", 180, QEasingCurve.OutCubic)
        self._init_button_motion()
        self._impact_anim = make_property_animation(self, b"impactValue", 260, QEasingCurve.OutCubic)

        # Smoothly eased fill colour for the "led" role (the power button) so it
        # glides to the new strip colour instead of snapping.
        self._led_color: QColor | None = None
        self._led_anim = QVariantAnimation(self)
        self._led_anim.setDuration(260)
        self._led_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._led_anim.valueChanged.connect(self._on_led_value)

    def set_led_color(self, color: QColor) -> None:
        target = QColor(color)
        start = QColor(self._led_color) if self._led_color is not None else target
        self._led_anim.stop()
        self._led_anim.setStartValue(start)
        self._led_anim.setEndValue(target)
        play_or_complete(self._led_anim)  # button colour snaps; the strip is untouched

    def _on_led_value(self, value) -> None:
        self._led_color = QColor(value)
        self.update()

    def _led_paint_color(self) -> QColor:
        if self._led_color is not None:
            return QColor(self._led_color)
        glow = getattr(theme_manager, "led_glow", None)
        return QColor(glow) if glow is not None else QColor(120, 150, 255)

    def set_icon_kind(self, kind: str) -> None:
        self._icon_kind = kind
        self._icon_renderer = QSvgRenderer(str(LUCIDE_ICON_DIR / f"{kind}.svg"), self) if kind else None
        self._icon_pixmap_cache.clear()
        self.update()

    def set_embedded_action(self, text: str = "", callback=None) -> None:
        self._embedded_action_text = text
        self._embedded_action_callback = callback
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

    def get_impact(self):
        return self._impact

    def set_impact(self, value):
        self._impact = float(value)
        self.update()

    impactValue = Property(float, get_impact, set_impact)

    def mousePressEvent(self, event):
        pos = event.position()
        restart_animation(self._impact_anim, 1.0, 0.0)
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
        if self._embedded_action_text and self._embedded_action_rect().contains(event.position()):
            if callable(self._embedded_action_callback):
                self._embedded_action_callback()
            event.accept()
            self._handle_button_release()
            return
        self._handle_button_release()
        super().mouseReleaseEvent(event)

    # ── shared light-mode palette ──────────────────────────────────────
    @staticmethod
    def _light_palette() -> dict:
        return {
            "fill_top": QColor(255, 255, 255, 220),
            "fill_mid": QColor(248, 249, 251, 196),
            "fill_bottom": QColor(228, 231, 236, 184),
            "body_mid": QColor(42, 47, 56, 8),
            "body_bottom": QColor(42, 47, 56, 12),
            "border_top": QColor(72, 79, 91, 92),
            "border_bot": QColor(72, 79, 91, 112),
            "text": QColor("#202329"),
        }

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        grow = max(0.0, self._scale - 1.0)
        inset = max(0.8, 4.0 - grow * 75.0)
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

        if self._role in ("nav", "nav_active"):
            self._paint_nav(painter, rect)
            return

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

        self._paint_impact(painter, rect)

        painter.setClipping(False)
        self._paint_border(painter, rect, radius, lc)
        self._paint_label(painter, rect, lc)

    # ── flat navigation item (sidebar) ─────────────────────────────────
    def _paint_nav(self, painter: QPainter, rect: QRectF) -> None:
        active = self._role == "nav_active"
        dark = theme_manager.is_dark
        radius = 10.0

        if active:
            bg_alpha = 18 if dark else 30
        elif self._hover > 0.01:
            bg_alpha = int((11 if dark else 20) * self._hover)
        else:
            bg_alpha = 0
        if bg_alpha > 0:
            bg_path = QPainterPath()
            bg_path.addRoundedRect(rect, radius, radius)
            fill = QColor(255, 255, 255, bg_alpha) if dark else QColor(40, 55, 95, bg_alpha)
            painter.fillPath(bg_path, fill)

        if active:
            accent = qcolor_from_token(theme_manager.palette["accent_start"])
            bar_height = rect.height() * 0.5
            bar = QRectF(rect.left() + 2.0, rect.center().y() - bar_height / 2.0, 3.0, bar_height)
            bar_path = QPainterPath()
            bar_path.addRoundedRect(bar, 1.5, 1.5)
            painter.fillPath(bar_path, accent)

        if active:
            text_color = QColor("#ffffff") if dark else QColor("#18243d")
        else:
            text_color = QColor(255, 255, 255, 150) if dark else QColor(24, 36, 61, 150)
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold if active else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(text_color)
        content = rect.adjusted(16.0, 0.0, -8.0, 0.0)
        if self._icon_renderer is not None and self._icon_renderer.isValid():
            requested = self.iconSize()
            icon_size = float(requested.width() or 18)
            icon_rect = QRectF(
                content.left(),
                content.center().y() - icon_size / 2.0,
                icon_size,
                icon_size,
            )
            self._draw_svg_icon(painter, icon_rect, text_color)
            content.setLeft(icon_rect.right() + 10.0)
        painter.drawText(content, Qt.AlignLeft | Qt.AlignVCenter, self.text())

    # ── ghost (Liquid Glass) ───────────────────────────────────────────
    def _paint_ghost(self, painter: QPainter, path: QPainterPath, rect: QRectF, radius: float, lc: dict) -> None:
        painter.setClipPath(path)
        enabled = self.isEnabled()

        # 1. quiet neutral material
        base_a = 5 + int(3 * self._hover)
        base = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if theme_manager.is_dark:
            base.setColorAt(0.0, QColor(255, 255, 255, base_a + 1))
            base.setColorAt(0.34, QColor(240, 246, 255, base_a))
            base.setColorAt(0.68, QColor(226, 236, 248, max(0, base_a - 1)))
            base.setColorAt(1.0, QColor(214, 226, 242, max(0, base_a - 2)))
        else:
            ft, fm, fb = lc["fill_top"], lc["fill_mid"], lc["fill_bottom"]
            base.setColorAt(0.0, QColor(ft.red(), ft.green(), ft.blue(), ft.alpha()))
            base.setColorAt(0.34, QColor(fm.red(), fm.green(), fm.blue(), fm.alpha()))
            base.setColorAt(0.68, QColor(fm.red(), fm.green(), fm.blue(), 154))
            base.setColorAt(1.0, QColor(fb.red(), fb.green(), fb.blue(), 126))
        painter.fillPath(path, base)

        body = QLinearGradient(0, rect.top(), 0, rect.bottom())
        bm, bb = lc["body_mid"], lc["body_bottom"]
        if theme_manager.is_dark:
            body.setColorAt(0.0, QColor(255, 255, 255, 2))
            body.setColorAt(0.42, QColor(160, 160, 166, 4 if enabled else 2))
            body.setColorAt(1.0, QColor(12, 13, 16, 6 if enabled else 3))
        else:
            body.setColorAt(0.0, QColor(255, 255, 255, 8 if enabled else 4))
            body.setColorAt(0.42, QColor(bm.red(), bm.green(), bm.blue(), 12 if enabled else 5))
            body.setColorAt(1.0, QColor(bb.red(), bb.green(), bb.blue(), 12 if enabled else 5))
        painter.fillPath(path, body)

        # 2. soft top fresnel
        fresnel = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.14)
        fresnel.setColorAt(0.0, QColor(255, 255, 255, 26 if enabled else 10))
        fresnel.setColorAt(0.22, QColor(255, 255, 255, 6 if enabled else 2))
        fresnel.setColorAt(1.0, QColor(255, 255, 255, 0))
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
            spec.setColorAt(0.0, QColor(255, 255, 255, sa))
            spec.setColorAt(0.22, QColor(255, 255, 255, max(0, sa // 8)))
            spec.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, spec)

        # 5. ripple
        if self._ripple_opacity > 0.01:
            rr = 8 + self._ripple * max(rect.width(), rect.height()) * 0.9
            ripple = QRadialGradient(self._ripple_x, self._ripple_y, rr)
            ripple.setColorAt(0.0, QColor(255, 255, 255, int(24 * self._ripple_opacity)))
            ripple.setColorAt(0.45, QColor(255, 255, 255, int(6 * self._ripple_opacity)))
            ripple.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), ripple)

        self._paint_impact(painter, rect)

        painter.setClipping(False)

        # 6. glass border
        bt, bb2 = lc["border_top"], lc["border_bot"]
        border_g = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if theme_manager.is_dark:
            border_g.setColorAt(0.0, QColor(255, 255, 255, 36 if enabled else 18))
            border_g.setColorAt(1.0, QColor(218, 224, 236, 20 if enabled else 9))
        else:
            border_g.setColorAt(0.0, QColor(bt.red(), bt.green(), bt.blue(), 168 if enabled else 60))
            border_g.setColorAt(1.0, QColor(bb2.red(), bb2.green(), bb2.blue(), 140 if enabled else 52))
        painter.setPen(QPen(QBrush(border_g), 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        # 7. text
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        text_color = QColor("#ffffff") if theme_manager.is_dark else QColor(lc["text"])
        if not enabled:
            text_color.setAlpha(110)
        elif not theme_manager.is_dark:
            text_color.setAlpha(232)
        painter.setPen(text_color)
        self._draw_content(painter, rect, text_color)

    def _paint_impact(self, painter: QPainter, rect: QRectF) -> None:
        if self._impact <= 0.01 or not self.isEnabled():
            return
        radius = max(rect.width(), rect.height()) * (0.34 + (1.0 - self._impact) * 0.42)
        alpha = int((42 if theme_manager.is_dark else 34) * self._impact)
        glow = QRadialGradient(self._ripple_x, self._ripple_y, radius)
        glow.setColorAt(0.0, QColor(255, 255, 255, alpha))
        glow.setColorAt(0.35, QColor(230, 230, 235, max(0, alpha // 3)))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), glow)

    # ── base fill colours per role ────────────────────────────────────
    def _role_base_colors(self, lc: dict) -> tuple[QColor, QColor]:
        palette = theme_manager.palette
        ft, fb = lc["fill_top"], lc["fill_bottom"]
        role = self._role
        if role == "led":
            glow = self._led_paint_color()
            top = QColor(glow.red(), glow.green(), glow.blue())
            bot = QColor(glow.red(), glow.green(), glow.blue())
            if theme_manager.is_dark:
                top.setAlpha(150)
                bot.setAlpha(104)
            else:
                top.setAlpha(220)
                bot.setAlpha(180)
            return top, bot
        if role == "mode":
            return (
                (QColor(255, 255, 255, 17), QColor(78, 79, 84, 10))
                if theme_manager.is_dark
                else (QColor(ft), QColor(fb))
            )
        if role == "mode_active":
            return (
                (QColor(251, 191, 146, 138), QColor(114, 73, 54, 94))
                if theme_manager.is_dark
                else (QColor(ft), QColor(fb))
            )
        if role == "primary_warm":
            return (
                (QColor(255, 218, 198, 58), QColor(118, 72, 66, 44))
                if theme_manager.is_dark
                else (QColor(ft), QColor(fb))
            )
        if role == "accent_soft":
            return (
                (QColor(255, 255, 255, 18), QColor(222, 222, 228, 10))
                if theme_manager.is_dark
                else (QColor(ft), QColor(fb))
            )
        if role == "accent":
            top = qcolor_from_token(palette["accent_start"])
            bot = qcolor_from_token(palette["accent_end"])
            if theme_manager.is_dark:
                top.setAlpha(118)
                bot.setAlpha(78)
            else:
                # Near-opaque, deepened fill: dark enough that the white label
                # clears 4.5:1 after compositing (the raw accent_start alone
                # only reaches ~3.2:1).
                top = QColor(
                    round(top.red() * 0.4 + bot.red() * 0.6),
                    round(top.green() * 0.4 + bot.green() * 0.6),
                    round(top.blue() * 0.4 + bot.blue() * 0.6),
                ).darker(106)
                bot = bot.darker(120)
                top.setAlpha(252)
                bot.setAlpha(244)
                top, bot = self._ensure_label_contrast(top, bot)
            return top, bot
        if role == "premium":
            start = qcolor_from_token(palette["accent_start"])
            end = qcolor_from_token(palette["accent_end"])
            fill = QColor(
                round(start.red() * 0.58 + end.red() * 0.42),
                round(start.green() * 0.58 + end.green() * 0.42),
                round(start.blue() * 0.58 + end.blue() * 0.42),
            )
            fill.setAlpha(248 if theme_manager.is_dark else 252)
            return self._ensure_label_contrast(fill, QColor(fill))
        if role == "danger":
            top = qcolor_from_token(palette["danger_start"])
            bot = qcolor_from_token(palette["danger_end"])
            if theme_manager.is_dark:
                top.setAlpha(132)
                bot.setAlpha(96)
            else:
                top = QColor(
                    round(top.red() * 0.35 + bot.red() * 0.65),
                    round(top.green() * 0.35 + bot.green() * 0.65),
                    round(top.blue() * 0.35 + bot.blue() * 0.65),
                ).darker(108)
                bot = bot.darker(118)
                top.setAlpha(252)
                bot.setAlpha(244)
                top, bot = self._ensure_label_contrast(top, bot)
            return top, bot
        # primary / fallback
        top = qcolor_from_token(palette["accent_start"])
        top.setAlpha(
            126 if role == "primary" and theme_manager.is_dark else 108 if theme_manager.is_dark else ft.alpha()
        )
        bot = qcolor_from_token(palette["accent_end"])
        bot.setAlpha(88 if role == "primary" and theme_manager.is_dark else 72 if theme_manager.is_dark else fb.alpha())
        return top, bot

    # ── outer glow (non-ghost roles that need it) ──────────────────────
    def _paint_glow(self, painter: QPainter, path: QPainterPath, rect: QRectF, radius: float, top: QColor) -> None:
        role = self._role
        is_mode = role in {"mode", "mode_active"}
        is_warm = role == "primary_warm"
        is_soft = role == "accent_soft"
        is_led = role == "led"
        is_danger = role == "danger"
        if role not in {"accent", "primary"} and not is_mode and not is_warm and not is_soft and not is_led and not is_danger:
            return
        palette = theme_manager.palette
        glow_rect = rect.adjusted(-1.0, -1.0, 1.0, 1.0)
        glow_path = QPainterPath()
        glow_path.addRoundedRect(glow_rect, radius + 1.0, radius + 1.0)
        if is_led:
            led = self._led_paint_color()
            glow_color = QColor(led.red(), led.green(), led.blue())
        elif is_danger:
            glow_color = qcolor_from_token(palette["danger_start"])
        elif is_warm or role == "mode_active":
            glow_color = QColor(255, 187, 140)
        elif is_soft:
            glow_color = QColor(150, 188, 255) if not theme_manager.is_dark else QColor(255, 255, 255)
        else:
            glow_color = qcolor_from_token(palette["accent_start"])
        if not theme_manager.is_dark and not is_led and not is_danger:
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
        shine.setColorAt(0.0, QColor(255, 255, 255, 116 if enabled else 28))
        shine.setColorAt(0.18, QColor(255, 255, 255, 38 if enabled else 10))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, shine)

        bot_r = QLinearGradient(0, rect.bottom() - rect.height() * 0.32, 0, rect.bottom())
        bot_r.setColorAt(0.0, QColor(0, 0, 0, 0))
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
            spec.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, spec)

        if not theme_manager.is_dark:
            unify = QLinearGradient(0, rect.top(), 0, rect.bottom())
            unify.setColorAt(0.0, QColor(180, 200, 255, 70))
            unify.setColorAt(0.48, QColor(140, 170, 255, 50))
            unify.setColorAt(1.0, QColor(100, 140, 240, 32))
            painter.fillPath(path, unify)

    # ── accent_soft fill ───────────────────────────────────────────────
    def _paint_accent_soft_fill(self, painter: QPainter, path: QPainterPath, rect: QRectF, lc: dict) -> None:
        enabled = self.isEnabled()
        ft, fm, fb = lc["fill_top"], lc["fill_mid"], lc["fill_bottom"]
        bm, bb = lc["body_mid"], lc["body_bottom"]
        base = QLinearGradient(0, rect.top(), 0, rect.bottom())
        base_alpha = (16 if theme_manager.is_dark else 46) + int(8 * self._hover)
        if theme_manager.is_dark:
            base.setColorAt(0.0, QColor(255, 255, 255, base_alpha + 3))
            base.setColorAt(0.38, QColor(238, 244, 252, base_alpha))
            base.setColorAt(1.0, QColor(214, 224, 240, max(0, base_alpha - 4)))
        else:
            base.setColorAt(0.0, QColor(ft.red(), ft.green(), ft.blue(), ft.alpha()))
            base.setColorAt(0.38, QColor(fm.red(), fm.green(), fm.blue(), fm.alpha()))
            base.setColorAt(1.0, QColor(fb.red(), fb.green(), fb.blue(), fb.alpha()))
        painter.fillPath(path, base)

        body = QLinearGradient(0, rect.top(), 0, rect.bottom())
        if theme_manager.is_dark:
            body.setColorAt(0.0, QColor(255, 255, 255, 1))
            body.setColorAt(0.46, QColor(160, 160, 166, 4 if enabled else 2))
            body.setColorAt(1.0, QColor(12, 13, 16, 6 if enabled else 3))
        else:
            body.setColorAt(0.0, QColor(255, 255, 255, 8))
            body.setColorAt(0.46, QColor(bm.red(), bm.green(), bm.blue(), 12 if enabled else 5))
            body.setColorAt(1.0, QColor(bb.red(), bb.green(), bb.blue(), 14 if enabled else 6))
        painter.fillPath(path, body)

        fresnel = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.15)
        fresnel.setColorAt(0.0, QColor(255, 255, 255, 24 if enabled else 10))
        fresnel.setColorAt(0.26, QColor(255, 255, 255, 6 if enabled else 2))
        fresnel.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, fresnel)

        bot_r = QLinearGradient(0, rect.bottom() - rect.height() * 0.30, 0, rect.bottom())
        bot_r.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot_r.setColorAt(1.0, QColor(0, 0, 0, 8 if theme_manager.is_dark else 10))
        painter.fillPath(path, bot_r)

        if self._hover > 0.01 and enabled:
            sa = int(10 * self._hover)
            spec = QRadialGradient(
                rect.left() + rect.width() * self._pointer_x,
                rect.top() + rect.height() * self._pointer_y * 0.82,
                rect.width() * 0.76,
            )
            spec.setColorAt(0.0, QColor(255, 255, 255, sa))
            spec.setColorAt(0.28, QColor(255, 255, 255, max(0, sa // 8)))
            spec.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, spec)

    # ── standard fill (mode / mode_active / accent / primary) ─────────
    def _paint_standard_fill(
        self, painter: QPainter, path: QPainterPath, rect: QRectF, top: QColor, bottom: QColor
    ) -> None:
        role = self._role
        is_mode = role in {"mode", "mode_active"}
        enabled = self.isEnabled()
        if not enabled:
            top = QColor(top)
            top.setAlpha(round(top.alpha() * 0.45))
            bottom = QColor(bottom)
            bottom.setAlpha(round(bottom.alpha() * 0.45))
        if role == "premium":
            fill = QColor(top)
            if enabled and self._hover > 0.01:
                fill = fill.lighter(round(100 + self._hover * 5))
            painter.fillPath(path, fill)
            return
        fill = QLinearGradient(0, 0, 0, self.height())
        if role == "mode":
            fill.setColorAt(0.0, top)
            fill.setColorAt(1.0, bottom)
        else:
            lift = 108 if role == "mode_active" else 106 if role == "primary" else 101
            fill.setColorAt(0.0, top.lighter(lift + int(self._hover * 5)))
            fill.setColorAt(1.0, bottom)
        painter.fillPath(path, fill)

        # Only the neutral mode chips get the cool white-blue veil. A filled
        # accent/primary button must keep its saturation, otherwise the "main
        # action" washes out to the same weight as every other button.
        if not theme_manager.is_dark and role in {"mode", "mode_active"}:
            cool = QLinearGradient(0, rect.top(), 0, rect.bottom())
            cool.setColorAt(0.0, QColor(226, 238, 255, 84))
            cool.setColorAt(0.46, QColor(200, 222, 252, 64))
            cool.setColorAt(1.0, QColor(166, 196, 244, 40))
            painter.fillPath(path, cool)

        base_haze = 26 if role == "mode_active" else 22 if role == "primary" else 16 if not is_mode else 12
        haze = QRadialGradient(
            rect.left() + rect.width() * 0.50,
            rect.top() - rect.height() * 0.06,
            rect.width() * 0.76,
        )
        haze.setColorAt(0.0, QColor(255, 255, 255, base_haze if enabled else 10))
        haze.setColorAt(
            0.35, QColor(255, 255, 255, 10 if role in {"primary", "mode_active"} and enabled else 6 if enabled else 3)
        )
        haze.setColorAt(1.0, QColor(255, 255, 255, 0))
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
                g.setColorAt(0.0, QColor(255, 255, 255, 170 if enabled else 66))
                g.setColorAt(0.42, QColor(255, 255, 255, 54 if enabled else 22))
                g.setColorAt(1.0, QColor(208, 186, 180, 82 if enabled else 34))
            else:
                g.setColorAt(0.0, QColor(255, 255, 255, 144 if enabled else 52))
                g.setColorAt(0.42, QColor(255, 226, 205, 92 if enabled else 30))
                g.setColorAt(1.0, QColor(232, 150, 96, 64 if enabled else 22))
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
            c = (
                QColor(255, 255, 255, 36)
                if theme_manager.is_dark
                else QColor(bb.red(), bb.green(), bb.blue(), bb.alpha())
            )
            painter.setPen(QPen(c, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif role == "mode_active":
            c = (
                QColor(255, 205, 170, 132)
                if theme_manager.is_dark
                else QColor(bb.red(), bb.green(), bb.blue(), bb.alpha())
            )
            painter.setPen(QPen(c, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif role == "accent_soft":
            g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                g.setColorAt(0.0, QColor(255, 255, 255, 46 if enabled else 20))
                g.setColorAt(1.0, QColor(214, 222, 236, 20 if enabled else 8))
            else:
                g.setColorAt(0.0, QColor(bt.red(), bt.green(), bt.blue(), bt.alpha()))
                g.setColorAt(1.0, QColor(bb.red(), bb.green(), bb.blue(), bb.alpha()))
            painter.setPen(QPen(g, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif role in {"accent", "premium"}:
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
        if role in {"accent", "primary", "premium", "danger"}:
            # Filled action button: white label like macOS/iOS by default, but a
            # quick-mode accent override can dye the fill with a light pastel —
            # then a white label drops below ~3:1 and must flip to dark.
            text_color = self._fill_label_color(lc)
        elif role == "mode" and not theme_manager.is_dark:
            text_color = QColor(lc["text"])
        elif role in {"mode", "mode_active"} and theme_manager.is_dark:
            text_color = QColor("#fff8f4") if role == "mode_active" else QColor("#ecf1ff")
        else:
            text_color = QColor("#ffffff") if theme_manager.is_dark else QColor(lc["text"])
        if not enabled:
            text_color.setAlpha(132 if not theme_manager.is_dark else 110)
        font = self.font()
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        if role == "primary_warm" and enabled:
            painter.setPen(QColor(0, 0, 0, 52 if theme_manager.is_dark else 18))
            painter.drawText(rect.adjusted(0.0, 1.0, 0.0, 1.0), Qt.AlignCenter, self.text())
        painter.setPen(text_color)
        self._draw_content(painter, rect, text_color)

    @staticmethod
    def _relative_luminance(color: QColor) -> float:
        def linear(value: int) -> float:
            c = value / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * linear(color.red()) + 0.7152 * linear(color.green()) + 0.0722 * linear(color.blue())

    @classmethod
    def _composite_fill_luminance(cls, top: QColor, bottom: QColor) -> float:
        """Luminance of the fill as it actually reaches the eye: the gradient
        midpoint composited over the card behind the button."""
        mid = QColor(
            round((top.red() + bottom.red()) / 2),
            round((top.green() + bottom.green()) / 2),
            round((top.blue() + bottom.blue()) / 2),
        )
        backdrop = QColor(26, 27, 30) if theme_manager.is_dark else QColor(248, 249, 251)
        alpha = ((top.alpha() + bottom.alpha()) / 2.0) / 255.0
        composite = QColor(
            round(mid.red() * alpha + backdrop.red() * (1.0 - alpha)),
            round(mid.green() * alpha + backdrop.green() * (1.0 - alpha)),
            round(mid.blue() * alpha + backdrop.blue() * (1.0 - alpha)),
        )
        return cls._relative_luminance(composite)

    @classmethod
    def _ensure_label_contrast(cls, top: QColor, bottom: QColor) -> tuple[QColor, QColor]:
        """Darken a light-theme fill until the white label clears 4.5:1.

        Quick-mode accents dye the fill with light pastels that land in a dead
        zone where neither white nor dark text reaches 4.5:1 — the fill itself
        has to give way, the text colour alone cannot fix it.
        """
        for _ in range(5):
            lum = cls._composite_fill_luminance(top, bottom)
            if 1.05 / (lum + 0.05) >= 4.5:
                break
            top = top.darker(108)
            bottom = bottom.darker(108)
        return top, bottom

    def _fill_label_color(self, lc: dict) -> QColor:
        """White or dark label — whichever has the higher WCAG contrast ratio
        against the effective (composited) fill."""
        top, bottom = self._role_base_colors(lc)
        fill_lum = self._composite_fill_luminance(top, bottom)
        dark = QColor("#1e2633")
        white_contrast = 1.05 / (fill_lum + 0.05)
        dark_contrast = (fill_lum + 0.05) / (self._relative_luminance(dark) + 0.05)
        return QColor("#ffffff") if white_contrast >= dark_contrast else dark

    def _draw_content(self, painter: QPainter, rect: QRectF, text_color: QColor) -> None:
        text = self.text()
        if self._embedded_action_text:
            content_rect = QRectF(rect).adjusted(0.0, 0.0, -20.0, 0.0)
            self._draw_embedded_action(painter, text_color)
        else:
            content_rect = rect
        if self._icon_renderer is None or not self._icon_renderer.isValid():
            painter.drawText(content_rect, Qt.AlignCenter, text)
            return

        metrics = painter.fontMetrics()
        requested_icon_size = self.iconSize()
        icon_size = float(requested_icon_size.width() or 0)
        if icon_size <= 0:
            icon_size = min(17.0, max(14.0, rect.height() * 0.43))
        if not text:
            icon_rect = QRectF(
                content_rect.center().x() - icon_size / 2.0,
                content_rect.center().y() - icon_size / 2.0,
                icon_size,
                icon_size,
            )
            self._draw_svg_icon(painter, icon_rect, text_color)
            return

        gap = 7.0
        text_width = metrics.horizontalAdvance(text)
        total_width = icon_size + gap + text_width
        start_x = content_rect.center().x() - total_width / 2.0
        icon_rect = QRectF(start_x, content_rect.center().y() - icon_size / 2.0, icon_size, icon_size)
        text_rect = QRectF(icon_rect.right() + gap, content_rect.top(), text_width + 2.0, content_rect.height())

        self._draw_svg_icon(painter, icon_rect, text_color)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)

    def _embedded_action_rect(self) -> QRectF:
        size = min(20.0, max(16.0, self.height() * 0.46))
        return QRectF(self.width() - size - 7.0, (self.height() - size) / 2.0, size, size)

    def _draw_embedded_action(self, painter: QPainter, text_color: QColor) -> None:
        rect = self._embedded_action_rect()
        if rect.width() <= 0:
            return
        is_dark = theme_manager.is_dark
        enabled = self.isEnabled()
        glow = max(0.0, min(1.0, self._hover))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)

        # No enclosing chip: a soft radial glow has no hard edge, so it can never
        # clash with the host button's corner radius. At rest only the cross
        # shows; on hover a gentle red halo appears behind it.
        if glow > 0.02 and enabled:
            center = rect.center()
            outer = rect.width() * 0.95
            halo = QRadialGradient(center, outer)
            halo.setColorAt(0.0, QColor(255, 108, 130, int(150 * glow)))
            halo.setColorAt(0.62, QColor(255, 108, 130, int(58 * glow)))
            halo.setColorAt(1.0, QColor(255, 108, 130, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(halo)
            painter.drawEllipse(center, outer, outer)

        if glow > 0.4:
            cross = QColor(255, 255, 255, 245)
        elif is_dark:
            cross = QColor(255, 255, 255, int(92 + 120 * glow))
        else:
            cross = QColor(46, 60, 92, int(120 + 90 * glow))
        if not enabled:
            cross.setAlpha(80)
        inset = rect.width() * 0.32
        arm = rect.adjusted(inset, inset, -inset, -inset)
        pen = QPen(cross, max(1.4, rect.width() * 0.11))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(arm.topLeft(), arm.bottomRight())
        painter.drawLine(arm.topRight(), arm.bottomLeft())
        painter.restore()

    def _draw_svg_icon(self, target_painter: QPainter, rect: QRectF, color: QColor) -> None:
        if self._icon_renderer is None or not self._icon_renderer.isValid():
            return
        width = max(1, round(rect.width()))
        height = max(1, round(rect.height()))
        icon_color = QColor(color)
        icon_color.setAlpha(230 if self.isEnabled() else 120)

        # The tinted icon only changes with its size and colour, so cache it as a
        # pixmap instead of allocating and compositing two QImages every paint.
        pixel_ratio = self.devicePixelRatioF()
        key = (self._icon_kind, width, height, pixel_ratio, icon_color.rgba())
        pixmap = self._icon_pixmap_cache.get(key)
        if pixmap is None:
            pixmap = self._build_tinted_icon(width, height, pixel_ratio, icon_color)
            self._icon_pixmap_cache[key] = pixmap
        target_painter.drawPixmap(rect.topLeft(), pixmap)

    def _build_tinted_icon(self, width: int, height: int, pixel_ratio: float, icon_color: QColor) -> QPixmap:
        glyph = QImage(
            round(width * pixel_ratio),
            round(height * pixel_ratio),
            QImage.Format_ARGB32_Premultiplied,
        )
        glyph.setDevicePixelRatio(pixel_ratio)
        glyph.fill(Qt.transparent)
        painter = QPainter(glyph)
        painter.setRenderHint(QPainter.Antialiasing)
        self._icon_renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()

        tint = QImage(glyph.size(), QImage.Format_ARGB32_Premultiplied)
        tint.setDevicePixelRatio(pixel_ratio)
        tint.fill(Qt.transparent)
        painter = QPainter(tint)
        painter.fillRect(tint.rect(), icon_color)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, glyph)
        painter.end()
        return QPixmap.fromImage(tint)
