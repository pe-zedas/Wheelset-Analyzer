"""Tabellen: Status-Symbol in Spalte 0 auch bei "Messwerte anzeigen"; Spaltenbreiten
(Zaehlspalten so schmal wie der Text, Namensspalte fuellt, aber nie schmaler als ihr Text)."""
import pytest

from tests.test_prognose_icon import flotte  # noqa: F401  (Fixture)
from wheelset_dashboard.ui import views
from wheelset_dashboard.ui.views import DrehgestellView, EinheitView, FlotteView, LagerView
from wheelset_dashboard.ui.views.common import fill_column_min_text, text_width

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def mit_messwerten():
    views.set_show_values(True)
    yield
    views.set_show_values(False)


def _alle_ansichten(flotte):
    e = flotte.einheiten["Zug A"]
    f = FlotteView(); f.set_flotte(flotte)
    ei = EinheitView(); ei.set_flotte(flotte); ei.set_einheit(e)
    d = DrehgestellView(); d.set_flotte(flotte); d.set_dg(e, e.drehgestelle["DG1"])
    la = LagerView(); la.set_flotte(flotte)
    return [f, ei, d, la]


def test_status_symbol_in_spalte_0_bleibt_bei_messwerte_anzeigen(flotte, mit_messwerten):
    for v in _alle_ansichten(flotte):
        t = v._table
        assert t.rowCount() > 0
        for r in range(t.rowCount()):
            assert t.cellWidget(r, 0) is not None, type(v).__name__


def test_messspalten_zeigen_bei_messwerte_anzeigen_weiter_nur_vorhandene_werte(flotte, mit_messwerten):
    v = FlotteView(); v.set_flotte(flotte)
    # Spalte 4 (LKD): Werte sind vorhanden, Spalte 5 (Sd) hat keine -> leer
    assert all(v._table.cellWidget(r, 5) is None for r in range(v._table.rowCount()))


def test_zaehlspalten_sind_so_schmal_wie_der_text(flotte):
    v = FlotteView(); v.set_flotte(flotte); v.resize(1200, 400); v.show()
    t = v._table
    assert t.columnWidth(2) == text_width(t, 2) and t.columnWidth(3) == text_width(t, 3)


def test_namensspalte_fuellt_die_tabelle_und_wird_nicht_schmaler_als_der_text(flotte, qapp):
    v = FlotteView(); v.set_flotte(flotte); v.resize(1400, 400); v.show(); qapp.processEvents()
    t = v._table
    breit = t.columnWidth(1)
    summe = sum(t.columnWidth(c) for c in range(t.columnCount()))
    assert abs(summe - t.viewport().width()) <= 2                  # gefuellt, kein Scrollbalken
    assert t.horizontalScrollBar().maximum() == 0
    v.resize(300, 400); qapp.processEvents()
    assert t.columnWidth(1) == text_width(t, 1) < breit            # nicht schmaler als der Text
    assert t.horizontalScrollBar().maximum() > 0                   # stattdessen Scrollbalken


def test_breiteste_einheit_bestimmt_die_mindestbreite(flotte, qapp):
    v = FlotteView(); v.set_flotte(flotte); v.resize(150, 400); v.show(); qapp.processEvents()
    t = v._table
    assert t.columnWidth(1) == text_width(t, 1)
    schmal = t.columnWidth(1)
    t.item(0, 1).setText("Ein sehr langer Einheitenname FLIRT 3 Sonderzug")
    fill_column_min_text(t, 1)                      # wie nach dem Neuaufbau der Tabelle
    assert t.columnWidth(1) == text_width(t, 1) > schmal


def test_alle_ansichten_behalten_ihre_namensspalte_lesbar(flotte, qapp):
    for v, col in zip(_alle_ansichten(flotte), (1, 1, 2, 3)):
        v.resize(350, 400); v.show(); qapp.processEvents()
        t = v._table
        assert t.columnWidth(col) >= text_width(t, col), type(v).__name__
