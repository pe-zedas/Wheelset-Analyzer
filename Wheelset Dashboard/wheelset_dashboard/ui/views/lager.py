"""Lager: ausgebaute Komponenten mit Status und Faelligkeiten."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...data.models import ComponentState, Flotte, LagerKomponente, PrognoseConfig, StatusAmpel
from ...logic.aggregation import collect_gantt_entries, status_counts

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
            set_ampel_cell(self._table, i, 0, c.status())

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
                set_ampel_cell(self._table, i, 6 + j, s, v)
            set_messdaten_cell(self._table, i, c_data, c)
        self._table.setSortingEnabled(True)

        self._table.resizeColumnsToContents()
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed); self._table.setColumnWidth(0, 28)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed); self._table.setColumnWidth(1, 90)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive); self._table.setColumnWidth(2, 160)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)   # Stretch jetzt auf "letzte Einheit"
        hdr.setSectionResizeMode(4, QHeaderView.Fixed); self._table.setColumnWidth(4, 90)
        hdr.setSectionResizeMode(5, QHeaderView.Fixed); self._table.setColumnWidth(5, 110)
        col_w = 76 if show_values() else 60
        for j in range(6, 6 + len(MGROESSEN_SPALTEN)):
            hdr.setSectionResizeMode(j, QHeaderView.Fixed)
            self._table.setColumnWidth(j, col_w)
        setup_messdaten_column(self._table, c_data)

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
