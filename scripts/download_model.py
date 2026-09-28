"""Scarica una tantum il modello MediaPipe Face Landmarker in models/.

È l'unica operazione di rete del progetto e non invia alcun dato:
scarica soltanto il file del modello.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
TARGET = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"


def main() -> int:
    if TARGET.exists() and "--force" not in sys.argv:
        print(f"Modello già presente: {TARGET} (usa --force per riscaricarlo)")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    tmp = TARGET.with_suffix(".part")
    print(f"Scarico {MODEL_URL}")
    urllib.request.urlretrieve(MODEL_URL, tmp)
    tmp.replace(TARGET)
    print(f"Salvato in {TARGET} ({TARGET.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
