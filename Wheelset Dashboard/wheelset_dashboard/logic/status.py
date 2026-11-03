"""Status-Ampel-Berechnung.

Pro Messreihe wird der Status ausschliesslich aus dem letzten Ist-Messwert
gegen die hinterlegten Schwellen (MIN/MAX/GELB_MIN/GELB_MAX) bestimmt.
Die Prognose fliesst NICHT in die Ampel ein — sie wird im Detail-Plot nur
visualisiert.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..data.models import (
    Flotte,
    Messpunkt,
    Messreihe,
    StatusAmpel,
)


# ---------- Einzel-Messreihe ----------

def classify_messpunkt_ist(mp: Messpunkt, direction: str = "both") -> StatusAmpel:
    """Ist-Status eines Messpunkts aus seinen Schwellen (ohne Prognose).

    `direction` steuert, welche Seite der Schwellen semantisch relevant ist:
    - "decreasing": nur min_val / gelb_min (z. B. LKD, SD — Verschleiss fuehrt
      zu kleinerem Wert; Schwellen auf der oberen Seite werden ignoriert, auch
      wenn die CSV sie liefert).
    - "increasing": nur max_val / gelb_max (z. B. Ueberwalzung — Verschleiss
      fuehrt zu groesserem Wert).
    - "both": beide Seiten (Standard, fuer symmetrische Groessen).

    Zusaetzliche Validitaetspruefung: Warn-/Grenzwerte muessen innerhalb des
    gueltigen Zahlenbereichs liegen, damit unsinnige CSV-Werte die Ampel nicht
    faelsch auf GELB/ROT setzen.
    """
    stand = mp.stand
    min_v, max_v = mp.min_val, mp.max_val
    gmin, gmax = mp.gelb_min, mp.gelb_max

    use_lower = direction in ("decreasing", "both")
    use_upper = direction in ("increasing", "both")

    use_min = use_lower and min_v is not None and (max_v is None or min_v < max_v)
    use_max = use_upper and max_v is not None and (min_v is None or max_v > min_v)
    use_gmin = use_lower and gmin is not None \
                         and (max_v is None or gmin < max_v) \
                         and (min_v is None or gmin > min_v)
    use_gmax = use_upper and gmax is not None \
                         and (min_v is None or gmax > min_v) \
                         and (max_v is None or gmax < max_v)

    if use_min and stand <= min_v:
        return StatusAmpel.RED
    if use_max and stand >= max_v:
        return StatusAmpel.RED
    if use_gmin and stand <= gmin:
        return StatusAmpel.YELLOW
    if use_gmax and stand >= gmax:
        return StatusAmpel.YELLOW
    if not (use_min or use_max or use_gmin or use_gmax):
        return StatusAmpel.GRAY
    return StatusAmpel.GREEN


def classify_messreihe(mr: Messreihe, now: Optional[datetime] = None) -> StatusAmpel:
    """Gesamt-Status einer Messreihe aus dem letzten Ist-Messwert."""
    letzt = mr.letzter_wert()
    if letzt is None:
        return StatusAmpel.GRAY
    direction = getattr(mr, "direction", "both")
    return classify_messpunkt_ist(letzt, direction=direction)


# ---------- Rollup fuer die ganze Flotte ----------

def recompute_all(flotte: Flotte, now: Optional[datetime] = None) -> None:
    """Berechnet Status pro Messreihe in der gesamten Flotte und im Lager."""
    for einheit in flotte.einheiten.values():
        for dg in einheit.drehgestelle.values():
            for mr in dg.direkt_messreihen.values():
                mr.status = classify_messreihe(mr, now)
            for achse in dg.achsen.values():
                for rad in achse.raeder.values():
                    for mr in rad.messreihen.values():
                        mr.status = classify_messreihe(mr, now)
    for comp in flotte.lager:
        for mr in comp.messreihen.values():
            mr.status = classify_messreihe(mr, now)
        for rad in comp.raeder.values():
            for mr in rad.messreihen.values():
                mr.status = classify_messreihe(mr, now)
        for a in comp.achsen.values():
            for rad in a.raeder.values():
                for mr in rad.messreihen.values():
                    mr.status = classify_messreihe(mr, now)
