"""Ebene 1: Flotte (Tabelle der Einheiten, Donut, Faelligkeiten)."""
from __future__ import annotations

from typing import List

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...data.models import Einheit, Flotte, PrognoseConfig, StatusAmpel
from ...logic.aggregation import (
    collect_gantt_entries,
    collect_messgroessen_values,
    n_real_achsen,
    n_real_dg,
    status_counts,
)

from ..overview_widgets import DonutPane, GanttPane

from .common import (
    BaseView,
    MGROESSEN_LABEL,
    MGROESSEN_SPALTEN,
    set_ampel_cell,
    set_messdaten_cell,
    set_prognose_cell,
    fill_column_min_text,
    fit_to_text,
    setup_messdaten_column,
    setup_prognose_column,
    show_values,
)


# -----------------------------------------------------------
# L1 Flotte
# -----------------------------------------------------------

class FlotteView(BaseView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheiten: List[Einheit] = []
        # PrognoseConfig fuer die Gantt-Berechnung — vom MainWindow gesetzt;
        # Default sorgt dafuer, dass set_flotte auch standalone laeuft.
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
                  [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN] + ["", ""]
        c_data = len(headers) - 2
        c_prog = len(headers) - 1
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._einheiten))
        # Etwas luftigere Zeilen in der Flottenuebersicht
        self._table.verticalHeader().setDefaultSectionSize(36)

        for row, e in enumerate(self._einheiten):
            set_ampel_cell(self._table, row, 0, e.status(), always_dot=True)
            self._table.setItem(row, 1, QTableWidgetItem(e.topeinheit_bez))
            self._table.setItem(row, 2, QTableWidgetItem(str(n_real_dg(e))))
            self._table.setItem(row, 3, QTableWidgetItem(
                str(sum(n_real_achsen(dg) for dg in e.drehgestelle.values()))))
            mg_data = collect_messgroessen_values(e)
            for i, mg in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(mg, (StatusAmpel.GRAY, None))
                set_ampel_cell(self._table, row, 4 + i, s, v)
            set_messdaten_cell(self._table, row, c_data, e)
            set_prognose_cell(self._table, row, c_prog, e)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter_edit.text())

        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        col_w = 76 if show_values() else 60
        for i in range(4, 4 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, col_w)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 28)
        setup_messdaten_column(self._table, c_data)
        setup_prognose_column(self._table, c_prog)
        fit_to_text(self._table, 2)          # Drehgestelle
        fit_to_text(self._table, 3)          # Achsen
        fill_column_min_text(self._table, 1)  # Einheit: fuellt, aber nie schmaler als der Text

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
