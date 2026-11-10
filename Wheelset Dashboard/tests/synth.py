"""Synthetische Rohdaten je Kundenprofil (ohne Datenbank, ohne echte Kundendaten).

``write_csv(profile_name, path)`` schreibt eine kleine ``BO_RADSATZDATEN``-CSV im
Spaltenaufbau des Profils. Sie enthaelt immer dieselbe Lage:

* eingebaute Einheit ``U1`` mit Drehgestellen, Achsen und Messreihen
  (MOB: ein Drehgestell mit vier Messpositionen, ohne Radsatz-Ebene),
* ein ausgebautes Drehgestell im Lager,
* ein frueherer Ausbau eines inzwischen wieder eingebauten Drehgestells
  (muss in der Lager-Liste fehlen).
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from wheelset_dashboard.data.profile import load_profile_by_name

PROFILES = ("vgf", "abellio", "mob")

T0 = datetime(2024, 1, 10, 8, 0)

# Eingebaute Raeder je Profil (Donut) und Lager-Raeder
WHEELS_INSTALLED = {"vgf": 6, "abellio": 6, "mob": 4}
WHEELS_LAGER = {"vgf": 2, "abellio": 2, "mob": 4}
N_DG = {"vgf": 2, "abellio": 2, "mob": 1}

# LKD / Spurkranzdicke links+rechts: Bezeichnung je Profil (echte Schreibweise)
_SIDED = {
    "vgf": {"lkd": ("Rad-Laufkreisdurchmesser-1", "Rad-Laufkreisdurchmesser-2"),
            "sd": ("Rad-Spurkranzstärke-1", "Rad-Spurkranzstärke-2")},
    "abellio": {"lkd": ("Laufkreisdurchmesser Dlk links", "Laufkreisdurchmesser Dlk rechts"),
                "sd": ("Rad-Spurkranzdicke Sd links", "Rad-Spurkranzdicke Sd rechts")},
}
_MOB = {"lkd": "Diamètre de roue", "sd": "Epaisseur du boudin "}


def _row(**kw) -> Dict[str, object]:
    base = dict(topeinheit_id=1, topeinheit_bez="U1", dg_id=None, dg_bez="", dg_einbaupos="",
                rs_id=None, rs_bez="", rs_einbaupos="", einbau=datetime(2020, 1, 1),
                ausbau=None, aktuell=1, zaehlerart_id=1, laufleistung=None,
                min_val=None, max_val=None, gelb_min=None, gelb_max=None,
                bereich_min=None, bereich_max=None)
    base.update(kw)
    return base


def _sided_rows(name: str) -> List[Dict[str, object]]:
    lkd, sd = _SIDED[name]["lkd"], _SIDED[name]["sd"]
    rows: List[Dict[str, object]] = []

    def series(*, te, dg, axle, ausbau, aktuell, start, n):
        dg_id, dg_pos = dg
        rs_id, rs_pos = axle
        for k in range(n):
            datum = start + timedelta(days=60 * k)
            for names, level, spread in ((lkd, 800.0, 0.3), (sd, 28.0, 0.1)):
                for off, zart in zip((0.0, spread), names):
                    rows.append(_row(
                        topeinheit_id=te[0], topeinheit_bez=te[1], dg_id=dg_id,
                        dg_bez=f"DG-{dg_id}", dg_einbaupos=dg_pos, rs_id=rs_id,
                        rs_bez=f"RS-{rs_id}", rs_einbaupos=rs_pos, ausbau=ausbau,
                        aktuell=aktuell, zartbez=zart, stand=level - 1.5 * k + off,
                        datum=datum, min_val=level - 20, max_val=level + 40,
                        gelb_min=level - 10, laufleistung=100000.0 + 20000 * k))

    u1 = (1, "U1")
    for dg, axle in (((10, "Drehgestell 1"), (100, "Achse 1")),
                     ((10, "Drehgestell 1"), (101, "Achse 2")),
                     ((11, "Drehgestell 2"), (102, "Achse 1"))):
        series(te=u1, dg=dg, axle=axle, ausbau=None, aktuell=1, start=T0, n=3)
    # Lager: ausgebautes Drehgestell mit einer Achse
    series(te=(0, "U0"), dg=(20, "Drehgestell 1"), axle=(200, "Achse 1"),
           ausbau=datetime(2023, 5, 1), aktuell=0, start=datetime(2022, 1, 10), n=2)
    # frueherer Ausbau von DG 10 (inzwischen wieder in U1 eingebaut)
    series(te=(0, "U0"), dg=(10, "Drehgestell 1"), axle=(100, "Achse 1"),
           ausbau=datetime(2022, 12, 1), aktuell=0, start=datetime(2021, 1, 10), n=2)
    return rows


def _mob_rows() -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []

    def session(*, te, dg_id, ausbau, aktuell, start, level):
        # je Messgroesse 4 Werte im Abstand von einer Minute (vier Raeder)
        for zart, base in ((_MOB["lkd"], level), (_MOB["sd"], 26.0)):
            for k in range(4):
                rows.append(_row(
                    topeinheit_id=te[0], topeinheit_bez=te[1], dg_id=dg_id,
                    dg_bez=f"Bogie {dg_id}", dg_einbaupos="Bogie EV 1 (IO)", ausbau=ausbau,
                    aktuell=aktuell, zartbez=zart, stand=base + k * 0.2,
                    datum=start + timedelta(minutes=k)))

    u1 = (1, "U1")
    session(te=u1, dg_id=10, ausbau=None, aktuell=1, start=T0, level=650.0)
    session(te=u1, dg_id=10, ausbau=None, aktuell=1, start=T0 + timedelta(days=150), level=649.0)
    session(te=(0, "U0"), dg_id=20, ausbau=datetime(2023, 5, 1), aktuell=0,
            start=datetime(2022, 1, 10), level=655.0)
    session(te=(0, "U0"), dg_id=10, ausbau=datetime(2022, 12, 1), aktuell=0,
            start=datetime(2021, 1, 10), level=660.0)
    return rows


def make_rows(name: str) -> List[Dict[str, object]]:
    return _mob_rows() if name == "mob" else _sided_rows(name)


def _fmt(v, date_format: str) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime(date_format)
    return str(v)


def write_csv(name: str, path: Path) -> Path:
    """Schreibt die Szenario-CSV im Spaltenaufbau des Profils ``name``."""
    profile = load_profile_by_name(name)
    cols = list(profile.columns_raw.items())          # (DB-Spalte, interner Name)
    with open(path, "w", encoding=profile.encoding, newline="") as fh:
        w = csv.writer(fh, delimiter=profile.delimiter)
        w.writerow([c for c, _ in cols])
        for row in make_rows(name):
            w.writerow([_fmt(row.get(internal), profile.date_format) for _, internal in cols])
    return path
