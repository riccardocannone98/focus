"""Dashboard: pannello di controllo + KPI + grafici + esportazione CSV.

La finestra non contiene logica di tracking: emette segnali verso il
controller e mostra lo stato che il controller le passa. I KPI sono
calcolati dal registro eventi locale.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from focus_guard.stats.kpi import (
    compute_kpis,
    distractions_by_hour,
    focus_rate_by_day,
    period_bounds,
)
from focus_guard.stats.store import EventLog
from focus_guard.ui.charts import DistractionsByHourChart, FocusRateByDayChart

PERIOD_LABELS = {"today": "Oggi", "7d": "Ultimi 7 giorni", "30d": "Ultimi 30 giorni"}
PAUSE_MINUTES = (15, 30, 60)
DELAY_STEP_S = 0.5
DELAY_RANGE_S = (0.5, 10.0)
MARGIN_RANGE_PCT = (0, 50)
STATS_REFRESH_MS = 30_000


@dataclass(frozen=True)
class TrackingStatus:
    tracking: bool = False
    paused: bool = False
    paused_until: float | None = None  # epoch; None = pausa senza scadenza
    inside: bool | None = None  # None = sconosciuto (volto assente, tracking fermo)
    face: bool | None = None
    area_defined: bool = False


def fmt(value: float | None, decimals: int = 1) -> str:
    """Numero in formato italiano; trattino se non disponibile."""
    if value is None:
        return "—"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


class KpiTile(QFrame):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.setObjectName("tile")
        self.setStyleSheet(
            "#tile { background: #fcfcfb; border: 1px solid #e6e5e1; border-radius: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        caption = QLabel(label)
        caption.setStyleSheet("color: #52514e; font-size: 11px;")
        caption.setWordWrap(True)
        self.value = QLabel("—")
        self.value.setStyleSheet("color: #0b0b0b; font-size: 22px; font-weight: 600;")
        layout.addWidget(caption)
        layout.addWidget(self.value)

    def set(self, text: str) -> None:
        self.value.setText(text)


# (chiave, etichetta con unità, formattatore)
KPI_SPEC = (
    ("active_min", "Tempo di sessione attiva [min]", lambda k: fmt(k.active_min, 0)),
    ("focus_rate_pct", "Tasso di focus [%]", lambda k: fmt(k.focus_rate_pct, 1)),
    ("distractions", "N. distrazioni [n]", lambda k: str(k.distractions)),
    ("glances", "N. sguardi fuori senza allarme [n]", lambda k: str(k.glances)),
    ("avg_distraction_s", "Durata media distrazione [s]", lambda k: fmt(k.avg_distraction_s, 1)),
    ("max_distraction_s", "Distrazione più lunga [s]", lambda k: fmt(k.max_distraction_s, 1)),
    ("longest_streak_min", "Striscia di focus più lunga [min]", lambda k: fmt(k.longest_streak_min, 1)),
    ("distractions_per_hour", "Distrazioni per ora di sessione [n/h]",
     lambda k: fmt(k.distractions_per_hour, 2)),
)


class Dashboard(QMainWindow):
    start_tracking = pyqtSignal()
    stop_tracking = pyqtSignal()
    pause_for = pyqtSignal(int)  # minuti
    resume = pyqtSignal()
    define_area = pyqtSignal()
    activation_delay_changed = pyqtSignal(float)  # secondi
    exit_margin_changed = pyqtSignal(float)  # frazione del lato area

    def __init__(self, event_log: EventLog) -> None:
        super().__init__()
        self.setWindowTitle("Focus Guard – Dashboard")
        self.resize(1080, 780)
        self._log = event_log
        self._status = TrackingStatus()

        central = QWidget()
        root = QVBoxLayout(central)
        root.addWidget(self._build_controls())
        root.addWidget(self._build_stats(), 1)
        self.setCentralWidget(central)

        self._stats_timer = QTimer(self, interval=STATS_REFRESH_MS, timeout=self.refresh_stats)
        self.set_status(self._status)

    # --- pannello di controllo -------------------------------------------
    def _build_controls(self) -> QGroupBox:
        box = QGroupBox("Controllo")
        grid = QGridLayout(box)

        self.tracking_label = QLabel()
        self.gaze_label = QLabel()
        self.face_label = QLabel()
        self.area_label = QLabel()
        status_row = QHBoxLayout()
        for caption, label in (
            ("Tracking", self.tracking_label),
            ("Sguardo", self.gaze_label),
            ("Volto rilevato", self.face_label),
            ("Area", self.area_label),
        ):
            cell = QLabel(f"<span style='color:#52514e'>{caption}:</span>")
            status_row.addWidget(cell)
            label.setStyleSheet("font-weight: 600;")
            status_row.addWidget(label)
            status_row.addSpacing(18)
        status_row.addStretch(1)
        grid.addLayout(status_row, 0, 0, 1, 3)

        self.toggle_button = QPushButton()
        self.toggle_button.clicked.connect(self._on_toggle)
        buttons = QHBoxLayout()
        buttons.addWidget(self.toggle_button)
        self.pause_buttons = []
        for minutes in PAUSE_MINUTES:
            b = QPushButton(f"Pausa {minutes} min")
            b.clicked.connect(lambda _=False, m=minutes: self.pause_for.emit(m))
            buttons.addWidget(b)
            self.pause_buttons.append(b)
        self.resume_button = QPushButton("Riprendi")
        self.resume_button.clicked.connect(self.resume)
        buttons.addWidget(self.resume_button)
        buttons.addStretch(1)
        self.area_button = QPushButton("Ridefinisci area")
        self.area_button.clicked.connect(self.define_area)
        buttons.addWidget(self.area_button)
        grid.addLayout(buttons, 1, 0, 1, 3)

        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.delay_slider.setRange(int(DELAY_RANGE_S[0] / DELAY_STEP_S), int(DELAY_RANGE_S[1] / DELAY_STEP_S))
        self.delay_value = QLabel()
        self.delay_slider.valueChanged.connect(self._on_delay)
        self.margin_slider = QSlider(Qt.Orientation.Horizontal)
        self.margin_slider.setRange(*MARGIN_RANGE_PCT)
        self.margin_value = QLabel()
        self.margin_slider.valueChanged.connect(self._on_margin)
        for row, (caption, slider, value) in enumerate(
            (
                ("Ritardo di attivazione [s]", self.delay_slider, self.delay_value),
                ("Margine di uscita [% lato area]", self.margin_slider, self.margin_value),
            ),
            start=2,
        ):
            grid.addWidget(QLabel(caption), row, 0)
            grid.addWidget(slider, row, 1)
            value.setMinimumWidth(60)
            grid.addWidget(value, row, 2)
        grid.setColumnStretch(1, 1)
        return box

    def _on_toggle(self) -> None:
        (self.stop_tracking if self._status.tracking else self.start_tracking).emit()

    def _on_delay(self, steps: int) -> None:
        seconds = steps * DELAY_STEP_S
        self.delay_value.setText(f"{fmt(seconds, 1)} s")
        self.activation_delay_changed.emit(seconds)

    def _on_margin(self, pct: int) -> None:
        self.margin_value.setText(f"{pct} %")
        self.exit_margin_changed.emit(pct / 100)

    def set_thresholds(self, activation_delay_s: float, exit_margin: float, min_margin: float = 0.0) -> None:
        """Aggiorna i cursori senza riemettere i segnali."""
        for slider in (self.delay_slider, self.margin_slider):
            slider.blockSignals(True)
        low = max(MARGIN_RANGE_PCT[0], int(round(min_margin * 100 + 0.4999)))
        self.margin_slider.setMinimum(low)
        self.delay_slider.setValue(int(round(activation_delay_s / DELAY_STEP_S)))
        self.margin_slider.setValue(int(round(exit_margin * 100)))
        self.delay_value.setText(f"{fmt(self.delay_slider.value() * DELAY_STEP_S, 1)} s")
        self.margin_value.setText(f"{self.margin_slider.value()} %")
        for slider in (self.delay_slider, self.margin_slider):
            slider.blockSignals(False)

    def set_status(self, status: TrackingStatus) -> None:
        self._status = status
        if not status.tracking:
            tracking = "Fermo"
        elif status.paused:
            tracking = "In pausa" + (
                f" fino alle {datetime.fromtimestamp(status.paused_until):%H:%M}"
                if status.paused_until else ""
            )
        else:
            tracking = "Attivo"
        self.tracking_label.setText(tracking)
        live = status.tracking and not status.paused
        if not live or status.inside is None:
            self.gaze_label.setText("—")
            self.gaze_label.setStyleSheet("font-weight: 600; color: #52514e;")
        else:
            self.gaze_label.setText("Dentro l'area" if status.inside else "Fuori area")
            self.gaze_label.setStyleSheet(
                "font-weight: 600; color: %s;" % ("#2e9d4f" if status.inside else "#d93b3b")
            )
        self.face_label.setText("—" if not live or status.face is None else ("Sì" if status.face else "No"))
        self.area_label.setText("Definita" if status.area_defined else "Da definire")
        self.toggle_button.setText("Ferma tracking" if status.tracking else "Avvia tracking")
        for b in self.pause_buttons:
            b.setEnabled(status.tracking)
        self.resume_button.setEnabled(status.tracking and status.paused)

    # --- statistiche -------------------------------------------------------
    def _build_stats(self) -> QGroupBox:
        box = QGroupBox("Statistiche")
        layout = QVBoxLayout(box)
        top = QHBoxLayout()
        top.addWidget(QLabel("Periodo:"))
        self.period_combo = QComboBox()
        for key, label in PERIOD_LABELS.items():
            self.period_combo.addItem(label, key)
        self.period_combo.currentIndexChanged.connect(self.refresh_stats)
        top.addWidget(self.period_combo)
        top.addStretch(1)
        self.updated_label = QLabel()
        self.updated_label.setStyleSheet("color: #52514e;")
        top.addWidget(self.updated_label)
        export = QPushButton("Esporta CSV")
        export.clicked.connect(self.export_csv)
        top.addWidget(export)
        layout.addLayout(top)

        tiles = QGridLayout()
        self.tiles: dict[str, KpiTile] = {}
        for i, (key, label, _) in enumerate(KPI_SPEC):
            tile = KpiTile(label)
            self.tiles[key] = tile
            tiles.addWidget(tile, i // 4, i % 4)
        layout.addLayout(tiles)

        charts = QHBoxLayout()
        self.hour_chart = DistractionsByHourChart()
        self.day_chart = FocusRateByDayChart()
        charts.addWidget(self.hour_chart)
        charts.addWidget(self.day_chart)
        layout.addLayout(charts, 1)
        return box

    @property
    def period(self) -> str:
        return self.period_combo.currentData()

    def refresh_stats(self) -> None:
        lo, hi = period_bounds(self.period, time.time())
        events = self._log.query(lo, hi)
        kpis = compute_kpis(events, lo, hi)
        for key, _, formatter in KPI_SPEC:
            self.tiles[key].set(formatter(kpis))
        self.hour_chart.plot(distractions_by_hour(events, lo, hi))
        self.day_chart.plot(focus_rate_by_day(events, lo, hi))
        self.updated_label.setText(f"aggiornato alle {datetime.now():%H:%M:%S}")
        self.last_kpis = kpis

    def export_csv(self, path: Path | None = None) -> Path | None:
        lo, hi = period_bounds(self.period, time.time())
        if path is None:
            default = f"focus_guard_eventi_{datetime.now():%Y%m%d}.csv"
            chosen, _ = QFileDialog.getSaveFileName(self, "Esporta eventi", default, "CSV (*.csv)")
            if not chosen:
                return None
            path = Path(chosen)
        n = self._log.export_csv(path, lo, hi)
        if self.isVisible():
            QMessageBox.information(self, "Esporta CSV", f"Esportati {n} eventi in:\n{path}")
        return path

    # --- finestra ------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh_stats()
        self._stats_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._stats_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Chiudere la dashboard non chiude l'app: resta attiva nella tray
        event.ignore()
        self.hide()
