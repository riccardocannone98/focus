"""Schermata di calibrazione: 4 angoli + verifica live.

Per ogni angolo l'utente lo guarda e preme SPAZIO: per COLLECT_SECONDS si
raccolgono i campioni (esclusi i battiti di ciglia) e se ne prende la
mediana. Alla fine una fase di verifica mostra dove il sistema stima lo
sguardo: INVIO salva, R ripete, ESC annulla.
"""

from __future__ import annotations

from enum import Enum, auto

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from focus_guard.config import CORNER_NAMES
from focus_guard.logic.features import GazeSmoother
from focus_guard.logic.geometry import CalibrationError, CalibrationModel, signed_distance
from focus_guard.vision.tracker import GazeSample

COLLECT_SECONDS = 1.5
MIN_SAMPLES = 8
DOT_MARGIN = 40

CORNER_LABELS = {
    "top_left": "in alto a sinistra",
    "top_right": "in alto a destra",
    "bottom_right": "in basso a destra",
    "bottom_left": "in basso a sinistra",
}


class Phase(Enum):
    WAITING = auto()
    COLLECTING = auto()
    VERIFY = auto()


class CalibrationWindow(QWidget):
    finished = pyqtSignal(object)  # dict angoli -> valori grezzi, oppure None se annullata

    def __init__(self, head_weight: float, smoothing_alpha: float) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Focus Guard – Calibrazione")
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._head_weight = head_weight
        self._smoother = GazeSmoother(smoothing_alpha)
        self._timer = QTimer(self, singleShot=True, timeout=self._finish_collecting)
        self._done = False
        self._face_visible = False
        self._restart()

    # --- stato -----------------------------------------------------------
    def _restart(self, message: str = "") -> None:
        self._step = 0
        self._corners: dict[str, list[float]] = {}
        self._buffer: list[tuple[float, ...]] = []
        self._phase = Phase.WAITING
        self._model: CalibrationModel | None = None
        self._live_uv: tuple[float, float] | None = None
        self._message = message
        self.update()

    def on_sample(self, sample: GazeSample) -> None:
        self._face_visible = sample.raw is not None
        if self._phase is Phase.COLLECTING and sample.raw is not None and not sample.blinking:
            self._buffer.append(sample.raw)
        elif self._phase is Phase.VERIFY and self._model is not None:
            raw = self._smoother.update(sample.raw, sample.blinking)
            self._live_uv = self._model.to_area(raw) if raw is not None else None
        self.update()

    def _finish_collecting(self) -> None:
        name = CORNER_NAMES[self._step]
        if len(self._buffer) < MIN_SAMPLES:
            self._phase = Phase.WAITING
            self._message = "Volto non rilevato abbastanza a lungo: riprova."
            self.update()
            return
        self._corners[name] = np.median(np.array(self._buffer), axis=0).tolist()
        self._buffer = []
        self._message = ""
        self._step += 1
        if self._step < len(CORNER_NAMES):
            self._phase = Phase.WAITING
        else:
            try:
                self._model = CalibrationModel.from_corners(self._corners, self._head_weight)
            except CalibrationError as exc:
                self._restart(f"Calibrazione non valida ({exc}).")
                return
            self._smoother.reset()
            self._phase = Phase.VERIFY
        self.update()

    def _close_with(self, result) -> None:
        if not self._done:
            self._done = True
            self._timer.stop()
            self.finished.emit(result)
        self.close()

    # --- eventi Qt -------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._close_with(None)
        elif key == Qt.Key.Key_Space and self._phase is Phase.WAITING:
            self._buffer = []
            self._message = ""
            self._phase = Phase.COLLECTING
            self._timer.start(int(COLLECT_SECONDS * 1000))
            self.update()
        elif self._phase is Phase.VERIFY and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._close_with(dict(self._corners))
        elif key == Qt.Key.Key_R:
            self._timer.stop()
            self._restart()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._done:
            self._done = True
            self._timer.stop()
            self.finished.emit(None)
        super().closeEvent(event)

    def _corner_point(self, name: str) -> QPointF:
        w, h, m = self.width(), self.height(), DOT_MARGIN
        return {
            "top_left": QPointF(m, m),
            "top_right": QPointF(w - m, m),
            "bottom_right": QPointF(w - m, h - m),
            "bottom_left": QPointF(m, h - m),
        }[name]

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(20, 22, 28))
        font = QFont()
        font.setPointSize(16)
        p.setFont(font)
        p.setPen(QColor("white"))

        if self._phase is Phase.VERIFY:
            self._paint_verify(p)
        else:
            name = CORNER_NAMES[self._step]
            center = self._corner_point(name)
            collecting = self._phase is Phase.COLLECTING
            p.setBrush(QColor("#ff5252" if collecting else "#4fc3f7"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(center, 14, 14)
            p.setPen(QColor("white"))
            text = (
                f"Punto {self._step + 1}/4 – Guarda l'angolo {CORNER_LABELS[name]} "
                "dell'area di lavoro\n"
                + ("Tieni lo sguardo fermo..." if collecting else "e premi SPAZIO")
            )
            self._paint_text(p, text)

    def _paint_verify(self, p: QPainter) -> None:
        w, h, m = self.width(), self.height(), DOT_MARGIN
        area = QRectF(m, m, w - 2 * m, h - 2 * m)
        inside = self._live_uv is not None and signed_distance(*self._live_uv) <= 0
        p.setPen(QPen(QColor("#66bb6a" if inside else "#ef5350"), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(area)
        if self._live_uv is not None:
            u, v = self._live_uv
            x = min(max(m + u * area.width(), 0), w)
            y = min(max(m + v * area.height(), 0), h)
            p.setBrush(QColor("#ffca28"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 12, 12)
        p.setPen(QColor("white"))
        self._paint_text(
            p,
            "Verifica: il punto giallo segue il tuo sguardo.\n"
            "INVIO = salva    R = ripeti    ESC = annulla",
        )

    def _paint_text(self, p: QPainter, text: str) -> None:
        extra = []
        if self._message:
            extra.append(self._message)
        if not self._face_visible:
            extra.append("⚠ Volto non rilevato: controlla webcam e illuminazione")
        full = text + ("\n\n" + "\n".join(extra) if extra else "") + "\n\nESC per annullare"
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, full)
