# Focus Guard

App desktop locale che usa la webcam per capire quando lo sguardo esce da
un'area definita (lo schermo, o una zona della scrivania). Dopo un ritardo
configurabile mostra un banner con un'immagine casuale e fa partire una
musica in loop. Entrambi si fermano appena lo sguardo rientra.

## Privacy

- Tutta l'elaborazione avviene **in locale**: OpenCV legge la webcam e il
  modello MediaPipe gira sulla tua macchina.
- I frame restano solo in memoria, dentro il loop di cattura
  (`focus_guard/vision/tracker.py`), e vengono scartati subito. **Nessun frame
  viene salvato su disco né inviato in rete.** Fuori dal tracker escono solo
  numeri (posizione dell'iride e angoli della testa).
- Il test `tests/test_privacy.py` fallisce se nel pacchetto compaiono
  scritture di immagini/video o import di librerie di rete.
- L'unica operazione di rete è lo script esplicito che scarica **una volta**
  il file del modello; non invia alcun dato.
- In **pausa** la webcam viene rilasciata del tutto: il LED si spegne.

## Installazione

Requisiti: Python 3.10–3.12 (le versioni supportate da MediaPipe), una webcam.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_model.py      # scarica models/face_landmarker.task (~3,7 MB)
```

Metti i tuoi contenuti in:

- `assets/images/`: png, jpg, jpeg, gif, bmp, webp (ne viene scelta una a caso a ogni attivazione)
- `assets/music/`: mp3, ogg, wav, flac (un brano a caso, in loop)

Le cartelle vengono rilette a ogni attivazione, quindi puoi aggiungere file
senza riavviare. Se una cartella è vuota il banner mostra solo il testo, o
non parte la musica.

> Linux: MediaPipe richiede `libegl1` e `libgles2`; la tray richiede un
> desktop con area di notifica (su GNOME serve l'estensione AppIndicator).

## Uso

```bash
python -m focus_guard              # avvio normale
python -m focus_guard --calibrate  # forza una nuova calibrazione
python -m focus_guard -v           # log dettagliati
```

Al primo avvio parte la **calibrazione** a schermo intero:

1. Per ciascuno dei 4 angoli (alto-sx, alto-dx, basso-dx, basso-sx) guarda
   l'angolo dell'area e premi **SPAZIO**. Tieni lo sguardo fermo per 1,5 s.
   I punti azzurri indicano gli angoli dello schermo; se la tua area è
   un'altra (es. la scrivania), guarda l'angolo corrispondente di quella.
2. Nella fase di **verifica** un punto giallo segue il tuo sguardo e il bordo
   diventa verde o rosso (dentro o fuori). **INVIO** salva in `config.json`,
   **R** ripete, **ESC** annulla.

Poi l'app vive nella **system tray**. Il colore dell'icona indica lo stato:
verde concentrato, arancio in uscita, rosso distratto, grigio in pausa, blu
da calibrare. Il menu offre *Pausa/Riprendi*, *Ricalibra* ed *Esci*.

Il banner copre lo schermo ma è **trasparente a mouse e tastiera**: anche se
il rilevamento sbagliasse, non blocca il lavoro.

## Configurazione (`config.json`)

Il file viene creato al primo avvio. Le modifiche valgono al riavvio.

| Chiave | Default | Significato |
|---|---|---|
| `exit_margin` | `0.10` | Quanto oltre il bordo deve andare lo sguardo per contare come "fuori" (frazione del lato dell'area) |
| `reentry_margin` | `0.0` | Soglia di rientro; deve essere ≤ `exit_margin`. Valori negativi obbligano a rientrare più a fondo |
| `activation_delay_s` | `2.0` | Secondi continuativi fuori area prima dell'allarme |
| `reentry_delay_s` | `0.0` | Secondi dentro l'area prima di spegnere (0 = stop immediato) |
| `face_lost_counts_as_out` | `true` | Volto non visibile (ti alzi, ti giri) = fuori area |
| `head_weight` | `0.007` | Peso della rotazione della testa (per grado) rispetto all'iride; `0` = solo occhi |
| `smoothing_alpha` | `0.35` | Smoothing esponenziale (1 = nessuno) |
| `blink_threshold` | `0.5` | Sopra questo score l'occhio è considerato chiuso e il campione ignorato |
| `camera_index`, `frame_width`, `frame_height`, `target_fps` | `0`, `640`, `480`, `15` | Webcam |
| `images_dir`, `music_dir` | `assets/...` | Cartelle dei contenuti (relative al progetto o assolute) |
| `music_volume`, `overlay_opacity` | `0.6`, `0.6` | 0–1 |
| `banner_text` | `Torna a concentrarti!` | Testo del banner |
| `calibration` | `null` | Scritto dalla calibrazione: non modificarlo a mano |

### Isteresi

La posizione dello sguardo viene proiettata nell'area calibrata: `(0,0)` è
l'angolo in alto a sinistra, `(1,1)` quello in basso a destra. Da qui si
calcola una distanza con segno dal bordo: positiva fuori, negativa dentro.

```
FOCUSED ──d > exit_margin──▶ LEAVING ──per activation_delay_s──▶ DISTRACTED  (banner + musica)
   ▲                            │                                      │
   └──────d ≤ exit_margin───────┘                         d ≤ reentry_margin
   ▲                                                                   ▼
   └───────────per reentry_delay_s───────────── RETURNING ◀────────────┘
                                                    │ d > reentry_margin → DISTRACTED
```

Con `reentry_margin < exit_margin` lo sguardo che oscilla sul bordo non fa
lampeggiare il banner.

## Come si stima lo sguardo

Dai 478 landmark di MediaPipe si prende la posizione del centro dell'iride
rispetto agli angoli dell'occhio, normalizzata sulla larghezza dell'occhio
e indipendente dall'inclinazione della testa. La si media sui due occhi e
le si somma yaw/pitch della testa pesati da `head_weight`. Il verso del
contributo della testa viene dedotto dalla calibrazione. I 4 angoli
calibrati definiscono un'omografia verso il quadrato unitario. I battiti di
ciglia (blendshape `eyeBlink*`) vengono ignorati.

Limiti noti: la precisione verticale è inferiore a quella orizzontale, e se
ti sposti molto (non ruoti, ma trasli) rispetto alla posizione di
calibrazione conviene ricalibrare. Per aree piccole alza `exit_margin`.

## Struttura

```
focus_guard/
  config.py            Config + load/save config.json (scrittura atomica)
  logic/geometry.py    omografia, distanza con segno, modello di calibrazione   (puro)
  logic/features.py    landmark → iride/testa, smoothing, blink                 (puro)
  logic/focus.py       macchina a stati soglia/ritardo/isteresi                 (puro)
  vision/tracker.py    thread webcam + MediaPipe (frame solo in RAM)
  media.py             immagine casuale, MusicPlayer (pygame.mixer)
  ui/overlay.py        banner sempre in primo piano, click-through
  ui/calibration.py    calibrazione 4 angoli + verifica
  ui/tray.py           icona e menu nella tray
  app.py               controller
  __main__.py          CLI
scripts/download_model.py
tests/
```

## Test

```bash
pip install -r requirements-dev.txt
python -m pytest
```

I test coprono soglie, ritardi e isteresi (`test_focus.py`), la geometria
e la calibrazione, l'estrazione delle feature da landmark sintetici, la
config e la scelta dei media. `test_app.py` prova il ciclo completo
(calibrazione → allarme → rientro → pausa) con webcam e audio finti,
usando Qt in modalità `offscreen`.
