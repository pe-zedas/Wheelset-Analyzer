"""Tests fuer das Abellio-Profil: Namensvarianten, Struktur-Sonderfaelle,
Wertebereiche und Toleranzbereiche (ohne Datenbank, mit synthetischen Zeilen)."""
from datetime import datetime

import pytest

from wheelset_dashboard.data.models import Side, StatusAmpel
from wheelset_dashboard.data.oracle_source import _parse_flotte_rows
from wheelset_dashboard.data.profile import load_profile_by_name
from wheelset_dashboard.logic.status import classify_messreihe

ABELLIO = load_profile_by_name("abellio")
VGF = load_profile_by_name("vgf")

HEADER = list(ABELLIO.columns_raw.keys())
D = datetime(2020, 5, 1, 10, 0)


def row(zartbez, stand, *, te=(1, "T1"), dg=None, rs=None, ausbau=None, aktuell=1,
        min_=None, max_=None, min_b=None, max_b=None, datum=D):
    """Eine BO_RADSATZDATEN-Zeile im Spaltenaufbau des Abellio-Profils."""
    v = {
        "TOPEINHEITID": te[0], "TOPEINHEITBEZEICHNUNG": te[1],
        "DGEINHEITID": dg[0] if dg else None, "DGBEZEICHNUNG": dg[1] if dg else None,
        "DGEINBAUPOS": dg[2] if dg else None,
        "RSEINHEITID": rs[0] if rs else None, "RSBEZEICHNUNG": rs[1] if rs else None,
        "RSEINBAUPOS": rs[2] if rs else None,
        "EINBAU": datetime(2018, 1, 1), "AUSBAU": ausbau, "AKTUELL": aktuell,
        "ZAEHLERARTID": 1, "ZARTBEZ": zartbez, "STAND": stand, "DATUM": datum,
        "MIN": min_, "MAX": max_, "MIN_BEREICH": min_b, "MAX_BEREICH": max_b,
        "LAUFLEISTUNG": 1000.0,
    }
    return tuple(v.get(c) for c in HEADER)


def load(*rows):
    return _parse_flotte_rows(list(rows), HEADER, ABELLIO)


# ---------- Namensvarianten ----------

@pytest.mark.parametrize("name, messgroesse, side", [
    ("Laufkreisdurchmesser Dlk links", "LKD", Side.LEFT),
    ("Laufkreisdurchmesser Dlk rechts", "LKD", Side.RIGHT),
    ("Laufkreisdurchmesser Dlk", "LKD", Side.UNSPECIFIED),
    ("Laufkreisdurchmesser Dlk [Radscheibe Laufradsatz (L)]", "LKD", Side.LEFT),
    ("Laufkreisdurchmesser Dlk [Radscheibe Laufradsatz (R)]", "LKD", Side.RIGHT),
    ("Laufkreisdurchmesser Dlk [Radscheibe Treibradsatz (L)]", "LKD", Side.LEFT),
    ("Laufkreisdurchmesser Dlk [Radscheibe Treibradsatz (R)]", "LKD", Side.RIGHT),
    ("Laufkreisdurchmesser Dlk [Radscheibe links]", "LKD", Side.LEFT),
    ("Laufkreisdurchmesser Dlk [Radscheibe rechts]", "LKD", Side.RIGHT),
    # "Laufradsatz" enthaelt ein grosses L: darf nie als linke Seite gelten
    ("Rad-Spurkranzhöhe Sh [Radscheibe Laufradsatz (R)]", "SPURKRANZHOEHE_SH", Side.RIGHT),
    ("Rad-Spurkranzdicke Sd links", "SPURKRANZDICKE_SD", Side.LEFT),
    ("Rad-Spurkranzflankenmaß qR rechts", "SPURKRANZFLANKE_QR", Side.RIGHT),
    ("Auswalzung (Hohllauf) [Radscheibe Treibradsatz (L)]", "HOHLLAUF", Side.LEFT),
    ("Überwalzung [Radscheibe rechts]", "UEBERWALZUNG", Side.RIGHT),
    ("Radbreite [Radscheibe Laufradsatz (L)]", "RADBREITE", Side.LEFT),
    ("Rad-Spurmaß SR", "SPURMASS_SR", Side.UNSPECIFIED),
    ("Radinnenabstand AR", "STICHMASS_ABSTAND", Side.UNSPECIFIED),
])
def test_namensvarianten(name, messgroesse, side):
    mdef, s = ABELLIO.classify_zartbez(name)
    assert (mdef.name, s) == (messgroesse, side)


@pytest.mark.parametrize("name", [
    "Bremsscheibe BH [Bremsscheibe Laufradsatz innen (L)]",
    "Rad-Rundlaufabweichung links", "Planlaufabweichung rechts", "Durchmesser Differenz",
])
def test_nicht_angezeigte_messgroessen(name):
    assert ABELLIO.classify_zartbez(name) is None


# ---------- Wertebereich ----------

def test_nullwert_ist_platzhalter_und_wird_verworfen():
    f = load(
        row("Laufkreisdurchmesser Dlk links", 0, dg=(10, "DG", "Drehgestell"), rs=(20, "RS", "Radsatz 1/3")),
        row("Laufkreisdurchmesser Dlk links", 850.0, dg=(10, "DG", "Drehgestell"), rs=(20, "RS", "Radsatz 1/3")),
    )
    achse = next(iter(next(iter(f.einheiten["T1"].drehgestelle.values())).achsen.values()))
    assert [mp.stand for mp in achse.raeder[Side.LEFT].messreihen["LKD"].historie] == [850.0]


def test_null_bleibt_gueltig_bei_hohllauf():
    f = load(row("Auswalzung (Hohllauf) links", 0.0, dg=(10, "DG", "Drehgestell"), rs=(20, "RS", "Radsatz 1/3")))
    achse = next(iter(next(iter(f.einheiten["T1"].drehgestelle.values())).achsen.values()))
    assert len(achse.raeder[Side.LEFT].messreihen["HOHLLAUF"].historie) == 1


# ---------- Struktur ----------

def test_gleichnamige_drehgestelle_bleiben_getrennt_und_eindeutig_beschriftet():
    f = load(
        row("Laufkreisdurchmesser Dlk links", 800.0, dg=(10, "Laufdrehgestell / 50-466", "Drehgestell"), rs=(20, "RS-A", "Radsatz 1/3")),
        row("Laufkreisdurchmesser Dlk links", 801.0, dg=(11, "Laufdrehgestell / 50-467", "Drehgestell"), rs=(21, "RS-B", "Radsatz 1/3")),
        row("Laufkreisdurchmesser Dlk links", 802.0, dg=(12, "Triebdrehgestell / 1", "Triebdrehgestell"), rs=(22, "RS-C", "Radsatz 1/3")),
    )
    dgs = f.einheiten["T1"].drehgestelle
    assert set(dgs) == {
        "Drehgestell · Laufdrehgestell / 50-466",
        "Drehgestell · Laufdrehgestell / 50-467",
        "Triebdrehgestell",                      # eindeutige Position bleibt kurz
    }
    # Dict-Schluessel und dg_einbaupos stimmen ueberein (die UI sucht darueber)
    assert all(k == dg.dg_einbaupos for k, dg in dgs.items())
    # Messreihen verschiedener Drehgestelle wurden nicht vermischt
    anzahl = [sum(len(r.messreihen["LKD"].historie) for a in dg.achsen.values() for r in a.raeder.values())
              for dg in dgs.values()]
    assert anzahl == [1, 1, 1]


def test_einheit_ohne_drehgestell_und_radsatz_bekommt_sammelachse_mit_seiten():
    f = load(
        row("Laufkreisdurchmesser Dlk links", 810.0),
        row("Laufkreisdurchmesser Dlk rechts", 811.0),
    )
    (dg,) = f.einheiten["T1"].drehgestelle.values()
    assert dg.dg_einbaupos == "(ohne Drehgestell)"
    (achse,) = dg.achsen.values()
    assert set(achse.raeder) == {Side.LEFT, Side.RIGHT}
    assert dg.direkt_messreihen == {}


def test_drehgestell_ohne_radsatz_wird_darstellbare_achse():
    f = load(row("Laufkreisdurchmesser Dlk", 820.0, dg=(10, "DG", "Drehgestell")))
    (dg,) = f.einheiten["T1"].drehgestelle.values()
    (achse,) = dg.achsen.values()
    assert Side.UNSPECIFIED in achse.raeder


def test_lager_zeile_ohne_dg_und_radsatz_wird_uebersprungen():
    ausgebaut = datetime(2021, 1, 1)
    f = load(
        row("Laufkreisdurchmesser Dlk links", 800.0, ausbau=ausgebaut, aktuell=0),
        row("Laufkreisdurchmesser Dlk links", 801.0, ausbau=ausgebaut, aktuell=0,
            dg=(10, "DG-X", "Drehgestell"), rs=(20, "RS-X", "Radsatz 1/3")),
    )
    assert len(f.lager) == 1
    assert f.lager[0].dg_bez == "DG-X"


# ---------- Toleranzbereiche als Grenzwerte ----------

def _status(zartbez, stand, **kw):
    f = load(row(zartbez, stand, dg=(10, "DG", "Drehgestell"), rs=(20, "RS", "Radsatz 1/3"), **kw))
    achse = next(iter(next(iter(f.einheiten["T1"].drehgestelle.values())).achsen.values()))
    rad = next(iter(achse.raeder.values()))
    return classify_messreihe(next(iter(rad.messreihen.values())))


def test_bereich_wirkt_als_grenzwert_sh_nur_obergrenze():
    # Sh waechst mit Verschleiss: Bereich 26..36 -> nur die Obergrenze 36 zaehlt
    assert _status("Rad-Spurkranzhöhe Sh links", 30.0, min_b=26, max_b=36) == StatusAmpel.GREEN
    assert _status("Rad-Spurkranzhöhe Sh links", 36.5, min_b=26, max_b=36) == StatusAmpel.RED
    assert _status("Rad-Spurkranzhöhe Sh links", 26.5, min_b=26, max_b=36) == StatusAmpel.GREEN


def test_bereich_sd_nur_untergrenze():
    assert _status("Rad-Spurkranzdicke Sd links", 30.0, min_b=27.5, max_b=33) == StatusAmpel.GREEN
    assert _status("Rad-Spurkranzdicke Sd links", 27.0, min_b=27.5, max_b=33) == StatusAmpel.RED
    assert _status("Rad-Spurkranzdicke Sd links", 33.8, min_b=27.5, max_b=33) == StatusAmpel.GREEN


def test_bereich_spurmass_beidseitig():
    assert _status("Rad-Spurmaß SR", 1420.0, min_b=1415, max_b=1426) == StatusAmpel.GREEN
    assert _status("Rad-Spurmaß SR", 1414.0, min_b=1415, max_b=1426) == StatusAmpel.RED
    assert _status("Rad-Spurmaß SR", 1427.0, min_b=1415, max_b=1426) == StatusAmpel.RED


def test_ohne_grenzwerte_bleibt_ampel_grau():
    assert _status("Laufkreisdurchmesser Dlk links", 800.0) == StatusAmpel.GRAY


def test_min_hat_vorrang_vor_bereich():
    assert _status("Rad-Spurkranzflankenmaß qR links", 6.0, min_=6.5) == StatusAmpel.RED


# ---------- VGF bleibt unveraendert ----------

def test_vgf_nutzt_weiter_einbauposition_als_schluessel():
    assert (VGF.dg_key, VGF.fallback_axle, VGF.bereich_as_limits) == ("einbaupos", False, False)
    assert all(m.valid_range is None for m in VGF.catalog)
