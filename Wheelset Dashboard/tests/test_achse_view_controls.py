"""Achsen-Diagramm: X-Achse und Radauswahl duerfen nach dem Wechsel auf eine Achse
ohne Laufleistung bzw. ohne Radseite (Abellio, MOB) nicht zu einem leeren
Diagramm fuehren."""
import warnings
from datetime import datetime, timedelta

import pytest

from wheelset_dashboard.data.models import (
    Achse, Drehgestell, Einheit, Messpunkt, Messreihe, Rad, Side,
)
from wheelset_dashboard.ui.views import AchseView

pytestmark = pytest.mark.usefixtures("qapp")

T0 = datetime(2024, 1, 1)


def _rad(side, km):
    hist = [Messpunkt(datum=T0 + timedelta(days=30 * k), stand=800.0 - k,
                      laufleistung=(100000.0 + 1000 * k) if km else None) for k in range(3)]
    return Rad(seite=side, messreihen={"LKD": Messreihe(messgroesse="LKD", historie=hist)})


def _achse(raeder):
    return Achse(rs_id=None, rs_bez="", rs_einbaupos="A", raeder=raeder)


def _open(view, achse):
    dg = Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG", achsen={"A": achse})
    e = Einheit(topeinheit_id=1, topeinheit_bez="E", drehgestelle={"DG": dg})
    view.set_achse(e, dg, achse)


def _linien(view):
    return len(view._tabs.currentWidget().canvas._ax.lines)


@pytest.fixture
def sided():
    return _achse({Side.LEFT: _rad(Side.LEFT, True), Side.RIGHT: _rad(Side.RIGHT, True)})


@pytest.fixture
def ohne_seite_ohne_km():
    return _achse({Side.UNSPECIFIED: _rad(Side.UNSPECIFIED, False)})


def test_laufleistung_wird_bei_achse_ohne_km_zurueckgesetzt(sided, ohne_seite_ohne_km):
    view = AchseView()
    _open(view, sided)
    view._x_combo.setCurrentIndex(1)                      # Laufleistung [km]
    assert _linien(view) == 2
    _open(view, ohne_seite_ohne_km)                       # Achse ohne Laufleistung
    assert view._x_combo.currentIndex() == 0 and view._x_mode == "datum"
    assert not view._x_combo.model().item(1).isEnabled()
    assert _linien(view) == 1


def test_radfilter_wird_bei_achse_ohne_radseite_zurueckgesetzt(sided, ohne_seite_ohne_km):
    view = AchseView()
    _open(view, sided)
    view._side_combo.setCurrentIndex(1)                   # nur links
    assert _linien(view) == 1
    _open(view, ohne_seite_ohne_km)
    assert view._side_combo.currentIndex() == 0 and view._side_filter == "both"
    assert not view._side_combo.isEnabled()
    assert _linien(view) == 1


def test_auswahl_ist_bei_normaler_achse_wieder_verfuegbar(sided, ohne_seite_ohne_km):
    view = AchseView()
    _open(view, ohne_seite_ohne_km)
    _open(view, sided)
    assert view._x_combo.model().item(1).isEnabled() and view._side_combo.isEnabled()
    view._x_combo.setCurrentIndex(1)
    assert _linien(view) == 2


def test_auswahl_bleibt_bei_normaler_achse_erhalten(sided):
    view = AchseView()
    _open(view, sided)
    view._x_combo.setCurrentIndex(1)
    view._side_combo.setCurrentIndex(2)                   # nur rechts
    _open(view, sided)                                    # naechste Achse mit denselben Moeglichkeiten
    assert view._x_mode == "km" and view._side_filter == "right"
    assert _linien(view) == 1


def test_reihe_ohne_messpunkte_zeigt_hinweis_und_warnt_nicht(sided):
    view = AchseView()
    _open(view, sided)
    canvas = view._tabs.currentWidget().canvas
    leer = Messreihe(messgroesse="LKD", historie=[])
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        canvas.plot_messreihen([("left", leer, None)], x_mode="datum", achse=sided)
    assert len(canvas._ax.lines) == 0
    assert [t.get_text() for t in canvas._ax.texts] == ["Keine Messwerte für diese Auswahl"]
    assert not [x for x in w if "No artists with labels" in str(x.message)]


def test_ohne_punkte_steht_ein_hinweis_im_diagramm(ohne_seite_ohne_km):
    view = AchseView()
    _open(view, ohne_seite_ohne_km)
    canvas = view._tabs.currentWidget().canvas
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        canvas.plot_messreihen(
            [("unspecified", ohne_seite_ohne_km.raeder[Side.UNSPECIFIED].messreihen["LKD"], None)],
            x_mode="km", achse=ohne_seite_ohne_km)        # km angefordert, aber keine Laufleistung
    assert len(canvas._ax.lines) == 0
    assert [t.get_text() for t in canvas._ax.texts] == ["Keine Laufleistung in den Daten"]
    assert not [x for x in w if "No artists with labels" in str(x.message)]
