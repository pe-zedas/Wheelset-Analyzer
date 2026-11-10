"""Ableitung des Lager-Zustands aus der Mess-Historie.

Regel (F-DATA-1, PRD Abschnitt 3.4):
  - STORED_READY     — nach dem letzten AUSBAU existiert ein Messpunkt mit
                       deutlich positivem LKD-Sprung (>= jump_mm) oder
                       deutlich hoeherem LKD als beim Ausbau.
  - STORED_TO_OVERHAUL — sonst (keine Messung nach Ausbau oder kein Sprung).

Nur die kanonische Messgroesse ``LKD`` wird fuer die Erkennung herangezogen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..data.models import ComponentState, Flotte, LagerKomponente


@dataclass
class LagerParams:
    jump_mm: float = 2.0           # Mindest-LKD-Sprung, der als Reprofilierung gilt
    tolerance_mm: float = 0.5      # kleinere Schwankungen beim Vergleich ignorieren


def _lkd_history(comp: LagerKomponente):
    """Kombinierte LKD-Historie ueber flache messreihen + beide Raeder."""
    hist = []
    mr = comp.messreihen.get("LKD")
    if mr: hist.extend(mr.historie)
    for r in comp.raeder.values():
        mr = r.messreihen.get("LKD")
        if mr: hist.extend(mr.historie)
    return hist


def classify_komponente(comp: LagerKomponente, params: LagerParams) -> ComponentState:
    """Bestimmt den Zustand einer Lager-Komponente."""
    historie = _lkd_history(comp)
    if not historie or comp.ausbau is None:
        return ComponentState.STORED_TO_OVERHAUL

    # Vor- und Nach-Ausbau trennen
    vor = [mp for mp in historie if mp.datum <= comp.ausbau]
    nach = [mp for mp in historie if mp.datum > comp.ausbau]
    if not nach:
        return ComponentState.STORED_TO_OVERHAUL

    letzt_vor = max(vor, key=lambda mp: mp.datum).stand if vor else None
    hoechst_nach = max(mp.stand for mp in nach)

    # Variante 1: direkter Vergleich mit letztem Vor-Ausbau-Wert
    if letzt_vor is not None and hoechst_nach - letzt_vor >= params.jump_mm:
        return ComponentState.STORED_READY

    # Variante 2: Sprung zwischen aufeinanderfolgenden Punkten in `nach`
    sorted_nach = sorted(nach, key=lambda mp: mp.datum)
    for prev, cur in zip(sorted_nach, sorted_nach[1:]):
        if cur.stand - prev.stand >= params.jump_mm:
            return ComponentState.STORED_READY

    return ComponentState.STORED_TO_OVERHAUL


def recompute_all(flotte: Flotte, params: Optional[LagerParams] = None) -> dict:
    params = params or LagerParams()
    counts = {"ready": 0, "to_overhaul": 0}
    for comp in flotte.lager:
        comp.state = classify_komponente(comp, params)
        if comp.state == ComponentState.STORED_READY:
            counts["ready"] += 1
        else:
            counts["to_overhaul"] += 1
    return counts
