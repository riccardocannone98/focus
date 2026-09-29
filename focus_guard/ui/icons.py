"""Icona dell'applicazione e icone della tray per stato, disegnate in vettoriale.

Nessun file immagine: le icone sono generate a ogni dimensione con QPainter,
quindi restano nitide su qualsiasi DPI.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

APP_ACCENT = "#0078d4"  # azzurro Windows per l'icona dell'app

# stato -> (colore, simbolo del badge)
TRAY_STATES = {
    "focused": ("#2e9d4f", "check"),
    "leaving": ("#d89614", "dots"),
    "distracted": ("#d13438", "alert"),
    "returning": ("#d13438", "alert"),
    "paused": ("#7a7a7a", "pause"),
    "stopped": ("#7a7a7a", "stop"),
    "uncalibrated": (APP_ACCENT, "plus"),
    "error": ("#8e562e", "cross"),
}


def _draw_mark(p: QPainter, s: float, base: QColor) -> None:
    """Mirino (4 angoli) con occhio al centro: il segno di Focus Guard."""
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, base.lighter(118))
    g.setColorAt(1, base.darker(122))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.24, s * 0.24)
    white = QColor("white")
    pen = QPen(white, max(1.0, s * 0.065))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    m, arm = s * 0.2, s * 0.15
    for x, y, dx, dy in ((m, m, 1, 1), (s - m, m, -1, 1), (m, s - m, 1, -1), (s - m, s - m, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * arm, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * arm))
    eye = QPainterPath()
    eye.moveTo(s * 0.27, s * 0.5)
    eye.quadTo(s * 0.5, s * 0.29, s * 0.73, s * 0.5)
    eye.quadTo(s * 0.5, s * 0.71, s * 0.27, s * 0.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(white)
    p.drawPath(eye)
    p.setBrush(base.darker(145))
    p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.08, s * 0.08)


def _draw_badge(p: QPainter, s: float, color: QColor, symbol: str) -> None:
    r = s * 0.22
    c = QPointF(s - r, s - r)
    p.setPen(QPen(QColor("white"), s * 0.05))
    p.setBrush(color)
    p.drawEllipse(c, r, r)
    pen = QPen(QColor("white"), max(1.0, s * 0.055))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    k = r * 0.45
    x, y = c.x(), c.y()
    if symbol == "check":
        p.drawPolyline([QPointF(x - k, y), QPointF(x - k * 0.2, y + k * 0.7), QPointF(x + k, y - k * 0.6)])
    elif symbol == "pause":
        p.drawLine(QPointF(x - k * 0.45, y - k * 0.7), QPointF(x - k * 0.45, y + k * 0.7))
        p.drawLine(QPointF(x + k * 0.45, y - k * 0.7), QPointF(x + k * 0.45, y + k * 0.7))
    elif symbol == "stop":
        p.setBrush(QColor("white"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(x - k * 0.65, y - k * 0.65, k * 1.3, k * 1.3), k * 0.2, k * 0.2)
    elif symbol == "alert":
        p.drawLine(QPointF(x, y - k * 0.8), QPointF(x, y + k * 0.15))
        p.drawPoint(QPointF(x, y + k * 0.75))
    elif symbol == "dots":
        for dx in (-0.6, 0, 0.6):
            p.drawPoint(QPointF(x + dx * k, y))
    elif symbol == "plus":
        p.drawLine(QPointF(x - k * 0.7, y), QPointF(x + k * 0.7, y))
        p.drawLine(QPointF(x, y - k * 0.7), QPointF(x, y + k * 0.7))
    elif symbol == "cross":
        p.drawLine(QPointF(x - k * 0.6, y - k * 0.6), QPointF(x + k * 0.6, y + k * 0.6))
        p.drawLine(QPointF(x + k * 0.6, y - k * 0.6), QPointF(x - k * 0.6, y + k * 0.6))


def render_mark(size: int, accent: str = APP_ACCENT, state: str | None = None) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if state is None:
        _draw_mark(p, size, QColor(accent))
    else:
        color, symbol = TRAY_STATES.get(state, TRAY_STATES["error"])
        # nella tray il segno resta azzurro, lo stato è nel badge (colore + simbolo)
        inner = size * 0.9
        _draw_mark(p, inner, QColor(accent))
        _draw_badge(p, size, QColor(color), symbol)
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        ic.addPixmap(render_mark(size))
    return ic


def tray_icon(state: str) -> QIcon:
    ic = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        ic.addPixmap(render_mark(size, state=state))
    return ic
