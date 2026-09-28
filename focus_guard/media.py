"""Scelta dell'immagine del banner e riproduzione della musica in loop."""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MUSIC_EXTENSIONS = {".mp3", ".ogg", ".wav", ".flac"}


def list_files(folder: Path, extensions: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in extensions
    )


class RandomPicker:
    """Scelta casuale che evita di ripetere due volte di fila lo stesso file."""

    def __init__(self, folder: Path, extensions: set[str], rng: random.Random | None = None):
        self.folder = folder
        self.extensions = extensions
        self._rng = rng or random.Random()
        self._last: Path | None = None

    def pick(self) -> Path | None:
        files = list_files(self.folder, self.extensions)  # riletta ogni volta: cartella modificabile a caldo
        if not files:
            return None
        candidates = [f for f in files if f != self._last] or files
        self._last = self._rng.choice(candidates)
        return self._last


class MusicPlayer:
    """Musica in loop con pygame.mixer; stop immediato.

    pygame viene importato solo al primo uso: se manca un dispositivo audio
    l'app continua a funzionare, solo senza musica.
    """

    def __init__(self, folder: Path, volume: float = 0.6, rng: random.Random | None = None):
        self._picker = RandomPicker(folder, MUSIC_EXTENSIONS, rng)
        self.volume = volume
        self._mixer = None
        self._unavailable = False

    def _ensure_mixer(self):
        if self._mixer is None and not self._unavailable:
            try:
                os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
                import pygame

                pygame.mixer.init()
                self._mixer = pygame.mixer
            except Exception as exc:  # pygame assente o nessun dispositivo audio
                log.warning("Audio non disponibile, musica disattivata: %s", exc)
                self._unavailable = True
        return self._mixer

    @property
    def playing(self) -> bool:
        return self._mixer is not None and self._mixer.music.get_busy()

    def play(self) -> Path | None:
        track = self._picker.pick()
        if track is None:
            log.info("Nessun brano in %s", self._picker.folder)
            return None
        mixer = self._ensure_mixer()
        if mixer is None:
            return None
        try:
            mixer.music.load(str(track))
            mixer.music.set_volume(self.volume)
            mixer.music.play(loops=-1)
        except Exception as exc:
            log.warning("Impossibile riprodurre %s: %s", track.name, exc)
            return None
        return track

    def stop(self) -> None:
        if self._mixer is not None:
            self._mixer.music.stop()

    def close(self) -> None:
        if self._mixer is not None:
            self._mixer.music.stop()
            self._mixer.quit()
            self._mixer = None
