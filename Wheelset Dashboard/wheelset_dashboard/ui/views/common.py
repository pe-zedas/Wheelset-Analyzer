"""Gemeinsames fuer alle Tabellen-Ansichten: Spaltenreihenfolge der Messgroessen, Anzeigemodus,
Ampel- und Messdaten-Zellen, Basis-View (KPI-Zeile + Panel mit Tabelle)."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ...data.models import StatusAmpel
from ...logic.aggregation import has_messdaten, has_prognose

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


def fmt_date(d) -> str:
    """Datum fuer die Kacheln: TT.MM.JJJJ."""
    return d.strftime("%d.%m.%Y")


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
                    status: StatusAmpel, value: Optional[float] = None, always_dot: bool = False):
    """Setzt eine Status-Zelle gemaess globalem SHOW_VALUES-Modus.
    Immer: unsichtbares Sort-Item fuer Sortierung.
    SHOW_VALUES=False → AmpelDot. SHOW_VALUES=True+value → Dot+Zahl.
    SHOW_VALUES=True+kein value → leere Zelle.
    ``always_dot``: immer der AmpelDot, auch bei SHOW_VALUES (Gesamtstatus der Zeile in Spalte 0).

    Das Widget wird in einen zentrierenden Wrapper gesetzt, damit der
    AmpelDot in der schmalen Status-Spalte (28 px) nicht an einen Rand
    rutscht oder vom QTableWidget-Padding (4 px) uebermalt wird.
    """
    table.setItem(row, col, _ampel_sort_item(status))
    # vorherigen CellWidget-Zustand immer bereinigen (auch nach setItem,
    # weil Qt das alte Widget sonst stehen lassen kann)
    table.removeCellWidget(row, col)
    if SHOW_VALUES and not always_dot:
        if value is None:
            return  # leer
        table.setCellWidget(row, col, _centered(_value_cell_widget(status, value)))
    else:
        table.setCellWidget(row, col, _centered(AmpelDot(status, size=10)))


# -----------------------------------------------------------
# Spalte "Messdaten vorhanden" (Diagramm-Symbol ganz rechts)
# -----------------------------------------------------------

MESSDATEN_TOOLTIP = "Historische Daten vorhanden"
_messdaten_icon = None


def _graph_icon():
    """Diagramm-Symbol; erst beim ersten Gebrauch erzeugt (braucht QApplication)."""
    global _messdaten_icon
    if _messdaten_icon is None:
        import qtawesome as qta
        _messdaten_icon = qta.icon("mdi.chart-line", color="#378ADD")
    return _messdaten_icon


PROGNOSE_TOOLTIP = "Prognose vorhanden"
_prognose_icon = None


def _prognose_symbol():
    """Diagramm mit durchgezogener Linie, die gepunktet weiterlaeuft (= Prognose).
    Selbst gezeichnet; erst beim ersten Gebrauch erzeugt (braucht QApplication)."""
    global _prognose_icon
    if _prognose_icon is None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
        size = 32
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        axis = QPen(QColor("#6B6F78"), 2)
        p.setPen(axis)
        p.drawLine(QPointF(4, 4), QPointF(4, 28))          # y-Achse
        p.drawLine(QPointF(4, 28), QPointF(29, 28))        # x-Achse
        solid = QPen(QColor("#378ADD"), 2.6)
        solid.setCapStyle(Qt.RoundCap)
        p.setPen(solid)
        p.drawPolyline(QPolygonF([QPointF(7, 21), QPointF(12, 14), QPointF(17, 17)]))
        dotted = QPen(QColor("#378ADD"), 2.6)
        dotted.setStyle(Qt.CustomDashLine)
        dotted.setDashPattern([0.1, 2.4])
        dotted.setCapStyle(Qt.RoundCap)
        p.setPen(dotted)
        p.drawPolyline(QPolygonF([QPointF(17, 17), QPointF(23, 9), QPointF(29, 6)]))
        p.end()
        _prognose_icon = QIcon(pm)
    return _prognose_icon


class _SymbolItem(QTableWidgetItem):
    """Zelle mit Symbol, wenn ``vorhanden``; sortiert danach (mit Symbol zuerst bei absteigend)."""
    def __init__(self, vorhanden: bool, icon_factory, tooltip: str):
        super().__init__()
        self.setData(Qt.UserRole, 1 if vorhanden else 0)
        self.setFlags(self.flags() & ~Qt.ItemIsEditable)
        self.setTextAlignment(Qt.AlignCenter)
        if vorhanden:
            self.setIcon(icon_factory())
            self.setToolTip(tooltip)

    def __lt__(self, other):
        try:
            return self.data(Qt.UserRole) < other.data(Qt.UserRole)
        except TypeError:
            return False


def set_messdaten_cell(table: QTableWidget, row: int, col: int, obj):
    """Setzt das Diagramm-Symbol, wenn ``obj`` selbst oder eine darunterliegende
    Komponente Messdaten hat; sonst bleibt die Zelle leer."""
    table.setItem(row, col, _SymbolItem(has_messdaten(obj), _graph_icon, MESSDATEN_TOOLTIP))


def set_prognose_cell(table: QTableWidget, row: int, col: int, obj):
    """Setzt das Prognose-Symbol (Linie, gepunktet fortgesetzt), wenn ``obj`` selbst oder eine
    darunterliegende Komponente Prognosewerte hat; sonst bleibt die Zelle leer."""
    table.setItem(row, col, _SymbolItem(has_prognose(obj), _prognose_symbol, PROGNOSE_TOOLTIP))


def _setup_symbol_column(table: QTableWidget, col: int, tooltip: str):
    table.setIconSize(QSize(16, 16))
    table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
    table.setColumnWidth(col, 30)
    item = table.horizontalHeaderItem(col)
    if item is not None:
        item.setToolTip(tooltip)


def setup_messdaten_column(table: QTableWidget, col: int):
    """Schmale, feste Symbolspalte (Messdaten vorhanden)."""
    _setup_symbol_column(table, col, MESSDATEN_TOOLTIP)


def setup_prognose_column(table: QTableWidget, col: int):
    """Schmale, feste Symbolspalte ganz rechts (Prognosewerte vorhanden)."""
    _setup_symbol_column(table, col, PROGNOSE_TOOLTIP)


# -----------------------------------------------------------
# Spaltenbreiten
# -----------------------------------------------------------

HEADER_EXTRA_PX = 30      # Kopfzeile: Innenabstand + Sortierpfeil
CELL_EXTRA_PX = 20        # Zelle: Innenabstand


def text_width(table: QTableWidget, col: int) -> int:
    """Breite in Pixeln, die Kopfzeile und alle Zellen der Spalte als Text brauchen (inkl. Rand)."""
    fm = table.fontMetrics()
    head = table.horizontalHeaderItem(col)
    w = fm.horizontalAdvance(head.text()) + HEADER_EXTRA_PX if head is not None else 0
    for row in range(table.rowCount()):
        item = table.item(row, col)
        if item is not None and item.text():
            w = max(w, fm.horizontalAdvance(item.text()) + CELL_EXTRA_PX)
    return w


def fit_to_text(table: QTableWidget, col: int):
    """Spalte so schmal wie ihr Text es zulaesst (statt Qt-Standardbreite)."""
    table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
    table.setColumnWidth(col, text_width(table, col))


class _FillColumn(QObject):
    """Haelt eine Spalte so breit, dass die Tabelle genau ausgefuellt ist, aber nie schmaler
    als ihr breitester Eintrag. Wird das Fenster schmaler, erscheint stattdessen der
    waagerechte Scrollbalken."""

    def __init__(self, table: QTableWidget, col: int):
        super().__init__(table)
        self._table, self.col = table, col
        table.viewport().installEventFilter(self)

    def apply(self):
        t = self._table
        t.horizontalHeader().setSectionResizeMode(self.col, QHeaderView.Fixed)
        others = sum(t.columnWidth(c) for c in range(t.columnCount())
                     if c != self.col and not t.isColumnHidden(c))
        t.setColumnWidth(self.col, max(text_width(t, self.col), t.viewport().width() - others))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self.apply()
        return False


def fill_column_min_text(table: QTableWidget, col: int):
    """Spalte ``col`` fuellt den freien Platz, bleibt aber mindestens so breit wie ihr Text.
    Nach dem Neuaufbau der Tabelle erneut aufrufen."""
    helper = getattr(table, "_fill_column", None)
    if helper is None or helper.col != col:
        helper = _FillColumn(table, col)
        table._fill_column = helper
    helper.apply()


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
        self._table.cellClicked.connect(self._on_cell_clicked)
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

    def _on_cell_clicked(self, row, col):
        """Klick auf ein Symbol (Historische Daten / Prognose vorhanden) blendet dessen Text ein;
        beim Ueberfahren mit der Maus zeigt ihn der normale Tooltip."""
        item = self._table.item(row, col)
        if isinstance(item, _SymbolItem) and not item.icon().isNull():
            QToolTip.showText(QCursor.pos(), item.toolTip(), self._table)

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
