"""Navigationsleiste im Lager-Kontext: ein Sprung zurueck auf das Lager-Drehgestell fuehrt zur
Achsenliste dieses Drehgestells (nicht sofort zur Lager-Tabelle)."""
from datetime import datetime

import pytest
from PySide6.QtWidgets import QPushButton

from tests.synth import write_csv
from wheelset_dashboard.data.models import (
    Achse, LagerKomponente, Messpunkt, Messreihe, Rad, Side,
)
from wheelset_dashboard.data.repository import Repository, RepositoryConfig
from wheelset_dashboard.ui.main_window import MainWindow

pytestmark = pytest.mark.usefixtures("qapp")
T = datetime(2024, 1, 1)


def _achse(pos):
    mr = Messreihe(messgroesse="LKD", historie=[Messpunkt(datum=T, stand=800.0)])
    return Achse(rs_id=None, rs_bez=pos, rs_einbaupos=pos, raeder={Side.LEFT: Rad(seite=Side.LEFT, messreihen={"LKD": mr})})


@pytest.fixture
def win(tmp_path):
    raw = write_csv("vgf", tmp_path / "raw.csv")
    w = MainWindow(Repository(RepositoryConfig(profile_name="vgf", source="csv", csv_raw_path=raw)), async_load=False)
    assert w.wait_for_load()
    komp = LagerKomponente(rs_id=None, rs_bez="", letzte_einheit="E", ausbau=T, kind="drehgestell",
                           dg_bez="LDG test", achsen={"A1": _achse("A1"), "A2": _achse("A2")})
    w._flotte.lager.append(komp)
    w._test_komp = komp
    return w


def _crumbs(win):
    lay = win._breadcrumb._h                    # nur die aktuell eingehaengten Knoepfe (alte warten auf deleteLater)
    return [lay.itemAt(i).widget() for i in range(lay.count()) if isinstance(lay.itemAt(i).widget(), QPushButton)]


def _klick(win, text):
    next(b for b in _crumbs(win) if b.text() == text).click()


def test_von_der_achse_zurueck_zum_drehgestell_zeigt_die_achsenliste(win):
    komp = win._test_komp
    win._open_lager_axle(komp, None)
    assert win._stack.currentWidget() is win._view_dg
    win._open_lager_axle(komp, komp.achsen["A1"])
    assert win._stack.currentWidget() is win._view_achse
    assert [b.text() for b in _crumbs(win)] == ["Lager", "LDG test", "A1"]

    _klick(win, "LDG test")                                 # Navigationsleiste: Drehgestell
    assert win._stack.currentWidget() is win._view_dg
    assert win._view_dg._table.rowCount() == 2              # Achsenliste des Drehgestells
    assert [b.text() for b in _crumbs(win)] == ["Lager", "LDG test"]


def test_lager_in_der_navigationsleiste_fuehrt_zur_lager_tabelle(win):
    komp = win._test_komp
    win._open_lager_axle(komp, komp.achsen["A2"])
    _klick(win, "Lager")
    assert win._stack.currentWidget() is win._view_lager
    assert [b.text() for b in _crumbs(win)] == ["Lager · Komponenten"]


def test_aus_der_achsenliste_ueber_die_leiste_zum_lager_und_wieder_hinein(win):
    komp = win._test_komp
    win._open_lager_axle(komp, None)
    _klick(win, "Lager")
    assert win._stack.currentWidget() is win._view_lager
    win._open_lager_axle(komp, None)
    assert win._stack.currentWidget() is win._view_dg


def test_messwerte_anzeigen_in_der_lager_achsenliste_bleibt_in_der_achsenliste(win):
    komp = win._test_komp
    win._open_lager_axle(komp, None)
    win._values_cb.setChecked(True)
    assert win._stack.currentWidget() is win._view_dg
    assert win._view_dg._table.rowCount() == 2
    win._values_cb.setChecked(False)


def test_nach_dem_neuladen_kein_zugriff_auf_alte_lager_objekte(win):
    win._open_lager_axle(win._test_komp, None)
    win.reload_data()
    assert win.wait_for_load()
    assert win._stack.currentWidget() is win._view_lager      # alte Komponente gibt es nicht mehr
