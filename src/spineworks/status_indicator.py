from random import randint

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, QTimer
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
    QShowEvent,
)
from PySide6.QtWidgets import QWidget

from spineworks.spine_validation import ValidationState


class StatusIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self._color = QColor("#bd525d")
        self._clock = QElapsedTimer()
        self._cycle_ms = randint(4000, 8000)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.update)

    def set_state(self, state: ValidationState) -> None:
        colors = {
            ValidationState.ERROR: "#bd525d",
            ValidationState.PENDING: "#c99d45",
            ValidationState.VALID: "#35a36d",
        }
        self._color = QColor(colors[state])
        descriptions = {
            ValidationState.ERROR: "Zakres wymaga korekty",
            ValidationState.PENDING: "Propozycje oczekują na zatwierdzenie",
            ValidationState.VALID: "Zakres poprawny",
        }
        self.setToolTip(descriptions[state])
        self.setAccessibleName(descriptions[state])
        self.update()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._cycle_ms = randint(4000, 8000)
        self._clock.start()
        self._timer.start()

    def hideEvent(self, event: QHideEvent) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        sphere = QRectF(6, 6, 28, 28)

        shadow = QRadialGradient(QPointF(20, 24), 17)
        shadow.setColorAt(0, QColor(0, 0, 0, 95))
        shadow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(QPen(QColor(0, 0, 0, 0)))
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(3, 7, 34, 34))

        surface = QRadialGradient(QPointF(15, 13), 25)
        surface.setColorAt(0, self._color.lighter(155))
        surface.setColorAt(0.45, self._color)
        surface.setColorAt(1, self._color.darker(210))
        painter.setBrush(surface)
        painter.setPen(QPen(self._color.darker(150), 1))
        painter.drawEllipse(sphere)

        clip = QPainterPath()
        clip.addEllipse(sphere)
        painter.setClipPath(clip)

        phase = self._clock.elapsed() if self._clock.isValid() else 0
        if phase >= self._cycle_ms:
            self._clock.restart()
            self._cycle_ms = randint(4000, 8000)
            phase = 0
        if phase < 1100:
            progress = phase / 1100
            strength = 1 - abs(2 * progress - 1)
            gleam = QRadialGradient(
                QPointF(7 + 28 * progress, 10 + 15 * progress),
                13,
            )
            gleam.setColorAt(0, QColor(255, 255, 255, int(65 * strength)))
            gleam.setColorAt(1, QColor(255, 255, 255, 0))
            painter.fillRect(sphere, gleam)

        highlight = QRadialGradient(QPointF(15, 12), 8)
        highlight.setColorAt(0, QColor(255, 255, 255, 70))
        highlight.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillRect(sphere, highlight)
