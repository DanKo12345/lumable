from __future__ import annotations

from PySide6.QtCore import QEasingCurve, Property, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QPushButton, QSizePolicy

from app.theme import qcolor_from_token, theme_manager
from app.widgets.animation_helpers import ButtonAnimationMixin, make_property_animation, restart_animation


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
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setMinimumHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = make_property_animation(self, b"hoverValue", 180, QEasingCurve.OutCubic)
        self._init_button_motion()

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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        grow = max(0.0, self._scale - 1.0)
        inset = max(0.8, 4.0 - grow * 75.0)
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)

        # ghost uses pill shape; all other roles keep original radius
        is_ghost = self._role == "ghost"
        radius = rect.height() / 2.0 if is_ghost else 17.0

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        palette = theme_manager.palette
        is_mode = self._role in {"mode", "mode_active"}
        is_warm_primary = self._role == "primary_warm"
        is_soft_accent = self._role == "accent_soft"
        is_light = not theme_manager.is_dark

        light_fill_top = QColor(255, 255, 255, 188)
        light_fill_mid = QColor(236, 244, 255, 154)
        light_fill_bottom = QColor(198, 218, 248, 138)
        light_body_mid = QColor(166, 192, 232, 12)
        light_body_bottom = QColor(92, 120, 168, 14)
        light_border_top = QColor(255, 255, 255, 144)
        light_border_bottom = QColor(164, 192, 236, 64)
        light_text = QColor("#18243d")

        # ── ghost: Liquid Glass path (entirely separate) ─────────────────
        if is_ghost:
            painter.setClipPath(path)

            # 1. quiet neutral material
            base_a = 5 + int(3 * self._hover)
            base = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                base.setColorAt(0.0, QColor(255, 255, 255, base_a + 1))
                base.setColorAt(0.34, QColor(240, 246, 255, base_a))
                base.setColorAt(0.68, QColor(226, 236, 248, max(0, base_a - 1)))
                base.setColorAt(1.0, QColor(214, 226, 242, max(0, base_a - 2)))
            else:
                base.setColorAt(0.0, QColor(light_fill_top.red(), light_fill_top.green(), light_fill_top.blue(), light_fill_top.alpha()))
                base.setColorAt(0.34, QColor(light_fill_mid.red(), light_fill_mid.green(), light_fill_mid.blue(), light_fill_mid.alpha()))
                base.setColorAt(0.68, QColor(220, 232, 248, 146))
                base.setColorAt(1.0, QColor(light_fill_bottom.red(), light_fill_bottom.green(), light_fill_bottom.blue(), 126))
            painter.fillPath(path, base)

            material_body = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                material_body.setColorAt(0.0, QColor(255, 255, 255, 2))
                material_body.setColorAt(0.42, QColor(156, 174, 204, 4 if self.isEnabled() else 2))
                material_body.setColorAt(1.0, QColor(14, 20, 36, 6 if self.isEnabled() else 3))
            else:
                material_body.setColorAt(0.0, QColor(255, 255, 255, 8 if self.isEnabled() else 4))
                material_body.setColorAt(0.42, QColor(light_body_mid.red(), light_body_mid.green(), light_body_mid.blue(), 12 if self.isEnabled() else 5))
                material_body.setColorAt(1.0, QColor(light_body_bottom.red(), light_body_bottom.green(), light_body_bottom.blue(), 12 if self.isEnabled() else 5))
            painter.fillPath(path, material_body)

            # 2. soft top light pass
            fresnel = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.14)
            fresnel.setColorAt(0.0, QColor(255, 255, 255, 26 if self.isEnabled() else 10))
            fresnel.setColorAt(0.22, QColor(255, 255, 255, 6 if self.isEnabled() else 2))
            fresnel.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, fresnel)

            # 3. subtle bottom refraction
            bot = QLinearGradient(0, rect.bottom() - rect.height() * 0.30, 0, rect.bottom())
            bot.setColorAt(0.0, QColor(0, 0, 0, 0))
            bot.setColorAt(1.0, QColor(0, 0, 0, 6 if theme_manager.is_dark else 10))
            painter.fillPath(path, bot)

            # 4. restrained cursor specular
            if self._hover > 0.01 and self.isEnabled():
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

            painter.setClipping(False)

            # 6. quiet glass border
            border_g = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                border_g.setColorAt(0.0, QColor(255, 255, 255, 36 if self.isEnabled() else 18))
                border_g.setColorAt(1.0, QColor(218, 224, 236, 20 if self.isEnabled() else 9))
            else:
                border_g.setColorAt(0.0, QColor(light_border_top.red(), light_border_top.green(), light_border_top.blue(), 132 if self.isEnabled() else 48))
                border_g.setColorAt(1.0, QColor(light_border_bottom.red(), light_border_bottom.green(), light_border_bottom.blue(), 54 if self.isEnabled() else 20))
            painter.setPen(QPen(QBrush(border_g), 1.0))
            painter.drawRoundedRect(rect, radius, radius)

            # 8. text
            font = self.font()
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            text_color = QColor("#ffffff") if theme_manager.is_dark else QColor(light_text)
            if not self.isEnabled():
                text_color.setAlpha(110)
            elif not theme_manager.is_dark:
                text_color.setAlpha(232)
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignCenter, self.text())
            return

        # ── all other roles: original logic untouched ────────────────────
        if self._role == "mode":
            if theme_manager.is_dark:
                top = QColor(255, 255, 255, 17)
                bottom = QColor(95, 110, 160, 10)
            else:
                top = QColor(light_fill_top)
                bottom = QColor(light_fill_bottom)
        elif self._role == "mode_active":
            if theme_manager.is_dark:
                top = QColor(251, 191, 146, 138)
                bottom = QColor(114, 73, 54, 94)
            else:
                top = QColor(light_fill_top)
                bottom = QColor(light_fill_bottom)
        elif is_warm_primary:
            if theme_manager.is_dark:
                top = QColor(255, 218, 198, 58)
                bottom = QColor(118, 72, 66, 44)
            else:
                top = QColor(light_fill_top)
                bottom = QColor(light_fill_bottom)
        elif is_soft_accent:
            if theme_manager.is_dark:
                top = QColor(255, 255, 255, 18)
                bottom = QColor(220, 232, 250, 10)
            else:
                top = QColor(light_fill_top)
                bottom = QColor(light_fill_bottom)
        elif self._role == "accent":
            top = qcolor_from_token(palette["accent_start"])
            top.setAlpha(118 if theme_manager.is_dark else light_fill_top.alpha())
            bottom = qcolor_from_token(palette["accent_end"])
            bottom.setAlpha(78 if theme_manager.is_dark else light_fill_bottom.alpha())
        else:
            top = qcolor_from_token(palette["accent_start"])
            top.setAlpha(126 if self._role == "primary" and theme_manager.is_dark else 108 if theme_manager.is_dark else light_fill_top.alpha())
            bottom = qcolor_from_token(palette["accent_end"])
            bottom.setAlpha(88 if self._role == "primary" and theme_manager.is_dark else 72 if theme_manager.is_dark else light_fill_bottom.alpha())

        if self._role in {"accent", "primary"} or is_mode or is_warm_primary or is_soft_accent:
            glow_rect = rect.adjusted(-1.0, -1.0, 1.0, 1.0)
            glow_path = QPainterPath()
            glow_path.addRoundedRect(glow_rect, radius + 1.0, radius + 1.0)
            if is_warm_primary or self._role == "mode_active":
                glow_color = QColor(255, 187, 140)
            elif is_soft_accent:
                glow_color = QColor(150, 188, 255) if not theme_manager.is_dark else QColor(255, 255, 255)
            else:
                glow_color = qcolor_from_token(palette["accent_start"])
            if not theme_manager.is_dark:
                glow_color = QColor(238, 172, 118) if is_warm_primary else QColor(168, 198, 244)
            if self._role == "mode":
                glow_alpha = 8
            elif self._role == "mode_active":
                glow_alpha = 38
            elif is_soft_accent:
                glow_alpha = 8 if theme_manager.is_dark else 14
            elif self._role == "accent":
                glow_alpha = 18
            else:
                glow_alpha = 36
            if self._hover > 0.0:
                glow_alpha += int(14 * self._hover)
            glow_color.setAlpha(glow_alpha if self.isEnabled() else 10)
            painter.fillPath(glow_path, glow_color)

        painter.setClipPath(path)

        if is_warm_primary:
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
            shine.setColorAt(0.0, QColor(255, 255, 255, 116 if self.isEnabled() else 28))
            shine.setColorAt(0.18, QColor(255, 255, 255, 38 if self.isEnabled() else 10))
            shine.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, shine)

            bottom_refraction = QLinearGradient(0, rect.bottom() - rect.height() * 0.32, 0, rect.bottom())
            bottom_refraction.setColorAt(0.0, QColor(0, 0, 0, 0))
            bottom_refraction.setColorAt(1.0, QColor(0, 0, 0, 26 if theme_manager.is_dark else 18))
            painter.fillPath(path, bottom_refraction)

            if self._hover > 0.01:
                specular = QRadialGradient(
                    rect.left() + rect.width() * self._pointer_x,
                    rect.top() + rect.height() * self._pointer_y * 0.82,
                    rect.width() * 0.52,
                )
                specular_alpha = int(52 * self._hover) if self.isEnabled() else 12
                specular.setColorAt(0.0, QColor(255, 255, 255, specular_alpha))
                specular.setColorAt(0.3, QColor(255, 246, 240, specular_alpha // 4))
                specular.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillPath(path, specular)
            if not theme_manager.is_dark:
                warm_unify = QLinearGradient(0, rect.top(), 0, rect.bottom())
                warm_unify.setColorAt(0.0, QColor(255, 236, 222, 82))
                warm_unify.setColorAt(0.48, QColor(250, 196, 152, 62))
                warm_unify.setColorAt(1.0, QColor(232, 150, 96, 40))
                painter.fillPath(path, warm_unify)
        elif is_soft_accent:
            base = QLinearGradient(0, rect.top(), 0, rect.bottom())
            base_alpha = (16 if theme_manager.is_dark else 46) + int(8 * self._hover)
            if theme_manager.is_dark:
                base.setColorAt(0.0, QColor(255, 255, 255, base_alpha + 3))
                base.setColorAt(0.38, QColor(238, 244, 252, base_alpha))
                base.setColorAt(1.0, QColor(214, 224, 240, max(0, base_alpha - 4)))
            else:
                base.setColorAt(0.0, QColor(light_fill_top.red(), light_fill_top.green(), light_fill_top.blue(), light_fill_top.alpha()))
                base.setColorAt(0.38, QColor(light_fill_mid.red(), light_fill_mid.green(), light_fill_mid.blue(), light_fill_mid.alpha()))
                base.setColorAt(1.0, QColor(light_fill_bottom.red(), light_fill_bottom.green(), light_fill_bottom.blue(), light_fill_bottom.alpha()))
            painter.fillPath(path, base)

            body = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                body.setColorAt(0.0, QColor(255, 255, 255, 1))
                body.setColorAt(0.46, QColor(154, 174, 204, 4 if self.isEnabled() else 2))
                body.setColorAt(1.0, QColor(14, 20, 36, 6 if self.isEnabled() else 3))
            else:
                body.setColorAt(0.0, QColor(255, 255, 255, 8))
                body.setColorAt(0.46, QColor(light_body_mid.red(), light_body_mid.green(), light_body_mid.blue(), 12 if self.isEnabled() else 5))
                body.setColorAt(1.0, QColor(light_body_bottom.red(), light_body_bottom.green(), light_body_bottom.blue(), 14 if self.isEnabled() else 6))
            painter.fillPath(path, body)

            fresnel = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * 0.15)
            fresnel.setColorAt(0.0, QColor(255, 255, 255, 24 if self.isEnabled() else 10))
            fresnel.setColorAt(0.26, QColor(255, 255, 255, 6 if self.isEnabled() else 2))
            fresnel.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, fresnel)

            bottom_refraction = QLinearGradient(0, rect.bottom() - rect.height() * 0.30, 0, rect.bottom())
            bottom_refraction.setColorAt(0.0, QColor(0, 0, 0, 0))
            bottom_refraction.setColorAt(1.0, QColor(0, 0, 0, 8 if theme_manager.is_dark else 10))
            painter.fillPath(path, bottom_refraction)

            if self._hover > 0.01 and self.isEnabled():
                specular = QRadialGradient(
                    rect.left() + rect.width() * self._pointer_x,
                    rect.top() + rect.height() * self._pointer_y * 0.82,
                    rect.width() * 0.76,
                )
                specular_alpha = int(10 * self._hover)
                specular.setColorAt(0.0, QColor(255, 255, 255, specular_alpha))
                specular.setColorAt(0.28, QColor(255, 255, 255, max(0, specular_alpha // 8)))
                specular.setColorAt(1.0, QColor(255, 255, 255, 0))
                painter.fillPath(path, specular)
        else:
            fill = QLinearGradient(0, 0, 0, self.height())
            if self._role == "mode":
                fill.setColorAt(0.0, top)
                fill.setColorAt(1.0, bottom)
            else:
                lift = 108 if self._role == "mode_active" else 106 if self._role == "primary" else 101
                fill.setColorAt(0.0, top.lighter(lift + int(self._hover * 5)))
                fill.setColorAt(1.0, bottom)
            painter.fillPath(path, fill)

            if not theme_manager.is_dark and self._role in {"mode", "mode_active", "accent", "primary"}:
                cool_unify = QLinearGradient(0, rect.top(), 0, rect.bottom())
                cool_unify.setColorAt(0.0, QColor(226, 238, 255, 84))
                cool_unify.setColorAt(0.46, QColor(200, 222, 252, 64))
                cool_unify.setColorAt(1.0, QColor(166, 196, 244, 40))
                painter.fillPath(path, cool_unify)

            haze = QRadialGradient(
                rect.left() + rect.width() * 0.50,
                rect.top() - rect.height() * 0.06,
                rect.width() * 0.76,
            )
            base_haze = 26 if self._role == "mode_active" else 22 if self._role == "primary" else 16 if not is_mode else 12
            haze.setColorAt(0.0, QColor(255, 255, 255, base_haze if self.isEnabled() else 10))
            haze.setColorAt(0.35, QColor(255, 255, 255, 10 if self._role in {"primary", "mode_active"} and self.isEnabled() else 6 if self.isEnabled() else 3))
            haze.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), haze)

            shine = QLinearGradient(0, 0, 0, self.height() * 0.52)
            shine_alpha = 82 if self._role == "mode_active" else 80 if self._role == "primary" else 64 if not is_mode else 44
            shine.setColorAt(0.0, QColor(255, 255, 255, shine_alpha if self.isEnabled() else 26))
            shine.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillPath(path, shine)

        if self._ripple_opacity > 0.01:
            ripple_radius = 8 + self._ripple * max(rect.width(), rect.height()) * 0.9
            ripple = QRadialGradient(self._ripple_x, self._ripple_y, ripple_radius)
            ripple.setColorAt(0.0, QColor(255, 255, 255, int(72 * self._ripple_opacity)))
            ripple.setColorAt(0.45, QColor(210, 228, 255, int(32 * self._ripple_opacity)))
            ripple.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(self.rect(), ripple)
        painter.setClipping(False)

        if is_warm_primary:
            border_gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                border_gradient.setColorAt(0.0, QColor(255, 255, 255, 170 if self.isEnabled() else 66))
                border_gradient.setColorAt(0.42, QColor(255, 255, 255, 54 if self.isEnabled() else 22))
                border_gradient.setColorAt(1.0, QColor(208, 186, 180, 82 if self.isEnabled() else 34))
            else:
                border_gradient.setColorAt(0.0, QColor(255, 255, 255, 144 if self.isEnabled() else 52))
                border_gradient.setColorAt(0.42, QColor(255, 226, 205, 92 if self.isEnabled() else 30))
                border_gradient.setColorAt(1.0, QColor(232, 150, 96, 64 if self.isEnabled() else 22))
            painter.setPen(QPen(border_gradient, 1.0))
            painter.drawRoundedRect(rect, radius, radius)

            inner = rect.adjusted(0.8, 0.8, -0.8, -0.8)
            inner_path = QPainterPath()
            inner_path.addRoundedRect(inner, radius - 0.8, radius - 0.8)
            painter.setPen(QPen(QColor(255, 255, 255, 62 if self.isEnabled() else 20), 0.7))
            painter.setClipRect(QRectF(inner.left(), inner.top(), inner.width(), inner.height() * 0.44))
            painter.drawPath(inner_path)
            painter.setClipping(False)
        elif self._role == "mode":
            border = QColor(255, 255, 255, 36) if theme_manager.is_dark else QColor(light_border_bottom.red(), light_border_bottom.green(), light_border_bottom.blue(), light_border_bottom.alpha())
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif self._role == "mode_active":
            border = QColor(255, 205, 170, 132) if theme_manager.is_dark else QColor(light_border_bottom.red(), light_border_bottom.green(), light_border_bottom.blue(), light_border_bottom.alpha())
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif is_soft_accent:
            border_gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
            if theme_manager.is_dark:
                border_gradient.setColorAt(0.0, QColor(255, 255, 255, 46 if self.isEnabled() else 20))
                border_gradient.setColorAt(1.0, QColor(214, 222, 236, 20 if self.isEnabled() else 8))
            else:
                border_gradient.setColorAt(0.0, QColor(light_border_top.red(), light_border_top.green(), light_border_top.blue(), light_border_top.alpha()))
                border_gradient.setColorAt(1.0, QColor(light_border_bottom.red(), light_border_bottom.green(), light_border_bottom.blue(), light_border_bottom.alpha()))
            painter.setPen(QPen(border_gradient, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        elif self._role == "accent":
            border = QColor(255, 255, 255, 54 if theme_manager.is_dark else light_border_top.alpha())
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(rect, radius, radius)
        else:
            border = QColor(255, 255, 255, 70 if self._role == "primary" and theme_manager.is_dark else 46 if theme_manager.is_dark else light_border_top.alpha())
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(rect, radius, radius)

        if self._role == "mode" and not theme_manager.is_dark:
            text_color = QColor(light_text)
        elif self._role in {"mode", "mode_active"} and theme_manager.is_dark:
            text_color = QColor("#fff8f4") if self._role == "mode_active" else QColor("#ecf1ff")
        else:
            text_color = QColor("#ffffff") if theme_manager.is_dark else QColor(light_text)
        if not self.isEnabled():
            text_color.setAlpha(132 if not theme_manager.is_dark else 110)
        font = self.font()
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        if is_warm_primary and self.isEnabled():
            shadow_alpha = 52 if theme_manager.is_dark else 18
            painter.setPen(QColor(0, 0, 0, shadow_alpha))
            painter.drawText(rect.adjusted(0.0, 1.0, 0.0, 1.0), Qt.AlignCenter, self.text())
        painter.setPen(text_color)
        painter.drawText(rect, Qt.AlignCenter, self.text())
