"""Design system: palette, tipografia, spaziature e foglio di stile globale.

Tutti i colori dell'interfaccia vengono da qui (tema scuro e chiaro). I
widget non usano mai colori letterali: leggono `theme.tokens` e si
ridisegnano quando arriva il segnale `theme.changed`.

Stile: Fluent (Windows 11), colore principale azzurro Windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication

DARK = "dark"
LIGHT = "light"
MODES = (DARK, LIGHT)

# --- spaziature: griglia a multipli di 8 px ------------------------------------
S1, S2, S3, S4, S5 = 8, 16, 24, 32, 40
HALF = 4  # solo per micro-allineamenti (icone/testo)

# --- raggi ----------------------------------------------------------------------
R_CONTROL = 4  # pulsanti, campi
R_CARD = 8  # card, pannelli
R_LARGE = 16  # banner, anteprima webcam

# --- tipografia (rampa Fluent) -------------------------------------------------
FONT_TEXT = ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Open Sans",
             "Noto Sans", "Helvetica Neue", "Arial"]
FONT_DISPLAY = ["Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI", "Open Sans",
                "Noto Sans", "Helvetica Neue", "Arial"]
FONT_EMOJI = ["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"]

CAPTION = 12
BODY = 14
SUBTITLE = 20
TITLE = 28
DISPLAY = 40


@dataclass(frozen=True)
class Tokens:
    mode: str
    bg: str  # sfondo finestra (effetto Mica)
    sidebar: str  # barra laterale
    card: str  # superfici in rilievo
    card_alt: str  # controlli su card, campi
    stroke: str  # bordi e filetti
    stroke_strong: str
    text: str
    text2: str  # testo secondario
    text3: str  # testo terziario / disabilitato
    accent: str
    accent_hover: str
    on_accent: str  # testo sopra l'accento
    good: str
    bad: str
    warn: str
    idle: str
    shadow_alpha: int
    scrim_alpha: int  # velo del banner


DARK_TOKENS = Tokens(
    mode=DARK,
    bg="#202020", sidebar="#1b1b1b", card="#2b2b2b", card_alt="#323232",
    stroke="#3b3b3b", stroke_strong="#4a4a4a",
    text="#ffffff", text2="#cfcfcf", text3="#9a9a9a",
    accent="#60cdff", accent_hover="#7ad7ff", on_accent="#00263a",
    good="#6ccb5f", bad="#ff99a4", warn="#fce100", idle="#9a9a9a",
    shadow_alpha=90, scrim_alpha=150,
)

LIGHT_TOKENS = Tokens(
    mode=LIGHT,
    bg="#f3f3f3", sidebar="#ebebeb", card="#ffffff", card_alt="#f9f9f9",
    stroke="#e5e5e5", stroke_strong="#d1d1d1",
    text="#1a1a1a", text2="#5d5d5d", text3="#8a8a8a",
    accent="#005fb8", accent_hover="#1975c5", on_accent="#ffffff",
    good="#0f7b0f", bad="#c42b1c", warn="#9d5d00", idle="#8a8a8a",
    shadow_alpha=28, scrim_alpha=120,
)


def tokens_for(mode: str) -> Tokens:
    return DARK_TOKENS if mode == DARK else LIGHT_TOKENS


def font(size: int = BODY, weight: int = 400, display: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONT_DISPLAY if display else FONT_TEXT)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


def rgba(color: str, alpha: float) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha:.3f})"


def qcolor(color: str, alpha: int | None = None) -> QColor:
    c = QColor(color)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def stylesheet(t: Tokens) -> str:
    """Foglio di stile globale. Le varianti dei pulsanti usano la proprietà `variant`."""
    return f"""
    QMainWindow, QDialog, QMessageBox, QWidget#page, QWidget#window {{
        background: {t.bg}; color: {t.text};
    }}
    QLabel {{ background: transparent; color: {t.text}; }}
    QToolTip {{
        background: {t.card}; color: {t.text}; border: 1px solid {t.stroke};
        border-radius: {R_CONTROL}px; padding: {HALF}px {S1}px;
    }}
    QMenu {{
        background: {t.card}; color: {t.text}; border: 1px solid {t.stroke};
        border-radius: {R_CARD}px; padding: {HALF}px;
    }}
    QMenu::item {{ padding: 6px {S3}px 6px {S2}px; border-radius: {R_CONTROL}px; }}
    QMenu::item:selected {{ background: {t.card_alt}; }}
    QMenu::item:disabled {{ color: {t.text3}; }}
    QMenu::separator {{ height: 1px; background: {t.stroke}; margin: {HALF}px {S1}px; }}

    QPushButton {{
        background: {t.card_alt}; color: {t.text}; border: 1px solid {t.stroke};
        border-radius: {R_CONTROL}px; padding: 6px {S2}px; min-height: 20px;
    }}
    QPushButton:hover {{ border-color: {t.stroke_strong}; background: {t.card}; }}
    QPushButton:pressed {{ color: {t.text2}; }}
    QPushButton:disabled {{ color: {t.text3}; background: transparent; }}
    QPushButton[variant="primary"] {{
        background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent}; font-weight: 600;
    }}
    QPushButton[variant="primary"]:hover {{ background: {t.accent_hover}; }}
    QPushButton[variant="primary"]:disabled {{
        background: {t.stroke}; border-color: {t.stroke}; color: {t.text3};
    }}
    QPushButton[variant="subtle"] {{ background: transparent; border: 1px solid transparent; }}
    QPushButton[variant="subtle"]:hover {{ background: {t.card_alt}; }}
    QPushButton[variant="segment"] {{
        background: transparent; border: 1px solid transparent; color: {t.text2};
        padding: 4px {S2}px;
    }}
    QPushButton[variant="segment"]:checked {{
        background: {t.card}; color: {t.text}; border: 1px solid {t.stroke}; font-weight: 600;
    }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.stroke_strong}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 20px; height: 20px; margin: -8px 0; border-radius: 10px;
        background: {t.accent}; border: 5px solid {t.card_alt};
    }}
    QSlider::handle:horizontal:hover {{ border-width: 4px; }}

    QProgressBar {{ background: {t.stroke}; border: none; border-radius: 2px; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 2px; }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ background: transparent; width: {S1}px; }}
    QScrollBar::handle:vertical {{ background: {t.stroke_strong}; border-radius: 4px; min-height: {S4}px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def palette(t: Tokens) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.card,
        QPalette.ColorRole.AlternateBase: t.card_alt,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.card_alt,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.on_accent,
        QPalette.ColorRole.ToolTipBase: t.card,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.text3,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.text3))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.text3))
    return p


class ThemeManager(QObject):
    """Tema corrente dell'applicazione; emette `changed` a ogni cambio."""

    changed = pyqtSignal(object)  # Tokens

    def __init__(self) -> None:
        super().__init__()
        self.tokens: Tokens = DARK_TOKENS

    @property
    def mode(self) -> str:
        return self.tokens.mode

    @property
    def is_dark(self) -> bool:
        return self.tokens.mode == DARK

    def apply(self, mode: str) -> None:
        """Imposta il tema e lo applica all'intera applicazione."""
        self.tokens = tokens_for(mode)
        app = QApplication.instance()
        if app is not None:
            app.setStyle("Fusion")
            app.setFont(font(BODY))
            app.setPalette(palette(self.tokens))
            app.setStyleSheet(stylesheet(self.tokens))
        self.changed.emit(self.tokens)


theme = ThemeManager()
