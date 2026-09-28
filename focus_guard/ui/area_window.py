"""Finestra "Definisci area": anteprima webcam + mappa dello sguardo.

Fasi:
    IDLE       anteprima e punto live; pulsante "Avvia registrazione"
    RECORDING  per recording_seconds si raccolgono i campioni (battiti esclusi)
    EDIT       il rettangolo ricavato (percentili) si ritocca con il mouse

I frame dell'anteprima arrivano dal thread di cattura come array in memoria,
vengono disegnati e scartati: nulla viene salvato.
"""

from __future__ import annotations

from collections import deque
from enum import Enum, auto

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from focus_guard.logic.area import (
    AreaError,
    AreaModel,
    GazeMapper,
    apply_drag,
    build_area_from_samples,
    fit_view,
    hit_test,
)
from focus_guard.logic.features import GazeSmoother
from focus_guard.vision.tracker import GazeSample

GREEN = QColor("#2e9d4f")
RED = QColor("#d93b3b")
GREY = QColor("#9a9892")
ACCENT = QColor("#2a78d6")
SURFACE = QColor("#fcfcfb")
GRID = QColor("#e6e5e1")
TEXT_MUTED = QColor("#52514e")

HANDLE_TOLERANCE_PX = 8
LIVE_VIEW_POINTS = 150
CURSORS = {
    "left": Qt.CursorShape.SizeHorCursor,
    "right": Qt.CursorShape.SizeHorCursor,
    "top": Qt.CursorShape.SizeVerCursor,
    "bottom": Qt.CursorShape.SizeVerCursor,
    "top_left": Qt.CursorShape.SizeFDiagCursor,
    "bottom_right": Qt.CursorShape.SizeFDiagCursor,
    "top_right": Qt.CursorShape.SizeBDiagCursor,
    "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    "move": Qt.CursorShape.SizeAllCursor,
}


class Phase(Enum):
    IDLE = auto()
    RECORDING = auto()
    EDIT = auto()


class CameraPreview(QWidget):
    """Anteprima specchiata (come uno specchio) con le iridi evidenziate."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image: QImage | None = None
        self._irises: tuple = ()
        self._face = False

    def set_frame(self, rgb: np.ndarray) -> None:
        mirrored = np.ascontiguousarray(rgb[:, ::-1])
        h, w = mirrored.shape[:2]
        self._image = QImage(mirrored.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.update()

    def set_sample(self, sample: GazeSample) -> None:
        self._irises = sample.irises
        self._face = sample.face_found
        self.update()

    def clear(self) -> None:
        self._image = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#1e1f22"))
        if self._image is None:
            p.setPen(QColor("white"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Webcam in avvio…")
            return
        img = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(
            (self.width() - img.width()) / 2, (self.height() - img.height()) / 2,
            img.width(), img.height(),
        )
        p.drawImage(target, self._image)
        if self._face:
            p.setPen(QPen(QColor("#00e5ff"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for cx, cy, r in self._irises:
                center = QPointF(target.left() + (1 - cx) * target.width(),
                                 target.top() + cy * target.height())
                radius = max(3.0, r * target.width())
                p.drawEllipse(center, radius, radius)
                p.drawPoint(center)
        else:
            p.setPen(QColor("#ffca28"))
            p.drawText(target.adjusted(0, 8, 0, 0),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       "Volto non rilevato")


class GazeMap(QWidget):
    """Mappa 2D dello sguardo con rettangolo dell'area trascinabile."""

    rect_changed = pyqtSignal(tuple)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(360, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.view = (-0.8, -0.2, -0.2, 0.2)
        self.area_rect: tuple[float, float, float, float] | None = None
        self.editable = False
        self.exit_margin = 0.1
        self.point: tuple[float, float] | None = None
        self.point_inside: bool | None = None
        self.cloud: list[tuple[float, float]] = []
        self._drag: tuple[str, QPointF, tuple] | None = None

    # conversioni mappa <-> pixel
    def to_px(self, x: float, y: float) -> QPointF:
        x0, y0, x1, y1 = self.view
        return QPointF((x - x0) / (x1 - x0) * self.width(), (y - y0) / (y1 - y0) * self.height())

    def rect_px(self) -> tuple[float, float, float, float] | None:
        if self.area_rect is None:
            return None
        a, b = self.to_px(*self.area_rect[:2]), self.to_px(*self.area_rect[2:])
        return a.x(), a.y(), b.x(), b.y()

    def _scale(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.view
        return (x1 - x0) / max(1, self.width()), (y1 - y0) / max(1, self.height())

    # mouse
    def mousePressEvent(self, event) -> None:  # noqa: N802
        rect = self.rect_px()
        if not self.editable or rect is None:
            return
        pos = event.position()
        handle = hit_test(rect, pos.x(), pos.y(), HANDLE_TOLERANCE_PX)
        if handle is not None:
            self._drag = (handle, pos, self.area_rect)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._drag is not None:
            handle, origin, start_rect = self._drag
            sx, sy = self._scale()
            self.area_rect = apply_drag(
                start_rect, handle, (pos.x() - origin.x()) * sx, (pos.y() - origin.y()) * sy
            )
            self.rect_changed.emit(self.area_rect)
            self.update()
            return
        rect = self.rect_px()
        handle = hit_test(rect, pos.x(), pos.y(), HANDLE_TOLERANCE_PX) if (
            self.editable and rect is not None) else None
        self.setCursor(CURSORS.get(handle, Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    # disegno
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), SURFACE)
        p.setPen(QPen(GRID, 1))
        for i in range(1, 8):
            x = self.width() * i / 8
            y = self.height() * i / 8
            p.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            p.drawLine(QPointF(0, y), QPointF(self.width(), y))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(42, 120, 214, 70))
        for x, y in self.cloud:
            p.drawEllipse(self.to_px(x, y), 2.5, 2.5)

        rect = self.rect_px()
        if rect is not None:
            left, top, right, bottom = rect
            mx, my = (right - left) * self.exit_margin, (bottom - top) * self.exit_margin
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(GREY, 1, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(left - mx, top - my, right - left + 2 * mx, bottom - top + 2 * my))
            p.setBrush(QColor(42, 120, 214, 28))
            p.setPen(QPen(ACCENT, 2))
            p.drawRect(QRectF(left, top, right - left, bottom - top))
            if self.editable:
                p.setBrush(ACCENT)
                p.setPen(QPen(SURFACE, 2))
                for hx in (left, (left + right) / 2, right):
                    for hy in (top, (top + bottom) / 2, bottom):
                        if (hx, hy) != ((left + right) / 2, (top + bottom) / 2):
                            p.drawRect(QRectF(hx - 5, hy - 5, 10, 10))

        if self.point is not None:
            color = GREY if self.point_inside is None else (GREEN if self.point_inside else RED)
            p.setBrush(color)
            p.setPen(QPen(SURFACE, 2))
            p.drawEllipse(self.to_px(*self.point), 9, 9)

        p.setPen(TEXT_MUTED)
        p.drawText(self.rect().adjusted(8, 6, -8, -6),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                   "tratteggio = margine di uscita")


class AreaWindow(QWidget):
    finished = pyqtSignal(object)  # AreaModel salvata oppure None

    def __init__(
        self,
        recording_seconds: float,
        percentiles: tuple[float, float],
        head_weight: float,
        exit_margin: float,
        smoothing_alpha: float,
        current: AreaModel | None = None,
    ) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("Focus Guard – Definisci area")
        self.resize(1100, 620)
        self._recording_seconds = recording_seconds
        self._percentiles = percentiles
        self._head_weight = head_weight
        self._smoother = GazeSmoother(smoothing_alpha)
        self._area = current
        self._default_signs = (current.sign_x, current.sign_y) if current else (1.0, 1.0)
        self._samples: list[tuple[float, ...]] = []
        self._recent: deque[tuple[float, float]] = deque(maxlen=LIVE_VIEW_POINTS)
        self._elapsed = 0.0
        self._done = False

        self.preview = CameraPreview()
        self.map = GazeMap()
        self.map.exit_margin = exit_margin
        self.map.rect_changed.connect(self._on_rect_dragged)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.record_button = QPushButton()
        self.record_button.clicked.connect(self.start_recording)
        self.save_button = QPushButton("Salva")
        self.save_button.clicked.connect(self.save)
        cancel_button = QPushButton("Annulla")
        cancel_button.clicked.connect(self.cancel)

        views = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Webcam</b> (anteprima, nulla viene salvato)"))
        left.addWidget(self.preview, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Mappa dello sguardo</b>"))
        right.addWidget(self.map, 1)
        views.addLayout(left, 2)
        views.addLayout(right, 3)
        buttons = QHBoxLayout()
        buttons.addWidget(self.record_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel_button)
        root = QVBoxLayout(self)
        root.addLayout(views, 1)
        root.addWidget(self.info)
        root.addWidget(self.progress)
        root.addLayout(buttons)

        self._timer = QTimer(self, interval=100, timeout=self._tick)
        if current is not None:
            self._enter_edit(current, "Area attuale: trascina bordi e angoli per ritoccarla, "
                                      "oppure ripeti la registrazione.")
        else:
            self._enter_idle()

    # --- fasi ------------------------------------------------------------
    @property
    def mapper(self) -> GazeMapper:
        if self._area is not None:
            return self._area.mapper
        return GazeMapper(self._head_weight, *self._default_signs)

    def _enter_idle(self, message: str = "") -> None:
        self.phase = Phase.IDLE
        self.map.editable = False
        self.map.area_rect = None
        self.map.cloud = []
        self.progress.setValue(0)
        self.record_button.setText("Avvia registrazione")
        self.record_button.setEnabled(True)
        self.save_button.setEnabled(False)
        self.info.setText(
            (message + "\n" if message else "")
            + f"Premi «Avvia registrazione» e per {self._recording_seconds:g} s guarda con "
            "naturalezza la tua area di lavoro: schermo, tastiera, appunti."
        )
        self.map.update()

    def start_recording(self) -> None:
        if self.phase is Phase.RECORDING:
            return
        self.phase = Phase.RECORDING
        self._area = None
        self._samples = []
        self._elapsed = 0.0
        self.map.editable = False
        self.map.area_rect = None
        self.map.cloud = []
        self.record_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.info.setText("Registrazione in corso: guarda la tua area di lavoro come fai di solito…")
        self._timer.start()

    def _tick(self) -> None:
        self._elapsed += self._timer.interval() / 1000
        self.progress.setValue(int(1000 * min(1.0, self._elapsed / self._recording_seconds)))
        if self._elapsed >= self._recording_seconds:
            self.finish_recording()

    def finish_recording(self) -> None:
        self._timer.stop()
        try:
            area = build_area_from_samples(
                self._samples, self._head_weight, self._percentiles, self._default_signs
            )
        except AreaError as exc:
            self._enter_idle(f"⚠ {exc}")
            return
        self._enter_edit(area, "Area registrata: trascina bordi e angoli per ritoccarla, poi «Salva».")

    def _enter_edit(self, area: AreaModel, message: str) -> None:
        self.phase = Phase.EDIT
        self._area = area
        self.map.area_rect = area.rect
        self.map.editable = True
        self.map.view = fit_view(area.rect)
        mapper = area.mapper
        self.map.cloud = [mapper.map(s) for s in self._samples]
        self.progress.setValue(1000 if self._samples else 0)
        self.record_button.setText("Ripeti registrazione")
        self.record_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.info.setText(message)
        self.map.update()

    def _on_rect_dragged(self, rect: tuple) -> None:
        if self._area is not None:
            self._area = self._area.with_rect(rect)

    # --- campioni --------------------------------------------------------
    def on_sample(self, sample: GazeSample) -> None:
        self.preview.set_sample(sample)
        if self.phase is Phase.RECORDING and sample.raw is not None and not sample.blinking:
            self._samples.append(sample.raw)
            self.map.cloud.append(self.mapper.map(sample.raw))
        raw = self._smoother.update(sample.raw, sample.blinking)
        if raw is None:
            self.map.point = None
        else:
            point = self.mapper.map(raw)
            self.map.point = point
            self.map.point_inside = (
                self._area.point_distance(point) <= 0 if self._area is not None else None
            )
            if self.phase is not Phase.EDIT:
                self._recent.append(point)
                xs, ys = zip(*self._recent)
                self.map.view = fit_view((min(xs), min(ys), max(xs), max(ys)), factor=1.6)
        self.map.update()

    def on_preview(self, rgb: np.ndarray) -> None:
        self.preview.set_frame(rgb)

    # --- chiusura --------------------------------------------------------
    def save(self) -> None:
        if self.phase is Phase.EDIT and self._area is not None:
            self._close_with(self._area)

    def cancel(self) -> None:
        self._close_with(None)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancel()
        else:
            super().keyPressEvent(event)

    def _close_with(self, result) -> None:
        if not self._done:
            self._done = True
            self._timer.stop()
            self.finished.emit(result)
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._done:
            self._done = True
            self._timer.stop()
            self.finished.emit(None)
        self.preview.clear()
        super().closeEvent(event)
