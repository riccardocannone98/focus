"""Icona nella system tray: dashboard, pausa/riprendi, ridefinisci area, esci."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

STATUS_COLORS = {
    "focused": "#43a047",
    "leaving": "#fb8c00",
    "distracted": "#e53935",
    "returning": "#e53935",
    "paused": "#9e9e9e",
    "stopped": "#9e9e9e",
    "uncalibrated": "#1e88e5",
    "error": "#6d4c41",
}


def make_icon(color: str) -> QIcon:
    """Icona "occhio" disegnata al volo: nessun file esterno."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(32, 32), 30, 30)
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(32, 32), 22, 13)
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(32, 32), 9, 9)
    p.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    pause_toggled = pyqtSignal(bool)  # True = pausa
    recalibrate_requested = pyqtSignal()
    dashboard_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._icons = {k: make_icon(c) for k, c in STATUS_COLORS.items()}
        menu = QMenu()
        self._status_action = QAction("Avvio...", menu, enabled=False)
        self._pause_action = QAction("Pausa", menu, checkable=True)
        self._pause_action.toggled.connect(self._on_pause_toggled)
        dashboard = QAction("Apri dashboard", menu)
        dashboard.triggered.connect(self.dashboard_requested)
        recalibrate = QAction("Ridefinisci area", menu)
        recalibrate.triggered.connect(self.recalibrate_requested)
        quit_action = QAction("Esci", menu)
        quit_action.triggered.connect(self.quit_requested)
        for item in (
            self._status_action, None, dashboard, self._pause_action, recalibrate, None, quit_action
        ):
            menu.addSeparator() if item is None else menu.addAction(item)
        self._menu = menu  # riferimento esplicito: evita la garbage collection
        self.setContextMenu(menu)
        self.set_status("uncalibrated", "Area da definire")
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.dashboard_requested.emit()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._pause_action.setText("Riprendi" if paused else "Pausa")
        self.pause_toggled.emit(paused)

    def set_paused(self, paused: bool) -> None:
        """Aggiorna la voce di menu senza riemettere il segnale."""
        self._pause_action.blockSignals(True)
        self._pause_action.setChecked(paused)
        self._pause_action.setText("Riprendi" if paused else "Pausa")
        self._pause_action.blockSignals(False)

    def set_status(self, key: str, text: str) -> None:
        self.setIcon(self._icons.get(key, self._icons["error"]))
        self._status_action.setText(f"Stato: {text}")
        self.setToolTip(f"Focus Guard – {text}")
