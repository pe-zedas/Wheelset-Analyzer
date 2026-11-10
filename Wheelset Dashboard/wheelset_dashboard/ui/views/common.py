"""Gemeinsames fuer alle Tabellen-Ansichten: Spaltenreihenfolge der Messgroessen, Anzeigemodus,
Ampel- und Messdaten-Zellen, Basis-View (KPI-Zeile + Panel mit Tabelle)."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...data.models import StatusAmpel
from ...logic.aggregation import has_messdaten

from ..widgets import AMPEL_COLORS, AmpelDot, KpiCard


# Reihenfolge der Messgroessen-Spalten (festgelegt, grau wenn nicht vorhanden)
MGROESSEN_SPALTEN: List[str] = [
    "LKD", "SPURKRANZDICKE_SD", "SPURKRANZHOEHE_SH",
    "SPURKRANZFLANKE_QR", "HOHLLAUF", "UEBERWALZUNG", "RADBREITE",
    "SPURMASS_SR", "STICHMASS_ABSTAND",
]
MGROESSEN_LABEL = {
    "LKD": "LKD", "SPURKRANZDICKE_SD": "Sd", "SPURKRANZHOEHE_SH": "Sh",
    "SPURKRANZFLANKE_QR": "qR", "HOHLLAUF": "Hohll.", "UEBERWALZUNG": "Überw.",
    "RADBREITE": "Breite", "SPURMASS_SR": "Spur", "STICHMASS_ABSTAND": "Abst.",
}


# -----------------------------------------------------------
# Globaler Anzeigemodus: Ampel-Punkt oder Punkt+Messwert
# -----------------------------------------------------------
SHOW_VALUES: bool = False


def show_values() -> bool:
    """Aktueller Anzeigemodus (Ampelpunkt oder Punkt + Messwert)."""
    return SHOW_VALUES


def set_show_values(flag: bool):
    """Globalen Anzeigemodus umschalten (wird vom MainWindow aufgerufen)."""
    global SHOW_VALUES
    SHOW_VALUES = bool(flag)


# -----------------------------------------------------------
# Sort-Helper fuer Ampelspalten
# -----------------------------------------------------------

_STATUS_ORDER = {StatusAmpel.GRAY: 0, StatusAmpel.GREEN: 1,
                 StatusAmpel.YELLOW: 2, StatusAmpel.RED: 3}


class _AmpelSortItem(QTableWidgetItem):
    """Unsichtbares Item hinter einem AmpelDot-CellWidget; sortiert nach UserRole."""
    def __init__(self, status: StatusAmpel):
        super().__init__()
        self.setData(Qt.UserRole, _STATUS_ORDER.get(status, 0))
        self.setText("")
        self.setFlags(self.flags() & ~Qt.ItemIsEditable)

    def __lt__(self, other):
        try:
            return self.data(Qt.UserRole) < other.data(Qt.UserRole)
        except TypeError:
            return False


def _ampel_sort_item(status: StatusAmpel) -> QTableWidgetItem:
    return _AmpelSortItem(status)


def fmt_num(value: float, decimals: int = 1) -> str:
    """Europäische Zahlendarstellung mit Komma als Dezimaltrenner."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _value_cell_widget(status: StatusAmpel, value: Optional[float]) -> QWidget:
    """AmpelDot + letzter Messwert farbig daneben."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(2, 0, 2, 0)
    lay.setSpacing(4)
    lay.addWidget(AmpelDot(status, size=8))
    lab = QLabel(fmt_num(value))
    lab.setStyleSheet(
        f"color: {AMPEL_COLORS[status]}; font-size: 11px; font-weight: 600;")
    lay.addWidget(lab)
    lay.addStretch(1)
    return w


def _centered(inner: QWidget) -> QWidget:
    """Zentriert ``inner`` horizontal und vertikal in einem Wrapper, so dass
    das Widget auch in schmalen Tabellenzellen (z. B. 28-px Status-Spalte)
    immer vollstaendig sichtbar in der Mitte liegt."""
    wrap = QWidget()
    lay = QHBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    lay.addStretch(1)
    lay.addWidget(inner, 0, Qt.AlignVCenter)
    lay.addStretch(1)
    return wrap


def set_ampel_cell(table: QTableWidget, row: int, col: int,
                    status: StatusAmpel, value: Optional[float] = None):
    """Setzt eine Status-Zelle gemaess globalem SHOW_VALUES-Modus.
    Immer: unsichtbares Sort-Item fuer Sortierung.
    SHOW_VALUES=False → AmpelDot. SHOW_VALUES=True+value → Dot+Zahl.
    SHOW_VALUES=True+kein value → leere Zelle.

    Das Widget wird in einen zentrierenden Wrapper gesetzt, damit der
    AmpelDot in der schmalen Status-Spalte (28 px) nicht an einen Rand
    rutscht oder vom QTableWidget-Padding (4 px) uebermalt wird.
    """
    table.setItem(row, col, _ampel_sort_item(status))
    # vorherigen CellWidget-Zustand immer bereinigen (auch nach setItem,
    # weil Qt das alte Widget sonst stehen lassen kann)
    table.removeCellWidget(row, col)
    if SHOW_VALUES:
        if value is None:
            return  # leer
        table.setCellWidget(row, col, _centered(_value_cell_widget(status, value)))
    else:
        table.setCellWidget(row, col, _centered(AmpelDot(status, size=10)))


# -----------------------------------------------------------
# Spalte "Messdaten vorhanden" (Diagramm-Symbol ganz rechts)
# -----------------------------------------------------------

MESSDATEN_TOOLTIP = "Messdaten vorhanden"
_messdaten_icon = None


def _graph_icon():
    """Diagramm-Symbol; erst beim ersten Gebrauch erzeugt (braucht QApplication)."""
    global _messdaten_icon
    if _messdaten_icon is None:
        import qtawesome as qta
        _messdaten_icon = qta.icon("mdi.chart-line", color="#378ADD")
    return _messdaten_icon


class _MessdatenItem(QTableWidgetItem):
    """Zelle mit Diagramm-Symbol, wenn Messdaten vorhanden sind; sortiert danach."""
    def __init__(self, has_data: bool):
        super().__init__()
        self.setData(Qt.UserRole, 1 if has_data else 0)
        self.setFlags(self.flags() & ~Qt.ItemIsEditable)
        self.setTextAlignment(Qt.AlignCenter)
        if has_data:
            self.setIcon(_graph_icon())
            self.setToolTip(MESSDATEN_TOOLTIP)

    def __lt__(self, other):
        try:
            return self.data(Qt.UserRole) < other.data(Qt.UserRole)
        except TypeError:
            return False


def set_messdaten_cell(table: QTableWidget, row: int, col: int, obj):
    """Setzt das Diagramm-Symbol, wenn ``obj`` selbst oder eine darunterliegende
    Komponente Messdaten hat; sonst bleibt die Zelle leer."""
    table.setItem(row, col, _MessdatenItem(has_messdaten(obj)))


def setup_messdaten_column(table: QTableWidget, col: int):
    """Schmale, feste Spalte ganz rechts."""
    table.setIconSize(QSize(16, 16))
    table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
    table.setColumnWidth(col, 30)
    item = table.horizontalHeaderItem(col)
    if item is not None:
        item.setToolTip(MESSDATEN_TOOLTIP)


# -----------------------------------------------------------
# Basis-View: KPI-Zeile + Panel mit Tabelle
# -----------------------------------------------------------

class BaseView(QWidget):
    drilldown = Signal(list)   # Pfad als Liste [("Einheit", "FS102"), ...]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)
        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(10)
        self._layout.addLayout(self._kpi_row)
        self._panel = QFrame()
        self._panel.setProperty("class", "Panel")
        pl = QVBoxLayout(self._panel)
        pl.setContentsMargins(12, 10, 12, 12)
        self._panel_title = QLabel()
        self._panel_title.setProperty("class", "PanelTitle")
        pl.addWidget(self._panel_title)
        self._table = QTableWidget()
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setSortingEnabled(True)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        # Mindesthoehe fuer ~6 Datenzeilen + Header (Standard-Zeilenhoehe ~28 px)
        self._table.setMinimumHeight(6 * 28 + 36)

        # Filterzeile oberhalb der Tabelle
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Freitext …")
        self._filter_edit.setClearButtonEnabled(True)   # X-Button rechts im Feld
        self._filter_edit.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._filter_edit, 1)
        self._filter_hint = QLabel("")
        self._filter_hint.setStyleSheet("color: #6B6F78; font-size: 11px;")
        filter_row.addWidget(self._filter_hint)
        pl.addLayout(filter_row)
        pl.addWidget(self._table)
        self._layout.addWidget(self._panel, 5)   # Tabelle bekommt klaren Vorrang vor Overview

    def _clear_kpis(self):
        while self._kpi_row.count():
            item = self._kpi_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _add_kpi(self, label, value, variant="default"):
        self._kpi_row.addWidget(KpiCard(label, value, variant=variant))

    def _on_double_click(self, row, col):
        pass  # ueberschreiben in Subklassen

    def _on_selection_changed(self):
        pass  # ueberschreiben in Subklassen

    def _selected_row(self) -> int:
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _apply_filter(self, text: str):
        """Blendet Zeilen aus, deren Textspalten den Suchbegriff nicht enthalten."""
        needle = (text or "").strip().lower()
        shown = 0
        total = self._table.rowCount()
        cols = self._table.columnCount()
        for row in range(total):
            if not needle:
                self._table.setRowHidden(row, False)
                shown += 1
                continue
            match = False
            for col in range(cols):
                item = self._table.item(row, col)
                if item and needle in item.text().lower():
                    match = True
                    break
            self._table.setRowHidden(row, not match)
            if match:
                shown += 1
        self._filter_hint.setText(f"{shown}/{total}" if needle else "")
