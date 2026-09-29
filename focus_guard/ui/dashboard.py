"""Dashboard: barra laterale, pannello di controllo, KPI, grafici, impostazioni.

La finestra non contiene logica di tracking: emette segnali verso il
controller e mostra lo stato che il controller le passa. I KPI sono
calcolati dal registro eventi locale.

Stile: barra laterale e card Fluent, KPI in stile minimale (numeri grandi e
leggeri separati da filetti), colori dal tema in `ui/theme.py`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from focus_guard.stats.kpi import (
    compare,
    compute_kpis,
    distractions_by_hour,
    focus_rate_by_day,
    period_bounds,
    previous_bounds,
)
from focus_guard.stats.store import EventLog
from focus_guard.ui.charts import DistractionsByHourChart, FocusRateByDayChart
from focus_guard.ui.icons import app_icon, render_mark
from focus_guard.ui.theme import (
    BODY,
    CAPTION,
    DARK,
    LIGHT,
    S1,
    S2,
    S3,
    S4,
    S5,
    SUBTITLE,
    TITLE,
    theme,
)
from focus_guard.ui.widgets import (
    Card,
    Divider,
    IconLabel,
    KpiTile,
    NavItem,
    SegmentedControl,
    StatusPill,
    ToggleSwitch,
    button,
    set_role,
    text_label,
)

PERIOD_LABELS = {"today": "Oggi", "7d": "7 giorni", "30d": "30 giorni"}
PAUSE_MINUTES = (15, 30, 60)
DELAY_STEP_S = 0.5
DELAY_RANGE_S = (0.5, 10.0)
MARGIN_RANGE_PCT = (0, 50)
STATS_REFRESH_MS = 30_000
SIDEBAR_WIDTH = 232  # 29 × 8 px
HALF_GAP = 4

WEEKDAYS = ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica")
MONTHS = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre")
MINUS = "−"


@dataclass(frozen=True)
class TrackingStatus:
    tracking: bool = False
    paused: bool = False
    paused_until: float | None = None  # epoch; None = pausa senza scadenza
    inside: bool | None = None  # None = sconosciuto (volto assente, tracking fermo)
    face: bool | None = None
    area_defined: bool = False
    alert: bool = False  # allarme attivo (distrazione in corso)


def fmt(value: float | None, decimals: int = 1) -> str:
    """Numero in formato italiano; trattino se non disponibile."""
    if value is None:
        return "—"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_signed(value: float, decimals: int, suffix: str = "") -> str:
    sign = "+" if value > 0 else (MINUS if value < 0 else "±")
    return f"{sign}{fmt(abs(value), decimals)}{suffix}"


def _delta_pct_or_abs(d, unit: str, decimals: int) -> str:
    if d.relative is not None:
        return fmt_signed(d.relative * 100, 0, " %")
    return fmt_signed(d.diff, decimals, f" {unit}")


# chiave, icona, etichetta, unità, formattatore valore, più alto è meglio, formattatore variazione
KPI_SPEC = (
    ("active_min", "time", "Tempo di sessione attiva", "min",
     lambda k: fmt(k.active_min, 0), True, lambda d: _delta_pct_or_abs(d, "min", 0)),
    ("focus_rate_pct", "focus", "Tasso di focus", "%",
     lambda k: fmt(k.focus_rate_pct, 1), True, lambda d: fmt_signed(d.diff, 1, " pt")),
    ("distractions", "distraction", "N. distrazioni", "n",
     lambda k: str(k.distractions), False, lambda d: fmt_signed(d.diff, 0)),
    ("glances", "glance", "N. sguardi fuori senza allarme", "n",
     lambda k: str(k.glances), False, lambda d: fmt_signed(d.diff, 0)),
    ("avg_distraction_s", "avg", "Durata media distrazione", "s",
     lambda k: fmt(k.avg_distraction_s, 1), False, lambda d: fmt_signed(d.diff, 1, " s")),
    ("max_distraction_s", "max", "Distrazione più lunga", "s",
     lambda k: fmt(k.max_distraction_s, 1), False, lambda d: fmt_signed(d.diff, 1, " s")),
    ("longest_streak_min", "streak", "Striscia di focus più lunga", "min",
     lambda k: fmt(k.longest_streak_min, 1), True, lambda d: fmt_signed(d.diff, 1, " min")),
    ("distractions_per_hour", "rate", "Distrazioni per ora di sessione", "n/h",
     lambda k: fmt(k.distractions_per_hour, 2), False, lambda d: fmt_signed(d.diff, 2)),
)


def italian_date(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


class Dashboard(QMainWindow):
    start_tracking = pyqtSignal()
    stop_tracking = pyqtSignal()
    pause_for = pyqtSignal(int)  # minuti
    resume = pyqtSignal()
    define_area = pyqtSignal()
    activation_delay_changed = pyqtSignal(float)  # secondi
    exit_margin_changed = pyqtSignal(float)  # frazione del lato area
    theme_toggled = pyqtSignal(str)  # "dark" | "light"

    def __init__(self, event_log: EventLog) -> None:
        super().__init__()
        self.setWindowTitle("Focus Guard")
        self.setWindowIcon(app_icon())
        self.resize(1360, 900)
        self.setMinimumSize(1040, 680)
        self._log = event_log
        self._status = TrackingStatus()

        central = QWidget()
        central.setObjectName("window")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._scroll(self._build_dashboard_page()))
        self.pages.addWidget(self._scroll(self._build_settings_page()))
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        self._stats_timer = QTimer(self, interval=STATS_REFRESH_MS, timeout=self.refresh_stats)
        theme.changed.connect(self._on_theme)
        self._on_theme(theme.tokens)
        self.set_status(self._status)

    # --- struttura ---------------------------------------------------------
    def _scroll(self, page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def _build_sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(SIDEBAR_WIDTH)
        self._sidebar = side
        lay = QVBoxLayout(side)
        lay.setContentsMargins(S1, S2, S1, S2)
        lay.setSpacing(HALF_GAP)

        brand = QHBoxLayout()
        brand.setContentsMargins(S2 - S1 + 4, 0, 0, S2)
        logo = QLabel()
        logo.setPixmap(render_mark(28))
        brand.addWidget(logo)
        brand.addSpacing(S1 + HALF_GAP)
        brand.addWidget(text_label("Focus Guard", 15, 600))
        brand.addStretch(1)
        lay.addLayout(brand)

        self.nav_dashboard = NavItem("dashboard", "Dashboard")
        self.nav_area = NavItem("area", "Definisci area")
        self.nav_settings = NavItem("settings", "Impostazioni")
        self.nav_dashboard.setChecked(True)
        self.nav_dashboard.clicked.connect(lambda: self.show_page(0))
        self.nav_settings.clicked.connect(lambda: self.show_page(1))
        self.nav_area.clicked.connect(self._on_nav_area)
        for item in (self.nav_dashboard, self.nav_area, self.nav_settings):
            lay.addWidget(item)
        lay.addStretch(1)

        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(S2 - S1 + 4, 0, S1, 0)
        self._theme_icon = IconLabel("moon", 18, "text2")
        theme_row.addWidget(self._theme_icon)
        theme_row.addSpacing(S1 + HALF_GAP)
        theme_row.addWidget(text_label("Tema scuro", 13, 400, "text2"))
        theme_row.addStretch(1)
        self.theme_switch = ToggleSwitch(theme.is_dark)
        self.theme_switch.setToolTip("Tema scuro / chiaro")
        self.theme_switch.toggled.connect(self._on_theme_switch)
        theme_row.addWidget(self.theme_switch)
        lay.addLayout(theme_row)
        return side

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_dashboard.setChecked(index == 0)
        self.nav_settings.setChecked(index == 1)
        self.nav_area.setChecked(False)

    def _on_nav_area(self) -> None:
        self.nav_area.setChecked(False)
        self.define_area.emit()

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(S4, S3, S4, S3)
        lay.setSpacing(S2)
        return page, lay

    # --- pagina Dashboard ------------------------------------------------------
    def _build_dashboard_page(self) -> QWidget:
        page, lay = self._page()

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(text_label("Dashboard", TITLE, 600, display=True))
        self.subtitle = text_label("", 13, 400, "text2")
        titles.addWidget(self.subtitle)
        head.addLayout(titles)
        head.addStretch(1)
        self.status_pill = StatusPill()
        head.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addSpacing(S3)
        head.addWidget(text_label("Tracking", 13, 600, "text2"))
        head.addSpacing(S1)
        self.toggle_button = ToggleSwitch()
        self.toggle_button.clicked.connect(self._on_toggle)
        head.addWidget(self.toggle_button)
        lay.addLayout(head)

        live = QHBoxLayout()
        live.setSpacing(S1)
        self._live_labels = {}
        for key, icon_name, caption in (
            ("gaze", "eye", "Sguardo"), ("face", "face", "Volto rilevato"), ("area", "area", "Area"),
        ):
            live.addWidget(IconLabel(icon_name, 14, "text3"))
            live.addWidget(text_label(f"{caption}:", CAPTION, 400, "text3"))
            value = text_label("—", CAPTION, 600, "text2")
            self._live_labels[key] = value
            live.addWidget(value)
            live.addSpacing(S2)
        live.addStretch(1)
        lay.addLayout(live)
        self.gaze_label = self._live_labels["gaze"]
        self.face_label = self._live_labels["face"]
        self.area_label = self._live_labels["area"]

        lay.addWidget(self._build_controls())

        stats_head = QHBoxLayout()
        stats_head.addWidget(text_label("Statistiche", SUBTITLE, 600, display=True))
        stats_head.addSpacing(S2)
        self.period_control = SegmentedControl(PERIOD_LABELS, "today")
        self.period_control.changed.connect(lambda _k: self.refresh_stats())
        stats_head.addWidget(self.period_control)
        stats_head.addStretch(1)
        self.updated_label = text_label("", CAPTION, 400, "text3")
        stats_head.addWidget(self.updated_label)
        stats_head.addSpacing(S1)
        export = button("Esporta CSV", "export")
        export.clicked.connect(lambda: self.export_csv())
        stats_head.addWidget(export)
        lay.addSpacing(S1)
        lay.addLayout(stats_head)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(0)
        tiles.setVerticalSpacing(0)
        self.tiles: dict[str, KpiTile] = {}
        for i, (key, icon_name, label, unit, *_rest) in enumerate(KPI_SPEC):
            tile = KpiTile(icon_name, label, unit)
            self.tiles[key] = tile
            tiles.addWidget(tile, 2 * (i // 4), i % 4)
        for col in range(4):
            tiles.addWidget(Divider(), 1, col)
        tiles_box = QVBoxLayout()
        tiles_box.setSpacing(0)
        tiles_box.addWidget(Divider())
        tiles_box.addLayout(tiles)
        tiles_box.addWidget(Divider())
        lay.addLayout(tiles_box)

        charts = QHBoxLayout()
        charts.setSpacing(S2)
        self.hour_chart = DistractionsByHourChart()
        self.day_chart = FocusRateByDayChart()
        for title, chart in (
            ("Distrazioni per fascia oraria [n]", self.hour_chart),
            ("Tasso di focus per giorno [%]", self.day_chart),
        ):
            card = Card()
            card.body.addWidget(text_label(title, BODY, 600))
            card.body.addWidget(chart, 1)
            chart.setMinimumHeight(240)
            charts.addWidget(card)
        lay.addLayout(charts, 1)
        return page

    def _build_controls(self) -> Card:
        card = Card()
        card.body.setSpacing(S2)
        actions = QHBoxLayout()
        actions.setSpacing(S1)
        self.pause_buttons = []
        for minutes in PAUSE_MINUTES:
            b = button(f"Pausa {minutes} min", "pause")
            b.clicked.connect(lambda _=False, m=minutes: self.pause_for.emit(m))
            actions.addWidget(b)
            self.pause_buttons.append(b)
        self.resume_button = button("Riprendi", "play")
        self.resume_button.clicked.connect(self.resume)
        actions.addWidget(self.resume_button)
        actions.addStretch(1)
        self.area_button = button("Ridefinisci area", "area", "primary")
        self.area_button.clicked.connect(self.define_area)
        actions.addWidget(self.area_button)
        card.body.addLayout(actions)
        card.body.addWidget(Divider())

        sliders = QHBoxLayout()
        sliders.setSpacing(S4)
        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
        self.delay_slider.setRange(int(DELAY_RANGE_S[0] / DELAY_STEP_S), int(DELAY_RANGE_S[1] / DELAY_STEP_S))
        self.delay_slider.valueChanged.connect(self._on_delay)
        self.margin_slider = QSlider(Qt.Orientation.Horizontal)
        self.margin_slider.setRange(*MARGIN_RANGE_PCT)
        self.margin_slider.valueChanged.connect(self._on_margin)
        self.delay_value = text_label("", CAPTION, 600)
        self.margin_value = text_label("", CAPTION, 600)
        for caption, slider, value in (
            ("Ritardo di attivazione [s]", self.delay_slider, self.delay_value),
            ("Margine di uscita [% lato area]", self.margin_slider, self.margin_value),
        ):
            row = QHBoxLayout()
            row.setSpacing(S2)
            slider.setMinimumWidth(120)
            slider.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(text_label(caption, CAPTION, 400, "text2"))
            row.addWidget(slider, 1)
            value.setMinimumWidth(S5 + S1)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(value)
            sliders.addLayout(row, 1)
        card.body.addLayout(sliders)
        return card

    # --- pagina Impostazioni ---------------------------------------------------
    def _build_settings_page(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(text_label("Impostazioni", TITLE, 600, display=True))
        lay.addWidget(text_label("Ritardo e margine si regolano dalla Dashboard; il resto è in config.json.",
                                 13, 400, "text2"))
        lay.addSpacing(S1)

        appearance = self._settings_card("palette", "Aspetto")
        row = QHBoxLayout()
        row.addWidget(text_label("Tema scuro", BODY))
        row.addStretch(1)
        self.settings_theme_switch = ToggleSwitch(theme.is_dark)
        self.settings_theme_switch.toggled.connect(self._on_theme_switch)
        row.addWidget(self.settings_theme_switch)
        appearance.body.addLayout(row)
        lay.addWidget(appearance)

        detection = self._settings_card("tune", "Rilevamento")
        self._info_labels: dict[str, QLabel] = {}
        for key, caption in (
            ("activation", "Ritardo di attivazione [s]"),
            ("exit", "Margine di uscita [% lato area]"),
            ("reentry", "Margine di rientro [% lato area]"),
            ("reentry_delay", "Ritardo di rientro [s]"),
            ("face_lost", "Volto non visibile"),
            ("recording", "Durata registrazione area [s]"),
        ):
            detection.body.addLayout(self._info_row(key, caption))
        lay.addWidget(detection)

        data = self._settings_card("shield", "Dati e privacy")
        for key, caption in (("config", "Configurazione"), ("database", "Registro eventi")):
            data.body.addLayout(self._info_row(key, caption))
        note = text_label(
            "Tutto resta su questo computer: nessun frame viene salvato né inviato in rete. "
            "Il registro contiene solo tipo di evento, inizio e fine.", 13, 400, "text2")
        note.setWordWrap(True)
        data.body.addWidget(note)
        self.open_folder_button = button("Apri cartella dati", "folder")
        self.open_folder_button.clicked.connect(self._open_data_folder)
        data.body.addWidget(self.open_folder_button, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(data)
        lay.addStretch(1)
        self._data_folder: Path | None = None
        return page

    def _settings_card(self, icon_name: str, title: str) -> Card:
        card = Card(S3)
        head = QHBoxLayout()
        head.addWidget(IconLabel(icon_name, 20, "accent"))
        head.addSpacing(S1)
        head.addWidget(text_label(title, 16, 600))
        head.addStretch(1)
        card.body.addLayout(head)
        card.body.addSpacing(S1)
        return card

    def _info_row(self, key: str, caption: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(text_label(caption, BODY, 400, "text2"))
        row.addStretch(1)
        value = text_label("—", BODY, 600)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._info_labels[key] = value
        row.addWidget(value)
        return row

    def set_info(self, info: dict[str, str], data_folder: Path | None = None) -> None:
        """Valori mostrati nella pagina Impostazioni (sola lettura)."""
        for key, value in info.items():
            if key in self._info_labels:
                self._info_labels[key].setText(value)
        self._data_folder = data_folder

    def _open_data_folder(self) -> None:
        if self._data_folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._data_folder)))

    # --- tema --------------------------------------------------------------------
    def _on_theme_switch(self, dark: bool) -> None:
        self.theme_toggled.emit(DARK if dark else LIGHT)

    def _on_theme(self, t) -> None:
        for switch in (self.theme_switch, self.settings_theme_switch):
            switch.set_checked_silently(t.mode == DARK)
        self._theme_icon.set_icon("moon" if t.mode == DARK else "sun")
        self._sidebar.setStyleSheet(f"QFrame#sidebar {{ background: {t.sidebar}; }}")

    # --- pannello di controllo ----------------------------------------------------
    def _on_toggle(self) -> None:
        (self.stop_tracking if self._status.tracking else self.start_tracking).emit()

    def _on_delay(self, steps: int) -> None:
        seconds = steps * DELAY_STEP_S
        self.delay_value.setText(f"{fmt(seconds, 1)} s")
        self._info_labels["activation"].setText(fmt(seconds, 1))
        self.activation_delay_changed.emit(seconds)

    def _on_margin(self, pct: int) -> None:
        self.margin_value.setText(f"{pct} %")
        self._info_labels["exit"].setText(str(pct))
        self.exit_margin_changed.emit(pct / 100)

    def set_thresholds(self, activation_delay_s: float, exit_margin: float, min_margin: float = 0.0) -> None:
        """Aggiorna i cursori senza riemettere i segnali."""
        for slider in (self.delay_slider, self.margin_slider):
            slider.blockSignals(True)
        low = max(MARGIN_RANGE_PCT[0], int(round(min_margin * 100 + 0.4999)))
        self.margin_slider.setMinimum(low)
        self.delay_slider.setValue(int(round(activation_delay_s / DELAY_STEP_S)))
        self.margin_slider.setValue(int(round(exit_margin * 100)))
        delay = self.delay_slider.value() * DELAY_STEP_S
        self.delay_value.setText(f"{fmt(delay, 1)} s")
        self.margin_value.setText(f"{self.margin_slider.value()} %")
        self._info_labels["activation"].setText(fmt(delay, 1))
        self._info_labels["exit"].setText(str(self.margin_slider.value()))
        for slider in (self.delay_slider, self.margin_slider):
            slider.blockSignals(False)

    def set_status(self, status: TrackingStatus) -> None:
        self._status = status
        live = status.tracking and not status.paused
        if not status.tracking:
            key, sub = "stopped", "webcam spenta"
        elif status.paused:
            key = "paused"
            sub = (f"fino alle {datetime.fromtimestamp(status.paused_until):%H:%M}"
                   if status.paused_until else "fino a nuovo ordine")
        elif not status.area_defined:
            key, sub = "no_area", ""
        elif status.alert:
            key, sub = "distracted", "sguardo fuori area"
        elif status.inside is False:
            key, sub = "leaving", ""
        else:
            key = "focus"
            sub = "volto non rilevato" if status.face is False else ""
        self.status_pill.set_state(key, sub)

        if not live or status.inside is None:
            self.gaze_label.setText("—")
            set_role(self.gaze_label, "text2")
        else:
            self.gaze_label.setText("dentro l'area" if status.inside else "fuori area")
            set_role(self.gaze_label, "good" if status.inside else "bad")
        self.face_label.setText("—" if not live or status.face is None else ("sì" if status.face else "no"))
        self.area_label.setText("definita" if status.area_defined else "da definire")
        set_role(self.area_label, "text2" if status.area_defined else "accent")

        self.toggle_button.set_checked_silently(status.tracking)
        self.toggle_button.setText("Ferma tracking" if status.tracking else "Avvia tracking")
        self.toggle_button.setToolTip(self.toggle_button.text())
        for b in self.pause_buttons:
            b.setEnabled(status.tracking)
        self.resume_button.setEnabled(status.tracking and status.paused)

    # --- statistiche -----------------------------------------------------------------
    @property
    def period(self) -> str:
        return self.period_control.current

    def refresh_stats(self) -> None:
        now = time.time()
        lo, hi = period_bounds(self.period, now)
        events = self._log.query(lo, hi)
        kpis = compute_kpis(events, lo, hi)
        plo, phi = previous_bounds(self.period, now)
        previous = compute_kpis(self._log.query(plo, phi), plo, phi)
        for key, _icon, _label, _unit, formatter, higher_is_better, delta_fmt in KPI_SPEC:
            tile = self.tiles[key]
            tile.set(formatter(kpis))
            delta = compare(getattr(kpis, key), getattr(previous, key), higher_is_better)
            if delta.diff is None:
                tile.set_delta("", "none", "text3", "nessun confronto con il periodo prec.")
            elif delta.improved is None:
                tile.set_delta("invariato", "flat", "text3", "vs periodo prec.")
            else:
                tile.set_delta(delta_fmt(delta), "up" if delta.diff > 0 else "down",
                               "good" if delta.improved else "bad")
        self.hour_chart.plot(distractions_by_hour(events, lo, hi))
        self.day_chart.plot(focus_rate_by_day(events, lo, hi))
        self.updated_label.setText(f"aggiornato alle {datetime.now():%H:%M}")
        self.subtitle.setText(italian_date(now))
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

    # --- finestra -----------------------------------------------------------------------
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
