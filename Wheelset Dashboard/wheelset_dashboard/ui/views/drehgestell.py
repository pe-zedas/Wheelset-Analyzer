"""Ebene 3: Drehgestell (Tabelle der Achsen bzw. Messpositionen)."""
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

from ...data.models import Achse, Drehgestell, Einheit, Flotte, PrognoseConfig, StatusAmpel
from ...logic.aggregation import (
    collect_gantt_entries,
    collect_messgroessen_values,
    n_messpositionen,
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
    setup_messdaten_column,
    show_values,
)


# -----------------------------------------------------------
# L3 Drehgestell
# -----------------------------------------------------------

class DrehgestellView(BaseView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._einheit: Optional[Einheit] = None
        self._dg: Optional[Drehgestell] = None
        self._achsen: List[Achse] = []
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
            set_ampel_cell(self._table, row, 0, status)
            self._table.setItem(row, 1, QTableWidgetItem(a.rs_einbaupos))
            self._table.setItem(row, 2, QTableWidgetItem(a.rs_bez))
            for i, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                set_ampel_cell(self._table, row, 3 + i, s, v)
            set_messdaten_cell(self._table, row, c_data, a)
        self._table.setSortingEnabled(True)
        self._apply_filter(self._filter_edit.text())
        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        col_w = 76 if show_values() else 60
        for i in range(3, 3 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, col_w)
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 28)
        setup_messdaten_column(self._table, c_data)

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
