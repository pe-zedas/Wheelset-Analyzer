"""Ebene 4: Achse (Diagramm je Messgroesse mit Kennzahlen)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from ...data.models import Achse, Drehgestell, Einheit, Side
from ...logic.prognose import faelligkeit_shift

from ..plot_widget import PlotPane
from ..widgets import KpiCard

from .common import fmt_num


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
        reihen = self._reihen_for(mg_name)
        current.canvas.plot_messreihen(
            reihen,
            y_label=f"{mg_name} [mm]",
            x_mode=self._x_mode,
            today=datetime.now(),
            prognose_config=self._prognose_config,
            flotte=self._flotte,
            achse=self._achse,
        )
        self._update_kennzahlen(mg_name, reihen)

    def _reihen_for(self, mg_name):
        """Messreihen der Messgroesse je Rad (gemaess Radauswahl) als
        ``(seite, messreihe, prognose)``."""
        reihen = []
        for seite, rad in self._achse.raeder.items():
            if self._side_filter != "both" and seite.value != self._side_filter:
                continue
            mr = rad.messreihen.get(mg_name)
            if mr is None:
                continue
            reihen.append((seite.value, mr, mr.prognose))
        return reihen

    def _update_kennzahlen(self, mg_name, reihen):
        """Kennzahlen unterhalb des Diagramms aktualisieren.

        Aufbau (von links nach rechts): [Kacheln Rad LINKS] [Radachsenbild]
        [Kacheln Rad RECHTS]. Raeder ohne Seitenangabe ("unspecified") werden an
        den Anfang gehaengt (vor dem linken Rad), damit das Mittelbild immer
        zwischen links und rechts bleibt.
        """
        self._clear_kennzahlen()
        unspec_cards: List[QWidget] = []
        left_cards: List[QWidget] = []
        right_cards: List[QWidget] = []
        for seite, mr, prog in reihen:
            cards = self._cards_for(mg_name, seite, mr, prog)
            if seite == "left":
                left_cards.extend(cards)
            elif seite == "right":
                right_cards.extend(cards)
            else:
                unspec_cards.extend(cards)

        for w in unspec_cards + left_cards:
            self._kennzahlen_row.addWidget(w)
        # Zentrale Radachsen-Illustration zwischen den beiden Seiten; nur wenn
        # ueberhaupt Seiten-Kacheln vorhanden sind.
        if left_cards or right_cards:
            radbild = self._radachse_bild()
            if radbild is not None:
                self._kennzahlen_row.addWidget(radbild, 0, Qt.AlignVCenter)
        for w in right_cards:
            self._kennzahlen_row.addWidget(w)
        # Die Prognose-Angaben (Warn-/Grenz-Datum und -km je Rad) stehen in den
        # Kacheln; nur ein Stretch bleibt, damit sie linksbuendig gruppiert sind.
        self._kennzahlen_row.addStretch(1)

    def _cards_for(self, mg_name, seite_key, mr, prog) -> List[QWidget]:
        """Kacheln eines Rades: letzter Messwert sowie Grenz- und Warntermin."""
        widgets: List[QWidget] = []
        seite_de = {"left": "links", "right": "rechts", "unspecified": "–"}.get(seite_key, seite_key)
        letzt = mr.letzter_wert()
        if letzt:
            card = KpiCard(f"{mg_name} {seite_de} (letzter)", f"{fmt_num(letzt.stand)} mm")
            card.set_status_border(mr.status)
            widgets.append(card)

        def add_prog_card(label_suffix, variant, date_val, km_val):
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

        # Werte stammen aus der Prognose-Tabelle (mr.prognose). Datumswerte werden
        # fuer die Anzeige ab heute verschoben (siehe faelligkeit_shift); km-Werte
        # bleiben unveraendert.
        dg = faelligkeit_shift(prog.datum_grenzwert, mr) if prog else None
        dw = faelligkeit_shift(prog.datum_warnwert, mr) if prog else None
        kg = prog.km_grenzwert if prog else None
        kw = prog.km_warnwert if prog else None
        add_prog_card("Grenz", "danger", dg, kg)
        add_prog_card("Warn", "warn", dw, kw)
        return widgets

    @staticmethod
    def _radachse_bild() -> Optional[QLabel]:
        """Radsatz-Illustration (PNG mit transparentem Hintergrund) oder ``None``."""
        img_path = Path(__file__).resolve().parent.parent / "assets" / "radachse.png"
        if not img_path.exists():
            return None
        radbild = QLabel()
        # Hoehe auf die volle Kachelhoehe (KpiCard ~ 73 px)
        pm = QPixmap(str(img_path)).scaledToHeight(73, Qt.SmoothTransformation)
        radbild.setPixmap(pm)
        radbild.setAlignment(Qt.AlignCenter)
        radbild.setAttribute(Qt.WA_TranslucentBackground, True)
        radbild.setStyleSheet("background: transparent;")
        radbild.setToolTip("Radsatz (links · rechts)")
        return radbild
