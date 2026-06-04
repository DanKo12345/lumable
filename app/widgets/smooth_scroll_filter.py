from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation


class SmoothScrollFilter(QObject):
    def __init__(self, target, step: int = 58, duration: int = 130):
        super().__init__(target)
        self._target = target
        self._step = step
        self._target_value: int | None = None
        self._animation = QPropertyAnimation(target.verticalScrollBar(), b"value", self)
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(QEasingCurve.OutQuad)
        self._animation.finished.connect(self._clear_target_value)

    def _clear_target_value(self) -> None:
        self._target_value = None

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return super().eventFilter(watched, event)

        if not watched.underMouse():
            return False

        scrollbar = self._target.verticalScrollBar()
        if not scrollbar.isVisible():
            return False

        pixel_delta = event.pixelDelta().y()
        delta = pixel_delta if pixel_delta else event.angleDelta().y()
        if delta == 0:
            return False

        if pixel_delta:
            distance = delta
        else:
            distance = round((delta / 120.0) * self._step)
        base_value = self._target_value if self._target_value is not None else scrollbar.value()
        target_value = base_value - distance
        target_value = max(scrollbar.minimum(), min(scrollbar.maximum(), target_value))
        self._target_value = target_value

        self._animation.stop()
        self._animation.setStartValue(scrollbar.value())
        self._animation.setEndValue(target_value)
        self._animation.start()
        event.accept()
        return True
