from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation


def make_property_animation(target, property_name: bytes, duration: int, easing: QEasingCurve.Type) -> QPropertyAnimation:
    animation = QPropertyAnimation(target, property_name, target)
    animation.setDuration(duration)
    animation.setEasingCurve(easing)
    return animation


def restart_animation(animation: QPropertyAnimation, start, end) -> None:
    animation.stop()
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.start()


class ButtonAnimationMixin:
    def _init_button_motion(self) -> None:
        self._scale_anim = make_property_animation(self, b"scaleValue", 160, QEasingCurve.OutCubic)
        self._ripple_anim = make_property_animation(self, b"rippleValue", 420, QEasingCurve.OutCubic)

    def _animate_button_scale(self, end_value: float) -> None:
        restart_animation(self._scale_anim, self._scale, end_value)

    def _handle_button_enter(self) -> None:
        self._animate_button_scale(1.04)

    def _handle_button_leave(self) -> None:
        self._animate_button_scale(1.0)

    def _handle_button_press(self, x: float, y: float) -> None:
        self._ripple_x = x
        self._ripple_y = y
        self._ripple = 0.0
        self._ripple_opacity = 1.0
        restart_animation(self._ripple_anim, 0.0, 1.0)
        self._animate_button_scale(0.98)

    def _handle_button_release(self) -> None:
        self._animate_button_scale(1.04 if self.underMouse() else 1.0)
