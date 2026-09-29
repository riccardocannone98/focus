"""Componenti riutilizzabili del design system (tutti sensibili al tema)."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from focus_guard.ui.theme import (
    BODY,
    CAPTION,
    DISPLAY,
    HALF,
    R_CARD,
    S1,
    S2,
    S3,
    S5,
    font,
    qcolor,
    theme,
)

# Icone vettoriali (Material Design Icons 6, via qtawesome)
ICONS = {
    "dashboard": "mdi6.view-dashboard-outline",
    "area": "mdi6.crop-free",
    "settings": "mdi6.cog-outline",
    "time": "mdi6.timer-outline",
    "focus": "mdi6.target",
    "distraction": "mdi6.alert-circle-outline",
    "glance": "mdi6.eye-off-outline",
    "avg": "mdi6.timer-sand",
    "max": "mdi6.clock-alert-outline",
    "streak": "mdi6.trophy-outline",
    "rate": "mdi6.chart-line",
    "pause": "mdi6.pause",
    "play": "mdi6.play",
    "export": "mdi6.file-export-outline",
    "moon": "mdi6.weather-night",
    "sun": "mdi6.white-balance-sunny",
    "record": "mdi6.record-circle-outline",
    "redo": "mdi6.refresh",
    "save": "mdi6.content-save-outline",
    "close": "mdi6.close",
    "up": "mdi6.arrow-up",
    "down": "mdi6.arrow-down",
    "flat": "mdi6.arrow-right",
    "eye": "mdi6.eye-outline",
    "face": "mdi6.face-recognition",
    "webcam": "mdi6.webcam",
    "folder": "mdi6.folder-outline",
    "shield": "mdi6.shield-lock-outline",
    "palette": "mdi6.palette-outline",
    "tune": "mdi6.tune-variant",
    "info": "mdi6.information-outline",
    "check": "mdi6.check",
}


def icon(name: str, color: str | None = None) -> QIcon:
    import qtawesome as qta

    return qta.icon(ICONS[name], color=color or theme.tokens.text)


def pixmap(name: str, color: str | None = None, size: int = 16) -> QPixmap:
    return icon(name, color).pixmap(QSize(size, size))


class RoleLabel(QLabel):
    """Etichetta con colore dal tema; role = text | text2 | text3 | accent | good | bad | warn."""

    def __init__(self, text: str, role: str) -> None:
        super().__init__(text)
        self._role = role
        self._apply()
        theme.changed.connect(self._apply)

    def set_role(self, role: str) -> None:
        self._role = role
        self._apply()

    def _apply(self, *_) -> None:
        self.setStyleSheet(f"color: {getattr(theme.tokens, self._role)}; background: transparent;")


def text_label(
    text: str = "", size: int = BODY, weight: int = 400, role: str = "text", display: bool = False
) -> RoleLabel:
    lab = RoleLabel(text, role)
    lab.setFont(font(size, weight, display))
    return lab


def set_role(lab: QLabel, role: str) -> None:
    if isinstance(lab, RoleLabel):
        lab.set_role(role)
    else:
        lab.setStyleSheet(f"color: {getattr(theme.tokens, role)}; background: transparent;")


class IconLabel(QLabel):
    """Icona vettoriale che segue il tema."""

    def __init__(self, name: str, size: int = 16, role: str = "text2") -> None:
        super().__init__()
        self._name, self._size, self._role = name, size, role
        self.setFixedSize(size, size)
        self._refresh()
        theme.changed.connect(self._refresh)

    def set_icon(self, name: str | None = None, role: str | None = None) -> None:
        self._name = name or self._name
        self._role = role or self._role
        self._refresh()

    def _refresh(self, *_):
        self.setPixmap(pixmap(self._name, getattr(theme.tokens, self._role), self._size))


class Button(QPushButton):
    """Pulsante del design system; variant = secondary | primary | subtle."""

    def __init__(self, text: str, icon_name: str | None = None, variant: str = "secondary") -> None:
        super().__init__(text)
        self._icon_name, self._variant = icon_name, variant
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(font(BODY, 600 if variant == "primary" else 400))
        if icon_name:
            self.setIconSize(QSize(16, 16))
            self._refresh()
            theme.changed.connect(self._refresh)

    def _refresh(self, *_) -> None:
        t = theme.tokens
        self.setIcon(icon(self._icon_name, t.on_accent if self._variant == "primary" else t.text))


def button(text: str, icon_name: str | None = None, variant: str = "secondary") -> Button:
    return Button(text, icon_name, variant)


class ShadowEffect(QGraphicsDropShadowEffect):
    """Ombra leggera la cui intensità segue il tema."""

    def __init__(self, parent: QWidget, blur: int = S2, dy: int = 2) -> None:
        super().__init__(parent)
        self.setBlurRadius(blur)
        self.setOffset(0, dy)
        self._apply()
        theme.changed.connect(self._apply)

    def _apply(self, *_) -> None:
        self.setColor(qcolor("#000000", theme.tokens.shadow_alpha))


class Card(QFrame):
    """Superficie in rilievo: angoli arrotondati, bordo sottile, ombra leggera."""

    def __init__(self, padding: int = S2) -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(S1)
        self.setGraphicsEffect(ShadowEffect(self))
        self._restyle()
        theme.changed.connect(self._restyle)

    def _restyle(self, *_):
        t = theme.tokens
        self.setStyleSheet(
            f"QFrame#card {{ background: {t.card}; border: 1px solid {t.stroke};"
            f" border-radius: {R_CARD}px; }}"
        )


class ToggleSwitch(QAbstractButton):
    """Interruttore a levetta Fluent (checkable) con animazione del cursore."""

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._pos = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self, duration=140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._animate)
        theme.changed.connect(self.update)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_anim(self, value) -> None:
        self._pos = float(value)
        self.update()

    def set_checked_silently(self, checked: bool) -> None:
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._anim.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(44, 24)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 2, 42, 20)
        on = self.isChecked()
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.accent if self.isEnabled() else t.stroke_strong))
        else:
            p.setPen(QPen(qcolor(t.text2), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(track, 10, 10)
        x = 12 + self._pos * 20
        radius = 7 if self.underMouse() else 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(t.on_accent if on else t.text2))
        p.drawEllipse(QPointF(x, 12), radius, radius)


# Stati dell'indicatore: chiave -> (testo, ruolo colore)
STATUS_STYLES = {
    "focus": ("In focus", "good"),
    "leaving": ("Sguardo fuori…", "warn"),
    "distracted": ("Distratto", "bad"),
    "paused": ("In pausa", "idle"),
    "stopped": ("Fermo", "idle"),
    "no_area": ("Area da definire", "accent"),
}


class StatusPill(QWidget):
    """Indicatore di stato ben visibile: pillola colorata con punto e alone."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(S5)
        self.setMinimumWidth(200)
        self.key = "stopped"
        self.subtitle = ""
        theme.changed.connect(self.update)

    @property
    def text(self) -> str:
        return STATUS_STYLES[self.key][0]

    def set_state(self, key: str, subtitle: str = "") -> None:
        self.key, self.subtitle = key, subtitle
        self.setToolTip(f"{self.text} {subtitle}".strip())
        fm_main = self.fontMetrics()
        width = 48 + fm_main.horizontalAdvance(self.text) * 1.15 + fm_main.horizontalAdvance(subtitle) + S3
        self.setMinimumWidth(int(max(200, width)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme.tokens
        color = qcolor(getattr(t, STATUS_STYLES[self.key][1]))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(qcolor(color.name(), 90), 1))
        p.setBrush(qcolor(color.name(), 38))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        cy = r.center().y()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(color.name(), 70))
        p.drawEllipse(QPointF(S3, cy), 9, 9)
        p.setBrush(color)
        p.drawEllipse(QPointF(S3, cy), 5, 5)
        p.setFont(font(15, 600))
        p.setPen(qcolor(t.text))
        text_rect = QRectF(S5, 0, self.width() - S5, self.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, self.text)
        advance = p.fontMetrics().horizontalAdvance(self.text)
        p.setFont(font(13))
        p.setPen(qcolor(t.text2))
        p.drawText(text_rect.adjusted(advance + S1, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.subtitle)


class SegmentedControl(QFrame):
    """Scelta esclusiva tra poche opzioni (es. periodo)."""

    changed = pyqtSignal(str)

    def __init__(self, options: dict[str, str], current: str) -> None:
        super().__init__()
        self.setObjectName("segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options.items():
            b = QPushButton(text)
            b.setProperty("variant", "segment")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(key == current)
            b.clicked.connect(lambda _=False, k=key: self._select(k))
            self._group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        self.current = current
        self._restyle()
        theme.changed.connect(self._restyle)

    def _select(self, key: str) -> None:
        if key != self.current:
            self.current = key
            self.changed.emit(key)

    def set_current(self, key: str) -> None:
        self.buttons[key].setChecked(True)
        self._select(key)

    def _restyle(self, *_):
        t = theme.tokens
        self.setStyleSheet(
            f"QFrame#segmented {{ background: {t.card_alt}; border: 1px solid {t.stroke};"
            f" border-radius: 7px; }}"
        )


class KpiTile(QFrame):
    """KPI in stile minimale: icona e etichetta, valore grande e leggero, unità, variazione."""

    def __init__(self, icon_name: str, label: str, unit: str) -> None:
        super().__init__()
        self.setObjectName("kpi")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, S2, S3, S2)
        lay.setSpacing(HALF)
        head = QHBoxLayout()
        head.setSpacing(S1)
        head.addWidget(IconLabel(icon_name, 16, "text3"))
        caption = text_label(label.upper(), 11, 600, "text3")
        caption.setWordWrap(True)
        head.addWidget(caption, 1)
        lay.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.value = text_label("—", DISPLAY, 300, "text", display=True)
        row.addWidget(self.value, 0, Qt.AlignmentFlag.AlignBaseline)
        self.unit = text_label(unit, BODY, 400, "text3")
        row.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBaseline)
        row.addStretch(1)
        lay.addLayout(row)

        delta = QHBoxLayout()
        delta.setSpacing(HALF)
        self.delta_icon = IconLabel("flat", 14, "text3")
        self.delta_text = text_label("", CAPTION, 600, "text3")
        self.delta_hint = text_label("vs periodo prec.", CAPTION, 400, "text3")
        delta.addWidget(self.delta_icon)
        delta.addWidget(self.delta_text)
        delta.addWidget(self.delta_hint)
        delta.addStretch(1)
        lay.addLayout(delta)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set(self, text: str) -> None:
        self.value.setText(text)

    def set_delta(self, text: str, direction: str, role: str, hint: str = "vs periodo prec.") -> None:
        """direction: up | down | flat | none; role: good | bad | text3."""
        self.delta_icon.setVisible(direction != "none")
        if direction != "none":
            self.delta_icon.set_icon(direction, role)
        self.delta_text.setText(text)
        set_role(self.delta_text, role)
        self.delta_hint.setText(hint)


class NavItem(QPushButton):
    """Voce della barra laterale Fluent: barretta d'accento + icona + testo."""

    def __init__(self, icon_name: str, text: str) -> None:
        super().__init__(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(S5)
        self._icon_name = icon_name
        self.setFont(font(BODY))
        theme.changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: N802
        t = theme.tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        sel = self.isChecked()
        if sel or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(t.card if sel else t.card_alt, 255 if sel else 140))
            p.drawRoundedRect(r, 6, 6)
        if sel:
            p.setBrush(qcolor(t.accent))
            p.drawRoundedRect(QRectF(0, r.center().y() - 8, 3, 16), 1.5, 1.5)
        pm = pixmap(self._icon_name, t.text if sel else t.text2, 18)
        p.drawPixmap(QPointF(S2, r.center().y() - 9), pm)
        f = font(BODY, 600 if sel else 400)
        p.setFont(f)
        p.setPen(qcolor(t.text if sel else t.text2))
        p.drawText(r.adjusted(S2 + 18 + 12, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, self.text())


class Divider(QFrame):
    def __init__(self, vertical: bool = False) -> None:
        super().__init__()
        if vertical:
            self.setFixedWidth(1)
        else:
            self.setFixedHeight(1)
        self._restyle()
        theme.changed.connect(self._restyle)

    def _restyle(self, *_):
        self.setStyleSheet(f"background: {theme.tokens.stroke}; border: none;")
