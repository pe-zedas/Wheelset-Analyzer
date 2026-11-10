"""Wieder eingebaute Bauteile gehoeren nicht in die Lager-Liste
(es zaehlt der zuletzt benutzte Platz)."""
from datetime import datetime

from wheelset_dashboard.data.structure import drop_reinstalled_lager
from wheelset_dashboard.data.models import (
    Achse, Drehgestell, Einheit, Flotte, LagerKomponente,
)

AUSBAU = datetime(2020, 1, 1)


def lager_achse(rs_id):
    return LagerKomponente(rs_id=rs_id, rs_bez=f"RS{rs_id}", letzte_einheit="E1",
                           ausbau=AUSBAU, kind="achse")


def lager_dg(dg_id, bez):
    return LagerKomponente(rs_id=None, rs_bez="", letzte_einheit="E1", ausbau=AUSBAU,
                           kind="drehgestell", dg_bez=bez, dg_id=dg_id)


def flotte_mit(dg_id=None, dg_bez="", rs_id=None):
    dg = Drehgestell(dg_id=dg_id, dg_bez=dg_bez, dg_einbaupos="DG1")
    if rs_id is not None:
        dg.achsen["RS1"] = Achse(rs_id=rs_id, rs_bez=f"RS{rs_id}", rs_einbaupos="RS1")
    f = Flotte()
    e = Einheit(topeinheit_id=1, topeinheit_bez="E2")
    e.drehgestelle["DG1"] = dg
    f.einheiten["E2"] = e
    return f


def test_drehgestell_ueber_id_abgeglichen():
    f = flotte_mit(dg_id=10, dg_bez="DG-A")
    f.lager = [lager_dg(10, "DG-A"), lager_dg(11, "DG-B")]
    assert drop_reinstalled_lager(f) == 1
    assert [c.dg_id for c in f.lager] == [11]


def test_gleiche_bezeichnung_aber_andere_id_ist_ein_anderes_drehgestell():
    f = flotte_mit(dg_id=10, dg_bez="DG-A")
    f.lager = [lager_dg(99, "DG-A")]
    assert drop_reinstalled_lager(f) == 0


def test_drehgestell_ohne_id_ueber_bezeichnung():
    f = flotte_mit(dg_id=None, dg_bez="DG-A")
    f.lager = [lager_dg(None, "DG-A"), lager_dg(None, "DG-B")]
    assert drop_reinstalled_lager(f) == 1
    assert [c.dg_bez for c in f.lager] == ["DG-B"]


def test_achse_ueber_radsatz_id():
    f = flotte_mit(dg_id=10, dg_bez="DG-A", rs_id=500)
    f.lager = [lager_achse(500), lager_achse(501)]
    assert drop_reinstalled_lager(f) == 1
    assert [c.rs_id for c in f.lager] == [501]


def test_leere_flotte_laesst_lager_unveraendert():
    f = Flotte()
    f.lager = [lager_achse(1), lager_dg(2, "X")]
    assert drop_reinstalled_lager(f) == 0
    assert len(f.lager) == 2
