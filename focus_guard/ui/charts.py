"""Grafici della dashboard (matplotlib dentro Qt), coerenti con il tema.

Una serie per grafico: colore d'accento, nessuna legenda (il titolo della
card nomina la serie e l'unità), griglia sottile e recessiva, testi nei
colori del tema, tooltip al passaggio del mouse. Al cambio di tema il
grafico si ridisegna con i nuovi colori.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Sequence

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from focus_guard.ui.theme import FONT_TEXT, theme  # noqa: E402

WEEKDAYS = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


class _Chart(FigureCanvasQTAgg):
    def __init__(self) -> None:
        self.figure = Figure(figsize=(5, 2.6), dpi=100, layout="constrained")
        super().__init__(self.figure)
        self.setStyleSheet("background: transparent;")
        self.ax = self.figure.add_subplot()
        self._tooltip = None
        self._hover_items: list[tuple] = []  # (artista, x, y, testo)
        self._data = None
        self.mpl_connect("motion_notify_event", self._on_move)
        theme.changed.connect(self._on_theme)

    def _on_theme(self, *_):
        if self._data is not None:
            try:
                self.plot(self._data)
            except RuntimeError:  # canvas già distrutto
                pass

    def _style(self) -> None:
        t = theme.tokens
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = FONT_TEXT + ["DejaVu Sans"]
        self.figure.set_facecolor(t.card)
        ax = self.ax
        ax.set_facecolor(t.card)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(t.stroke)
        ax.tick_params(colors=t.text3, labelsize=9, length=0, pad=6)
        ax.grid(axis="y", color=t.stroke, linewidth=1, linestyle="-")
        ax.set_axisbelow(True)
        self._tooltip = ax.annotate(
            "", xy=(0, 0), xytext=(10, 10), textcoords="offset points", fontsize=9, color=t.text,
            bbox=dict(boxstyle="round,pad=0.5", fc=t.card_alt, ec=t.stroke), zorder=10,
        )
        self._tooltip.set_visible(False)

    def _empty(self, x: float, y: float, text: str) -> None:
        self.ax.text(x, y, text, ha="center", va="center", color=theme.tokens.text3, fontsize=10)

    def _on_move(self, event) -> None:
        if self._tooltip is None:
            return
        visible = False
        if event.inaxes is self.ax:
            for artist, x, y, text in self._hover_items:
                if artist.contains(event)[0]:
                    self._tooltip.xy = (x, y)
                    self._tooltip.set_text(text)
                    visible = True
                    break
        if visible or self._tooltip.get_visible():
            self._tooltip.set_visible(visible)
            self.draw_idle()


class DistractionsByHourChart(_Chart):
    def plot(self, counts: Sequence[int]) -> None:
        t = theme.tokens
        self._data = list(counts)
        self.ax.clear()
        self._style()
        top = max(counts) if any(counts) else 1
        ceiling = top * 1.15 + 0.5
        self.ax.bar(range(24), counts, width=0.62, color=t.accent, linewidth=0)
        self.ax.set_xticks(range(0, 24, 3), [f"{h:02d}" for h in range(0, 24, 3)])
        self.ax.set_xlim(-0.6, 23.6)
        self.ax.set_ylim(0, ceiling)
        self.ax.yaxis.get_major_locator().set_params(integer=True)
        # area sensibile = tutta la colonna (più grande della barra)
        self._hover_items = []
        for h, n in enumerate(counts):
            hit = self.ax.bar(h, ceiling, width=1.0, alpha=0.0)[0]
            label = "distrazione" if n == 1 else "distrazioni"
            self._hover_items.append((hit, h, n, f"{h:02d}:00–{h:02d}:59\n{n} {label}"))
        if not any(counts):
            self._empty(11.5, ceiling / 2, "Nessuna distrazione nel periodo")
        self.draw_idle()


class FocusRateByDayChart(_Chart):
    def plot(self, rows: Sequence[tuple[date, float | None]]) -> None:
        t = theme.tokens
        self._data = list(rows)
        self.ax.clear()
        self._style()
        xs = list(range(len(rows)))
        ys = [math.nan if r is None else r for _, r in rows]
        self.ax.plot(xs, ys, color=t.accent, linewidth=2, marker="o", markersize=7,
                     markeredgecolor=t.card, markeredgewidth=2, zorder=3)
        self.ax.set_ylim(0, 105)
        self.ax.set_yticks([0, 25, 50, 75, 100])
        step = max(1, len(rows) // 8)
        self.ax.set_xticks(xs[::step], [d.strftime("%d/%m") for d, _ in rows][::step])
        self.ax.set_xlim(-0.5, max(0.5, len(rows) - 0.5))
        self._hover_items = []
        for x, (d, r) in zip(xs, rows):
            hit = self.ax.bar(x, 105, width=1.0, alpha=0.0)[0]
            value = "nessuna attività" if r is None else f"{r:.1f} %".replace(".", ",")
            self._hover_items.append(
                (hit, x, 0 if r is None else r, f"{WEEKDAYS[d.weekday()]} {d:%d/%m}\n{value}")
            )
        if all(r is None for _, r in rows):
            self._empty((len(rows) - 1) / 2, 52, "Nessuna sessione nel periodo")
        elif len(rows) == 1 and rows[0][1] is not None:
            self.ax.annotate(f"{rows[0][1]:.1f} %".replace(".", ","), (0, rows[0][1]), xytext=(12, 0),
                             textcoords="offset points", va="center", color=t.text, fontsize=10)
        self.draw_idle()
