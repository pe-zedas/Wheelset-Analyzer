"""Zeitachse mit Sprung zum aktuellen Datum: Marken/Beschriftung und Einbindung ins Diagramm.

Die Achse bleibt durchgehend und im gleichen Massstab; nur die Beschriftung rechts vom
Uebergang (letzter Messwert) wird um den Abstand zu heute verschoben. Mit ausgeschalteter
Einstellung darf sich am Diagramm nichts aendern."""
import dataclasses
from datetime import datetime, timedelta

import matplotlib.dates as mdates
import pytest

from wheelset_dashboard.data.models import Messpunkt, Messreihe, Prognose, PrognoseConfig, PrognosePunkt
from wheelset_dashboard.ui.plot_widget import PlotCanvas, TIME_JUMP_MIN_DAYS
from wheelset_dashboard.ui.time_axis import (
    LABEL_PX, MONTH_STEPS, ShiftedDateFormatter, ShiftedDateLocator, month_step,
)

pytestmark = pytest.mark.usefixtures("qapp")

HEUTE = datetime(2026, 11, 11)
LETZTER = datetime(2020, 6, 15)            # letzter Messwert, ~6,4 Jahre vor heute


def _reihe(letzter=LETZTER, mit_prognose=True):
    hist = [Messpunkt(datum=letzter - timedelta(days=90 * (5 - k)), stand=800.0 - 2 * k,
                      min_val=780.0, gelb_min=790.0) for k in range(6)]
    prog = None
    if mit_prognose:
        punkte = [PrognosePunkt(datum=letzter + timedelta(days=90 * k), stand=790.0 - 3 * k) for k in range(8)]
        prog = Prognose(punkte=punkte)
    return [("left", Messreihe(messgroesse="LKD", historie=hist, prognose=prog), prog)]


def _plot(cfg, reihen=None, heute=HEUTE, x_mode="datum"):
    cv = PlotCanvas()
    cv.resize(1000, 420)
    cv.plot_messreihen(reihen or _reihe(), y_label="LKD [mm]", x_mode=x_mode, today=heute, prognose_config=cfg)
    cv.draw()
    return cv


def _tick_texte(cv):
    return [t.get_text() for t in cv._ax.get_xticklabels() if t.get_text()]


# ---- month_step / Locator / Formatter ----------------------------------

def test_monatsintervall_waechst_mit_dem_zeitraum():
    steps = [month_step(days, 700) for days in (200, 700, 2000, 4000, 9000, 40000)]
    assert steps == sorted(steps) and steps[0] == 1 and steps[-1] == MONTH_STEPS[-1]


def _locator(junction=datetime(2020, 6, 15), heute=HEUTE, breite=700):
    j = mdates.date2num(junction)
    loc = ShiftedDateLocator(j, (heute - junction).days)
    loc._width_px = lambda: float(breite)           # feste Breite statt Achse
    return loc, j


def test_marken_liegen_links_echt_und_rechts_verschoben():
    loc, j = _locator()
    lo, hi = j - 3000, j + 1500
    ticks = loc.tick_values(lo, hi)
    assert ticks == sorted(ticks) and len(ticks) >= 4
    assert all(lo <= t <= hi for t in ticks) and j not in ticks
    fmt = ShiftedDateFormatter(loc)
    delta = loc.delta
    for t in ticks:
        if t < j:                                   # echtes Datum, rund (Jahresanfang bei Jahresmarken)
            d = mdates.num2date(t)
        else:                                       # Beschriftung = Datum + Offset, rund
            d = mdates.num2date(t + delta)
        if loc.fmt == "%Y":
            assert (d.month, d.day) == (1, 1)
        assert fmt(t) == d.strftime(loc.fmt)


def test_massstab_ist_durchgehend_gleich():
    """Der Abstand benachbarter rechter Marken entspricht dem echten Zeitabstand (kein Achsenbruch)."""
    loc, j = _locator()
    ticks = [t for t in loc.tick_values(j - 3000, j + 1500) if t > j]
    abstaende = {round(b - a) for a, b in zip(ticks, ticks[1:])}
    assert abstaende <= {365, 366, 730, 731}        # Jahresmarken (1 oder 2 Jahre Abstand)


def test_letzte_linke_marke_entfaellt_nur_bei_beruehrung():
    loc, j = _locator(junction=datetime(2020, 12, 20), breite=700)      # 12 Tage vor dem Jahreswechsel
    lo, hi = j - 3000, j + 1500
    per_px = (hi - lo) / 700
    ticks = loc.tick_values(lo, hi)
    links = [t for t in ticks if t < j]
    rechts = [t for t in ticks if t > j]
    if links and rechts:
        assert (rechts[0] - links[-1]) / per_px >= LABEL_PX


def test_keine_marken_bei_leerem_intervall():
    loc, j = _locator()
    assert loc.tick_values(j, j) == []


# ---- Diagramm ----------------------------------------------------------

def test_ohne_einstellung_bleibt_alles_wie_bisher():
    cv = _plot(PrognoseConfig())
    assert not any("heute (" in t.get_text() for t in cv._ax.texts)
    assert not isinstance(cv._ax.xaxis.get_major_locator(), ShiftedDateLocator)
    assert cv._ax.get_xlabel() == "Datum"


def test_ohne_prognose_config_wie_bisher():
    cv = PlotCanvas()
    cv.plot_messreihen(_reihe(), x_mode="datum", today=HEUTE)
    assert not isinstance(cv._ax.xaxis.get_major_locator(), ShiftedDateLocator)


def test_zeitsprung_ersetzt_heute_linie_durch_ueberschrift_am_uebergang():
    cv = _plot(PrognoseConfig(time_jump=True))
    ax = cv._ax
    texte = [t.get_text() for t in ax.texts]
    annot = [c.get_text() for c in ax.get_children() if hasattr(c, "get_text") and "heute (" in c.get_text()]
    assert annot == ["heute (11.11.2026)"]
    assert "heute" not in [t.strip() for t in texte]                           # kein altes "heute"
    assert "heute" not in " ".join(_tick_texte(cv))                            # nicht an der x-Achse
    assert isinstance(ax.xaxis.get_major_locator(), ShiftedDateLocator)
    assert "verschoben" in ax.get_xlabel()
    senkrechte = [l for l in ax.lines if len(l.get_xdata()) == 2 and l.get_xdata()[0] == l.get_xdata()[1]]
    assert len(senkrechte) == 1
    assert mdates.date2num(senkrechte[0].get_xdata()[0]) == pytest.approx(mdates.date2num(LETZTER))


def test_zeitsprung_aendert_die_achsengrenzen_nicht():
    aus = _plot(PrognoseConfig())
    an = _plot(PrognoseConfig(time_jump=True))
    assert an._ax.get_xlim() == pytest.approx(aus._ax.get_xlim())
    assert an._ax.get_ylim() == pytest.approx(aus._ax.get_ylim())
    # gezeichnete Linien (Messwerte, Prognose) sind identisch; nur die Marker-Linie kommt hinzu
    daten = lambda cv: [(list(l.get_xdata()), list(l.get_ydata())) for l in cv._ax.lines]
    assert daten(an)[:len(daten(aus)) - 1] == daten(aus)[:len(daten(aus)) - 1]


def test_beschriftung_nach_dem_uebergang_beginnt_bei_heute():
    cv = _plot(PrognoseConfig(time_jump=True))
    jahre = [int(t[:4]) for t in _tick_texte(cv)]
    assert jahre == sorted(jahre)
    assert jahre[-1] >= 2026                       # rechts steht das verschobene Datum (ab heute)
    assert any(j <= 2020 for j in jahre)           # links echte Daten


def test_nur_wenn_letzter_messwert_weit_genug_zurueckliegt():
    jung = _reihe(letzter=HEUTE - timedelta(days=TIME_JUMP_MIN_DAYS - 5))
    cv = _plot(PrognoseConfig(time_jump=True), reihen=jung)
    assert not isinstance(cv._ax.xaxis.get_major_locator(), ShiftedDateLocator)
    alt = _reihe(letzter=HEUTE - timedelta(days=TIME_JUMP_MIN_DAYS + 5))
    cv = _plot(PrognoseConfig(time_jump=True), reihen=alt)
    assert isinstance(cv._ax.xaxis.get_major_locator(), ShiftedDateLocator)


def test_ohne_prognose_und_bei_km_achse_keine_zeitachse_mit_sprung():
    cv = _plot(PrognoseConfig(time_jump=True), reihen=_reihe(mit_prognose=False))
    assert not isinstance(cv._ax.xaxis.get_major_locator(), ShiftedDateLocator)
    reihen = _reihe()
    for _, mr, prog in reihen:
        for p in mr.historie:
            p.laufleistung = 1000.0 * (p.datum.year - 2000)
        for p in prog.punkte:
            p.laufleistung = 30000.0
    cv = _plot(PrognoseConfig(time_jump=True), reihen=reihen, x_mode="km")
    assert not isinstance(cv._ax.xaxis.get_major_locator(), ShiftedDateLocator)
    assert not [c for c in cv._ax.get_children() if hasattr(c, "get_text") and "heute (" in c.get_text()]


def test_ueberschrift_liegt_links_der_linie_wenn_diese_weit_rechts_steht():
    # kurze Prognose -> Uebergang liegt im rechten Teil der Achse
    reihen = _reihe()
    for _, mr, prog in reihen:
        prog.punkte[:] = prog.punkte[:2]
    cv = _plot(PrognoseConfig(time_jump=True), reihen=reihen)
    ann = next(c for c in cv._ax.get_children() if hasattr(c, "get_text") and "heute (" in c.get_text())
    assert ann.get_ha() == "right"


def test_einstellung_ist_im_config_dataclass_standardmaessig_aus():
    assert PrognoseConfig().time_jump is False
    assert dataclasses.replace(PrognoseConfig(), time_jump=True).time_jump is True


def test_achse_view_zeichnet_nach_umschalten_sofort_neu():
    from wheelset_dashboard.data.models import Achse, Drehgestell, Einheit, Rad, Side
    from wheelset_dashboard.ui.views import AchseView

    _, mr, _ = _reihe()[0]
    achse = Achse(rs_id=None, rs_bez="", rs_einbaupos="A", raeder={Side.LEFT: Rad(seite=Side.LEFT, messreihen={"LKD": mr})})
    dg = Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG", achsen={"A": achse})
    e = Einheit(topeinheit_id=1, topeinheit_bez="E", drehgestelle={"DG": dg})
    view = AchseView()
    view.set_achse(e, dg, achse)
    ax = lambda: view._tabs.currentWidget().canvas._ax
    assert not isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    view.set_prognose_config(PrognoseConfig(time_jump=True))
    assert isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    view.set_prognose_config(PrognoseConfig(time_jump=False))
    assert not isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    view.redraw()                                           # oeffentliche Methode, darf nicht fehlschlagen


def _view_mit_prognose():
    from wheelset_dashboard.data.models import Achse, Drehgestell, Einheit, Rad, Side
    from wheelset_dashboard.ui.views import AchseView

    _, mr, _ = _reihe()[0]
    achse = Achse(rs_id=None, rs_bez="", rs_einbaupos="A", raeder={Side.LEFT: Rad(seite=Side.LEFT, messreihen={"LKD": mr})})
    dg = Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG", achsen={"A": achse})
    e = Einheit(topeinheit_id=1, topeinheit_bez="E", drehgestelle={"DG": dg})
    view = AchseView()
    view.set_prognose_config(PrognoseConfig())
    view.set_achse(e, dg, achse)
    return view, (lambda: view._tabs.currentWidget().canvas._ax)


def test_schalter_im_diagramm_wechselt_die_darstellung_und_meldet_den_stand():
    view, ax = _view_mit_prognose()
    gemeldet = []
    view.time_jump_changed.connect(gemeldet.append)
    assert not view._jump_cb.isChecked() and view._jump_cb.isEnabled()
    view._jump_cb.setChecked(True)
    assert isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    view._jump_cb.setChecked(False)
    assert not isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    assert gemeldet == [True, False]


def test_schalter_folgt_der_einstellung_ohne_rueckmeldung():
    view, ax = _view_mit_prognose()
    gemeldet = []
    view.time_jump_changed.connect(gemeldet.append)
    view.set_prognose_config(PrognoseConfig(time_jump=True))
    assert view._jump_cb.isChecked() and isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    assert gemeldet == []


def test_schalter_ist_bei_km_achse_gesperrt_und_erklaert_ohne_wirkung():
    view, ax = _view_mit_prognose()
    view._jump_cb.setChecked(True)
    assert "verschobene" in view._jump_cb.toolTip()
    view._x_combo.model().item(1).setEnabled(True)
    view._x_combo.setCurrentIndex(1)
    assert not view._jump_cb.isEnabled()
    assert not isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)
    view._x_combo.setCurrentIndex(0)
    assert view._jump_cb.isEnabled() and isinstance(ax().xaxis.get_major_locator(), ShiftedDateLocator)


def test_hauptfenster_merkt_den_stand_des_schalters(tmp_path):
    from tests.synth import write_csv
    from wheelset_dashboard.data.repository import Repository, RepositoryConfig
    from wheelset_dashboard.ui.main_window import MainWindow

    raw = write_csv("vgf", tmp_path / "raw.csv")
    repo = Repository(RepositoryConfig(profile_name="vgf", source="csv", csv_raw_path=raw,
                                       csv_prognose_path=None))
    win = MainWindow(repo, async_load=False)
    assert win.wait_for_load()
    assert win._prog_cfg.time_jump is False
    win._view_achse.time_jump_changed.emit(True)
    assert win._prog_cfg.time_jump is True
    win._view_achse.set_prognose_config(win._prog_cfg)           # naechstes Diagramm uebernimmt den Stand
    assert win._view_achse._jump_cb.isChecked()
    win.close()


def test_kachel_letzter_messwert_zeigt_datum_der_messung():
    from PySide6.QtWidgets import QLabel

    view, _ = _view_mit_prognose()
    texte = [l.text() for l in view._kennzahlen_container.findChildren(QLabel)]
    assert f"Messung {LETZTER.date().isoformat()}" in texte
    assert view._jump_cb.text() == "Zeitachse mit Prognose ab heute"
