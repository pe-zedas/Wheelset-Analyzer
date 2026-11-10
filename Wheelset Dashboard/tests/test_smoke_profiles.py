"""Smoke-Test: je Kundenprofil laden, das Fenster aufbauen, jede Ebene bis zum
Diagramm oeffnen und exportieren — mit synthetischen Daten (siehe synth.py).

Faengt ab, was Einzeltests der Datenregeln nicht sehen: Ansichten, die bei einem
Profil abstuerzen, falsche Donut-Summen, Exporte ohne Zeilen.
"""
from datetime import datetime, timedelta

import pytest
from openpyxl import load_workbook

from tests.synth import N_DG, WHEELS_INSTALLED, WHEELS_LAGER
from wheelset_dashboard.data.models import Prognose, Quality
from wheelset_dashboard.logic.aggregation import iter_messreihen, status_counts
from wheelset_dashboard.logic.export import export_raw_csv, werkstattliste_to_xlsx
from wheelset_dashboard.logic.status import recompute_all

pytestmark = pytest.mark.usefixtures("qapp")


def _count_messpunkte(flotte) -> int:
    n = sum(len(mr.historie) for mr in iter_messreihen(flotte))
    for c in flotte.lager:
        n += sum(len(mr.historie) for mr in c.messreihen.values())
        for rad in c.raeder.values():
            n += sum(len(mr.historie) for mr in rad.messreihen.values())
        for a in c.achsen.values():
            for rad in a.raeder.values():
                n += sum(len(mr.historie) for mr in rad.messreihen.values())
    return n


def test_daten_laden(scenario):
    name, repo = scenario
    f = repo.load()
    assert list(f.einheiten) == ["U1"]
    e = f.einheiten["U1"]
    assert len(e.drehgestelle) == N_DG[name]
    # Lager: nur das ausgebaute DG 20; DG 10 ist wieder eingebaut (zuletzt benutzter Platz)
    assert [c.dg_id for c in f.lager] == [20]
    assert sum(status_counts(e).values()) == WHEELS_INSTALLED[name]
    assert sum(status_counts(f.lager).values()) == WHEELS_LAGER[name]


def test_alle_ebenen_lassen_sich_oeffnen(scenario, qapp, monkeypatch):
    from wheelset_dashboard.ui import overview_widgets
    from wheelset_dashboard.ui.main_window import MainWindow

    name, repo = scenario
    donuts = []
    orig = overview_widgets.DonutCanvas.set_counts

    def spy(self, counts, center_label="Räder"):
        donuts.append(sum(counts.values()))
        return orig(self, counts, center_label)

    monkeypatch.setattr(overview_widgets.DonutCanvas, "set_counts", spy)

    win = MainWindow(repo, async_load=False)
    assert win.wait_for_load()
    assert win._flotte is not None
    assert name in win._schema_lbl.text().lower()

    win.navigate([])
    assert donuts[-1] == WHEELS_INSTALLED[name]
    win.navigate([("einheit", "U1")])
    assert donuts[-1] == WHEELS_INSTALLED[name]

    for dg in win._flotte.einheiten["U1"].drehgestelle.values():
        path = [("einheit", "U1"), ("drehgestell", dg.dg_einbaupos)]
        win.navigate(path)
        assert donuts[-1] == sum(status_counts(dg).values())
        for achse in dg.achsen.values():
            win.navigate(path + [("achse", achse.rs_einbaupos)])
            tabs = win._view_achse._tabs          # jede Messgroesse einmal zeichnen
            assert tabs.count() > 0
            for i in range(tabs.count()):
                tabs.setCurrentIndex(i)
                qapp.processEvents()

    win._show_lager()
    assert donuts[-1] == WHEELS_LAGER[name]


def test_werkstattliste_export(scenario, tmp_path):
    name, repo = scenario
    f = repo.load()
    recompute_all(f)
    now = datetime.now()
    # eine LKD-Reihe bekommt einen baldigen Warntermin -> muss in der Liste stehen
    lkd = next(mr for mr in iter_messreihen(f) if mr.messgroesse == "LKD")
    lkd.prognose = Prognose(datum_warnwert=now + timedelta(days=10),
                            datum_grenzwert=now + timedelta(days=40),
                            methode="theil_sen", qualitaet=Quality.OK)
    out = tmp_path / "werkstatt.xlsx"
    n = werkstattliste_to_xlsx(f, out, now=now)
    assert n == 1
    ws = load_workbook(out).active
    headers = [c.value for c in ws[1]]
    assert "Einheit" in headers and "nächster Warn-Termin" in headers
    assert ws.max_row == n + 1


def test_werkstattliste_ohne_prognose_ist_leer_aber_gueltig(scenario, tmp_path):
    name, repo = scenario
    out = tmp_path / "leer.xlsx"
    assert werkstattliste_to_xlsx(repo.load(), out) == 0
    assert out.exists() and load_workbook(out).active.max_row >= 1


def test_rohdaten_export_enthaelt_alle_messpunkte(scenario, tmp_path):
    name, repo = scenario
    f = repo.load()
    out = tmp_path / "roh.csv"
    n = export_raw_csv(f, repo.profile, out)
    assert n == _count_messpunkte(f)
    lines = out.read_text(encoding=repo.profile.encoding).splitlines()
    assert len(lines) == n + 1                       # Kopfzeile + Daten
    assert lines[0].split(repo.profile.delimiter) == list(repo.profile.columns_raw)
