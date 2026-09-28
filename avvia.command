#!/bin/bash
# Focus Guard - avvio con doppio click su macOS.
# Al primo avvio crea .venv, installa le dipendenze e scarica il modello.

cd "$(dirname "$0")" || exit 1

fail() {
    echo
    echo "ERRORE: $1"
    read -r -p "Premi INVIO per chiudere..."
    exit 1
}

if [ ! -f ".venv/bin/activate" ]; then
    echo "Primo avvio: creo l'ambiente virtuale .venv..."
    command -v python3 >/dev/null 2>&1 || fail "python3 non trovato. Installa Python 3.10-3.12 da python.org"
    python3 -m venv .venv || fail "creazione di .venv non riuscita"
    source .venv/bin/activate
    python -m pip install --upgrade pip || fail "aggiornamento di pip non riuscito"
    python -m pip install -r requirements.txt || fail "installazione delle dipendenze non riuscita"
else
    source .venv/bin/activate
fi

if [ ! -f "models/face_landmarker.task" ]; then
    python scripts/download_model.py || fail "download del modello non riuscito"
fi

python -m focus_guard "$@" || fail "Focus Guard si e' chiuso con un errore (vedi sopra)"
