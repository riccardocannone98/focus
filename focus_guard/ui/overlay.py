"""Banner di allarme: sempre in primo piano, trasparente ai click, con dissolvenza.

Il banner vero (AlertOverlay) diventa visibile subito e si nasconde subito,
così lo stato dell'allarme è sempre esatto. La dissolvenza in uscita la fa
una copia temporanea (_Ghost) che parte dallo stesso contenuto e sfuma.
"""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QGuiApplication, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QWidget

from focus_guard.ui.messages import MessagePicker, format_elapsed
from focus_guard.ui.theme import (
    FONT_EMOJI,
    FONT_TEXT,
    R_LARGE,
    S1,
    S2,
    S3,
    S4,
    S5,
    font,
    qcolor,
    theme,
)
from focus_guard.ui.widgets import pixmap

FADE_IN_MS = 280
FADE_OUT_MS = 320
CARD_WIDTH = 560
PHOTO_HEIGHT = 320

_FLAGS = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowTransparentForInput
    | Qt.WindowType.WindowDoesNotAcceptFocus
)


class _BannerView(QWidget):
    """Disegna velo, card, foto, messaggio e tempo fuori area."""

    def __init__(self, opacity: float) -> None:
        super().__init__(None, _FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.scrim_opacity = opacity
        self.photo: QPixmap | None = None
        self.headline = ""
        self.subtitle = ""
        self.elapsed_text = "0:00"

    def copy_state(self, other: "_BannerView") -> None:
        self.photo, self.headline = other.photo, other.headline
        self.subtitle, self.elapsed_text = other.subtitle, other.elapsed_text
        self.scrim_opacity = other.scrim_opacity
        self.setGeometry(other.geometry())

    def _cover(self, target: QRectF) -> QPixmap:
        """Foto ritagliata per riempire il riquadro (object-fit: cover)."""
        scaled = self.photo.scaled(
            int(target.width()), int(target.height()),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation,
        )
        x = (scaled.width() - int(target.width())) // 2
        y = (scaled.height() - int(target.height())) // 2
        return scaled.copy(x, y, int(target.width()), int(target.height()))

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        # velo morbido: più chiaro al centro, più scuro ai bordi
        alpha = int(255 * self.scrim_opacity)
        veil = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        veil.setColorAt(0, qcolor("#0a0a0e", int(alpha * 0.8)))
        veil.setColorAt(1, qcolor("#0a0a0e", min(255, int(alpha * 1.25))))
        p.fillRect(self.rect(), veil)

        card_w = min(CARD_WIDTH, w - 2 * S4)
        text_w = card_w - 2 * S3
        wrap = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        headline_font = font(26, 600, display=True)
        headline_font.setFamilies(FONT_TEXT + FONT_EMOJI)
        p.setFont(headline_font)
        headline_h = p.fontMetrics().boundingRect(QRect(0, 0, text_w, 1000), wrap, self.headline).height()
        p.setFont(font(15))
        subtitle_h = p.fontMetrics().boundingRect(QRect(0, 0, text_w, 1000), wrap, self.subtitle).height()
        has_photo = self.photo is not None
        photo_h = PHOTO_HEIGHT if has_photo else S5
        card_h = S2 + photo_h + S3 + headline_h + S1 + subtitle_h + S3 + 20 + S3
        card = QRectF((w - card_w) / 2, (h - card_h) / 2, card_w, card_h)

        # ombra leggera a strati
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(S2, 0, -2):
            p.setBrush(qcolor("#000000", 6))
            p.drawRoundedRect(card.adjusted(-i, -i + S1, i, i + S1), R_LARGE + i, R_LARGE + i)
        p.setBrush(qcolor(t.card))
        p.setPen(QPen(qcolor(t.stroke), 1))
        p.drawRoundedRect(card, R_LARGE, R_LARGE)

        y = card.top() + S2
        if has_photo:
            ph = QRectF(card.left() + S2, y, card_w - 2 * S2, photo_h)
            clip = QPainterPath()
            clip.addRoundedRect(ph, R_LARGE - 4, R_LARGE - 4)
            p.setClipPath(clip)
            p.drawPixmap(ph.topLeft(), self._cover(ph))
            p.setClipping(False)
            chip_origin = QPointF(ph.left() + 12, ph.top() + 12)
        else:
            chip_origin = QPointF(card.center().x() - 90, card.top() + S2)
        y = card.top() + S2 + photo_h + S3

        # chip "fuori area da m:ss"
        p.setFont(font(13, 600))
        chip_text = f"fuori area da {self.elapsed_text}"
        chip = QRectF(chip_origin, QPointF(chip_origin.x() + 44 + p.fontMetrics().horizontalAdvance(chip_text),
                                           chip_origin.y() + 30))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#000000", 150) if has_photo else qcolor(t.bad, 40))
        p.drawRoundedRect(chip, 15, 15)
        chip_color = "#ffffff" if has_photo else t.bad
        p.drawPixmap(QPointF(chip.left() + 12, chip.top() + 7), pixmap("time", chip_color, 16))
        p.setPen(qcolor(chip_color))
        p.drawText(chip.adjusted(34, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, chip_text)

        # messaggio e sottotitolo (altezze misurate: il testo può andare a capo)
        p.setFont(headline_font)
        p.setPen(qcolor(t.text))
        p.drawText(QRectF(card.left() + S3, y, text_w, headline_h), wrap, self.headline)
        y += headline_h + S1
        p.setFont(font(15))
        p.setPen(qcolor(t.text2))
        p.drawText(QRectF(card.left() + S3, y, text_w, subtitle_h), wrap, self.subtitle)
        y += subtitle_h + S3
        p.setFont(font(12))
        p.setPen(qcolor(t.text3))
        p.drawText(QRectF(card.left(), y, card_w, 20), Qt.AlignmentFlag.AlignHCenter,
                   "Torna a guardare la tua area: il banner sparisce da solo")


class _Ghost(_BannerView):
    """Copia del banner usata solo per la dissolvenza in uscita."""

    def fade_out(self) -> None:
        self.setWindowOpacity(1.0)
        self.show()
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(FADE_OUT_MS)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.finished.connect(self.close)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()


class AlertOverlay(_BannerView):
    """Schermo oscurato con foto, messaggio simpatico e tempo trascorso fuori area.

    Non prende il focus e lascia passare mouse e tastiera: anche se il
    rilevamento sbaglia, non blocca mai il lavoro.
    """

    def __init__(self, opacity: float = 0.6) -> None:
        super().__init__(opacity)
        self._messages = MessagePicker()
        self._since = time.monotonic()
        self._ticker = QTimer(self, interval=1000, timeout=self._tick)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(FADE_IN_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._ghosts: list[_Ghost] = []
        theme.changed.connect(self.update)

    def show_alert(self, image: Path | None, text: str, elapsed_s: float = 0.0) -> None:
        """Mostra il banner; elapsed_s = secondi già trascorsi fuori area."""
        self.subtitle = text
        self.headline = self._messages.pick()
        self.photo = None
        if image is not None:
            photo = QPixmap(str(image))
            self.photo = None if photo.isNull() else photo
        self._since = time.monotonic() - max(0.0, elapsed_s)
        self._tick()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._ticker.start()

    def _tick(self) -> None:
        self.elapsed_text = format_elapsed(time.monotonic() - self._since)
        self.update()

    def hide_alert(self) -> None:
        if not self.isVisible():
            return
        self._ticker.stop()
        self._fade.stop()
        ghost = _Ghost(self.scrim_opacity)
        ghost.copy_state(self)
        ghost.destroyed.connect(lambda *_: self._ghosts.remove(ghost) if ghost in self._ghosts else None)
        self._ghosts.append(ghost)
        self.hide()
        self.photo = None
        ghost.fade_out()
