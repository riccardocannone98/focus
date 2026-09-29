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
from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
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
from focus_guard.ui.icons import app_icon
from focus_guard.ui.theme import (
    CAPTION,
    HALF,
    R_CARD,
    R_LARGE,
    S1,
    S2,
    S3,
    S4,
    TITLE,
    font,
    qcolor,
    theme,
)
from focus_guard.ui.widgets import ShadowEffect, button, pixmap, set_role, text_label
from focus_guard.vision.tracker import GazeSample

HANDLE_TOLERANCE_PX = 8
LIVE_VIEW_POINTS = 150
TRAIL_POINTS = 45  # circa 3 s a 15 fps
GRID_STEP_PX = 24
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


def _rounded_clip(p: QPainter, rect: QRectF, radius: float) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.setClipPath(path)


class CameraPreview(QWidget):
    """Anteprima specchiata (come uno specchio) con le iridi evidenziate."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image: QImage | None = None
        self._irises: tuple = ()
        self._face = False
        theme.changed.connect(self.update)

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
        t = theme.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        _rounded_clip(p, r, R_LARGE)
        p.fillRect(r, qcolor("#15171a"))
        if self._image is None:
            p.drawPixmap(QPointF(r.center().x() - 20, r.center().y() - 36), pixmap("webcam", "#8a8f98", 40))
            p.setPen(qcolor("#c8ccd2"))
            p.setFont(font(14))
            p.drawText(r.adjusted(0, 32, 0, 0), Qt.AlignmentFlag.AlignCenter, "Webcam in avvio…")
        else:
            # riempie il riquadro (cover), come una videochiamata
            img = self._image.size().scaled(r.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            target = QRectF(r.center().x() - img.width() / 2, r.center().y() - img.height() / 2,
                            img.width(), img.height())
            p.drawImage(target, self._image)
            if self._face:
                pen = QPen(qcolor(t.accent), 2)
                for cx, cy, rad in self._irises:
                    center = QPointF(target.left() + (1 - cx) * target.width(),
                                     target.top() + cy * target.height())
                    radius = max(4.0, rad * target.width() * 1.25)
                    p.setBrush(qcolor(t.accent, 40))
                    p.setPen(pen)
                    p.drawEllipse(center, radius, radius)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(qcolor(t.accent))
                    p.drawEllipse(center, 1.8, 1.8)
        p.setClipping(False)

        # badge di stato del volto
        p.setFont(font(12, 600))
        text = "Volto rilevato" if self._face else "Volto non rilevato"
        badge = QRectF(r.left() + 12, r.top() + 12, 36 + p.fontMetrics().horizontalAdvance(text), 28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor("#000000", 150))
        p.drawRoundedRect(badge, 14, 14)
        p.setBrush(qcolor(t.good if self._face else t.warn))
        p.drawEllipse(QPointF(badge.left() + 14, badge.center().y()), 4, 4)
        p.setPen(qcolor("#ffffff"))
        p.drawText(badge.adjusted(26, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, text)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcolor(t.stroke), 1))
        p.drawRoundedRect(r, R_LARGE, R_LARGE)


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
        self.trail: deque[tuple[float, float]] = deque(maxlen=TRAIL_POINTS)
        self._drag: tuple[str, QPointF, tuple] | None = None
        self._hover: str | None = None
        theme.changed.connect(self.update)

    # conversioni mappa <-> pixel (su tutto il widget)
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
        if handle != self._hover:
            self._hover = handle
            self.update()
        self.setCursor(CURSORS.get(handle, Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.update()

    # disegno
    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        _rounded_clip(p, frame, R_LARGE)
        p.fillRect(frame, qcolor(t.card))

        # griglia a puntini
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.text3, 70))
        for x in range(GRID_STEP_PX, self.width(), GRID_STEP_PX):
            for y in range(GRID_STEP_PX, self.height(), GRID_STEP_PX):
                p.drawEllipse(QPointF(x, y), 1.1, 1.1)

        # nuvola dei campioni registrati
        p.setBrush(qcolor(t.accent, 60))
        for x, y in self.cloud:
            p.drawEllipse(self.to_px(x, y), 2.2, 2.2)

        rect = self.rect_px()
        if rect is not None:
            self._paint_area(p, rect, t)

        # scia leggera degli ultimi punti
        p.setPen(Qt.PenStyle.NoPen)
        n = len(self.trail)
        live = self.point_inside
        dot_color = t.idle if live is None else (t.good if live else t.bad)
        for i, (x, y) in enumerate(self.trail):
            k = (i + 1) / n
            p.setBrush(qcolor(dot_color, int(12 + 120 * k * k)))
            p.drawEllipse(self.to_px(x, y), 1.5 + 3 * k, 1.5 + 3 * k)

        if self.point is not None:
            center = self.to_px(*self.point)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(dot_color, 60))
            p.drawEllipse(center, 18, 18)
            p.setBrush(qcolor(dot_color))
            p.setPen(QPen(qcolor(t.card), 3))
            p.drawEllipse(center, 9, 9)

        self._paint_legend(p, t)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcolor(t.stroke), 1))
        p.drawRoundedRect(frame, R_LARGE, R_LARGE)

    def _paint_area(self, p: QPainter, rect, t) -> None:
        left, top, right, bottom = rect
        area = QRectF(left, top, right - left, bottom - top)
        mx, my = area.width() * self.exit_margin, area.height() * self.exit_margin
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcolor(t.text3), 1, Qt.PenStyle.DashLine))
        p.drawRoundedRect(area.adjusted(-mx, -my, mx, my), R_CARD + 2, R_CARD + 2)
        p.setBrush(qcolor(t.accent, 34))
        p.setPen(QPen(qcolor(t.accent), 2))
        p.drawRoundedRect(area, R_CARD, R_CARD)
        if not self.editable:
            return
        cx, cy = area.center().x(), area.center().y()
        handles = {
            "top_left": (left, top), "top_right": (right, top),
            "bottom_left": (left, bottom), "bottom_right": (right, bottom),
            "top": (cx, top), "bottom": (cx, bottom), "left": (left, cy), "right": (right, cy),
        }
        for name, (hx, hy) in handles.items():
            hot = name == self._hover or (self._drag is not None and self._drag[0] == name)
            p.setBrush(qcolor(t.accent if hot else t.card))
            p.setPen(QPen(qcolor(t.accent), 2))
            if "_" in name:
                p.drawEllipse(QPointF(hx, hy), 8 if hot else 7, 8 if hot else 7)
            else:
                w, h = (20, 8) if name in ("top", "bottom") else (8, 20)
                p.drawRoundedRect(QRectF(hx - w / 2, hy - h / 2, w, h), 4, 4)

    def _paint_legend(self, p: QPainter, t) -> None:
        p.setFont(font(CAPTION))
        x, y = float(S2), self.height() - float(S3)
        for kind, text in (("good", "dentro"), ("bad", "fuori"), ("dash", "margine di uscita")):
            if kind == "dash":
                p.setPen(QPen(qcolor(t.text3), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(x, y), QPointF(x + 14, y))
            else:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qcolor(getattr(t, kind)))
                p.drawEllipse(QPointF(x + 5, y), 5, 5)
            p.setPen(qcolor(t.text2))
            p.drawText(QPointF(x + 20, y + 4), text)
            x += 20 + p.fontMetrics().horizontalAdvance(text) + S2


class StepIndicator(QWidget):
    """Passaggi numerati: Registrazione libera → Ritocco → Salva."""

    STEPS = ("Registrazione libera", "Ritocco", "Salva")

    def __init__(self) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(S1)
        self._dots: list[QLabel] = []
        self._labels: list[QLabel] = []
        self._lines: list[QWidget] = []
        for i, text in enumerate(self.STEPS):
            dot = QLabel()
            dot.setFixedSize(S3, S3)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFont(font(CAPTION, 600))
            self._dots.append(dot)
            lay.addWidget(dot)
            lab = text_label(text, 13)
            self._labels.append(lab)
            lay.addWidget(lab)
            if i < len(self.STEPS) - 1:
                line = QWidget()
                line.setFixedSize(S4, 1)
                self._lines.append(line)
                lay.addWidget(line)
        self._active = 0
        theme.changed.connect(self._on_theme)
        self.set_active(0)

    def _on_theme(self, *_) -> None:
        self.set_active(self._active)

    def set_active(self, index: int) -> None:
        self._active = index
        t = theme.tokens
        for i, (dot, lab) in enumerate(zip(self._dots, self._labels)):
            if i < index:
                dot.setText("✓")
                dot.setStyleSheet(f"color: {t.on_accent}; background: {t.accent}; border-radius: 12px;")
                set_role(lab, "text")
            elif i == index:
                dot.setText(str(i + 1))
                dot.setStyleSheet(f"color: {t.on_accent}; background: {t.accent}; border-radius: 12px;")
                set_role(lab, "text")
            else:
                dot.setText(str(i + 1))
                dot.setStyleSheet(f"color: {t.text3}; border: 1px solid {t.stroke_strong}; border-radius: 12px;")
                set_role(lab, "text3")
            lab.setFont(font(13, 600 if i == index else 400))
        for line in self._lines:
            line.setStyleSheet(f"background: {t.stroke_strong};")


def _with_shadow(widget: QWidget) -> QWidget:
    widget.setGraphicsEffect(ShadowEffect(widget, S3, 3))
    return widget


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
        self.setObjectName("window")
        self.setWindowTitle("Focus Guard – Definisci area")
        self.setWindowIcon(app_icon())
        self.resize(1200, 720)
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

        self.steps = StepIndicator()
        self.info = text_label("", 13, 400, "text2")
        self.info.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(HALF)
        self.record_button = button("", "record")
        self.record_button.clicked.connect(self.start_recording)
        self.save_button = button("Salva area", "save", "primary")
        self.save_button.clicked.connect(self.save)
        cancel_button = button("Annulla", "close", "subtle")
        cancel_button.clicked.connect(self.cancel)

        root = QVBoxLayout(self)
        root.setContentsMargins(S4, S3, S4, S3)
        root.setSpacing(S2)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(text_label("Definisci area", TITLE, 600, display=True))
        titles.addWidget(text_label("Il punto è verde quando guardi dentro l'area, rosso quando guardi fuori.",
                                    13, 400, "text2"))
        head.addLayout(titles)
        head.addStretch(1)
        head.addWidget(self.steps, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(head)

        views = QHBoxLayout()
        views.setSpacing(S2)
        for title, hint, widget, stretch in (
            ("Webcam", "anteprima locale, nulla viene salvato", self.preview, 2),
            ("Mappa dello sguardo", "destra = destra, giù = giù", self.map, 3),
        ):
            box = QVBoxLayout()
            box.setSpacing(S1)
            caption = QHBoxLayout()
            caption.addWidget(text_label(title, 15, 600))
            caption.addSpacing(S1)
            caption.addWidget(text_label(hint, CAPTION, 400, "text3"))
            caption.addStretch(1)
            box.addLayout(caption)
            box.addWidget(_with_shadow(widget), 1)
            views.addLayout(box, stretch)
        root.addLayout(views, 1)

        bar = QHBoxLayout()
        bar.setSpacing(S1)
        status = QVBoxLayout()
        status.setSpacing(S1)
        status.addWidget(self.info)
        status.addWidget(self.progress)
        bar.addLayout(status, 1)
        bar.addSpacing(S3)
        bar.addWidget(self.record_button)
        bar.addWidget(cancel_button)
        bar.addWidget(self.save_button)
        root.addLayout(bar)

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
        self.steps.set_active(0)
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
        set_role(self.info, "bad" if message else "text2")
        self.map.update()

    def start_recording(self) -> None:
        if self.phase is Phase.RECORDING:
            return
        self.phase = Phase.RECORDING
        self.steps.set_active(0)
        self._area = None
        self._samples = []
        self._elapsed = 0.0
        self.map.editable = False
        self.map.area_rect = None
        self.map.cloud = []
        self.record_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.info.setText("Registrazione in corso: guarda la tua area di lavoro come fai di solito…")
        set_role(self.info, "text2")
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
        self._enter_edit(area, f"Area registrata da {len(self._samples)} campioni, outlier esclusi: "
                               "trascina bordi e angoli per ritoccarla, poi «Salva area».")

    def _enter_edit(self, area: AreaModel, message: str) -> None:
        self.phase = Phase.EDIT
        self.steps.set_active(1)
        self._area = area
        self.map.area_rect = area.rect
        self.map.editable = True
        self.map.view = fit_view(area.rect)
        self.map.trail.clear()
        mapper = area.mapper
        self.map.cloud = [mapper.map(s) for s in self._samples]
        self.progress.setValue(1000 if self._samples else 0)
        self.record_button.setText("Ripeti registrazione")
        self.record_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.info.setText(message)
        set_role(self.info, "text2")
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
            self.map.trail.append(point)
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
            self.steps.set_active(2)
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
