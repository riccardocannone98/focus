"""Banner di allarme: sempre in primo piano, trasparente ai click."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget


class AlertOverlay(QWidget):
    """Schermo oscurato con immagine e messaggio al centro.

    Non prende il focus e lascia passare mouse e tastiera: anche se il
    rilevamento sbaglia, non blocca mai il lavoro.
    """

    def __init__(self, opacity: float = 0.6) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._opacity = opacity
        self._pixmap: QPixmap | None = None
        self._text = ""

    def show_alert(self, image: Path | None, text: str) -> None:
        self._text = text
        self._pixmap = None
        if image is not None:
            pixmap = QPixmap(str(image))
            self._pixmap = None if pixmap.isNull() else pixmap
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.show()
        self.raise_()
        self.update()

    def hide_alert(self) -> None:
        self.hide()
        self._pixmap = None

    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(0, 0, 0, int(255 * self._opacity)))

        w, h = self.width(), self.height()
        text_h = max(60, h // 10)
        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                int(w * 0.6),
                int(h * 0.6),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            top = (h - scaled.height() - text_h) // 2
            painter.drawPixmap((w - scaled.width()) // 2, top, scaled)
            text_rect = QRect(0, top + scaled.height(), w, text_h)
        else:
            text_rect = QRect(0, (h - text_h) // 2, w, text_h)

        font = QFont()
        font.setPointSize(max(18, h // 30))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._text)
