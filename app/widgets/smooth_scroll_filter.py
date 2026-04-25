from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation


class SmoothScrollFilter(QObject):
    def __init__(self, target, step: int = 58, duration: int = 180):
        super().__init__(target)
        self._target = target
        self._step = step
        self._animation = QPropertyAnimation(target.verticalScrollBar(), b"value", self)
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return super().eventFilter(watched, event)

        if not watched.underMouse():
            return False

        scrollbar = self._target.verticalScrollBar()
        if not scrollbar.isVisible():
            return False

        delta = event.angleDelta().y()
        if delta == 0:
            return False

        steps = delta / 120.0
        target_value = scrollbar.value() - round(steps * self._step)
        target_value = max(scrollbar.minimum(), min(scrollbar.maximum(), target_value))

        self._animation.stop()
        self._animation.setStartValue(scrollbar.value())
        self._animation.setEndValue(target_value)
        self._animation.start()
        event.accept()
        return True
