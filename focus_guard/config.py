"""Configurazione persistente in config.json.

Contiene sia i parametri modificabili a mano sia la calibrazione salvata
(valori grezzi dello sguardo misurati ai 4 angoli dell'area).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

CORNER_NAMES = ("top_left", "top_right", "bottom_right", "bottom_left")


class ConfigError(ValueError):
    """Valore di configurazione non valido."""


@dataclass
class Config:
    # Webcam
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    target_fps: float = 15.0

    # Modello MediaPipe (percorso relativo alla cartella del progetto)
    model_path: str = "models/face_landmarker.task"

    # Stima dello sguardo
    head_weight: float = 0.007  # peso della rotazione testa (per grado) rispetto all'iride
    smoothing_alpha: float = 0.35  # EMA: 1 = nessuno smoothing
    blink_threshold: float = 0.5  # score blendshape oltre il quale l'occhio è chiuso

    # Soglie (unità = frazione del lato dell'area; >0 fuori, <0 dentro)
    exit_margin: float = 0.10
    reentry_margin: float = 0.0
    activation_delay_s: float = 2.0
    reentry_delay_s: float = 0.0
    face_lost_counts_as_out: bool = True

    # Allarme
    images_dir: str = "assets/images"
    music_dir: str = "assets/music"
    music_volume: float = 0.6
    banner_text: str = "Torna a concentrarti!"
    overlay_opacity: float = 0.6

    # Definizione dell'area (registrazione libera + ritocco)
    recording_seconds: float = 20.0
    outlier_percentiles: list[float] = field(default_factory=lambda: [5.0, 95.0])

    # Registro eventi (solo tempi, mai immagini)
    database_path: str = "data/focus_guard.db"

    # Area di lavoro sulla mappa dello sguardo (scritta dalla finestra "Definisci area")
    area: dict[str, float] | None = field(default=None)

    # Vecchia calibrazione a 4 angoli: letta solo per migrarla in "area"
    calibration: dict[str, list[float]] | None = field(default=None)

    def validate(self) -> None:
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise ConfigError("frame_width e frame_height devono essere > 0")
        if self.target_fps <= 0:
            raise ConfigError("target_fps deve essere > 0")
        if not 0.0 < self.smoothing_alpha <= 1.0:
            raise ConfigError("smoothing_alpha deve essere in (0, 1]")
        if self.head_weight < 0:
            raise ConfigError("head_weight deve essere >= 0")
        if self.activation_delay_s < 0 or self.reentry_delay_s < 0:
            raise ConfigError("i ritardi devono essere >= 0")
        if self.reentry_margin > self.exit_margin:
            raise ConfigError(
                "reentry_margin deve essere <= exit_margin (isteresi al rientro)"
            )
        if not 0.0 <= self.music_volume <= 1.0:
            raise ConfigError("music_volume deve essere in [0, 1]")
        if not 0.0 <= self.overlay_opacity <= 1.0:
            raise ConfigError("overlay_opacity deve essere in [0, 1]")
        if self.recording_seconds <= 0:
            raise ConfigError("recording_seconds deve essere > 0")
        if len(self.outlier_percentiles) != 2 or not (
            0.0 <= self.outlier_percentiles[0] < self.outlier_percentiles[1] <= 100.0
        ):
            raise ConfigError("outlier_percentiles deve essere [basso, alto] con 0 <= basso < alto <= 100")
        if self.area is not None and not isinstance(self.area, dict):
            raise ConfigError("area deve essere un oggetto")
        if self.calibration is not None:
            if set(self.calibration) != set(CORNER_NAMES):
                raise ConfigError(f"calibration deve contenere gli angoli {CORNER_NAMES}")
            for name, values in self.calibration.items():
                if len(values) != 4:
                    raise ConfigError(f"calibration.{name} deve avere 4 valori")

    def resolve_path(self, value: str, base: Path = PROJECT_ROOT) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else base / path

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            log.warning("Chiavi sconosciute in config.json ignorate: %s", sorted(unknown))
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.validate()
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """Carica config.json; se manca lo crea con i default."""
    if not path.exists():
        cfg = Config()
        save_config(cfg, path)
        return cfg
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ConfigError("config.json deve contenere un oggetto JSON")
    return Config.from_dict(data)


def save_config(cfg: Config, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Scrittura atomica: file temporaneo + rename."""
    cfg.validate()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(cfg.to_dict(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)
