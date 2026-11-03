"""Alle vier Hauptansichten (Flotte, Einheit, Drehgestell, Achse) + Lager.

Minimal-Variante fuer P3: Tabellen mit Status-Matrix.
Signalisiert via `drilldown(path)` einen Drill-Down-Wunsch an das Hauptfenster.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..data.models import (
    Achse, ComponentState, Drehgestell, Einheit, Flotte, LagerKomponente, Rad,
    Side, StatusAmpel, _worst_messreihe,
)
from .overview_widgets import DonutPane, GanttPane
from .plot_widget import PlotPane
from .widgets import AmpelDot, KpiCard, StatusPill, AMPEL_LABEL


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


def _iter_messreihen(obj):
    """Iteriert alle Messreihen unter einem Flotte-/Einheit-/DG-/Achse-Objekt."""
    if isinstance(obj, Flotte):
        for e in obj.einheiten.values():
            yield from _iter_messreihen(e)
    elif isinstance(obj, Einheit):
        for dg in obj.drehgestelle.values():
            yield from _iter_messreihen(dg)
    elif isinstance(obj, Drehgestell):
        for a in obj.achsen.values():
            yield from _iter_messreihen(a)
        for mr in obj.direkt_messreihen.values():
            yield mr
    elif isinstance(obj, Achse):
        for r in obj.raeder.values():
            for mr in r.messreihen.values():
                yield mr


def _status_counts(obj) -> Dict[StatusAmpel, int]:
    """Zaehlt Status ueber alle Messreihen (jede Reihe zaehlt separat)."""
    counts = {StatusAmpel.GREEN: 0, StatusAmpel.YELLOW: 0,
              StatusAmpel.RED: 0, StatusAmpel.GRAY: 0}
    for mr in _iter_messreihen(obj):
        counts[mr.status] = counts.get(mr.status, 0) + 1
    return counts


def _collect_messgroessen_values(obj) -> Dict[str, Tuple[StatusAmpel, Optional[float]]]:
    """Pro Messgroesse: Status und letzter Wert der schlechtesten Messreihe im Objekt."""
    out_mr: Dict[str, "Messreihe"] = {}

    def consider(mr):
        out_mr[mr.messgroesse] = _worst_messreihe(out_mr.get(mr.messgroesse), mr)

    if isinstance(obj, Einheit):
        for dg in obj.drehgestelle.values():
            for a in dg.achsen.values():
                for r in a.raeder.values():
                    for mr in r.messreihen.values():
                        consider(mr)
            for mr in dg.direkt_messreihen.values():
                consider(mr)
    elif isinstance(obj, Drehgestell):
        for a in obj.achsen.values():
            for r in a.raeder.values():
                for mr in r.messreihen.values():
                    consider(mr)
        for mr in obj.direkt_messreihen.values():
            consider(mr)
    elif isinstance(obj, Achse):
        for r in obj.raeder.values():
            for mr in r.messreihen.values():
                consider(mr)

    result: Dict[str, Tuple[StatusAmpel, Optional[float]]] = {}
    for name, mr in out_mr.items():
        letzt = mr.letzter_wert()
        result[name] = (mr.status, letzt.stand if letzt else None)
    return result


def _collect_messgroessen_statuses(obj) -> Dict[str, StatusAmpel]:
    """Sammelt Status je Messgroesse ueber alle Raeder / direkt_messreihen des Objekts."""
    out: Dict[str, StatusAmpel] = {}

    def add(mr):
        cur = out.get(mr.messgroesse, StatusAmpel.GRAY)
        from ..data.models import _worst_status
        out[mr.messgroesse] = _worst_status([cur, mr.status])

    if isinstance(obj, Einheit):
        for dg in obj.drehgestelle.values():
            for a in dg.achsen.values():
                for r in a.raeder.values():
                    for mr in r.messreihen.values():
                        add(mr)
            for mr in dg.direkt_messreihen.values():
                add(mr)
    elif isinstance(obj, Drehgestell):
        for a in obj.achsen.values():
            for r in a.raeder.values():
                for mr in r.messreihen.values():
                    add(mr)
        for mr in obj.direkt_messreihen.values():
            add(mr)
    elif isinstance(obj, Achse):
        for r in obj.raeder.values():
            for mr in r.messreihen.values():
                add(mr)
    return out


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


def _collect_gantt_entries(groups, flotte, prog_cfg):
    """Sammelt Reprof-/Warn-/Grenz-Termine pro Gruppe (Einheit oder DG).

    ``groups`` ist eine Liste ``(label, iterable_of_drehgestelle)``.
    Rueckgabe: Liste von
    ``(label, [(reprof_datum, achse_label), …],
             [(warn_datum, achse_label), …],
             [(grenz_datum, achse_label), …],
             note | None)``.

    ``note`` ist ein kurzer Status-Text, der in der Gantt-Zeile angezeigt
    wird, wenn fuer die Gruppe KEIN Marker erzeugt werden konnte. Die
    Gruppe erscheint in diesem Fall trotzdem (eigene Zeile), damit der
    Nutzer sieht, dass die Einheit vorhanden ist, aber nicht
    prognostizierbar:

    * ``keine historischen Daten vorhanden - Prognose konnte nicht erzeugt werden``
      → keine LKD-Messreihe oder Historie leer auf allen Raedern.
    * ``zu wenige historische Daten vorhanden - Prognose konnte nicht erzeugt werden``
      → Historie vorhanden, aber die Treppen-Prognose liefert nichts
      Verwertbares (zu wenige Punkte, keine km/Tag-Schaetzung …).

    Zeitlogik: Die Prognose-Treppe rechnet km ab dem letzten Messwert;
    km-Differenzen werden ueber die km/Tag-Rate in Tag-Differenzen
    umgerechnet und AB HEUTE aufaddiert.

    Pro Achse wird nur das kritischste Rad eingezeichnet (frueheste
    Grenzueberschreitung; sonst frueheste Warnung). Dessen
    Reprofilierungen, Warn- und Grenz-Marker werden aufgenommen; das
    andere Rad derselben Achse wird uebersprungen.
    """
    from ..logic.prognose import project_with_reprofs, crossings
    from .plot_widget import _estimate_km_per_day
    heute = datetime.now()
    out = []
    _side = {"left": "links", "right": "rechts", "unspecified": "–"}
    NOTE_NO_HISTORY = (
        "keine historischen Daten vorhanden - "
        "Prognose konnte nicht erzeugt werden"
    )
    NOTE_TOO_FEW = (
        "zu wenige historische Daten vorhanden - "
        "Prognose konnte nicht erzeugt werden"
    )
    for label, dgs in groups:
        reprofs: List[Tuple[datetime, str]] = []
        warns: List[Tuple[datetime, str]] = []
        grenze: List[Tuple[datetime, str]] = []
        has_any_history = False     # irgendein LKD-Datum vorhanden?
        has_any_prognose = False    # irgendeine Treppen-Prognose erzeugt?
        for dg in dgs:
            for achse in dg.achsen.values():
                # Pro Rad die Treppen-Prognose + Marker vorab berechnen.
                rad_marker = []   # (rad_reprofs, warn_d, grenz_d, axis_label)
                for seite, rad in achse.raeder.items():
                    mr = rad.messreihen.get("LKD")
                    if mr is None or not mr.historie:
                        continue
                    has_any_history = True
                    letzt = mr.letzter_wert()
                    if letzt is None or letzt.laufleistung is None:
                        continue
                    km_per_day = _estimate_km_per_day(mr)
                    if not km_per_day or km_per_day <= 0:
                        continue
                    treppen = project_with_reprofs(
                        mr, prog_cfg, flotte=flotte, achse=achse)
                    if not treppen:
                        continue
                    has_any_prognose = True
                    axis_label = (
                        f"{dg.dg_einbaupos} · {achse.rs_einbaupos} · "
                        f"Rad {_side.get(seite.value, seite.value)}"
                    )
                    def _km_to_date(km_val: float, _ref=letzt, _rate=km_per_day):
                        return heute + timedelta(
                            days=(km_val - _ref.laufleistung) / _rate)
                    rad_reprofs: List[Tuple[datetime, str]] = []
                    for (x1, y1), (x2, y2) in zip(treppen, treppen[1:]):
                        if x1 == x2 and y2 < y1:
                            rad_reprofs.append((_km_to_date(x1), axis_label))
                    warn_d = grenz_d = None
                    if letzt.gelb_min is not None:
                        cx = crossings(treppen, letzt.gelb_min)
                        if cx:
                            warn_d = _km_to_date(cx[0][0])
                    if letzt.min_val is not None:
                        cx = crossings(treppen, letzt.min_val)
                        if cx:
                            grenz_d = _km_to_date(cx[0][0])
                    rad_marker.append((rad_reprofs, warn_d, grenz_d, axis_label))
                if not rad_marker:
                    continue
                with_grenz = [r for r in rad_marker if r[2] is not None]
                if with_grenz:
                    crit = min(with_grenz, key=lambda r: r[2])
                else:
                    with_warn = [r for r in rad_marker if r[1] is not None]
                    if with_warn:
                        crit = min(with_warn, key=lambda r: r[1])
                    else:
                        crit = rad_marker[0]
                rad_reprofs, warn_d, grenz_d, axis_label = crit
                if grenz_d is not None:
                    rad_reprofs = [r for r in rad_reprofs if r[0] <= grenz_d]
                reprofs.extend(rad_reprofs)
                if warn_d is not None:
                    warns.append((warn_d, axis_label))
                if grenz_d is not None:
                    grenze.append((grenz_d, axis_label))
        reprofs.sort(key=lambda t: t[0])
        warns.sort(key=lambda t: t[0])
        grenze.sort(key=lambda t: t[0])
        if reprofs or warns or grenze:
            note = None
        elif not has_any_history:
            note = NOTE_NO_HISTORY
        elif not has_any_prognose:
            note = NOTE_TOO_FEW
        else:
            # Prognose vorhanden, aber keine Faelligkeit im Horizont —
            # fachlich auch "kein Treffer"; wir zeigen hier dennoch die
            # Zeile, aber ohne Note (bleibt leer).
            note = None
        out.append((label, reprofs, warns, grenze, note))
    return out


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
            dp_title = QLabel("Status Verteilung · alle Räder")
            dp_title.setProperty("class", "PanelTitle")
            dp.addWidget(dp_title)
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
        self._einheiten = sorted(flotte.einheiten.values(), key=lambda e: e.topeinheit_bez)
        self._flotte = flotte   # fuer _on_selection_changed benoetigt
        self._ensure_overview()
        n_e = len(self._einheiten)

        # Donut
        self._donut.canvas.set_counts(_status_counts(flotte), center_label="Messreihen")

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
        self._panel_title.setText(f"Einheiten · Status je Messgröße ({n_e})")
        headers = ["", "Einheit", "Drehgestelle", "Achsen"] + \
                  [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN]
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._einheiten))
        # Etwas luftigere Zeilen in der Flottenuebersicht
        self._table.verticalHeader().setDefaultSectionSize(36)

        for row, e in enumerate(self._einheiten):
            _set_ampel_cell(self._table, row, 0, e.status())
            self._table.setItem(row, 1, QTableWidgetItem(e.topeinheit_bez))
            self._table.setItem(row, 2, QTableWidgetItem(str(len(e.drehgestelle))))
            self._table.setItem(row, 3, QTableWidgetItem(
                str(sum(len(dg.achsen) for dg in e.drehgestelle.values()))))
            mg_data = _collect_messgroessen_values(e)
            for i, mg in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(mg, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, row, 4 + i, s, v)
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

        # Initiales Gantt aus der aktuell sichtbaren Tabellen-Reihenfolge
        self._rebuild_gantt_from_table()

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
        gantt_entries = _collect_gantt_entries(
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
            self._donut.canvas.set_counts(_status_counts(e), center_label=e.topeinheit_bez)
        else:
            if self._einheiten:
                self._donut.canvas.set_counts(
                    {s: sum(_status_counts(e).get(s, 0) for e in self._einheiten)
                     for s in StatusAmpel}, center_label="Messreihen")


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
            dp_t = QLabel("Status Verteilung"); dp_t.setProperty("class", "PanelTitle")
            dpl.addWidget(dp_t)
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

        self._donut.canvas.set_counts(_status_counts(einheit), center_label="Messreihen")
        self._gp_title.setText(f"Prognose Fälligkeiten LKD : Einheit {einheit.topeinheit_bez}")
        if not getattr(self, "_sort_hooked", False):
            self._table.model().layoutChanged.connect(
                lambda *_: self._rebuild_gantt_from_table())
            self._sort_hooked = True

        self._clear_kpis()

        self._panel_title.setText(f"Drehgestelle · {einheit.topeinheit_bez}")
        headers = ["", "DG-Position", "Achsen"] + [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN]
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._dgs))
        for row, dg in enumerate(self._dgs):
            _set_ampel_cell(self._table, row, 0, dg.status())
            self._table.setItem(row, 1, QTableWidgetItem(dg.dg_einbaupos))
            self._table.setItem(row, 2, QTableWidgetItem(str(len(dg.achsen))))
            mg_data = _collect_messgroessen_values(dg)
            for i, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, row, 3 + i, s, v)
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
        gantt_entries = _collect_gantt_entries(
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
            self._donut.canvas.set_counts(_status_counts(dg), center_label=dg.dg_einbaupos)


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
            dp_t = QLabel("Status Verteilung"); dp_t.setProperty("class", "PanelTitle")
            dpl.addWidget(dp_t)
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

        self._donut.canvas.set_counts(_status_counts(dg), center_label="Messreihen")
        self._gp_title.setText(
            f"Prognose Fälligkeiten LKD : {einheit.topeinheit_bez} · {dg.dg_einbaupos}")
        if not getattr(self, "_sort_hooked", False):
            self._table.model().layoutChanged.connect(
                lambda *_: self._rebuild_gantt_from_table())
            self._sort_hooked = True

        self._clear_kpis()

        self._panel_title.setText(f"Achsen · {dg.dg_einbaupos}  ({len(self._achsen)} Achsen)")
        headers = ["", "Achsen-Pos", "RS-Bezeichnung"] + [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN]
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)

        # Eine Zeile pro Achse (nicht pro Rad). Status/Messwerte aggregieren
        # beide Raeder; "schlechter gewinnt" (siehe _collect_messgroessen_values).
        self._rows = list(self._achsen)
        self._table.setRowCount(len(self._rows))
        for row, a in enumerate(self._rows):
            status = a.status()
            mg_data = _collect_messgroessen_values(a)
            _set_ampel_cell(self._table, row, 0, status)
            self._table.setItem(row, 1, QTableWidgetItem(a.rs_einbaupos))
            self._table.setItem(row, 2, QTableWidgetItem(a.rs_bez))
            for i, k in enumerate(MGROESSEN_SPALTEN):
                s, v = mg_data.get(k, (StatusAmpel.GRAY, None))
                _set_ampel_cell(self._table, row, 3 + i, s, v)
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
        gantt_entries = _collect_gantt_entries(groups, flotte, self._prog_cfg)
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
            self._donut.canvas.set_counts(_status_counts(a), center_label=a.rs_einbaupos)


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
        self._redraw_current()

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
            dg = prog.datum_grenzwert if prog else None
            dw = prog.datum_warnwert if prog else None
            kg = prog.km_grenzwert if prog else None
            kw = prog.km_warnwert if prog else None
            # Fallback: Schnittpunkt der eigenen Treppen-Prognose — der
            # Algorithmus ist nur fuer LKD gueltig, deshalb hier konditional.
            if (mr.messgroesse == "LKD" and (kg is None or kw is None)
                    and self._prognose_config):
                try:
                    from ..logic.prognose import project_with_reprofs, crossings
                    from ..ui.plot_widget import _estimate_km_per_day
                    treppen = project_with_reprofs(
                        mr, self._prognose_config,
                        flotte=self._flotte, achse=self._achse)
                    if treppen and letzt:
                        kmd = _estimate_km_per_day(mr)
                        if letzt.min_val is not None and kg is None:
                            cx = crossings(treppen, letzt.min_val)
                            if cx:
                                kg = cx[0][0]
                                if dg is None and kmd and kmd > 0 and letzt.laufleistung is not None:
                                    from datetime import timedelta as _td
                                    dg = letzt.datum + _td(days=(kg - letzt.laufleistung) / kmd)
                        if letzt.gelb_min is not None and kw is None:
                            cx = crossings(treppen, letzt.gelb_min)
                            if cx:
                                kw = cx[0][0]
                                if dw is None and kmd and kmd > 0 and letzt.laufleistung is not None:
                                    from datetime import timedelta as _td
                                    dw = letzt.datum + _td(days=(kw - letzt.laufleistung) / kmd)
                except Exception:
                    pass
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

        # Prognose-Status-Kachel ganz rechts. Zwei Varianten:
        # - Prognose vorhanden: Reprofilierungs-Intervall + Abtrag je Rad.
        # - Keine Prognose: Hinweistext.
        has_prognose = bool(getattr(current.canvas, "_prognose_available", False))
        info = getattr(current.canvas, "_prognose_info", []) or []
        if has_prognose and info:
            self._kennzahlen_row.addStretch(1)
            lines = []
            for label, interval_km, magnitude_mm in info:
                tkm = f"{interval_km/1000:,.0f}".replace(",", " ")
                mg = f"{magnitude_mm:.2f}".replace(".", ",")
                lines.append(
                    f"{label}: Reprofilierungsintervall {tkm} Tkm · Abtrag {mg} mm"
                )
            box = QLabel("\n".join(lines))
            box.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            box.setStyleSheet(
                "QLabel { color: #444441; font-size: 11px; "
                "background-color: #FFFFFF; border: 1px solid #D4D6DC; "
                "border-radius: 6px; padding: 6px 12px; }"
            )
            self._kennzahlen_row.addWidget(box)
        elif not has_prognose and self._prognose_config and getattr(
                self._prognose_config, "show_reprof_steps", False):
            self._kennzahlen_row.addStretch(1)
            hint = QLabel("Keine Prognose vorhanden")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet(
                "QLabel { color: #6B6F78; font-size: 11px; font-style: italic; "
                "background-color: #F5F6F8; border: 1px solid #D4D6DC; "
                "border-radius: 6px; padding: 8px 14px; }"
            )
            self._kennzahlen_row.addWidget(hint)
        else:
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
            # Donut: Status aller Messreihen in allen Lager-Komponenten
            dp_panel = QFrame(); dp_panel.setProperty("class", "Panel")
            dpl = QVBoxLayout(dp_panel); dpl.setContentsMargins(12, 10, 12, 10)
            dp_t = QLabel("Status Verteilung · alle Lager-Messreihen")
            dp_t.setProperty("class", "PanelTitle")
            dpl.addWidget(dp_t)
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

        # Donut 1: Status-Verteilung über alle Messreihen aller Lager-Komponenten
        status_counts = {s: 0 for s in StatusAmpel}
        for c in flotte.lager:
            for mr in c.messreihen.values():
                status_counts[mr.status] = status_counts.get(mr.status, 0) + 1
            for rad in c.raeder.values():
                for mr in rad.messreihen.values():
                    status_counts[mr.status] = status_counts.get(mr.status, 0) + 1
            for a in c.achsen.values():
                for rad in a.raeder.values():
                    for mr in rad.messreihen.values():
                        status_counts[mr.status] = status_counts.get(mr.status, 0) + 1
        self._donut.canvas.set_counts(status_counts, center_label="Messreihen")

        self._clear_kpis()

        title = "Lager-Komponenten"
        suffix = ""
        if filter_state == ComponentState.STORED_READY:
            suffix = " · einsatzbereit"
        elif filter_state == ComponentState.STORED_TO_OVERHAUL:
            suffix = " · zu überholen"
        self._panel_title.setText(f"{title}{suffix} ({len(items)})")
        self._gp_title.setText(f"Prognose Fälligkeiten LKD : Lager{suffix}")

        headers = ["", "Typ", "Bezeichnung", "letzte Einheit", "Ausbau", "Zustand"] + \
                  [MGROESSEN_LABEL[k] for k in MGROESSEN_SPALTEN]
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
        if not hasattr(self, "_gantt") or not self._items:
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
        gantt_entries = _collect_gantt_entries(groups, flotte, self._prog_cfg)
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

