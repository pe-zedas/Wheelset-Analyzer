"""Prognose-Tabelle (BO_RADSATZDATEN_PROGNOSE) an die Messreihen der Flotte haengen.

Gemeinsam fuer CSV und Oracle: ``attach_prognose`` bekommt Zeilen und den
Spaltenindex und haengt je Messreihe die juengste Prognose samt Treppenkurve an.
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Sequence

from .models import Flotte, Prognose, PrognosePunkt, Quality
from .parsing import get_field, parse_datetime, parse_float, parse_int, stringify_row
from .profile import Profile

log = logging.getLogger(__name__)


def attach_prognose(flotte: Flotte, profile: Profile, rows: Iterable[Sequence],
                    idx: Dict[str, int], *, stringify: bool = False,
                    label: str = "Prognose") -> int:
    """Reichert die Flotte um Prognosewerte an (nur prognose-faehige Messgroessen).

    Pro Messreihe wird die **juengste** Prognose uebernommen: bevorzugt eine Zeile
    mit AKTUELL=1; sonst die mit groesstem letzteaendzeit; sonst die mit spaetestem
    datum. Die Treppenkurve (``prog.punkte``) besteht aus allen Zeilen des Rades.

    ``rows``: Textzeilen (CSV) oder Datenbankwerte (Oracle, ``stringify=True``).
    Rueckgabe: Anzahl angereicherter Messreihen.
    """
    axis_by_ids = {}
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            for a in dg.achsen.values():
                axis_by_ids[(e.topeinheit_id, dg.dg_id, a.rs_id)] = (e, dg, a)

    # Lookup fuer Lagerkomponenten ueber rs_id (physische Achse; das Backend
    # identifiziert Lagerachsen eindeutig ueber RSEINHEITID).
    lager_axle_by_rsid: Dict[int, object] = {}
    lager_dg_axle_by_rsid: Dict[int, tuple] = {}
    for comp in flotte.lager:
        if comp.kind == "achse" and comp.rs_id is not None:
            lager_axle_by_rsid[comp.rs_id] = comp
        elif comp.kind == "drehgestell":
            for inner_axle in comp.achsen.values():
                if inner_axle.rs_id is not None:
                    lager_dg_axle_by_rsid[inner_axle.rs_id] = (comp, inner_axle)

    best: Dict[tuple, tuple] = {}
    punkte: Dict[tuple, List[PrognosePunkt]] = {}
    lager_best: Dict[tuple, tuple] = {}
    lager_punkte: Dict[tuple, List[PrognosePunkt]] = {}
    rows_total, skipped = 0, 0
    zi = idx.get("zartbez", -1)

    for raw in rows:
        rows_total += 1
        z = raw[zi] if 0 <= zi < len(raw) else None
        cls = profile.classify_zartbez(("" if z is None else str(z)).strip())
        if cls is None:
            continue
        mdef, side = cls
        if not mdef.prognosis:
            continue
        row = stringify_row(raw, profile.date_format) if stringify else raw

        key_axis = (
            parse_int(get_field(row, idx, "topeinheit_id")),
            parse_int(get_field(row, idx, "dg_id")),
            parse_int(get_field(row, idx, "rs_id")),
        )
        ausbau_s = get_field(row, idx, "ausbau")
        is_lager = bool(ausbau_s and ausbau_s.strip())

        if is_lager:
            rs_id = key_axis[2]
            if rs_id is None or (rs_id not in lager_axle_by_rsid
                                 and rs_id not in lager_dg_axle_by_rsid):
                skipped += 1
                continue
        elif axis_by_ids.get(key_axis) is None:
            skipped += 1
            continue

        datum = parse_datetime(get_field(row, idx, "datum"), profile.date_format)
        stand = parse_float(get_field(row, idx, "stand"), profile.decimal)
        lauf = parse_float(get_field(row, idx, "laufleistung"), profile.decimal)
        key_full = (key_axis[2], side, mdef.name) if is_lager else (key_axis, side, mdef.name)

        if datum is not None and stand is not None:
            pp = PrognosePunkt(datum=datum, stand=stand, laufleistung=lauf)
            (lager_punkte if is_lager else punkte).setdefault(key_full, []).append(pp)

        prog = Prognose(
            km_warnwert=parse_float(get_field(row, idx, "km_warnwert"), profile.decimal),
            datum_warnwert=parse_datetime(get_field(row, idx, "datum_warnwert"), profile.date_format),
            km_grenzwert=parse_float(get_field(row, idx, "km_grenzwert"), profile.decimal),
            datum_grenzwert=parse_datetime(get_field(row, idx, "datum_grenzwert"), profile.date_format),
            methode="theil_sen",
            qualitaet=Quality.OK,
        )
        # Score fuer "juengste" Prognose: AKTUELL > letzteaendzeit > datum
        aktuell = parse_int(get_field(row, idx, "aktuell")) or 0
        laend = parse_datetime(get_field(row, idx, "letzteaendzeit"), profile.date_format)
        score = (aktuell,
                 laend.timestamp() if laend else 0,
                 datum.timestamp() if datum else 0)
        store = lager_best if is_lager else best
        prev = store.get(key_full)
        if prev is None or score > prev[0]:
            store[key_full] = (score, prog)

    attached = 0
    for (key_axis, side, mg_name), (_score, prog) in best.items():
        _, _, achse = axis_by_ids[key_axis]
        rad = achse.raeder.get(side)
        mr = rad.messreihen.get(mg_name) if rad is not None else None
        if mr is None:
            skipped += 1
            continue
        prog.punkte = dedupe_treppe(punkte.get((key_axis, side, mg_name), []))
        mr.prognose = prog
        attached += 1

    attached_lager = 0
    for (rs_id, side, mg_name), (_score, prog) in lager_best.items():
        rad = None
        if rs_id in lager_axle_by_rsid:
            rad = lager_axle_by_rsid[rs_id].raeder.get(side)
        elif rs_id in lager_dg_axle_by_rsid:
            rad = lager_dg_axle_by_rsid[rs_id][1].raeder.get(side)
        mr = rad.messreihen.get(mg_name) if rad is not None else None
        if mr is None:
            skipped += 1
            continue
        prog.punkte = dedupe_treppe(lager_punkte.get((rs_id, side, mg_name), []))
        mr.prognose = prog
        attached_lager += 1

    log.info("%s: %d Zeilen gelesen, %d eingebaut + %d Lager angereichert, %d uebersprungen",
             label, rows_total, attached, attached_lager, skipped)
    return attached + attached_lager


def dedupe_treppe(raw: List[PrognosePunkt]) -> List[PrognosePunkt]:
    """Sortiert aufsteigend nach Datum und entfernt Duplikate.

    Bei zwei Punkten mit gleichem Datum bleibt die Reihenfolge der
    verbleibenden Punkte so, dass der groessere ``stand``-Wert zuerst
    kommt und der kleinere danach. Das macht aus einem Reprof-Doppel
    (vor/nach) einen sauberen senkrechten Sprung nach unten im
    verbundenen Linienzug.
    """
    seen = set()
    uniq = []
    for p in raw:
        key = (p.datum, round(p.stand, 4),
               round(p.laufleistung, 2) if p.laufleistung is not None else None)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    # Primaer nach Datum; sekundaer absteigend nach Stand (hoeherer Wert zuerst,
    # damit Reprof-Paare als "vor → nach"-Reihenfolge erscheinen).
    uniq.sort(key=lambda p: (p.datum, -p.stand))
    return uniq
