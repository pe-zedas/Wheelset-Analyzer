"""Wiederverwendbare UI-Bausteine (Ampel-Punkt, Status-Pill, KPI-Karte)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..data.models import StatusAmpel


AMPEL_COLORS = {
    StatusAmpel.GREEN: "#88C442",   # heller als vorher (#639922) für besseren Kontrast zu Rot
    StatusAmpel.YELLOW: "#F2B82B",  # etwas gelblicher als vorher (#EF9F27), weiter deutlich orange
    StatusAmpel.RED: "#E24B4A",
    StatusAmpel.GRAY: "#B4B2A9",
}

AMPEL_LABEL = {
    StatusAmpel.GREEN: "OK",
    StatusAmpel.YELLOW: "Warn",
    StatusAmpel.RED: "Grenz",
    StatusAmpel.GRAY: "unbek.",
}

AMPEL_PILL_BG = {
    StatusAmpel.GREEN: ("#EAF3DE", "#3B6D11"),
    StatusAmpel.YELLOW: ("#FAEEDA", "#633806"),
    StatusAmpel.RED: ("#FCEBEB", "#791F1F"),
    StatusAmpel.GRAY: ("#F1EFE8", "#444441"),
}


class AmpelDot(QWidget):
    """Kleiner farbiger Punkt (10 px)."""
    def __init__(self, status: StatusAmpel = StatusAmpel.GRAY, size: int = 10, parent=None):
        super().__init__(parent)
        self._status = status
        self._size = size
        self.setFixedSize(size + 4, size + 4)

    def setStatus(self, status: StatusAmpel):
        self._status = status
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(AMPEL_COLORS[self._status]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(2, 2, self._size, self._size)


class StatusPill(QLabel):
    """Abgerundeter farbiger Status-Chip."""
    def __init__(self, status: StatusAmpel, text: str = None, parent=None):
        bg, fg = AMPEL_PILL_BG[status]
        label = text or AMPEL_LABEL[status]
        super().__init__(label, parent)
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; padding: 2px 10px; "
            f"border-radius: 10px; font-size: 11px; font-weight: 500;"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class KpiCard(QFrame):
    clicked = Signal()

    def __init__(self, label: str, value: str, variant: str = "default", parent=None):
        super().__init__(parent)
        cls = "KpiCard"
        if variant == "warn":
            cls += " KpiCardWarn"
        elif variant == "danger":
            cls += " KpiCardDanger"
        self.setProperty("class", cls)
        self.setFrameShape(QFrame.NoFrame)
        self.setObjectName("KpiCard")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(1)
        lab = QLabel(label)
        lab.setProperty("class", "KpiLabel")
        val = QLabel(value)
        value_cls = "KpiValue"
        if variant == "warn":
            value_cls += " KpiValueWarn"
        elif variant == "danger":
            value_cls += " KpiValueDanger"
        val.setProperty("class", value_cls)
        sub = QLabel("")
        sub.setProperty("class", "KpiSub")
        sub.hide()
        lay.addWidget(lab)
        lay.addWidget(val)
        lay.addWidget(sub)
        self._val = val
        self._sub = sub
        self._clickable = False

    def setValue(self, value: str):
        self._val.setText(value)

    def setSubValue(self, text: str):
        """Zweite Zeile unterhalb des Hauptwerts (z. B. km-Stand ergaenzend
        zum Datum). Leerer Text blendet die Zeile aus."""
        if text:
            self._sub.setText(text)
            self._sub.show()
        else:
            self._sub.clear()
            self._sub.hide()

    def set_status_border(self, status: StatusAmpel):
        """Rahmen in Ampelfarbe faerben (fuer Messwert-Kacheln unter dem Plot)."""
        color = AMPEL_COLORS.get(status, "#E2E4EA")
        self.setStyleSheet(
            f"QFrame#KpiCard {{ background-color: #FFFFFF; border-radius: 6px; "
            f"border: 2px solid {color}; padding: 4px 8px; }}"
        )

    def set_clickable(self, callback):
        """Macht die Kachel klickbar; `callback` wird bei Klick aufgerufen."""
        self._clickable = True
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Klick → zu dieser Ebene wechseln")
        self.clicked.connect(callback)

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        if self._clickable:
            # Hover-Hinweis: etwas dunklerer Hintergrund via Property-Trigger
            self.setStyleSheet("background-color: #FAFBFC;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._clickable:
            self.setStyleSheet("")
        super().leaveEvent(event)
