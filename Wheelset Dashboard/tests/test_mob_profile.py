"""Tests fuer das MOB-Profil: franzoesische Bezeichnungen, nur Drehgestell-Ebene,
vier Raeder je Zaehler (ohne Seiten-/Achsangabe), keine Grenzwerte."""
from datetime import datetime, timedelta

import pytest

from wheelset_dashboard.data.structure import NO_RS_LABEL
from wheelset_dashboard.data.models import Side, StatusAmpel
from wheelset_dashboard.data.oracle_source import parse_flotte_rows
from wheelset_dashboard.data.profile import load_profile_by_name
from wheelset_dashboard.logic.status import classify_messreihe
from wheelset_dashboard.logic.aggregation import n_real_achsen, n_real_dg

MOB = load_profile_by_name("mob")
HEADER = list(MOB.columns_raw.keys())
T0 = datetime(2025, 1, 10, 7, 28)
DG = (206646, "Bogie EV 1 / 137.21.0026_A", "Bogie EV 1 (IO)")


def row(zartbez, stand, *, te=(397748, "273"), dg=DG, ausbau=None, aktuell=1, minuten=0):
    v = {
        "TOPEINHEITID": te[0], "TOPEINHEITBEZEICHNUNG": te[1],
        "DGEINHEITID": dg[0], "DGBEZEICHNUNG": dg[1], "DGEINBAUPOS": dg[2],
        "EINBAU": datetime(2024, 8, 22), "AUSBAU": ausbau, "AKTUELL": aktuell,
        "ZAEHLERARTID": 1078181, "ZARTBEZ": zartbez, "STAND": stand,
        "DATUM": T0 + timedelta(minutes=minuten),
    }
    return tuple(v.get(c) for c in HEADER)


def load(*rows):
    return parse_flotte_rows(list(rows), HEADER, MOB)


# Bezeichnungen exakt wie in der MOB-Datenbank (teils mit Leerzeichen am Ende)
@pytest.mark.parametrize("name, messgroesse", [
    ("Diamètre de roue", "LKD"),
    ("Epaisseur du boudin", "SPURKRANZDICKE_SD"),
    ("Hauteur du boudin", "SPURKRANZHOEHE_SH"),
    ("Cote qR ", "SPURKRANZFLANKE_QR"),
    ("Creux ", "HOHLLAUF"),
    ("Refoulement ", "UEBERWALZUNG"),
    ("Largeur de roue ", "RADBREITE"),
])
def test_bezeichnungen_inkl_leerzeichen_am_ende(name, messgroesse):
    mdef, side = MOB.classify_zartbez(name)
    assert (mdef.name, side) == (messgroesse, Side.UNSPECIFIED)


def test_einzelwert_haengt_an_sammelachse_statt_nur_am_drehgestell():
    # Ein einzelner Wert ist kein vollstaendiger Messtermin -> keine Zuordnung
    f = load(row("Diamètre de roue", 650.0))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert dg.direkt_messreihen == {}
    (achse,) = dg.achsen.values()
    assert achse.rs_einbaupos == NO_RS_LABEL
    assert len(achse.raeder[Side.UNSPECIFIED].messreihen["LKD"].historie) == 1


def positionen(dg, messgroesse):
    """{Messposition-Nr: [Messwerte chronologisch]} eines Drehgestells."""
    out = {}
    for label, a in dg.achsen.items():
        if label.startswith("Messposition "):
            mr = a.raeder[Side.UNSPECIFIED].messreihen.get(messgroesse)
            if mr is not None:
                out[int(label.split()[-1])] = [
                    p.stand for p in sorted(mr.historie, key=lambda p: p.datum)]
    return out


def test_vier_werte_eines_termins_werden_auf_vier_messpositionen_verteilt():
    f = load(*(row("Diamètre de roue", 650.0 + i, minuten=i) for i in range(4)))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert sorted(dg.achsen) == [f"Messposition {k}" for k in range(1, 5)]
    # der k-te Wert (nach Zeit) gehoert zur Messposition k
    assert positionen(dg, "LKD") == {1: [650.0], 2: [651.0], 3: [652.0], 4: [653.0]}


def test_reihenfolge_richtet_sich_nach_der_zeit_nicht_nach_der_zeilenfolge():
    zeilen = [row("Diamètre de roue", 650.0 + i, minuten=i) for i in range(4)]
    f = load(*reversed(zeilen))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert positionen(dg, "LKD") == {1: [650.0], 2: [651.0], 3: [652.0], 4: [653.0]}


def test_mehrere_termine_ergeben_je_position_eine_zeitreihe():
    spaeter = 60 * 24 * 150                      # 150 Tage spaeter
    f = load(*(row("Epaisseur du boudin", 26.0 + i, minuten=i) for i in range(4)),
             *(row("Epaisseur du boudin", 25.0 + i, minuten=spaeter + i) for i in range(4)))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert positionen(dg, "SPURKRANZDICKE_SD") == {
        1: [26.0, 25.0], 2: [27.0, 26.0], 3: [28.0, 27.0], 4: [29.0, 28.0]}
    assert NO_RS_LABEL not in dg.achsen


def test_termin_mit_anderer_anzahl_bleibt_in_der_sammelachse():
    # 3 Werte: Zuordnung waere geraten -> bleibt zusammen in der Sammel-Achse
    f = load(*(row("Diamètre de roue", 650.0 + i, minuten=i) for i in range(3)))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert list(dg.achsen) == [NO_RS_LABEL]
    assert len(dg.achsen[NO_RS_LABEL].raeder[Side.UNSPECIFIED].messreihen["LKD"].historie) == 3


def test_vollstaendiger_termin_wird_verteilt_unvollstaendiger_bleibt_zusammen():
    spaeter = 60 * 24 * 30
    f = load(*(row("Diamètre de roue", 650.0 + i, minuten=i) for i in range(4)),
             *(row("Diamètre de roue", 640.0 + i, minuten=spaeter + i) for i in range(3)))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert positionen(dg, "LKD") == {1: [650.0], 2: [651.0], 3: [652.0], 4: [653.0]}
    rest = dg.achsen[NO_RS_LABEL].raeder[Side.UNSPECIFIED].messreihen["LKD"].historie
    assert sorted(p.stand for p in rest) == [640.0, 641.0, 642.0]


def test_messgroessen_werden_unabhaengig_je_position_zugeordnet():
    # Der Durchmesser wird ca. 40 s nach den uebrigen Werten gemessen
    zeilen = []
    for i in range(4):
        zeilen.append(row("Epaisseur du boudin", 26.0 + i, minuten=i))
        zeilen.append(row("Diamètre de roue", 650.0 + i, minuten=i + 0.7))
    f = load(*zeilen)
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert positionen(dg, "LKD")[3] == [652.0]
    assert positionen(dg, "SPURKRANZDICKE_SD")[3] == [28.0]


def test_zahlen_in_der_uebersicht_zaehlen_nur_echte_strukturen():
    f = load(*(row("Diamètre de roue", 650.0 + i, minuten=i) for i in range(4)))
    e = f.einheiten["273"]
    (dg,) = e.drehgestelle.values()
    assert n_real_dg(e) == 1          # das Drehgestell ist echt
    assert n_real_achsen(dg) == 0     # Messpositionen sind keine Achsen
    assert len(dg.achsen) == 4


def test_messposition_zaehlt_im_donut_als_eigene_messstelle():
    from wheelset_dashboard.logic.aggregation import status_counts
    f = load(*(row("Diamètre de roue", 650.0 + i, minuten=i) for i in range(4)))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    assert sum(status_counts(dg).values()) == 4


def test_hohllauf_null_ist_gueltiger_messwert():
    f = load(row("Creux ", 0.0))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    (achse,) = dg.achsen.values()
    assert len(achse.raeder[Side.UNSPECIFIED].messreihen["HOHLLAUF"].historie) == 1


def test_null_durchmesser_ist_platzhalter():
    f = load(row("Diamètre de roue", 0.0), row("Diamètre de roue", 650.0, minuten=1))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    (achse,) = dg.achsen.values()
    assert [mp.stand for mp in achse.raeder[Side.UNSPECIFIED].messreihen["LKD"].historie] == [650.0]


def test_ohne_grenzwerte_bleibt_die_ampel_grau():
    f = load(row("Epaisseur du boudin", 26.5))
    (dg,) = f.einheiten["273"].drehgestelle.values()
    (achse,) = dg.achsen.values()
    mr = achse.raeder[Side.UNSPECIFIED].messreihen["SPURKRANZDICKE_SD"]
    assert classify_messreihe(mr) == StatusAmpel.GRAY


def test_ausgebautes_drehgestell_wird_lager_komponente_mit_sammelachse():
    f = load(row("Diamètre de roue", 648.0, te=(397728, "271"), ausbau=datetime(2024, 8, 16), aktuell=0))
    assert f.einheiten == {}
    (comp,) = f.lager
    assert comp.kind == "drehgestell" and comp.dg_bez == DG[1]
    assert list(comp.achsen) == [NO_RS_LABEL]


def test_ausgebautes_drehgestell_wird_auf_messpositionen_verteilt():
    f = load(*(row("Diamètre de roue", 648.0 + i, te=(397728, "271"),
                   ausbau=datetime(2024, 8, 16), aktuell=0, minuten=i) for i in range(4)))
    (comp,) = f.lager
    assert sorted(comp.achsen) == [f"Messposition {k}" for k in range(1, 5)]


def test_wieder_eingebautes_drehgestell_steht_nicht_im_lager():
    # Dasselbe Drehgestell: in 271 ausgebaut, in 273 wieder eingebaut.
    # Es zaehlt der zuletzt benutzte Platz -> eingebaut, nicht im Lager.
    f = load(
        row("Diamètre de roue", 648.0, te=(397728, "271"), ausbau=datetime(2024, 8, 16), aktuell=0),
        row("Diamètre de roue", 649.0, te=(397748, "273")),
    )
    assert set(f.einheiten) == {"273"}
    assert f.lager == []


def test_anderes_drehgestell_bleibt_im_lager():
    anderes = (999999, "Bogie EV 1 / 137.21.0099_A", "Bogie EV 1 (IO)")
    f = load(
        row("Diamètre de roue", 648.0, te=(397728, "271"), dg=anderes,
            ausbau=datetime(2024, 8, 16), aktuell=0),
        row("Diamètre de roue", 649.0, te=(397748, "273")),
    )
    assert [c.dg_bez for c in f.lager] == [anderes[1]]
