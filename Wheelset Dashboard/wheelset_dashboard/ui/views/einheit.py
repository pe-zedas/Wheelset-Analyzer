"""Ebene 2: Einheit (Tabelle der Drehgestelle)."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...data.models import Drehgestell, Einheit, Flotte, PrognoseConfig, StatusAmpel
from ...logic.aggregation import (
    collect_gantt_entries,
    collect_messgroessen_values,
    n_real_achsen,
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
# L2 Einheit
# -----------------------------------------------------------

class EinheitView(BaseView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheit: Optional[Einheit] = None
        self._dgs: List[Drehgestell] = []
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
        headers = ["", "DG-Position", "Achsen"] + [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN] + ["", ""]
        c_data = len(headers) - 2
        c_prog = len(headers) - 1
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._dgs))
        for row, dg in enumerate(self._dgs):
            set_ampel_cell(self._table, row, 0, dg.status(), always_dot=True)
            self._table.setItem(row, 1, QTableWidgetItem(dg.dg_einbaupos))
            self._table.setItem(row, 2, QTableWidgetItem(str(n_real_achsen(dg))))
            mg_data = collect_messgroessen_values(dg)
            for i, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                set_ampel_cell(self._table, row, 3 + i, s, v)
            set_messdaten_cell(self._table, row, c_data, dg)
            set_prognose_cell(self._table, row, c_prog, dg)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter_edit.text())
        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        col_w = 76 if show_values() else 60
        for i in range(3, 3 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, col_w)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 28)
        setup_messdaten_column(self._table, c_data)
        setup_prognose_column(self._table, c_prog)
        fit_to_text(self._table, 2)          # Achsen
        fill_column_min_text(self._table, 1)  # DG-Position: fuellt, aber nie schmaler als der Text

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
