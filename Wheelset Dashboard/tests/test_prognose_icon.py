"""Spalte "Prognosewerte vorhanden" (ganz rechts, rechts neben dem Messdaten-Symbol) und das
Datumsformat TT.MM.JJJJ in den Kacheln des Achsen-Diagramms."""
import re
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from wheelset_dashboard.data.models import (
    Achse, Drehgestell, Einheit, Flotte, LagerKomponente, Messpunkt, Messreihe, Prognose,
    PrognosePunkt, Rad, Side,
)
from wheelset_dashboard.logic.aggregation import has_prognose
from wheelset_dashboard.ui.views import (
    AchseView, DrehgestellView, EinheitView, FlotteView, LagerView, MESSDATEN_TOOLTIP, PROGNOSE_TOOLTIP,
)

pytestmark = pytest.mark.usefixtures("qapp")
T = datetime(2024, 1, 1)


def reihe(prognose="keine", historie=True):
    hist = [Messpunkt(datum=T, stand=800.0)] if historie else []
    prog = None
    if prognose == "punkte":
        prog = Prognose(punkte=[PrognosePunkt(datum=T + timedelta(days=30), stand=790.0)])
    elif prognose == "termin":
        prog = Prognose(datum_grenzwert=T + timedelta(days=400))
    elif prognose == "leer":
        prog = Prognose()
    return Messreihe(messgroesse="LKD", historie=hist, prognose=prog)


def achse(pos, mr):
    rad = Rad(seite=Side.LEFT, messreihen={"LKD": mr})
    return Achse(rs_id=None, rs_bez="", rs_einbaupos=pos, raeder={Side.LEFT: rad})


def dg(pos, *achsen):
    return Drehgestell(dg_id=None, dg_bez=pos, dg_einbaupos=pos, achsen={a.rs_einbaupos: a for a in achsen})


@pytest.fixture
def flotte():
    f = Flotte()
    a = Einheit(topeinheit_id=None, topeinheit_bez="Zug A", drehgestelle={
        "DG1": dg("DG1", achse("Achse 1", reihe("punkte")), achse("Achse 2", reihe("keine"))),
        "DG2": dg("DG2", achse("Achse 1", reihe("leer"))),
        "DG3": dg("DG3", achse("Achse 1", reihe("termin"))),
        "DG4": dg("DG4", achse("Achse 1", reihe("punkte", historie=False)))})
    b = Einheit(topeinheit_id=None, topeinheit_bez="Zug B",
                drehgestelle={"DG1": dg("DG1", achse("Achse 1", reihe("keine")))})
    f.einheiten = {"Zug A": a, "Zug B": b}
    f.lager = [
        LagerKomponente(rs_id=None, rs_bez="", letzte_einheit="E", ausbau=T, kind="drehgestell", dg_bez="LDG mit",
                        achsen={"A1": achse("A1", reihe("punkte"))}),
        LagerKomponente(rs_id=None, rs_bez="", letzte_einheit="E", ausbau=T, kind="drehgestell", dg_bez="LDG ohne",
                        achsen={"A1": achse("A1", reihe("keine"))})]
    return f


def prog_spalte(table, text_col):
    last = table.columnCount() - 1
    return {table.item(r, text_col).text(): not table.item(r, last).icon().isNull()
            for r in range(table.rowCount())}


def test_regel_prognose_vorhanden(flotte):
    a = flotte.einheiten["Zug A"]
    assert has_prognose(flotte) and has_prognose(a) and not has_prognose(flotte.einheiten["Zug B"])
    assert has_prognose(a.drehgestelle["DG1"]) and has_prognose(a.drehgestelle["DG3"])   # Treppe / nur Termin
    assert not has_prognose(a.drehgestelle["DG2"])          # leeres Prognoseobjekt
    assert not has_prognose(a.drehgestelle["DG4"])          # Prognose ohne Messwerte
    assert [has_prognose(c) for c in flotte.lager] == [True, False]


def test_flottentabelle(flotte):
    v = FlotteView(); v.set_flotte(flotte)
    assert prog_spalte(v._table, 1) == {"Zug A": True, "Zug B": False}


def test_einheitentabelle(flotte):
    v = EinheitView(); v.set_flotte(flotte); v.set_einheit(flotte.einheiten["Zug A"])
    assert prog_spalte(v._table, 1) == {"DG1": True, "DG2": False, "DG3": True, "DG4": False}


def test_drehgestelltabelle(flotte):
    v = DrehgestellView(); v.set_flotte(flotte)
    e = flotte.einheiten["Zug A"]
    v.set_dg(e, e.drehgestelle["DG1"])
    assert prog_spalte(v._table, 1) == {"Achse 1": True, "Achse 2": False}


def test_lagertabelle(flotte):
    v = LagerView(); v.set_flotte(flotte)
    assert prog_spalte(v._table, 2) == {"LDG mit": True, "LDG ohne": False}


def test_spalte_liegt_rechts_vom_messdaten_symbol_ist_schmal_und_hat_tooltip(flotte):
    v = FlotteView(); v.set_flotte(flotte)
    t = v._table
    last = t.columnCount() - 1
    assert t.horizontalHeaderItem(last).text() == "" and t.columnWidth(last) <= 32
    assert t.horizontalHeaderItem(last).toolTip() == PROGNOSE_TOOLTIP
    zeile = next(r for r in range(t.rowCount()) if t.item(r, 1).text() == "Zug A")
    assert t.item(zeile, last).toolTip() == PROGNOSE_TOOLTIP
    assert not t.item(zeile, last - 1).icon().isNull()      # Messdaten-Symbol steht links daneben


def test_spalte_sortiert_nach_vorhandensein(flotte):
    v = FlotteView(); v.set_flotte(flotte)
    t = v._table
    last = t.columnCount() - 1
    t.sortItems(last, Qt.DescendingOrder)
    assert t.item(0, 1).text() == "Zug A"
    t.sortItems(last, Qt.AscendingOrder)
    assert t.item(0, 1).text() == "Zug B"


def test_symbol_ist_ein_echtes_bild():
    from wheelset_dashboard.ui.views.common import _prognose_symbol
    pm = _prognose_symbol().pixmap(16, 16)
    assert not pm.isNull()
    img = pm.toImage()
    sichtbar = sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixelColor(x, y).alpha() > 0)
    assert sichtbar > 20


# ---- Datumsformat in den Kacheln ------------------------------------

def test_kacheln_unter_dem_diagramm_zeigen_datum_als_tt_mm_jjjj():
    letzter = datetime(2020, 6, 15)
    mr = Messreihe(
        messgroesse="LKD",
        historie=[Messpunkt(datum=letzter - timedelta(days=90 * k), stand=800.0 - k, min_val=780.0, gelb_min=790.0)
                  for k in range(4)],
        prognose=Prognose(datum_grenzwert=letzter + timedelta(days=700), datum_warnwert=letzter + timedelta(days=400),
                          km_grenzwert=200000.0, km_warnwert=150000.0,
                          punkte=[PrognosePunkt(datum=letzter + timedelta(days=30), stand=790.0)]))
    a = achse("A", mr)
    d = dg("DG", a)
    e = Einheit(topeinheit_id=None, topeinheit_bez="E", drehgestelle={"DG": d})
    v = AchseView()
    v.set_achse(e, d, a)
    texte = [l.text() for l in v._kennzahlen_container.findChildren(QLabel)]
    daten = [t for t in texte if re.search(r"\d{2,4}[-.]\d{2}[-.]\d{2,4}", t)]
    assert len(daten) >= 3                                   # letzter Messwert, Grenz-, Warn-Termin
    assert all(re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", t) for t in daten), daten
    assert not any(re.search(r"\b\d{4}-\d{2}-\d{2}\b", t) for t in texte)


# ---- Texte beim Ueberfahren und Anklicken ----------------------------

def test_texte_der_symbole():
    assert MESSDATEN_TOOLTIP == "Historische Daten vorhanden"
    assert PROGNOSE_TOOLTIP == "Prognose vorhanden"


def test_tooltip_beim_ueberfahren_und_in_der_kopfzeile(flotte):
    v = FlotteView(); v.set_flotte(flotte)
    t = v._table
    last = t.columnCount() - 1
    zeile = next(r for r in range(t.rowCount()) if t.item(r, 1).text() == "Zug A")
    assert t.item(zeile, last - 1).toolTip() == "Historische Daten vorhanden"
    assert t.item(zeile, last).toolTip() == "Prognose vorhanden"
    assert t.horizontalHeaderItem(last - 1).toolTip() == "Historische Daten vorhanden"
    assert t.horizontalHeaderItem(last).toolTip() == "Prognose vorhanden"


def test_klick_auf_symbol_blendet_den_text_ein(flotte, monkeypatch):
    from wheelset_dashboard.ui.views import common
    gezeigt = []
    monkeypatch.setattr(common.QToolTip, "showText", lambda pos, text, widget=None: gezeigt.append(text))
    v = FlotteView(); v.set_flotte(flotte)
    t = v._table
    last = t.columnCount() - 1
    zeile = next(r for r in range(t.rowCount()) if t.item(r, 1).text() == "Zug A")
    leer = next(r for r in range(t.rowCount()) if t.item(r, 1).text() == "Zug B")
    t.cellClicked.emit(zeile, last - 1)
    t.cellClicked.emit(zeile, last)
    t.cellClicked.emit(leer, last)               # Zelle ohne Symbol: nichts
    t.cellClicked.emit(zeile, 1)                 # Textspalte: nichts
    assert gezeigt == ["Historische Daten vorhanden", "Prognose vorhanden"]
