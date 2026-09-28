"""Grafici della dashboard (matplotlib dentro Qt).

Una serie per grafico: un solo colore, nessuna legenda (il titolo con
l'unità nomina la serie), griglia sottile e recessiva, testi in inchiostro
neutro, tooltip al passaggio del mouse.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Sequence

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

SERIES = "#2a78d6"
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e6e5e1"


class _Chart(FigureCanvasQTAgg):
    def __init__(self, title: str) -> None:
        self.figure = Figure(figsize=(5, 2.6), dpi=100, facecolor=SURFACE, layout="constrained")
        super().__init__(self.figure)
        self.ax = self.figure.add_subplot()
        self._title = title
        self._tooltip = None
        self._hover_items: list[tuple] = []  # (artist, x, y, testo)
        self.mpl_connect("motion_notify_event", self._on_move)

    def _style(self) -> None:
        ax = self.ax
        ax.set_facecolor(SURFACE)
        ax.set_title(self._title, loc="left", fontsize=10, color=TEXT, fontweight="bold")
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(colors=TEXT_MUTED, labelsize=8, length=0)
        ax.grid(axis="y", color=GRID, linewidth=1, linestyle="-")
        ax.set_axisbelow(True)
        self._tooltip = ax.annotate(
            "", xy=(0, 0), xytext=(8, 8), textcoords="offset points", fontsize=8, color=TEXT,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=GRID), zorder=10,
        )
        self._tooltip.set_visible(False)

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
        if visible != self._tooltip.get_visible() or visible:
            self._tooltip.set_visible(visible)
            self.draw_idle()


class DistractionsByHourChart(_Chart):
    def __init__(self) -> None:
        super().__init__("Distrazioni per fascia oraria [n]")

    def plot(self, counts: Sequence[int]) -> None:
        self.ax.clear()
        self._style()
        bars = self.ax.bar(range(24), counts, width=0.6, color=SERIES, edgecolor=SURFACE, linewidth=1)
        self.ax.set_xticks(range(0, 24, 2), [f"{h:02d}" for h in range(0, 24, 2)])
        self.ax.set_xlim(-0.6, 23.6)
        top = max(counts) if any(counts) else 1
        self.ax.set_ylim(0, top * 1.15 + 0.5)
        self.ax.yaxis.get_major_locator().set_params(integer=True)
        self.ax.set_xlabel("ora del giorno", fontsize=8, color=TEXT_MUTED)
        # area sensibile = tutta la colonna (più grande della barra)
        self._hover_items = []
        for h, (bar, n) in enumerate(zip(bars, counts)):
            hit = self.ax.bar(h, top * 1.15 + 0.5, width=1.0, alpha=0.0)[0]
            self._hover_items.append(
                (hit, h, n, f"{h:02d}:00–{h:02d}:59\n{n} distrazion{'e' if n == 1 else 'i'}")
            )
        if not any(counts):
            self.ax.text(11.5, (top * 1.15 + 0.5) / 2, "Nessuna distrazione nel periodo",
                         ha="center", va="center", color=TEXT_MUTED, fontsize=9)
        self.draw_idle()


class FocusRateByDayChart(_Chart):
    def __init__(self) -> None:
        super().__init__("Tasso di focus per giorno [%]")

    def plot(self, rows: Sequence[tuple[date, float | None]]) -> None:
        self.ax.clear()
        self._style()
        xs = list(range(len(rows)))
        ys = [math.nan if r is None else r for _, r in rows]
        self.ax.plot(xs, ys, color=SERIES, linewidth=2, marker="o", markersize=7,
                     markeredgecolor=SURFACE, markeredgewidth=2)
        self.ax.set_ylim(0, 105)
        self.ax.set_yticks([0, 25, 50, 75, 100])
        step = max(1, len(rows) // 8)
        self.ax.set_xticks(xs[::step], [d.strftime("%d/%m") for d, _ in rows][::step])
        self.ax.set_xlim(-0.5, max(0.5, len(rows) - 0.5))
        self._hover_items = []
        for x, (d, r) in zip(xs, rows):
            hit = self.ax.bar(x, 105, width=1.0, alpha=0.0)[0]
            text = f"{d.strftime('%a %d/%m')}\n" + ("nessuna attività" if r is None else f"{r:.1f} %")
            self._hover_items.append((hit, x, 0 if r is None else r, text))
        if all(r is None for _, r in rows):
            self.ax.text((len(rows) - 1) / 2, 52, "Nessuna sessione nel periodo",
                         ha="center", va="center", color=TEXT_MUTED, fontsize=9)
        elif len(rows) == 1 and rows[0][1] is not None:
            self.ax.annotate(f"{rows[0][1]:.1f} %", (0, rows[0][1]), xytext=(10, 0),
                             textcoords="offset points", va="center", color=TEXT, fontsize=9)
        self.draw_idle()
