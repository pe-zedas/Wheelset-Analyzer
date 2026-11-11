"""Spalte "Messdaten vorhanden": Diagramm-Symbol (vorletzte Spalte), wenn die Zeile selbst
oder eine darunterliegende Komponente Messdaten hat."""
from datetime import datetime

import pytest
from PySide6.QtCore import Qt

from wheelset_dashboard.data.models import (
    Achse, Drehgestell, Einheit, Flotte, LagerKomponente, Messpunkt, Messreihe, Rad, Side,
)
from wheelset_dashboard.logic.aggregation import has_messdaten
from wheelset_dashboard.ui.views import (
    DrehgestellView, EinheitView, FlotteView, LagerView, MESSDATEN_TOOLTIP,
)

pytestmark = pytest.mark.usefixtures("qapp")
T = datetime(2024, 1, 1)


def mit_daten():
    return Messreihe(messgroesse="LKD", historie=[Messpunkt(datum=T, stand=800.0)])


def ohne_daten():
    return Messreihe(messgroesse="LKD", historie=[])


def achse(pos, reihe):
    rad = Rad(seite=Side.LEFT, messreihen={"LKD": reihe} if reihe is not None else {})
    return Achse(rs_id=None, rs_bez="", rs_einbaupos=pos, raeder={Side.LEFT: rad})


def dg(pos, *achsen, direkt=None):
    return Drehgestell(dg_id=None, dg_bez=pos, dg_einbaupos=pos,
                       achsen={a.rs_einbaupos: a for a in achsen},
                       direkt_messreihen=direkt or {})


def einheit(bez, *dgs):
    return Einheit(topeinheit_id=None, topeinheit_bez=bez,
                   drehgestelle={d.dg_einbaupos: d for d in dgs})


def lager(bez, *achsen):
    return LagerKomponente(rs_id=None, rs_bez="", letzte_einheit="E", ausbau=T, kind="drehgestell",
                           dg_bez=bez, achsen={a.rs_einbaupos: a for a in achsen})


@pytest.fixture
def flotte():
    f = Flotte()
    # Zug A: DG1 hat Messdaten, DG2 nur eine leere Messreihe, DG3 gar nichts, DG4 nur direkt am DG
    a = einheit("Zug A",
                dg("DG1", achse("Achse 1", mit_daten()), achse("Achse 2", ohne_daten())),
                dg("DG2", achse("Achse 1", ohne_daten())),
                dg("DG3"),
                dg("DG4", direkt={"SPUR": mit_daten()}))
    # Zug B: nirgends Messdaten
    b = einheit("Zug B", dg("DG1", achse("Achse 1", ohne_daten())), dg("DG2"))
    f.einheiten = {"Zug A": a, "Zug B": b}
    f.lager = [lager("LDG mit", achse("A1", mit_daten())),
               lager("LDG leer", achse("A1", ohne_daten())),
               lager("LDG ohne Achsen")]
    return f


def zeilen(table, text_col):
    """{Text der Spalte text_col: hat Symbol in der letzten Spalte}."""
    last = table.columnCount() - 2        # vorletzte: Messdaten, letzte: Prognose
    out = {}
    for r in range(table.rowCount()):
        out[table.item(r, text_col).text()] = not table.item(r, last).icon().isNull()
    return out


# ---------- Regel (ohne Oberflaeche) ----------

def test_ebene_hat_messdaten_wenn_eine_komponente_darunter_welche_hat(flotte):
    a, b = flotte.einheiten["Zug A"], flotte.einheiten["Zug B"]
    assert has_messdaten(flotte) and has_messdaten(a)
    assert not has_messdaten(b)
    assert has_messdaten(a.drehgestelle["DG1"])
    assert not has_messdaten(a.drehgestelle["DG2"])        # nur leere Messreihe
    assert not has_messdaten(a.drehgestelle["DG3"])        # gar nichts
    assert has_messdaten(a.drehgestelle["DG4"])            # direkt am Drehgestell gemessen
    assert has_messdaten(a.drehgestelle["DG1"].achsen["Achse 1"])
    assert not has_messdaten(a.drehgestelle["DG1"].achsen["Achse 2"])
    assert [has_messdaten(c) for c in flotte.lager] == [True, False, False]


# ---------- Tabellen ----------

def test_flottentabelle_zeigt_symbol_nur_fuer_einheiten_mit_messdaten(flotte):
    v = FlotteView()
    v.set_flotte(flotte)
    assert zeilen(v._table, 1) == {"Zug A": True, "Zug B": False}


def test_einheitentabelle_zeigt_symbol_je_drehgestell(flotte):
    v = EinheitView()
    v.set_flotte(flotte)
    v.set_einheit(flotte.einheiten["Zug A"])
    assert zeilen(v._table, 1) == {"DG1": True, "DG2": False, "DG3": False, "DG4": True}


def test_drehgestelltabelle_zeigt_symbol_je_achse(flotte):
    v = DrehgestellView()
    v.set_flotte(flotte)
    e = flotte.einheiten["Zug A"]
    v.set_dg(e, e.drehgestelle["DG1"])
    assert zeilen(v._table, 1) == {"Achse 1": True, "Achse 2": False}


def test_lagertabelle_zeigt_symbol_je_komponente(flotte):
    v = LagerView()
    v.set_flotte(flotte)
    assert zeilen(v._table, 2) == {"LDG mit": True, "LDG leer": False, "LDG ohne Achsen": False}


def test_symbolspalte_ist_schmal_und_ohne_ueberschrift(flotte):
    v = FlotteView()
    v.set_flotte(flotte)
    t = v._table
    last = t.columnCount() - 2
    assert t.horizontalHeaderItem(last).text() == ""
    assert t.columnWidth(last) <= 32
    assert t.item(0, last).toolTip() in ("", MESSDATEN_TOOLTIP)


def test_symbolspalte_sortiert_nach_vorhandensein(flotte):
    v = FlotteView()
    v.set_flotte(flotte)
    t = v._table
    last = t.columnCount() - 2
    t.sortItems(last, Qt.DescendingOrder)
    assert t.item(0, 1).text() == "Zug A"          # mit Messdaten zuerst
    t.sortItems(last, Qt.AscendingOrder)
    assert t.item(0, 1).text() == "Zug B"


def test_filter_beruecksichtigt_die_symbolspalte_nicht_als_text(flotte):
    v = FlotteView()
    v.set_flotte(flotte)
    v._filter_edit.setText("Zug B")
    hidden = {v._table.item(r, 1).text(): v._table.isRowHidden(r) for r in range(v._table.rowCount())}
    assert hidden == {"Zug A": True, "Zug B": False}
