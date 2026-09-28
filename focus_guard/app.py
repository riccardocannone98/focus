"""Controller: collega webcam, logica, allarme, registro eventi e finestre."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from focus_guard.config import Config, load_config, save_config
from focus_guard.logic.area import AreaError, AreaModel, area_from_legacy_corners
from focus_guard.logic.episodes import EpisodeTracker
from focus_guard.logic.features import GazeSmoother
from focus_guard.logic.focus import FocusEvent, FocusMonitor, FocusState, Thresholds
from focus_guard.media import IMAGE_EXTENSIONS, MusicPlayer, RandomPicker
from focus_guard.stats.store import PAUSE, SESSION, EventLog
from focus_guard.ui.area_window import AreaWindow
from focus_guard.ui.dashboard import Dashboard, TrackingStatus
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

HEARTBEAT_MS = 30_000  # aggiornamento della fine di sessione/pausa aperta
CONFIG_SAVE_DEBOUNCE_MS = 800

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
        event_log: EventLog | None = None,
        wall_clock: Callable[[], float] = time.time,
        mono_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self.config_path = config_path
        self.cfg = load_config(config_path)
        self._worker_factory = worker_factory
        self._worker: CameraWorker | None = None
        self._now = wall_clock
        self._mono = mono_clock

        self.tracking = False
        self.paused = False
        self.paused_until: float | None = None
        self._session_id: int | None = None
        self._pause_id: int | None = None  # pausa esplicita o definizione area
        self._inside: bool | None = None
        self._face: bool | None = None
        self._last_state: FocusState | None = None

        self.monitor = FocusMonitor(self._thresholds())
        self.episodes = EpisodeTracker()
        self.smoother = GazeSmoother(self.cfg.smoothing_alpha)
        self.area = self._load_area()

        self.images = RandomPicker(self.cfg.resolve_path(self.cfg.images_dir), IMAGE_EXTENSIONS)
        self.music = music or MusicPlayer(
            self.cfg.resolve_path(self.cfg.music_dir), self.cfg.music_volume
        )
        self.overlay = AlertOverlay(self.cfg.overlay_opacity)
        self.event_log = event_log or EventLog(self.cfg.resolve_path(self.cfg.database_path))

        self.area_window: AreaWindow | None = None
        self.dashboard = Dashboard(self.event_log)
        self.dashboard.start_tracking.connect(self.start_tracking)
        self.dashboard.stop_tracking.connect(self.stop_tracking)
        self.dashboard.pause_for.connect(self.pause)
        self.dashboard.resume.connect(self.resume)
        self.dashboard.define_area.connect(self.open_area_window)
        self.dashboard.activation_delay_changed.connect(self.set_activation_delay)
        self.dashboard.exit_margin_changed.connect(self.set_exit_margin)
        self.dashboard.set_thresholds(
            self.cfg.activation_delay_s, self.cfg.exit_margin, self.cfg.reentry_margin
        )

        self.tray = TrayIcon()
        self.tray.pause_toggled.connect(self._on_tray_pause)
        self.tray.recalibrate_requested.connect(self.open_area_window)
        self.tray.dashboard_requested.connect(self.show_dashboard)
        self.tray.quit_requested.connect(self.quit)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            log.warning("System tray non disponibile: usa Ctrl+C nel terminale per uscire")

        self._heartbeat = QTimer(self, interval=HEARTBEAT_MS, timeout=self._touch_open_rows)
        self._resume_timer = QTimer(self, singleShot=True, timeout=self.resume)
        self._save_timer = QTimer(
            self, singleShot=True, interval=CONFIG_SAVE_DEBOUNCE_MS, timeout=self._save_config
        )

    # --- area -----------------------------------------------------------
    def _load_area(self) -> AreaModel | None:
        if self.cfg.area:
            try:
                return AreaModel.from_dict(self.cfg.area)
            except AreaError as exc:
                log.warning("Area salvata non valida: %s", exc)
                return None
        if self.cfg.calibration:
            try:
                area = area_from_legacy_corners(self.cfg.calibration, self.cfg.head_weight)
            except AreaError as exc:
                log.warning("Vecchia calibrazione non convertibile: %s", exc)
                return None
            self.cfg.area = area.to_dict()
            self.cfg.calibration = None
            save_config(self.cfg, self.config_path)
            log.info("Calibrazione a 4 angoli convertita nella nuova area rettangolare")
            return area
        return None

    def _thresholds(self) -> Thresholds:
        c = self.cfg
        return Thresholds(
            exit_margin=c.exit_margin,
            reentry_margin=c.reentry_margin,
            activation_delay_s=c.activation_delay_s,
            reentry_delay_s=c.reentry_delay_s,
            face_lost_counts_as_out=c.face_lost_counts_as_out,
        )

    # --- ciclo di vita ---------------------------------------------------
    def start(self, show_dashboard: bool = True, define_area: bool = False) -> None:
        if show_dashboard:
            self.show_dashboard()
        self.start_tracking()
        if self.area is None or define_area:
            self.open_area_window()

    def quit(self) -> None:
        if self.area_window is not None:
            self.area_window.cancel()
        self.stop_tracking()
        self._stop_camera()
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_config()
        self.music.close()
        self.event_log.close()
        self.tray.hide()
        QApplication.quit()

    def show_dashboard(self) -> None:
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()

    # --- sessione, pause ---------------------------------------------------
    def start_tracking(self) -> None:
        if self.tracking:
            return
        self.tracking = True
        self.paused = False
        self.paused_until = None
        self._session_id = self.event_log.begin(SESSION, self._now())
        if self.area_window is not None:
            self._begin_pause_row()  # definizione area in corso: non è tempo di lavoro
        self._heartbeat.start()
        self._reset_detection()
        self._sync_camera()
        self._push_status()

    def stop_tracking(self) -> None:
        if not self.tracking:
            return
        self._interrupt_detection()
        self._end_pause_row()
        self.event_log.finish(self._session_id, self._now())
        self._session_id = None
        self.tracking = False
        self.paused = False
        self.paused_until = None
        self._resume_timer.stop()
        self._heartbeat.stop()
        self._sync_camera()
        self._push_status()

    def pause(self, minutes: int | None = None) -> None:
        """Pausa; con minutes riprende da sola allo scadere."""
        if not self.tracking:
            return
        if not self.paused:
            self._interrupt_detection()
            self._begin_pause_row()
            self.paused = True
        if minutes:
            self.paused_until = self._now() + minutes * 60
            self._resume_timer.start(minutes * 60 * 1000)
        else:
            self.paused_until = None
            self._resume_timer.stop()
        self._sync_camera()
        self._push_status()

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        self.paused_until = None
        self._resume_timer.stop()
        if self.area_window is None:
            self._end_pause_row()
        self._reset_detection()
        self._sync_camera()
        self._push_status()

    def _on_tray_pause(self, paused: bool) -> None:
        if paused:
            if not self.tracking:
                self.start_tracking()
            self.pause()
        else:
            self.resume()

    def _begin_pause_row(self) -> None:
        if self._pause_id is None and self.tracking:
            self._pause_id = self.event_log.begin(PAUSE, self._now())

    def _end_pause_row(self) -> None:
        if self._pause_id is not None:
            self.event_log.finish(self._pause_id, self._now())
            self._pause_id = None

    def _touch_open_rows(self) -> None:
        now = self._now()
        for row in (self._session_id, self._pause_id):
            if row is not None:
                self.event_log.touch(row, now)

    @property
    def detecting(self) -> bool:
        return (
            self.tracking and not self.paused and self.area is not None and self.area_window is None
        )

    def _interrupt_detection(self) -> None:
        """Chiude l'episodio aperto e spegne l'allarme (pausa, stop, definizione area)."""
        self._log_episode(self.episodes.close(self._mono()))
        if self.monitor.reset() is FocusEvent.ALERT_OFF:
            self._set_alert(False)
        self._reset_detection()

    def _reset_detection(self) -> None:
        self.smoother.reset()
        self._inside = None
        self._face = None

    def _log_episode(self, episode) -> None:
        if episode is None:
            return
        offset = self._now() - self._mono()  # monotonic -> epoch
        self.event_log.add(episode.kind, episode.start + offset, episode.end + offset)
        if self.dashboard.isVisible():
            self.dashboard.refresh_stats()

    # --- webcam ----------------------------------------------------------
    def _sync_camera(self) -> None:
        needed = self.area_window is not None or (self.tracking and not self.paused)
        if needed:
            self._start_camera()
        else:
            self._stop_camera()

    def _start_camera(self) -> None:
        if self._worker is None:
            worker = self._worker_factory(self.cfg)
            worker.sample.connect(self.on_sample)
            worker.preview.connect(self._on_preview)
            worker.failed.connect(self._on_camera_failed)
            worker.finished.connect(self._on_worker_finished)
            self._worker = worker
            worker.start()
        self._worker.preview_enabled = self.area_window is not None

    def _stop_camera(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.preview_enabled = False
            worker.sample.disconnect(self.on_sample)
            worker.preview.disconnect(self._on_preview)
            worker.stop()
        self.smoother.reset()

    def _on_worker_finished(self) -> None:
        if self.sender() is self._worker:  # terminato da solo (errore)
            self._worker = None

    def _on_camera_failed(self, message: str) -> None:
        log.error("Webcam: %s", message)
        self._interrupt_detection()
        self.tray.set_status("error", "Errore webcam")
        self.tray.showMessage("Focus Guard", message, QSystemTrayIcon.MessageIcon.Critical)

    def _on_preview(self, rgb) -> None:
        if self.area_window is not None:
            self.area_window.on_preview(rgb)

    # --- elaborazione campioni --------------------------------------------
    def on_sample(self, sample: GazeSample) -> None:
        if self.area_window is not None:
            self.area_window.on_sample(sample)
            return
        if not self.detecting:
            return
        raw = self.smoother.update(sample.raw, sample.blinking)
        distance = self.area.distance(raw) if raw is not None else None
        prev = self.monitor.state
        event = self.monitor.update(sample.timestamp, distance)
        self._log_episode(self.episodes.observe(prev, self.monitor.state, sample.timestamp))
        if event is FocusEvent.ALERT_ON:
            self._set_alert(True)
        elif event is FocusEvent.ALERT_OFF:
            self._set_alert(False)

        inside = None if distance is None else distance <= 0
        face = sample.face_found
        if (inside, face, self.monitor.state) != (self._inside, self._face, self._last_state):
            self._inside, self._face = inside, face
            self._push_status()

    def _set_alert(self, active: bool) -> None:
        if active:
            self.overlay.show_alert(self.images.pick(), self.cfg.banner_text)
            self.music.play()
        else:
            self.music.stop()  # prima l'audio: stop immediato
            self.overlay.hide_alert()

    # --- stato verso dashboard e tray ---------------------------------------
    def status(self) -> TrackingStatus:
        return TrackingStatus(
            tracking=self.tracking,
            paused=self.paused,
            paused_until=self.paused_until,
            inside=self._inside,
            face=self._face,
            area_defined=self.area is not None,
        )

    def _push_status(self) -> None:
        self._last_state = self.monitor.state
        self.dashboard.set_status(self.status())
        self.tray.set_paused(self.paused)
        if not self.tracking:
            self.tray.set_status("stopped", "Tracking fermo")
        elif self.paused:
            self.tray.set_status("paused", "In pausa")
        elif self.area is None:
            self.tray.set_status("uncalibrated", "Area da definire")
        else:
            self.tray.set_status(self.monitor.state.value, STATE_LABELS[self.monitor.state])

    # --- soglie dal pannello di controllo ----------------------------------
    def set_activation_delay(self, seconds: float) -> None:
        self.cfg.activation_delay_s = seconds
        self.monitor.thresholds = self._thresholds()
        self._save_timer.start()

    def set_exit_margin(self, margin: float) -> None:
        self.cfg.exit_margin = max(margin, self.cfg.reentry_margin)
        self.monitor.thresholds = self._thresholds()
        if self.area_window is not None:
            self.area_window.map.exit_margin = self.cfg.exit_margin
        self._save_timer.start()

    def _save_config(self) -> None:
        save_config(self.cfg, self.config_path)

    # --- definizione area ------------------------------------------------
    def open_area_window(self) -> None:
        if self.area_window is not None:
            self.area_window.raise_()
            self.area_window.activateWindow()
            return
        if self.tracking and not self.paused:
            self._interrupt_detection()
            self._begin_pause_row()
        c = self.cfg
        window = AreaWindow(
            recording_seconds=c.recording_seconds,
            percentiles=(c.outlier_percentiles[0], c.outlier_percentiles[1]),
            head_weight=c.head_weight,
            exit_margin=c.exit_margin,
            smoothing_alpha=c.smoothing_alpha,
            current=self.area,
        )
        window.finished.connect(self._on_area_finished)
        self.area_window = window
        self._sync_camera()
        window.show()
        window.raise_()
        window.activateWindow()
        self._push_status()

    def _on_area_finished(self, area: AreaModel | None) -> None:
        self.area_window = None
        if area is not None:
            self.area = area
            self.cfg.area = area.to_dict()
            self.cfg.calibration = None
            save_config(self.cfg, self.config_path)
            log.info("Area salvata in %s", self.config_path)
        if not self.paused:
            self._end_pause_row()
        self.monitor.reset()
        self._reset_detection()
        self._sync_camera()
        if self.area is None:
            self.tray.showMessage(
                "Focus Guard",
                "Area da definire: usa 'Ridefinisci area' dalla dashboard o dalla tray.",
                QSystemTrayIcon.MessageIcon.Warning,
            )
        self._push_status()
