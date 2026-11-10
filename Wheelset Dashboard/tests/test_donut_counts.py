"""Donut-Zaehlung (Raeder je Status) fuer Achsen mit und ohne Radseite."""
from wheelset_dashboard.data.models import (
    Achse, Drehgestell, Einheit, Messreihe, Rad, Side, StatusAmpel,
)
from wheelset_dashboard.logic.aggregation import status_counts


def _rad(side, **stati):
    return Rad(seite=side, messreihen={
        name: Messreihe(messgroesse=name, status=st) for name, st in stati.items()})


def _einheit(*achsen):
    dg = Drehgestell(dg_id=1, dg_bez="DG", dg_einbaupos="Drehgestell",
                     achsen={a.rs_einbaupos: a for a in achsen})
    return Einheit(topeinheit_id=1, topeinheit_bez="E", drehgestelle={"Drehgestell": dg})


def _achse(pos, raeder):
    return Achse(rs_id=None, rs_bez="", rs_einbaupos=pos, raeder=raeder)


def test_achse_nur_mit_seitenlosen_messwerten_zaehlt_als_eine_messstelle():
    # z.B. Abellio: Messung am Drehgestell, keine Unterscheidung links/rechts
    e = _einheit(_achse("(Radsatz-Zuordnung fehlt)",
                        {Side.UNSPECIFIED: _rad(Side.UNSPECIFIED, LKD=StatusAmpel.GRAY)}))
    c = status_counts(e)
    assert c[StatusAmpel.GRAY] == 1 and sum(c.values()) == 1


def test_seitenloser_status_wird_uebernommen():
    e = _einheit(_achse("A", {Side.UNSPECIFIED: _rad(Side.UNSPECIFIED, SPUR=StatusAmpel.RED)}))
    assert status_counts(e)[StatusAmpel.RED] == 1


def test_mit_linkem_und_rechtem_rad_zaehlt_das_seitenlose_nicht_extra():
    # Spurmass/Stichmass haengen am seitenlosen Pseudo-Rad und gelten fuer beide Raeder
    e = _einheit(_achse("A", {
        Side.LEFT: _rad(Side.LEFT, LKD=StatusAmpel.GREEN),
        Side.RIGHT: _rad(Side.RIGHT, LKD=StatusAmpel.GREEN),
        Side.UNSPECIFIED: _rad(Side.UNSPECIFIED, SPUR=StatusAmpel.RED),
    }))
    c = status_counts(e)
    assert sum(c.values()) == 2
    assert c[StatusAmpel.RED] == 2          # achsweiter Status wird auf beide Raeder uebertragen


def test_achse_ohne_messreihen_zaehlt_nicht():
    e = _einheit(_achse("A", {Side.UNSPECIFIED: Rad(seite=Side.UNSPECIFIED)}))
    assert sum(status_counts(e).values()) == 0
