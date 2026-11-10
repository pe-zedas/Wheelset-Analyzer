"""logic.aggregation: Donut-Zaehlung (auch fuer Lager), Messgroessen-Spalten,
Strukturzahlen und Gantt-Eintraege — ohne Qt, mit handgebauten Objekten."""
from datetime import datetime, timedelta

from wheelset_dashboard.data.structure import (
    KIND_MESSPOSITION, KIND_SAMMEL, MESSPOS_PREFIX, NO_DG_LABEL, NO_RS_LABEL,
)
from wheelset_dashboard.data.models import (
    Achse, Drehgestell, Einheit, Flotte, LagerKomponente, Messpunkt, Messreihe, Prognose,
    Rad, Side, StatusAmpel,
)
from wheelset_dashboard.logic.aggregation import (
    collect_gantt_entries, collect_messgroessen_values, iter_achsen, n_messpositionen,
    n_real_achsen, n_real_dg, status_counts,
)

G, Y, R, GR = StatusAmpel.GREEN, StatusAmpel.YELLOW, StatusAmpel.RED, StatusAmpel.GRAY


def mr(name, status, stand=None, datum=None):
    hist = [Messpunkt(datum=datum or datetime(2024, 1, 1), stand=stand)] if stand is not None else []
    return Messreihe(messgroesse=name, status=status, historie=hist)


def rad(side, **stati):
    return Rad(seite=side, messreihen={n: mr(n, s) for n, s in stati.items()})


def achse(pos, raeder, kind="radsatz"):
    return Achse(rs_id=None, rs_bez="", rs_einbaupos=pos, raeder=raeder, kind=kind)


def lager_achse(raeder):
    return LagerKomponente(rs_id=1, rs_bez="RS", letzte_einheit="E", ausbau=datetime(2020, 1, 1),
                           kind="achse", raeder=raeder)


def lager_dg(*achsen):
    return LagerKomponente(rs_id=None, rs_bez="", letzte_einheit="E", ausbau=datetime(2020, 1, 1),
                           kind="drehgestell", dg_bez="DG", achsen={a.rs_einbaupos: a for a in achsen})


# ---------- Donut ----------

def test_lager_achse_und_lager_drehgestell_zaehlen_nach_derselben_regel():
    zwei_raeder = {Side.LEFT: rad(Side.LEFT, LKD=G), Side.RIGHT: rad(Side.RIGHT, LKD=Y)}
    c = status_counts([lager_achse(dict(zwei_raeder)),
                       lager_dg(achse("A1", dict(zwei_raeder)))])
    assert (c[G], c[Y], c[R], c[GR]) == (2, 2, 0, 0)


def test_achsweiter_status_gilt_auch_im_lager_fuer_beide_raeder():
    k = lager_dg(achse("A1", {
        Side.LEFT: rad(Side.LEFT, LKD=G), Side.RIGHT: rad(Side.RIGHT, LKD=G),
        Side.UNSPECIFIED: rad(Side.UNSPECIFIED, SPUR=R)}))
    c = status_counts(k)
    assert c[R] == 2 and sum(c.values()) == 2


def test_lager_komponente_nur_mit_seitenlosen_werten_ist_eine_messstelle():
    k = lager_dg(achse(NO_RS_LABEL, {Side.UNSPECIFIED: rad(Side.UNSPECIFIED, LKD=Y)}, KIND_SAMMEL))
    c = status_counts(k)
    assert c[Y] == 1 and sum(c.values()) == 1


def test_leeres_lager_und_leere_liste_zaehlen_null():
    assert sum(status_counts([]).values()) == 0
    assert sum(status_counts(lager_dg()).values()) == 0


def test_flotte_summiert_alle_ebenen():
    dg = Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG", achsen={"A": achse("A", {
        Side.LEFT: rad(Side.LEFT, LKD=R), Side.RIGHT: rad(Side.RIGHT, LKD=G)})})
    f = Flotte(einheiten={"E": Einheit(topeinheit_id=1, topeinheit_bez="E", drehgestelle={"DG": dg})})
    assert status_counts(f)[R] == status_counts(f.einheiten["E"])[R] == status_counts(dg)[R] == 1
    assert len(list(iter_achsen(f))) == 1


# ---------- Messgroessen-Spalten ----------

def test_messgroesse_zeigt_schlechtesten_status_und_dessen_letzten_wert():
    a = achse("A", {
        Side.LEFT: Rad(seite=Side.LEFT, messreihen={"LKD": mr("LKD", G, 800.0)}),
        Side.RIGHT: Rad(seite=Side.RIGHT, messreihen={"LKD": mr("LKD", R, 781.5)})})
    dg = Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG", achsen={"A": a},
                     direkt_messreihen={"SPUR": mr("SPUR", Y, 1435.0)})
    werte = collect_messgroessen_values(dg)
    assert werte["LKD"] == (R, 781.5)
    assert werte["SPUR"] == (Y, 1435.0)       # direkt am Drehgestell gemessen zaehlt mit


def test_messgroesse_ohne_messpunkt_hat_keinen_wert():
    a = achse("A", {Side.LEFT: Rad(seite=Side.LEFT, messreihen={"LKD": mr("LKD", GR)})})
    assert collect_messgroessen_values(a)["LKD"] == (GR, None)


# ---------- Strukturzahlen ----------

def test_sammelobjekte_und_messpositionen_zaehlen_nicht_als_echte_struktur():
    dg = Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG", achsen={
        "Achse 1": achse("Achse 1", {}),
        NO_RS_LABEL: achse(NO_RS_LABEL, {}, KIND_SAMMEL),
        f"{MESSPOS_PREFIX} 1": achse(f"{MESSPOS_PREFIX} 1", {}, KIND_MESSPOSITION),
        f"{MESSPOS_PREFIX} 2": achse(f"{MESSPOS_PREFIX} 2", {}, KIND_MESSPOSITION)})
    sammel = Drehgestell(dg_id=None, dg_bez="", dg_einbaupos=NO_DG_LABEL, synthetic=True)
    e = Einheit(topeinheit_id=1, topeinheit_bez="E", drehgestelle={"a": dg, "b": sammel})
    assert n_real_dg(e) == 1
    assert n_real_achsen(dg) == 1
    assert n_messpositionen(dg) == 2


# ---------- Gantt ----------

def _flotte_mit_prognose(prog):
    heute = datetime.now()
    lkd = Messreihe(messgroesse="LKD", historie=[Messpunkt(datum=heute - timedelta(days=1), stand=790.0)],
                    prognose=prog, status=G)
    a = achse("A1", {Side.LEFT: Rad(seite=Side.LEFT, messreihen={"LKD": lkd})})
    return Drehgestell(dg_id=1, dg_bez="", dg_einbaupos="DG1", achsen={"A1": a})


def test_gantt_ohne_prognose_zeigt_hinweis():
    dg = _flotte_mit_prognose(None)
    (label, reprofs, warns, grenze, note), = collect_gantt_entries([("E", [dg])], Flotte(), None)
    assert (label, reprofs, warns, grenze) == ("E", [], [], [])
    assert note == "keine Prognosedaten vorhanden"


def test_gantt_mit_warntermin_hat_marker_und_keinen_hinweis():
    prog = Prognose(datum_warnwert=datetime.now() + timedelta(days=30),
                    datum_grenzwert=datetime.now() + timedelta(days=90))
    dg = _flotte_mit_prognose(prog)
    (_, _, warns, grenze, note), = collect_gantt_entries([("E", [dg])], Flotte(), None)
    assert len(warns) == 1 and len(grenze) == 1 and note is None
    assert "DG1" in warns[0][1] and "A1" in warns[0][1]
