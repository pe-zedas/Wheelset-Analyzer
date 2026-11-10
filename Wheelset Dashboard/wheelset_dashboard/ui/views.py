"""Alle vier Hauptansichten (Flotte, Einheit, Drehgestell, Achse) + Lager.

Minimal-Variante fuer P3: Tabellen mit Status-Matrix.
Signalisiert via `drilldown(path)` einen Drill-Down-Wunsch an das Hauptfenster.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..logic.prognose import faelligkeit_shift
from ..logic.aggregation import (
    collect_gantt_entries, collect_messgroessen_values, has_messdaten, n_messpositionen,
    n_real_achsen, n_real_dg, status_counts,
)
from ..data.models import (
    Achse, ComponentState, Drehgestell, Einheit, Flotte, LagerKomponente, Side,
    StatusAmpel,
)
from .overview_widgets import DonutPane, GanttPane
from .plot_widget import PlotPane
from .widgets import AmpelDot, KpiCard


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


def _fmt_num(value: float, decimals: int = 1) -> str:
    """Europäische Zahlendarstellung mit Komma als Dezimaltrenner."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _value_cell_widget(status: StatusAmpel, value: Optional[float]) -> QWidget:
    """AmpelDot + letzter Messwert farbig daneben."""
    from .widgets import AMPEL_COLORS
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(2, 0, 2, 0)
    lay.setSpacing(4)
    lay.addWidget(AmpelDot(status, size=8))
    lab = QLabel(_fmt_num(value))
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


def _set_ampel_cell(table: QTableWidget, row: int, col: int,
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


def _set_messdaten_cell(table: QTableWidget, row: int, col: int, obj):
    """Setzt das Diagramm-Symbol, wenn ``obj`` selbst oder eine darunterliegende
    Komponente Messdaten hat; sonst bleibt die Zelle leer."""
    table.setItem(row, col, _MessdatenItem(has_messdaten(obj)))


def _setup_messdaten_column(table: QTableWidget, col: int):
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


# -----------------------------------------------------------
# L1 Flotte
# -----------------------------------------------------------

class FlotteView(BaseView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheiten: List[Einheit] = []
        # PrognoseConfig fuer die Gantt-Berechnung — vom MainWindow gesetzt;
        # Default sorgt dafuer, dass set_flotte auch standalone laeuft.
        from ..data.models import PrognoseConfig
        self._prog_cfg = PrognoseConfig()

    def set_prognose_config(self, cfg):
        self._prog_cfg = cfg

    def _ensure_overview(self):
        if not hasattr(self, "_overview_row"):
            self._overview_row = QHBoxLayout()
            self._overview_row.setSpacing(10)
            # Donut-Panel
            donut_panel = QFrame()
            donut_panel.setProperty("class", "Panel")
            dp = QVBoxLayout(donut_panel)
            dp.setContentsMargins(12, 10, 12, 10)
            self._dp_title = QLabel("Status Verteilung · alle Räder")
            self._dp_title.setProperty("class", "PanelTitle")
            dp.addWidget(self._dp_title)
            self._donut = DonutPane()
            dp.addWidget(self._donut)
            # Gantt-Panel
            gantt_panel = QFrame()
            gantt_panel.setProperty("class", "Panel")
            gp = QVBoxLayout(gantt_panel)
            gp.setContentsMargins(12, 10, 12, 10)
            self._gp_title = QLabel("Prognose Fälligkeiten LKD : Flotte")
            self._gp_title.setProperty("class", "PanelTitle")
            gp.addWidget(self._gp_title)
            self._gantt = GanttPane()
            gp.addWidget(self._gantt)
            self._overview_row.addWidget(donut_panel, 1)
            self._overview_row.addWidget(gantt_panel, 2)
            self._layout.addLayout(self._overview_row)

    def set_flotte(self, flotte: Flotte):
        # Waehrend des Fuellens loesen Sortier-Hook und Filter jeweils einen
        # Neuaufbau der Faelligkeiten-Kachel aus (je ~0.7 s bei ~170
        # Einheiten). Nur der abschliessende Aufbau ist noetig.
        self._gantt_suspended = True
        try:
            self._fill_flotte(flotte)
        finally:
            self._gantt_suspended = False
        # Initiales Gantt aus der aktuell sichtbaren Tabellen-Reihenfolge
        self._rebuild_gantt_from_table()

    def _fill_flotte(self, flotte: Flotte):
        self._einheiten = sorted(flotte.einheiten.values(), key=lambda e: e.topeinheit_bez)
        self._flotte = flotte   # fuer _on_selection_changed benoetigt
        self._ensure_overview()
        n_e = len(self._einheiten)

        # Donut
        self._donut.canvas.set_counts(status_counts(flotte), center_label="Räder")

        # Gantt wird spaeter aus der Tabellenreihenfolge gebaut (nach dem
        # Fuellen der Zeilen). Damit folgt die Kachel auch Sortierungen,
        # die der Nutzer per Spaltenkopf vornimmt.
        self._gp_title.setText("Prognose Fälligkeiten LKD : Flotte")

        # Signal nur einmal verbinden (idempotent via Attribut-Flag).
        # ``layoutChanged`` feuert erst NACH dem internen Umsortieren der
        # Zeilen; ``sortIndicatorChanged`` dagegen feuert davor, so dass der
        # Rebuild sonst die alte Zeilenreihenfolge lesen wuerde.
        if not getattr(self, "_sort_hooked", False):
            self._table.model().layoutChanged.connect(
                lambda *_: self._rebuild_gantt_from_table())
            self._sort_hooked = True

        # Panel
        self._panel_title.setText(
            f"Einheiten: Anzahl {n_e} - Status (anhand schlechtesten, "
            f"letzten Messwert)"
        )
        headers = ["", "Einheit", "Drehgestelle", "Achsen"] + \
                  [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN] + [""]
        c_data = len(headers) - 1
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._einheiten))
        # Etwas luftigere Zeilen in der Flottenuebersicht
        self._table.verticalHeader().setDefaultSectionSize(36)

        for row, e in enumerate(self._einheiten):
            _set_ampel_cell(self._table, row, 0, e.status())
            self._table.setItem(row, 1, QTableWidgetItem(e.topeinheit_bez))
            self._table.setItem(row, 2, QTableWidgetItem(str(n_real_dg(e))))
            self._table.setItem(row, 3, QTableWidgetItem(
                str(sum(n_real_achsen(dg) for dg in e.drehgestelle.values()))))
            mg_data = collect_messgroessen_values(e)
            for i, mg in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(mg, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, row, 4 + i, s, v)
            _set_messdaten_cell(self._table, row, c_data, e)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter_edit.text())

        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        col_w = 76 if SHOW_VALUES else 60
        for i in range(4, 4 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, col_w)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 28)
        _setup_messdaten_column(self._table, c_data)

    def _apply_filter(self, text: str):
        super()._apply_filter(text)
        # Filter blendet Zeilen aus; Kachel soll die ausgeblendeten auch
        # weglassen.
        if hasattr(self, "_gantt"):
            self._rebuild_gantt_from_table()

    def _rebuild_gantt_from_table(self):
        """Baut die Gantt-Kachel aus der aktuellen Reihenfolge der Tabelle
        (Sortierung + Filter beruecksichtigt)."""
        if not hasattr(self, "_gantt") or not self._einheiten:
            return
        if getattr(self, "_gantt_suspended", False):
            return
        flotte = getattr(self, "_flotte", None)
        if flotte is None:
            return
        ordered = []
        for row in range(self._table.rowCount()):
            if self._table.isRowHidden(row):
                continue
            e = self._einheit_from_row(row)
            if e is not None:
                ordered.append(e)
        gantt_entries = collect_gantt_entries(
            [(e.topeinheit_bez, e.drehgestelle.values()) for e in ordered],
            flotte, self._prog_cfg,
        )
        self._gantt.canvas.set_entries(gantt_entries, horizon_months=12)

    def _einheit_from_row(self, row: int):
        item = self._table.item(row, 1)
        if item is None:
            return None
        bez = item.text()
        return next((e for e in self._einheiten if e.topeinheit_bez == bez), None)

    def _on_double_click(self, row, col):
        e = self._einheit_from_row(row)
        if e:
            self.drilldown.emit([("einheit", e.topeinheit_bez)])

    def _on_selection_changed(self):
        # Auswahl bewegt NUR den Donut; die Fälligkeiten-Kachel wechselt
        # erst beim Doppelklick (= Drilldown in die naechste Ebene).
        row = self._selected_row()
        e = self._einheit_from_row(row)
        if e:
            self._donut.canvas.set_counts(status_counts(e), center_label="Räder")
            self._dp_title.setText(f"Status Verteilung · Räder · {e.topeinheit_bez}")
        else:
            if self._einheiten:
                self._donut.canvas.set_counts(
                    {s: sum(status_counts(e).get(s, 0) for e in self._einheiten)
                     for s in StatusAmpel}, center_label="Räder")
                self._dp_title.setText("Status Verteilung · alle Räder")


# -----------------------------------------------------------
# L2 Einheit
# -----------------------------------------------------------

class EinheitView(BaseView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheit: Optional[Einheit] = None
        self._dgs: List[Drehgestell] = []
        from ..data.models import PrognoseConfig
        self._prog_cfg = PrognoseConfig()
        self._flotte: Optional[Flotte] = None

    def set_prognose_config(self, cfg):
        self._prog_cfg = cfg

    def set_flotte(self, flotte: Flotte):
        self._flotte = flotte

    def _ensure_overview(self):
        if not hasattr(self, "_overview_row"):
            self._overview_row = QHBoxLayout()
            self._overview_row.setSpacing(10)
            dp_panel = QFrame(); dp_panel.setProperty("class", "Panel")
            dpl = QVBoxLayout(dp_panel); dpl.setContentsMargins(12, 10, 12, 10)
            self._dp_title = QLabel("Status Verteilung · Räder")
            self._dp_title.setProperty("class", "PanelTitle")
            dpl.addWidget(self._dp_title)
            self._donut = DonutPane(); dpl.addWidget(self._donut)
            gp_panel = QFrame(); gp_panel.setProperty("class", "Panel")
            gpl = QVBoxLayout(gp_panel); gpl.setContentsMargins(12, 10, 12, 10)
            self._gp_title = QLabel("Prognose Fälligkeiten LKD : Einheit")
            self._gp_title.setProperty("class", "PanelTitle")
            gpl.addWidget(self._gp_title)
            self._gantt = GanttPane(); gpl.addWidget(self._gantt)
            self._overview_row.addWidget(dp_panel, 1)
            self._overview_row.addWidget(gp_panel, 2)
            self._layout.addLayout(self._overview_row)

    def set_einheit(self, einheit: Einheit):
        self._einheit = einheit
        self._dgs = sorted(einheit.drehgestelle.values(), key=lambda d: d.dg_einbaupos)
        self._ensure_overview()

        self._donut.canvas.set_counts(status_counts(einheit), center_label="Räder")
        self._dp_title.setText(f"Status Verteilung · Räder · {einheit.topeinheit_bez}")
        self._gp_title.setText(f"Prognose Fälligkeiten LKD : Einheit {einheit.topeinheit_bez}")
        if not getattr(self, "_sort_hooked", False):
            self._table.model().layoutChanged.connect(
                lambda *_: self._rebuild_gantt_from_table())
            self._sort_hooked = True

        self._clear_kpis()

        self._panel_title.setText(f"Drehgestelle · {einheit.topeinheit_bez}")
        headers = ["", "DG-Position", "Achsen"] + [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN] + [""]
        c_data = len(headers) - 1
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._dgs))
        for row, dg in enumerate(self._dgs):
            _set_ampel_cell(self._table, row, 0, dg.status())
            self._table.setItem(row, 1, QTableWidgetItem(dg.dg_einbaupos))
            self._table.setItem(row, 2, QTableWidgetItem(str(n_real_achsen(dg))))
            mg_data = collect_messgroessen_values(dg)
            for i, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, row, 3 + i, s, v)
            _set_messdaten_cell(self._table, row, c_data, dg)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter_edit.text())
        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        col_w = 76 if SHOW_VALUES else 60
        for i in range(3, 3 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, col_w)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 28)

        # Initiales Gantt aus der aktuellen Tabellen-Reihenfolge
        self._rebuild_gantt_from_table()

    def _apply_filter(self, text: str):
        super()._apply_filter(text)
        if hasattr(self, "_gantt"):
            self._rebuild_gantt_from_table()

    def _rebuild_gantt_from_table(self):
        """Gantt aus der aktuellen Tabellen-Reihenfolge (Sortierung + Filter)."""
        if not hasattr(self, "_gantt") or not self._dgs:
            return
        flotte = self._flotte or type("F", (), {"einheiten": {}})()
        ordered = []
        for row in range(self._table.rowCount()):
            if self._table.isRowHidden(row):
                continue
            dg = self._dg_from_row(row)
            if dg is not None:
                ordered.append(dg)
        gantt_entries = collect_gantt_entries(
            [(dg.dg_einbaupos, [dg]) for dg in ordered],
            flotte, self._prog_cfg,
        )
        self._gantt.canvas.set_entries(gantt_entries)

    def _dg_from_row(self, row):
        item = self._table.item(row, 1)
        if item is None:
            return None
        pos = item.text()
        return next((d for d in self._dgs if d.dg_einbaupos == pos), None)

    def _on_double_click(self, row, col):
        dg = self._dg_from_row(row)
        if dg and self._einheit:
            self.drilldown.emit([
                ("einheit", self._einheit.topeinheit_bez),
                ("drehgestell", dg.dg_einbaupos),
            ])

    def _on_selection_changed(self):
        # Auswahl bewegt NUR den Donut; die Fälligkeiten-Kachel wechselt
        # erst beim Doppelklick in die DG-Ebene.
        row = self._selected_row()
        dg = self._dg_from_row(row)
        if dg:
            self._donut.canvas.set_counts(status_counts(dg), center_label=dg.dg_einbaupos)


# -----------------------------------------------------------
# L3 Drehgestell
# -----------------------------------------------------------

class DrehgestellView(BaseView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheit: Optional[Einheit] = None
        self._dg: Optional[Drehgestell] = None
        self._achsen: List[Achse] = []
        from ..data.models import PrognoseConfig
        self._prog_cfg = PrognoseConfig()
        self._flotte: Optional[Flotte] = None

    def set_prognose_config(self, cfg):
        self._prog_cfg = cfg

    def set_flotte(self, flotte: Flotte):
        self._flotte = flotte

    def _ensure_overview(self):
        if not hasattr(self, "_overview_row"):
            self._overview_row = QHBoxLayout()
            self._overview_row.setSpacing(10)
            dp_panel = QFrame(); dp_panel.setProperty("class", "Panel")
            dpl = QVBoxLayout(dp_panel); dpl.setContentsMargins(12, 10, 12, 10)
            self._dp_title = QLabel("Status Verteilung · Räder")
            self._dp_title.setProperty("class", "PanelTitle")
            dpl.addWidget(self._dp_title)
            self._donut = DonutPane(); dpl.addWidget(self._donut)
            gp_panel = QFrame(); gp_panel.setProperty("class", "Panel")
            gpl = QVBoxLayout(gp_panel); gpl.setContentsMargins(12, 10, 12, 10)
            self._gp_title = QLabel("Prognose Fälligkeiten LKD : Drehgestell")
            self._gp_title.setProperty("class", "PanelTitle")
            gpl.addWidget(self._gp_title)
            self._gantt = GanttPane(); gpl.addWidget(self._gantt)
            self._overview_row.addWidget(dp_panel, 1)
            self._overview_row.addWidget(gp_panel, 2)
            self._layout.addLayout(self._overview_row)

    def set_dg(self, einheit: Einheit, dg: Drehgestell):
        self._einheit = einheit
        self._dg = dg
        self._achsen = sorted(dg.achsen.values(), key=lambda a: a.rs_einbaupos)
        self._ensure_overview()

        self._donut.canvas.set_counts(status_counts(dg), center_label="Räder")
        self._dp_title.setText(
            f"Status Verteilung · Räder · {einheit.topeinheit_bez} · {dg.dg_einbaupos}")
        self._gp_title.setText(
            f"Prognose Fälligkeiten LKD : {einheit.topeinheit_bez} · {dg.dg_einbaupos}")
        if not getattr(self, "_sort_hooked", False):
            self._table.model().layoutChanged.connect(
                lambda *_: self._rebuild_gantt_from_table())
            self._sort_hooked = True

        self._clear_kpis()

        n_real = n_real_achsen(dg)
        n_pos = n_messpositionen(dg)
        if n_real == 0 and n_pos:
            # Keine Radsatz-Ebene in den Daten: Raeder nach Messreihenfolge
            self._panel_title.setText(
                f"Messpositionen · {dg.dg_einbaupos}  ({n_pos} Messpositionen)")
        else:
            self._panel_title.setText(f"Achsen · {dg.dg_einbaupos}  ({n_real} Achsen)")
        headers = ["", "Achsen-Pos", "RS-Bezeichnung"] + [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN] + [""]
        c_data = len(headers) - 1
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)

        # Eine Zeile pro Achse (nicht pro Rad). Status/Messwerte aggregieren
        # beide Raeder; "schlechter gewinnt" (siehe collect_messgroessen_values).
        self._rows = list(self._achsen)
        self._table.setRowCount(len(self._rows))
        for row, a in enumerate(self._rows):
            status = a.status()
            mg_data = collect_messgroessen_values(a)
            _set_ampel_cell(self._table, row, 0, status)
            self._table.setItem(row, 1, QTableWidgetItem(a.rs_einbaupos))
            self._table.setItem(row, 2, QTableWidgetItem(a.rs_bez))
            for i, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, row, 3 + i, s, v)
            _set_messdaten_cell(self._table, row, c_data, a)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter_edit.text())
        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        col_w = 76 if SHOW_VALUES else 60
        for i in range(3, 3 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, col_w)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 28)
        _setup_messdaten_column(self._table, c_data)

        # Initiales Gantt aus der aktuellen Tabellen-Reihenfolge
        self._rebuild_gantt_from_table()

    def _apply_filter(self, text: str):
        super()._apply_filter(text)
        if hasattr(self, "_gantt"):
            self._rebuild_gantt_from_table()

    def _rebuild_gantt_from_table(self):
        """Gantt pro Achse aus der aktuellen Tabellen-Reihenfolge."""
        if not hasattr(self, "_gantt") or not getattr(self, "_rows", None) or self._dg is None:
            return
        flotte = self._flotte or type("F", (), {"einheiten": {}})()
        dg = self._dg
        ordered = []
        for row in range(self._table.rowCount()):
            if self._table.isRowHidden(row):
                continue
            a = self._achse_from_row(row)
            if a is not None:
                ordered.append(a)
        groups = []
        for a in ordered:
            pseudo_dg = type("_PseudoDG", (), {
                "dg_einbaupos": dg.dg_einbaupos,
                "achsen": {a.rs_einbaupos: a},
            })()
            groups.append((a.rs_einbaupos, [pseudo_dg]))
        gantt_entries = collect_gantt_entries(groups, flotte, self._prog_cfg)
        self._gantt.canvas.set_entries(gantt_entries)

    def _achse_from_row(self, row):
        pos_item = self._table.item(row, 1)
        if pos_item is None:
            return None
        pos = pos_item.text()
        return next((a for a in self._rows if a.rs_einbaupos == pos), None)

    def _on_double_click(self, row, col):
        a = self._achse_from_row(row)
        if a and self._einheit and self._dg:
            self.drilldown.emit([
                ("einheit", self._einheit.topeinheit_bez),
                ("drehgestell", self._dg.dg_einbaupos),
                ("achse", a.rs_einbaupos),
            ])

    def _on_selection_changed(self):
        # Auswahl bewegt NUR den Donut; die Fälligkeiten-Kachel wechselt
        # erst beim Doppelklick in die Achsen-Ebene.
        row = self._selected_row()
        a = self._achse_from_row(row)
        if a:
            self._donut.canvas.set_counts(status_counts(a), center_label="Räder")
            self._dp_title.setText(
                f"Status Verteilung · Räder · "
                f"{self._einheit.topeinheit_bez} · {self._dg.dg_einbaupos} · {a.rs_einbaupos}"
            )


# -----------------------------------------------------------
# L4 Achse — Detail-Plot mit Reitern pro Messgroesse (P4)
# -----------------------------------------------------------

class AchseView(QWidget):
    """L4 Achsen-Detail: Reiter pro Messgroesse, Matplotlib-Plot.

    Fuer Prognose-faehige Messgroessen (LKD) werden Prognose-Fortsetzung,
    Warn-/Grenz-Datumslinien und Rad-Isolation unterstuetzt. Fuer andere
    Messgroessen nur die Historie gegen die Schwellen.
    """
    drilldown = Signal(list)   # fuer Konsistenz mit BaseView (ungenutzt in L4)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheit = None
        self._dg = None
        self._achse = None
        self._x_mode = "datum"
        self._side_filter = "both"   # both | left | right
        self._prognose_config = None   # von MainWindow gesetzt
        self._flotte = None             # fuer Fleet-Fallback der Prognose-Parameter

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # Kopf: KPIs
        self._kpi_row = QHBoxLayout()
        self._kpi_row.setSpacing(10)
        lay.addLayout(self._kpi_row)

        # Steuerleiste: x-Modus + Rad-Isolation
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        ctrl.addWidget(QLabel("X-Achse:"))
        self._x_combo = QComboBox()
        self._x_combo.addItems(["Datum", "Laufleistung [km]"])
        self._x_combo.currentIndexChanged.connect(self._on_x_mode_changed)
        ctrl.addWidget(self._x_combo)
        ctrl.addSpacing(16)
        ctrl.addWidget(QLabel("Rad:"))
        self._side_combo = QComboBox()
        self._side_combo.addItems(["Beide", "Nur links (LKD1)", "Nur rechts (LKD2)"])
        self._side_combo.currentIndexChanged.connect(self._on_side_changed)
        ctrl.addWidget(self._side_combo)
        ctrl.addStretch(1)
        lay.addLayout(ctrl)

        # Reiter je Messgroesse (werden pro Achse neu befuellt)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        lay.addWidget(self._tabs, 1)

        # unten: Kennzahlen-Zeile — horizontal scrollbar, damit alle
        # Kacheln (Letzter + Grenz + Warn je Rad + Hinweisbox) auch bei
        # schmalem Fenster erreichbar sind.
        from PySide6.QtWidgets import QScrollArea
        self._kennzahlen_container = QWidget()
        self._kennzahlen_row = QHBoxLayout(self._kennzahlen_container)
        # unteres Padding des Containers → Luft zwischen Kacheln und
        # horizontalem Scrollbalken.
        self._kennzahlen_row.setContentsMargins(0, 0, 0, 8)
        self._kennzahlen_row.setSpacing(10)
        self._kennzahlen_scroll = QScrollArea()
        self._kennzahlen_scroll.setWidget(self._kennzahlen_container)
        self._kennzahlen_scroll.setWidgetResizable(True)
        self._kennzahlen_scroll.setFrameShape(QScrollArea.NoFrame)
        self._kennzahlen_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._kennzahlen_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Hoehe: KpiCard ~73 px Natur + 8 px Container-Padding +
        # ~14 px fuer den horizontalen Scrollbalken.
        self._kennzahlen_scroll.setFixedHeight(100)
        lay.addWidget(self._kennzahlen_scroll)

    def set_prognose_config(self, cfg):
        self._prognose_config = cfg
        if hasattr(self, "_tabs") and self._achse is not None:
            self._redraw_current()

    def set_flotte(self, flotte):
        self._flotte = flotte

    # ------------------------------------------------------------------

    def _clear_kpis(self):
        while self._kpi_row.count():
            w = self._kpi_row.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _add_kpi(self, label, value, variant="default"):
        self._kpi_row.addWidget(KpiCard(label, value, variant=variant))

    def _clear_kennzahlen(self):
        while self._kennzahlen_row.count():
            w = self._kennzahlen_row.takeAt(0).widget()
            if w:
                w.deleteLater()

    # ------------------------------------------------------------------

    def set_achse(self, einheit: Einheit, dg: Drehgestell, achse: Achse):
        self._einheit = einheit
        self._dg = dg
        self._achse = achse

        self._clear_kpis()

        # Pro Messgroesse ein Tab bauen
        self._tabs.blockSignals(True)
        self._tabs.clear()
        verfuegbare = self._collect_messgroessen()
        for mg in verfuegbare:
            pane = PlotPane()
            self._tabs.addTab(pane, mg)
        self._tabs.blockSignals(False)
        if self._tabs.count() == 0:
            self._tabs.addTab(QLabel("Keine Messreihen vorhanden."), "–")
        self._tabs.currentChanged.connect(self._redraw_current)
        self._sync_controls()
        self._redraw_current()

    def _sync_controls(self):
        """Passt X-Achse und Radauswahl an die geoeffnete Achse an.

        Die Ansicht wird fuer alle Achsen wiederverwendet; eine fruehere Auswahl
        (``Laufleistung [km]``, ``Nur links``) bliebe sonst stehen. Bei Abellio/MOB
        gibt es weder Laufleistung noch Radseite -> das Diagramm waere leer.
        Nicht verfuegbare Auswahl wird deaktiviert und auf den Standard gesetzt.
        """
        raeder = self._achse.raeder
        has_km = any(mp.laufleistung is not None
                     for r in raeder.values() for mr in r.messreihen.values()
                     for mp in mr.historie)
        sided = any(side != Side.UNSPECIFIED for side in raeder)

        km_item = self._x_combo.model().item(1)
        km_item.setEnabled(has_km)
        self._x_combo.setItemData(
            1, "" if has_km else "Keine Laufleistung in den Daten dieser Achse",
            Qt.ToolTipRole)
        if not has_km and self._x_combo.currentIndex() != 0:
            self._x_combo.blockSignals(True)
            self._x_combo.setCurrentIndex(0)
            self._x_combo.blockSignals(False)
            self._x_mode = "datum"

        self._side_combo.setEnabled(sided)
        self._side_combo.setToolTip(
            "" if sided else "Die Messwerte dieser Achse haben keine Radseite")
        if not sided and self._side_combo.currentIndex() != 0:
            self._side_combo.blockSignals(True)
            self._side_combo.setCurrentIndex(0)
            self._side_combo.blockSignals(False)
            self._side_filter = "both"

    def _collect_messgroessen(self):
        """Alle Messgroessen, die auf dieser Achse ueberhaupt vorkommen."""
        out = []
        seen = set()
        for seite, rad in self._achse.raeder.items():
            for mg in rad.messreihen.keys():
                if mg not in seen:
                    seen.add(mg)
                    out.append(mg)
        # LKD immer zuerst
        out.sort(key=lambda m: (0 if m == "LKD" else 1, m))
        return out

    # ------------------------------------------------------------------

    def _on_x_mode_changed(self, idx):
        self._x_mode = "datum" if idx == 0 else "km"
        self._redraw_current()

    def _on_side_changed(self, idx):
        self._side_filter = {0: "both", 1: "left", 2: "right"}[idx]
        self._redraw_current()

    def _redraw_current(self):
        if self._tabs.count() == 0 or self._achse is None:
            return
        current = self._tabs.currentWidget()
        if not isinstance(current, PlotPane):
            return
        mg_name = self._tabs.tabText(self._tabs.currentIndex())

        reihen = []
        for seite, rad in self._achse.raeder.items():
            if self._side_filter != "both" and seite.value != self._side_filter:
                continue
            mr = rad.messreihen.get(mg_name)
            if mr is None:
                continue
            reihen.append((seite.value, mr, mr.prognose))

        current.canvas.plot_messreihen(
            reihen,
            y_label=f"{mg_name} [mm]",
            x_mode=self._x_mode,
            today=datetime.now(),
            prognose_config=self._prognose_config,
            flotte=self._flotte,
            achse=self._achse,
        )

        # Kennzahlen unterhalb aktualisieren.
        # Aufbau pro Zeile (von links nach rechts):
        #   [Kacheln Rad LINKS]  [Radachsenbild]  [Kacheln Rad RECHTS]
        #   [Hinweisbox]
        # Räder ohne Seitenangabe ("unspecified") werden an den Anfang
        # gehängt (vor dem linken Rad), damit das Mittelbild immer
        # zwischen links und rechts bleibt.
        self._clear_kennzahlen()
        _side_label = {"left": "links", "right": "rechts", "unspecified": "–"}

        def _build_cards_for(seite_key: str, mr, prog):
            """Baut die KpiCards fuer ein Rad und liefert sie als Liste zurueck."""
            widgets: List[QWidget] = []
            seite_de = _side_label.get(seite_key, seite_key)
            letzt = mr.letzter_wert()
            if letzt:
                card = KpiCard(
                    f"{mg_name} {seite_de} (letzter)",
                    f"{_fmt_num(letzt.stand)} mm")
                card.set_status_border(mr.status)
                widgets.append(card)

            def _add_prog_card(label_suffix, variant, date_val, km_val):
                if date_val is None and km_val is None:
                    return
                date_txt = date_val.date().isoformat() if date_val else "–"
                km_txt = (f"{km_val/1000:,.0f} Tkm".replace(",", " ")
                          if km_val is not None else "–")
                if self._x_mode == "km":
                    main_txt, sub_txt = km_txt, date_txt
                else:
                    main_txt, sub_txt = date_txt, km_txt
                card = KpiCard(f"{seite_de} · {label_suffix}", main_txt, variant=variant)
                if sub_txt and sub_txt != "–":
                    card.setSubValue(sub_txt)
                widgets.append(card)
            # Werte stammen aus der Prognose-Tabelle (mr.prognose).
            # Datumswerte werden fuer die Anzeige ab heute verschoben
            # (siehe faelligkeit_shift); km-Werte bleiben unveraendert.
            dg = faelligkeit_shift(prog.datum_grenzwert, mr) if prog else None
            dw = faelligkeit_shift(prog.datum_warnwert, mr) if prog else None
            kg = prog.km_grenzwert if prog else None
            kw = prog.km_warnwert if prog else None
            _add_prog_card("Grenz", "danger", dg, kg)
            _add_prog_card("Warn", "warn", dw, kw)
            return widgets

        # Kacheln pro Rad sammeln und in drei Gruppen aufteilen:
        # - unspec: Räder ohne Seitenangabe (eher Ausnahme) → nach ganz links
        # - left_cards, right_cards: die eigentlichen Seiten
        unspec_cards: List[QWidget] = []
        left_cards: List[QWidget] = []
        right_cards: List[QWidget] = []
        for seite, mr, prog in reihen:
            cards = _build_cards_for(seite, mr, prog)
            if seite == "left":
                left_cards.extend(cards)
            elif seite == "right":
                right_cards.extend(cards)
            else:
                unspec_cards.extend(cards)

        for w in unspec_cards:
            self._kennzahlen_row.addWidget(w)
        for w in left_cards:
            self._kennzahlen_row.addWidget(w)

        # Zentrale Radachsen-Illustration zwischen den beiden Seiten.
        # Nur fuer die LKD-Ansicht (bzw. wenn ueberhaupt Seiten-Kacheln
        # vorhanden sind) und wenn das Bild im Package liegt.
        if (left_cards or right_cards):
            img_path = Path(__file__).parent / "assets" / "radachse.png"
            if img_path.exists():
                from PySide6.QtGui import QPixmap
                radbild = QLabel()
                pm = QPixmap(str(img_path))
                # Hoehe auf die volle Kachelhoehe (KpiCard ~ 73 px
                # ausgedehnt). PNG mit transparentem Hintergrund — kein
                # weisser Block mehr zwischen den Kacheln.
                pm = pm.scaledToHeight(73, Qt.SmoothTransformation)
                radbild.setPixmap(pm)
                radbild.setAlignment(Qt.AlignCenter)
                radbild.setAttribute(Qt.WA_TranslucentBackground, True)
                radbild.setStyleSheet("background: transparent;")
                radbild.setToolTip("Radsatz (links · rechts)")
                self._kennzahlen_row.addWidget(radbild, 0, Qt.AlignVCenter)

        for w in right_cards:
            self._kennzahlen_row.addWidget(w)

        # Die frueher ganz rechts angezeigte Prognose-Info-Box ist
        # entfallen: ihre Angaben (Warn-/Grenz-Datum und -km je Rad)
        # stehen bereits in den Kacheln links und rechts vom Radsatz-
        # Bild. Nur ein Stretch bleibt, damit die Kacheln links
        # buendig gruppiert sind.
        self._kennzahlen_row.addStretch(1)


# -----------------------------------------------------------
# Lager-View
# -----------------------------------------------------------


class LagerView(BaseView):
    # Signal fuer Drilldown in eine Achse unter einem Lager-DG
    lager_drilldown = Signal(object, object)  # (komponente, achse|None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_state: Optional[ComponentState] = None
        self._items: List[LagerKomponente] = []
        self._filter_edit.setPlaceholderText(
            "Bezeichnung · Einheit · Typ · Zustand …")

    def _ensure_overview(self):
        if not hasattr(self, "_overview_row"):
            self._overview_row = QHBoxLayout()
            self._overview_row.setSpacing(10)
            # Donut: Status pro Rad in den aktuell sichtbaren Lager-Komponenten
            dp_panel = QFrame(); dp_panel.setProperty("class", "Panel")
            dpl = QVBoxLayout(dp_panel); dpl.setContentsMargins(12, 10, 12, 10)
            self._dp_title = QLabel("Status Verteilung · alle Lager-Räder")
            self._dp_title.setProperty("class", "PanelTitle")
            dpl.addWidget(self._dp_title)
            self._donut = DonutPane(); dpl.addWidget(self._donut)
            # Gantt: Fälligkeiten je Lagerkomponente
            gp_panel = QFrame(); gp_panel.setProperty("class", "Panel")
            gpl = QVBoxLayout(gp_panel); gpl.setContentsMargins(12, 10, 12, 10)
            self._gp_title = QLabel("Prognose Fälligkeiten LKD : Lager")
            self._gp_title.setProperty("class", "PanelTitle")
            gpl.addWidget(self._gp_title)
            self._gantt = GanttPane(); gpl.addWidget(self._gantt)
            self._overview_row.addWidget(dp_panel, 1)
            self._overview_row.addWidget(gp_panel, 2)
            self._layout.addLayout(self._overview_row)
        # PrognoseConfig fuer die Treppen-Prognose (Default genuegt;
        # das Hauptfenster kann sie spaeter per set_prognose_config()
        # ueberschreiben).
        if not hasattr(self, "_prog_cfg"):
            from ..data.models import PrognoseConfig
            self._prog_cfg = PrognoseConfig()
        if not hasattr(self, "_flotte_ref"):
            self._flotte_ref = None

    def set_prognose_config(self, cfg):
        self._prog_cfg = cfg

    def set_flotte(self, flotte: Flotte, filter_state: Optional[ComponentState] = None):
        self._filter_state = filter_state
        self._ensure_overview()
        self._flotte_ref = flotte
        items = flotte.lager
        if filter_state is not None:
            items = [c for c in items if c.state == filter_state]
        items = sorted(items, key=lambda c: c.ausbau or datetime(1970, 1, 1), reverse=True)
        self._items = items

        # Signal fuer Live-Sortierung einmalig verbinden
        if not getattr(self, "_sort_hooked", False):
            self._table.model().layoutChanged.connect(
                lambda *_: self._rebuild_gantt_from_table())
            self._sort_hooked = True

        # Donut: Status-Verteilung — ein Status pro Rad; nur die aktuell
        # sichtbaren Lagerkomponenten (Filter beachten). Gleiche Zaehlregel
        # wie in allen anderen Ansichten (logic.aggregation.status_counts).
        self._donut.canvas.set_counts(status_counts(items), center_label="Räder")

        self._clear_kpis()

        title = "Lager-Komponenten"
        suffix = ""
        if filter_state == ComponentState.STORED_READY:
            suffix = " · einsatzbereit"
        elif filter_state == ComponentState.STORED_TO_OVERHAUL:
            suffix = " · zu überholen"
        self._panel_title.setText(
            f"{title}{suffix}: Anzahl {len(items)} - Status "
            f"(anhand schlechtesten, letzten Messwert)"
        )
        self._gp_title.setText(f"Prognose Fälligkeiten LKD : Lager{suffix}")
        self._dp_title.setText(f"Status Verteilung · Lager-Räder{suffix}")

        headers = ["", "Typ", "Bezeichnung", "letzte Einheit", "Ausbau", "Zustand"] + \
                  [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN] + [""]
        c_data = len(headers) - 1
        # Beim Fuellen temporaer Sortierung aus, sonst wandern Zeilen beim Einfuegen
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(items))
        for i, c in enumerate(items):
            _set_ampel_cell(self._table, i, 0, c.status())

            kind_text = "Drehgestell" if c.kind == "drehgestell" else "Achse"
            if c.kind == "drehgestell" and c.achsen:
                kind_text += f" ({len(c.achsen)})"
            self._table.setItem(i, 1, QTableWidgetItem(kind_text))

            bez = c.dg_bez if c.kind == "drehgestell" else c.rs_bez
            self._table.setItem(i, 2, QTableWidgetItem(bez or "-"))
            self._table.setItem(i, 3, QTableWidgetItem(c.letzte_einheit or "-"))

            # Ausbau: ISO-Text ist bereits chronologisch sortierbar
            ausbau_item = QTableWidgetItem(
                c.ausbau.date().isoformat() if c.ausbau else "-")
            self._table.setItem(i, 4, ausbau_item)

            self._table.setItem(i, 5, QTableWidgetItem(
                "einsatzbereit" if c.state == ComponentState.STORED_READY else "zu überholen"))

            mg_data = c.messgroessen_data()
            for j, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, i, 6 + j, s, v)
            _set_messdaten_cell(self._table, i, c_data, c)
        self._table.setSortingEnabled(True)

        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed); self._table.setColumnWidth(0, 28)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed); self._table.setColumnWidth(1, 90)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive); self._table.setColumnWidth(2, 160)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)   # Stretch jetzt auf "letzte Einheit"
        hdr.setSectionResizeMode(4, QHeaderView.Fixed); self._table.setColumnWidth(4, 90)
        hdr.setSectionResizeMode(5, QHeaderView.Fixed); self._table.setColumnWidth(5, 110)
        col_w = 76 if SHOW_VALUES else 60
        for j in range(6, 6 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(j, QHeaderView.Fixed)
            self._table.setColumnWidth(j, col_w)
        _setup_messdaten_column(self._table, c_data)

        # Gantt-Kachel aus der aktuellen Zeilenreihenfolge aufbauen
        self._rebuild_gantt_from_table()

    def _apply_filter(self, text: str):
        super()._apply_filter(text)
        if hasattr(self, "_gantt"):
            self._rebuild_gantt_from_table()

    def _rebuild_gantt_from_table(self):
        """Gantt aus der aktuellen Reihenfolge der Lager-Tabelle (Sortierung +
        Freitext-Filter beruecksichtigt). Jede Lagerkomponente wird als
        eigene Gruppe uebergeben:

        * ``kind == 'drehgestell'`` → Pseudo-DG mit den eingebauten Achsen.
        * ``kind == 'achse'`` → Pseudo-DG, der genau eine Pseudo-Achse mit
          den Raedern dieser Lagerachse enthaelt.
        """
        if not hasattr(self, "_gantt"):
            return
        if not self._items:
            # Leeres Lager (z.B. MOB): Hinweis statt Standard-Diagramm bzw.
            # Resten des vorherigen Profils.
            self._gantt.canvas.set_entries([])
            return
        ordered = []
        for row in range(self._table.rowCount()):
            if self._table.isRowHidden(row):
                continue
            c = self._row_to_component(row)
            if c is not None:
                ordered.append(c)
        groups = []
        for c in ordered:
            label = (c.dg_bez if c.kind == "drehgestell" else c.rs_bez) or "-"
            if c.kind == "drehgestell":
                pseudo_dg = type("_LagerDG", (), {
                    "dg_einbaupos": label,
                    "achsen": c.achsen,
                })()
            else:
                pseudo_axle = type("_LagerAxle", (), {
                    "rs_einbaupos": label,
                    "raeder": c.raeder,
                })()
                pseudo_dg = type("_LagerDG", (), {
                    "dg_einbaupos": "–",
                    "achsen": {label: pseudo_axle},
                })()
            groups.append((label, [pseudo_dg]))
        flotte = self._flotte_ref or type("F", (), {"einheiten": {}})()
        gantt_entries = collect_gantt_entries(groups, flotte, self._prog_cfg)
        self._gantt.canvas.set_entries(gantt_entries, horizon_months=12)

    def _row_to_component(self, row: int) -> Optional[LagerKomponente]:
        """Weil Sortierung den Zeilenindex verschiebt, laufen wir ueber den
        Bezeichnungs-Text und finden das Original-Objekt."""
        if row < 0:
            return None
        item = self._table.item(row, 2)
        if item is None:
            return None
        bez = item.text()
        kind_text = self._table.item(row, 1).text() if self._table.item(row, 1) else ""
        is_dg = kind_text.startswith("Drehgestell")
        for c in self._items:
            cand = c.dg_bez if c.kind == "drehgestell" else c.rs_bez
            if (cand or "-") == bez and (c.kind == "drehgestell") == is_dg:
                return c
        return None

    def _on_double_click(self, row, col):
        c = self._row_to_component(row)
        if c is None:
            return
        # Immer Komponente ohne Achsenvorauswahl weiterreichen – MainWindow
        # entscheidet, ob die Achsenliste (DG) oder direkt die AchseView zu zeigen ist.
        self.lager_drilldown.emit(c, None)

