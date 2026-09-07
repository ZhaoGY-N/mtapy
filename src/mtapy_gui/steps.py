"""A horizontal step indicator widget for the transfer pipeline."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .theme import DARK, LIGHT


class StepIndicator(QWidget):
    """Draws N labelled steps; the current one is highlighted, finished ones
    get a check, future ones are dimmed."""

    def __init__(self, steps, parent=None) -> None:
        super().__init__(parent)
        self._steps = list(steps)  # [(id, label), ...]
        self._current = 0          # index of the active step
        self._dark = False
        self.setMinimumHeight(56)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().Policy.Fixed)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    def set_current_step(self, step_id: int) -> None:
        """Highlight the step whose id matches (fall back to last known)."""
        idx = next((i for i, (sid, _) in enumerate(self._steps) if sid == step_id), None)
        if idx is not None:
            self._current = idx
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = DARK if self._dark else LIGHT

        n = len(self._steps)
        h = self.height()
        dot_y = h // 2
        # Horizontal span between first and last dot.
        label_h = 18
        left = 40
        right = self.width() - 40
        span = max(right - left, 10)
        step_x = [left + int(span * i / (n - 1)) for i in range(n)] if n > 1 else [self.width() // 2]

        # Connecting lines (dim, except past the current one which uses accent).
        pen = QPen(QColor(c["border"]), 3)
        pen_accent = QPen(QColor(c["accent"]), 3)
        for i in range(n - 1):
            x1, x2 = step_x[i], step_x[i + 1]
            if i < self._current:
                p.setPen(pen_accent)
            else:
                p.setPen(pen)
            p.drawLine(x1, dot_y, x2, dot_y)

        # Dots + labels.
        for i, (sid, label) in enumerate(self._steps):
            x = step_x[i]
            r = 11
            rect = QRectF(x - r, dot_y - r, 2 * r, 2 * r)
            if i < self._current:
                # Done: filled accent with a check mark.
                p.setPen(QPen(QColor(c["success"]), 2))
                p.setBrush(QColor(c["success"]))
                p.drawEllipse(rect)
                p.setPen(QPen(QColor("#ffffff"), 2))
                # Simple check.
                p.drawLine(x - 4, dot_y, x - 1, dot_y + 3)
                p.drawLine(x - 1, dot_y + 3, x + 5, dot_y - 3)
            elif i == self._current:
                # Active: accent ring + white dot.
                p.setPen(QPen(QColor(c["accent"]), 3))
                p.setBrush(QColor(c["window"]))
                p.drawEllipse(rect)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(c["accent"]))
                p.drawEllipse(QRectF(x - 4, dot_y - 4, 8, 8))
            else:
                # Future: dim outline.
                p.setPen(QPen(QColor(c["border"]), 2))
                p.setBrush(QColor(c["window"]))
                p.drawEllipse(rect)

            # Label under the dot.
            p.setPen(QColor(c["text"] if i <= self._current else c["text_dim"]))
            f = QFont(self.font())
            f.setPointSize(9)
            if i == self._current:
                f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(x - 70, dot_y + 14, 140, label_h),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

        p.end()
