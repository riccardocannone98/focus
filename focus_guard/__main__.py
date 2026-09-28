"""Avvio: python -m focus_guard [--config PATH] [--define-area] [--no-dashboard] [-v]"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from focus_guard.config import DEFAULT_CONFIG_PATH, ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="focus_guard", description="Focus Guard")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument(
        "--define-area", "--calibrate", dest="define_area", action="store_true",
        help="apre subito la finestra di definizione dell'area",
    )
    parser.add_argument(
        "--no-dashboard", action="store_true", help="avvia solo nella tray, senza aprire la dashboard"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from focus_guard.app import FocusGuardApp

    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName("Focus Guard")
    qapp.setQuitOnLastWindowClosed(False)  # vive nella tray

    try:
        app = FocusGuardApp(args.config)
    except ConfigError as exc:
        logging.error("config.json non valido: %s", exc)
        return 2

    # Ctrl+C dal terminale: il timer restituisce periodicamente il controllo a Python
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer(interval=250, timeout=lambda: None)
    keepalive.start()

    app.start(show_dashboard=not args.no_dashboard, define_area=args.define_area)
    return qapp.exec()


if __name__ == "__main__":
    raise SystemExit(main())
