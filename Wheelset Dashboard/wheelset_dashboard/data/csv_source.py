"""CSV-Loader fuer bo_radsatzdaten / bo_radsatzdaten_prognose, profilgesteuert."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .models import (
    Achse,
    ComponentState,
    Drehgestell,
    Einheit,
    Flotte,
    LagerKomponente,
    Messpunkt,
    Messreihe,
    Prognose,
    PrognosePunkt,
    Quality,
    Rad,
    Side,
    StatusAmpel,
)
from .profile import Profile

log = logging.getLogger(__name__)


# ---------- helpers ----------

def _parse_float(s: str, decimal: str) -> Optional[float]:
    if s is None or s == "":
        return None
    s = s.strip()
    if not s:
        return None
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(s: str) -> Optional[int]:
    if not s:
        return None
    try:
        return int(float(s.strip()))
    except ValueError:
        return None


def _parse_datetime(s: str, fmt: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for f in (fmt, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _get(row: List[str], idx_map: Dict[str, int], key: str) -> str:
    i = idx_map.get(key)
    if i is None or i >= len(row):
        return ""
    return row[i]


# ---------- raw -> Flotte ----------

def load_raw_csv(path: Path, profile: Profile) -> Flotte:
    """Liest bo_radsatzdaten_export.csv und baut die Flotten-/Lager-Struktur auf."""
    flotte = Flotte()
    lager_map: Dict[Tuple[Optional[int], str], LagerKomponente] = {}
    stats = dict(rows=0, kept=0, dropped=0, unknown_zartbez=0, lager=0)

    with open(path, "r", encoding=profile.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=profile.delimiter)
        header = next(reader)
        idx = profile.map_raw_header(header)
        if "zartbez" not in idx or "datum" not in idx or "stand" not in idx:
            missing = [k for k in ("zartbez", "datum", "stand") if k not in idx]
            raise ValueError(
                f"Pflicht-Spalten fehlen nach Mapping (Profil {profile.name}): {missing}. "
                f"Header war: {header[:5]}..."
            )

        for row in reader:
            stats["rows"] += 1
            zartbez = _get(row, idx, "zartbez").strip()
            if not zartbez:
                stats["dropped"] += 1
                continue

            cls = profile.classify_zartbez(zartbez)
            if cls is None:
                stats["unknown_zartbez"] += 1
                continue
            mdef, side = cls

            datum = _parse_datetime(_get(row, idx, "datum"), profile.date_format)
            stand = _parse_float(_get(row, idx, "stand"), profile.decimal)
            if datum is None or stand is None:
                stats["dropped"] += 1
                continue

            mp = Messpunkt(
                datum=datum,
                stand=stand,
                laufleistung=_parse_float(_get(row, idx, "laufleistung"), profile.decimal),
                min_val=_parse_float(_get(row, idx, "min_val"), profile.decimal),
                max_val=_parse_float(_get(row, idx, "max_val"), profile.decimal),
                gelb_min=_parse_float(_get(row, idx, "gelb_min"), profile.decimal),
                gelb_max=_parse_float(_get(row, idx, "gelb_max"), profile.decimal),
            )

            ausbau = _parse_datetime(_get(row, idx, "ausbau"), profile.date_format)
            aktuell = _parse_int(_get(row, idx, "aktuell")) or 0
            installed = ausbau is None and aktuell == 1

            if installed:
                _add_installed(flotte, row, idx, profile, mdef, side, mp)
                stats["kept"] += 1
            else:
                _add_lager(lager_map, row, idx, profile, mdef, side, mp, ausbau)
                stats["lager"] += 1

    flotte.lager = list(lager_map.values())
    log.info("CSV geladen (%s): %s", profile.name, stats)
    return flotte


def _add_installed(flotte: Flotte, row, idx, profile: Profile, mdef, side: Side, mp: Messpunkt):
    topeinheit_bez = _get(row, idx, "topeinheit_bez").strip() or "<unbekannt>"
    einheit = flotte.einheiten.get(topeinheit_bez)
    if einheit is None:
        einheit = Einheit(
            topeinheit_id=_parse_int(_get(row, idx, "topeinheit_id")),
            topeinheit_bez=topeinheit_bez,
        )
        flotte.einheiten[topeinheit_bez] = einheit

    dg_key = _get(row, idx, "dg_einbaupos").strip() or "<DG?>"
    dg = einheit.drehgestelle.get(dg_key)
    if dg is None:
        dg = Drehgestell(
            dg_id=_parse_int(_get(row, idx, "dg_id")),
            dg_bez=_get(row, idx, "dg_bez").strip(),
            dg_einbaupos=dg_key,
        )
        einheit.drehgestelle[dg_key] = dg

    rs_einbaupos = _get(row, idx, "rs_einbaupos").strip()
    if profile.hierarchy_depth >= 4 and rs_einbaupos:
        achse = dg.achsen.get(rs_einbaupos)
        if achse is None:
            achse = Achse(
                rs_id=_parse_int(_get(row, idx, "rs_id")),
                rs_bez=_get(row, idx, "rs_bez").strip(),
                rs_einbaupos=rs_einbaupos,
                einbau=_parse_datetime(_get(row, idx, "einbau"), profile.date_format),
                ausbau=None,
                aktuell=1,
                state=ComponentState.INSTALLED,
            )
            dg.achsen[rs_einbaupos] = achse

        rad = achse.raeder.get(side)
        if rad is None:
            rad = Rad(seite=side)
            achse.raeder[side] = rad
        _append_messreihe(rad.messreihen, mdef, mp)
    else:
        # keine Radsatz-Ebene (MOB) -> direkt am DG
        _append_messreihe(dg.direkt_messreihen, mdef, mp)


def _add_lager(lager_map, row, idx, profile: Profile, mdef, side: Side, mp: Messpunkt, ausbau):
    """Regel: Hat eine ausgebaute Achse ein zugeordnetes DG, so wurde das
    komplette DG ausgebaut. Dann gruppieren wir alle Achsen desselben DG unter
    einer gemeinsamen Lager-Komponente (kind=drehgestell)."""
    rs_id = _parse_int(_get(row, idx, "rs_id"))
    rs_bez = _get(row, idx, "rs_bez").strip()
    dg_bez = _get(row, idx, "dg_bez").strip()
    dg_id = _parse_int(_get(row, idx, "dg_id"))
    rs_einbaupos = _get(row, idx, "rs_einbaupos").strip()

    has_dg = (dg_id is not None) or bool(dg_bez)
    if has_dg:
        key = ("dg", dg_id, dg_bez)
        kind = "drehgestell"
    else:
        key = ("rs", rs_id, rs_bez)
        kind = "achse"

    comp = lager_map.get(key)
    if comp is None:
        comp = LagerKomponente(
            rs_id=None if has_dg else rs_id,
            rs_bez="" if has_dg else rs_bez,
            letzte_einheit=_get(row, idx, "topeinheit_bez").strip(),
            ausbau=ausbau or datetime(1970, 1, 1),
            einbau=_parse_datetime(_get(row, idx, "einbau"), profile.date_format),
            state=ComponentState.STORED_TO_OVERHAUL,
            kind=kind,
            dg_bez=dg_bez,
        )
        lager_map[key] = comp
    else:
        # Mehrere Ausbau-Zyklen -> immer das juengste Ausbau-Datum verwenden
        if ausbau and (comp.ausbau is None or ausbau > comp.ausbau):
            comp.ausbau = ausbau
            comp.letzte_einheit = _get(row, idx, "topeinheit_bez").strip()

    if kind == "drehgestell":
        # Unter dem DG: eine Achse pro rs_id/rs_einbaupos
        axle_key = rs_einbaupos or (rs_bez or f"RS-{rs_id}")
        achse = comp.achsen.get(axle_key)
        if achse is None:
            achse = Achse(
                rs_id=rs_id, rs_bez=rs_bez,
                rs_einbaupos=rs_einbaupos or axle_key,
                einbau=_parse_datetime(_get(row, idx, "einbau"), profile.date_format),
                ausbau=ausbau,
                aktuell=0,
                state=ComponentState.STORED_TO_OVERHAUL,
            )
            comp.achsen[axle_key] = achse
        rad = achse.raeder.get(side)
        if rad is None:
            rad = Rad(seite=side)
            achse.raeder[side] = rad
        _append_messreihe(rad.messreihen, mdef, mp)
    else:
        rad = comp.raeder.get(side)
        if rad is None:
            rad = Rad(seite=side)
            comp.raeder[side] = rad
        _append_messreihe(rad.messreihen, mdef, mp)


def _append_messreihe(container: Dict[str, Messreihe], mdef, mp: Messpunkt):
    key = mdef.name
    mr = container.get(key)
    if mr is None:
        mr = Messreihe(messgroesse=key, einheit=mdef.unit,
                       direction=getattr(mdef, "direction", "decreasing"))
        container[key] = mr
    mr.historie.append(mp)


# ---------- Prognose ----------

def load_prognose_csv(path: Path, profile: Profile, flotte: Flotte) -> int:
    """Reichert vorhandene Flotte um Prognosewerte an (nur prognose-faehige Messgroessen).

    Pro Messreihe wird die **jüngste** Prognose übernommen: bevorzugt eine Zeile mit
    AKTUELL=1; sonst die mit größtem letzteaendzeit; sonst die mit spätestem datum.
    """
    if not Path(path).exists():
        log.warning("Prognose-CSV nicht gefunden: %s", path)
        return 0

    axis_by_ids = {}
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            for a in dg.achsen.values():
                axis_by_ids[(e.topeinheit_id, dg.dg_id, a.rs_id)] = (e, dg, a)

    # Lookup fuer Lagerkomponenten ueber rs_id (physische Achse).
    lager_axle_by_rsid: Dict[int, "object"] = {}
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

    with open(path, "r", encoding=profile.encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=profile.delimiter)
        header = next(reader)
        idx = profile.map_prognose_header(header)

        for row in reader:
            rows_total += 1
            zartbez = _get(row, idx, "zartbez").strip()
            cls = profile.classify_zartbez(zartbez)
            if cls is None:
                continue
            mdef, side = cls
            if not mdef.prognosis:
                continue

            key_axis = (
                _parse_int(_get(row, idx, "topeinheit_id")),
                _parse_int(_get(row, idx, "dg_id")),
                _parse_int(_get(row, idx, "rs_id")),
            )
            ausbau_s = _get(row, idx, "ausbau")
            is_lager = bool(ausbau_s and ausbau_s.strip())

            if is_lager:
                rs_id = key_axis[2]
                if rs_id is None:
                    skipped += 1
                    continue
                if rs_id not in lager_axle_by_rsid and rs_id not in lager_dg_axle_by_rsid:
                    skipped += 1
                    continue
            else:
                if axis_by_ids.get(key_axis) is None:
                    skipped += 1
                    continue

            datum = _parse_datetime(_get(row, idx, "datum"), profile.date_format)
            stand = _parse_float(_get(row, idx, "stand"), profile.decimal)
            lauf = _parse_float(_get(row, idx, "laufleistung"), profile.decimal)
            if is_lager:
                key_full = (key_axis[2], side, mdef.name)
            else:
                key_full = (key_axis, side, mdef.name)

            if datum is not None and stand is not None:
                pp = PrognosePunkt(datum=datum, stand=stand, laufleistung=lauf)
                if is_lager:
                    lager_punkte.setdefault(key_full, []).append(pp)
                else:
                    punkte.setdefault(key_full, []).append(pp)

            prog = Prognose(
                km_warnwert=_parse_float(_get(row, idx, "km_warnwert"), profile.decimal),
                datum_warnwert=_parse_datetime(_get(row, idx, "datum_warnwert"), profile.date_format),
                km_grenzwert=_parse_float(_get(row, idx, "km_grenzwert"), profile.decimal),
                datum_grenzwert=_parse_datetime(_get(row, idx, "datum_grenzwert"), profile.date_format),
                methode="theil_sen",
                qualitaet=Quality.OK,
            )
            # Score fuer "jüngste" Prognose: AKTUELL > letzteaendzeit > datum
            aktuell = _parse_int(_get(row, idx, "aktuell")) or 0
            laend = _parse_datetime(_get(row, idx, "letzteaendzeit"), profile.date_format)
            score = (
                aktuell,
                laend.timestamp() if laend else 0,
                datum.timestamp() if datum else 0,
            )
            store = lager_best if is_lager else best
            prev = store.get(key_full)
            if prev is None or score > prev[0]:
                store[key_full] = (score, prog)

    attached = 0
    for (key_axis, side, mg_name), (_score, prog) in best.items():
        _, _, achse = axis_by_ids[key_axis]
        rad = achse.raeder.get(side)
        if rad is None:
            skipped += 1
            continue
        mr = rad.messreihen.get(mg_name)
        if mr is None:
            skipped += 1
            continue
        raw = punkte.get((key_axis, side, mg_name), [])
        prog.punkte = _dedupe_treppe(raw)
        mr.prognose = prog
        attached += 1

    attached_lager = 0
    for (rs_id, side, mg_name), (_score, prog) in lager_best.items():
        rad = None
        if rs_id in lager_axle_by_rsid:
            comp = lager_axle_by_rsid[rs_id]
            rad = comp.raeder.get(side)
        elif rs_id in lager_dg_axle_by_rsid:
            _comp, inner_axle = lager_dg_axle_by_rsid[rs_id]
            rad = inner_axle.raeder.get(side)
        if rad is None:
            skipped += 1
            continue
        mr = rad.messreihen.get(mg_name)
        if mr is None:
            skipped += 1
            continue
        raw = lager_punkte.get((rs_id, side, mg_name), [])
        prog.punkte = _dedupe_treppe(raw)
        mr.prognose = prog
        attached_lager += 1

    log.info(
        "Prognose-CSV: %d Zeilen gelesen, %d eingebaut + %d Lager angereichert, %d uebersprungen",
        rows_total, attached, attached_lager, skipped,
    )
    return attached + attached_lager


def _dedupe_treppe(raw: List[PrognosePunkt]) -> List[PrognosePunkt]:
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
