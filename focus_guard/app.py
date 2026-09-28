"""Controller: collega webcam, logica, allarme, calibrazione e tray."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from focus_guard.config import Config, load_config, save_config
from focus_guard.logic.features import GazeSmoother
from focus_guard.logic.focus import FocusEvent, FocusMonitor, FocusState, Thresholds
from focus_guard.logic.geometry import CalibrationError, CalibrationModel
from focus_guard.media import IMAGE_EXTENSIONS, MusicPlayer, RandomPicker
from focus_guard.ui.calibration import CalibrationWindow
from focus_guard.ui.overlay import AlertOverlay
from focus_guard.ui.tray import TrayIcon
from focus_guard.vision.tracker import CameraWorker, GazeSample

log = logging.getLogger(__name__)

STATE_LABELS = {
    FocusState.FOCUSED: "Concentrato",
    FocusState.LEAVING: "Sguardo fuori area...",
    FocusState.DISTRACTED: "Distratto",
    FocusState.RETURNING: "Rientro in corso",
}

WorkerFactory = Callable[[Config], CameraWorker]


def default_worker_factory(cfg: Config) -> CameraWorker:
    return CameraWorker(
        camera_index=cfg.camera_index,
        frame_size=(cfg.frame_width, cfg.frame_height),
        target_fps=cfg.target_fps,
        model_path=cfg.resolve_path(cfg.model_path),
        blink_threshold=cfg.blink_threshold,
    )


class FocusGuardApp(QObject):
    def __init__(
        self,
        config_path: Path,
        worker_factory: WorkerFactory = default_worker_factory,
        music: MusicPlayer | None = None,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self._worker_factory = worker_factory
        self._worker: CameraWorker | None = None
        self._calibration: CalibrationWindow | None = None
        self.paused = False

        self.monitor = FocusMonitor(
            Thresholds(
                exit_margin=self.cfg.exit_margin,
                reentry_margin=self.cfg.reentry_margin,
                activation_delay_s=self.cfg.activation_delay_s,
                reentry_delay_s=self.cfg.reentry_delay_s,
                face_lost_counts_as_out=self.cfg.face_lost_counts_as_out,
            )
        )
        self.smoother = GazeSmoother(self.cfg.smoothing_alpha)
        self.model = self._build_model(self.cfg.calibration)

        self.images = RandomPicker(self.cfg.resolve_path(self.cfg.images_dir), IMAGE_EXTENSIONS)
        self.music = music or MusicPlayer(
            self.cfg.resolve_path(self.cfg.music_dir), self.cfg.music_volume
        )
        self.overlay = AlertOverlay(self.cfg.overlay_opacity)

        self.tray = TrayIcon()
        self.tray.pause_toggled.connect(self.set_paused)
        self.tray.recalibrate_requested.connect(self.start_calibration)
        self.tray.quit_requested.connect(self.quit)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            log.warning("System tray non disponibile: usa Ctrl+C nel terminale per uscire")
        self._last_state: FocusState | None = None

    # --- ciclo di vita ---------------------------------------------------
    def start(self, force_calibration: bool = False) -> None:
        self._start_camera()
        if self.model is None or force_calibration:
            self.start_calibration()
        else:
            self._refresh_status()

    def quit(self) -> None:
        self._set_alert(False)
        self._stop_camera()
        self.music.close()
        self.tray.hide()
        QApplication.quit()

    def _build_model(self, corners) -> CalibrationModel | None:
        if not corners:
            return None
        try:
            return CalibrationModel.from_corners(corners, self.cfg.head_weight)
        except CalibrationError as exc:
            log.warning("Calibrazione salvata non valida: %s", exc)
            return None

    # --- webcam ----------------------------------------------------------
    def _start_camera(self) -> None:
        if self._worker is not None:
            return
        worker = self._worker_factory(self.cfg)
        worker.sample.connect(self.on_sample)
        worker.failed.connect(self._on_camera_failed)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        worker.start()

    def _stop_camera(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.sample.disconnect(self.on_sample)
            worker.stop()
        self.smoother.reset()

    def _on_worker_finished(self) -> None:
        if self.sender() is self._worker:  # terminato da solo (errore)
            self._worker = None

    def _on_camera_failed(self, message: str) -> None:
        log.error("Webcam: %s", message)
        self._set_alert(False)
        self.monitor.reset()
        self.tray.set_status("error", "Errore webcam")
        self.tray.showMessage("Focus Guard", message, QSystemTrayIcon.MessageIcon.Critical)

    # --- elaborazione campioni --------------------------------------------
    def on_sample(self, sample: GazeSample) -> None:
        if self._calibration is not None:
            self._calibration.on_sample(sample)
            return
        if self.paused or self.model is None:
            return
        raw = self.smoother.update(sample.raw, sample.blinking)
        distance = self.model.distance(raw) if raw is not None else None
        event = self.monitor.update(sample.timestamp, distance)
        if event is FocusEvent.ALERT_ON:
            self._set_alert(True)
        elif event is FocusEvent.ALERT_OFF:
            self._set_alert(False)
        if self.monitor.state is not self._last_state:
            self._refresh_status()

    def _set_alert(self, active: bool) -> None:
        if active:
            self.overlay.show_alert(self.images.pick(), self.cfg.banner_text)
            self.music.play()
        else:
            self.music.stop()  # prima l'audio: stop immediato
            self.overlay.hide_alert()

    def _refresh_status(self) -> None:
        self._last_state = self.monitor.state
        if self.paused:
            self.tray.set_status("paused", "In pausa")
        elif self.model is None:
            self.tray.set_status("uncalibrated", "Da calibrare")
        else:
            self.tray.set_status(self.monitor.state.value, STATE_LABELS[self.monitor.state])

    # --- comandi dalla tray -----------------------------------------------
    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.tray.set_paused(paused)
        if paused:
            if self.monitor.reset() is FocusEvent.ALERT_OFF:
                self._set_alert(False)
            self._stop_camera()  # webcam spenta durante la pausa
        else:
            self._start_camera()
        self._refresh_status()

    def start_calibration(self) -> None:
        if self._calibration is not None:
            self._calibration.activateWindow()
            return
        if self.paused:
            self.set_paused(False)
        if self.monitor.reset() is FocusEvent.ALERT_OFF:
            self._set_alert(False)
        self._start_camera()
        window = CalibrationWindow(self.cfg.head_weight, self.cfg.smoothing_alpha)
        window.finished.connect(self._on_calibration_finished)
        self._calibration = window
        window.showFullScreen()
        window.activateWindow()

    def _on_calibration_finished(self, corners) -> None:
        self._calibration = None
        if corners:
            model = self._build_model(corners)
            if model is not None:
                self.cfg.calibration = corners
                save_config(self.cfg, self.config_path)
                self.model = model
                log.info("Calibrazione salvata in %s", self.config_path)
        self.smoother.reset()
        self.monitor.reset()
        if self.model is None:
            self.tray.showMessage(
                "Focus Guard",
                "Calibrazione necessaria: usa 'Ricalibra' dal menu della tray.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        self._refresh_status()
