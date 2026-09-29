"""Icona nella system tray: dashboard, pausa/riprendi, ridefinisci area, esci."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from focus_guard.ui.icons import TRAY_STATES, tray_icon
from focus_guard.ui.theme import theme
from focus_guard.ui.widgets import icon


class TrayIcon(QSystemTrayIcon):
    pause_toggled = pyqtSignal(bool)  # True = pausa
    recalibrate_requested = pyqtSignal()
    dashboard_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._icons = {k: tray_icon(k) for k in TRAY_STATES}
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
        self._menu_icons = {
            dashboard: "dashboard", self._pause_action: "pause", recalibrate: "area", quit_action: "close",
        }
        self._refresh_menu_icons()
        theme.changed.connect(self._refresh_menu_icons)
        self.setContextMenu(menu)
        self.set_status("uncalibrated", "Area da definire")
        self.activated.connect(self._on_activated)

    def _refresh_menu_icons(self, *_) -> None:
        for action, name in self._menu_icons.items():
            if action is self._pause_action and action.isChecked():
                name = "play"
            action.setIcon(icon(name, theme.tokens.text2))

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.dashboard_requested.emit()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._pause_action.setText("Riprendi" if paused else "Pausa")
        self._refresh_menu_icons()
        self.pause_toggled.emit(paused)

    def set_paused(self, paused: bool) -> None:
        """Aggiorna la voce di menu senza riemettere il segnale."""
        self._pause_action.blockSignals(True)
        self._pause_action.setChecked(paused)
        self._pause_action.setText("Riprendi" if paused else "Pausa")
        self._pause_action.blockSignals(False)
        self._refresh_menu_icons()

    def set_status(self, key: str, text: str) -> None:
        self.setIcon(self._icons.get(key, self._icons["error"]))
        self._status_action.setText(f"Stato: {text}")
        self.setToolTip(f"Focus Guard – {text}")
