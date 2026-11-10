"""Aufbau der Flottenstruktur aus Rohzeilen (gemeinsam fuer CSV und Oracle).

``build_flotte`` macht aus Rohzeilen (``BO_RADSATZDATEN``) die Hierarchie
Flotte > Einheit > Drehgestell > Achse > Rad > Messreihe sowie die Lager-
Komponenten und bringt sie in die endgueltige Form (``finalize_structure``):
wieder eingebaute Komponenten aus dem Lager nehmen, Raeder auf Messpositionen
verteilen, Drehgestell-Beschriftungen eindeutig machen.

Synthetische Strukturen (Sammel-Drehgestell, Sammel-Achse, Messpositionen) sind
im Modell markiert (``Drehgestell.synthetic``, ``Achse.kind``); Ansichten und
Auswertungen pruefen diese Felder, nicht die Beschriftung.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from .models import (
    Achse,
    ComponentState,
    Drehgestell,
    Einheit,
    Flotte,
    LagerKomponente,
    Messpunkt,
    Messreihe,
    Rad,
    Side,
)
from .parsing import get_field, parse_datetime, parse_float, parse_int, stringify_row
from .profile import Profile

log = logging.getLogger(__name__)

# Achsen-Arten (siehe ``Achse.kind``)
KIND_RADSATZ = "radsatz"
KIND_SAMMEL = "sammel"
KIND_MESSPOSITION = "messposition"


# Beschriftung fuer Zeilen ohne Drehgestell-/Radsatz-Ebene (Profile mit
# ``dg_key: id`` bzw. ``fallback_axle``).
NO_DG_LABEL = "(ohne Drehgestell)"
NO_RS_LABEL = "(Radsatz-Zuordnung fehlt)"
# Synthetische Achsen "Messposition 1..N" (Profil ``wheel_positions``).
MESSPOS_PREFIX = "Messposition"
# Werte desselben Messtermins liegen innerhalb weniger Minuten; Termine sind
# mindestens Stunden auseinander.
SESSION_GAP = timedelta(minutes=30)


def make_messpunkt(get, profile: Profile, mdef, datum: datetime,
                    stand: float) -> Optional[Messpunkt]:
    """Baut einen Messpunkt aus einer Rohzeile. ``get(name)`` liefert den
    Rohtext der internen Spalte ``name``.

    Gibt ``None`` zurueck, wenn der Messwert ausserhalb des gueltigen
    Wertebereichs der Messgroesse liegt (z.B. 0 als Platzhalter ohne
    Messung).
    """
    if mdef.valid_range is not None:
        lo, hi = mdef.valid_range
        if not (lo <= stand <= hi):
            return None
    dec = profile.decimal
    min_val = parse_float(get("min_val"), dec)
    max_val = parse_float(get("max_val"), dec)
    if profile.bereich_as_limits:
        if min_val is None:
            min_val = parse_float(get("bereich_min"), dec)
        if max_val is None:
            max_val = parse_float(get("bereich_max"), dec)
    return Messpunkt(
        datum=datum,
        stand=stand,
        laufleistung=parse_float(get("laufleistung"), dec),
        min_val=min_val,
        max_val=max_val,
        gelb_min=parse_float(get("gelb_min"), dec),
        gelb_max=parse_float(get("gelb_max"), dec),
    )


def split_wheel_positions(achsen: Dict[str, Achse], n: int) -> int:
    """Verteilt die Werte der Sammel-Achse auf ``n`` Messpositionen.

    Datenlage (MOB): je Messtermin liefert die Messanlage ``n`` Werte je Messgroesse
    nacheinander im Abstand von ca. einer Minute, ohne Seiten- oder Achsangabe. Der
    k-te Wert eines Termins gehoert zur k-ten Messposition. Das ist die
    Messreihenfolge, **nicht** nachgewiesen die Radnummer am Fahrzeug.

    Nur Termine mit genau ``n`` Werten einer Messgroesse werden verteilt; alle
    anderen bleiben in der Sammel-Achse (es wird nichts geraten).
    Gibt die Anzahl verteilter Messpunkte zurueck.
    """
    sammel = achsen.get(NO_RS_LABEL)
    rad = sammel.raeder.get(Side.UNSPECIFIED) if sammel is not None else None
    if rad is None or n < 2:
        return 0
    moved = 0
    for name in list(rad.messreihen):
        mr = rad.messreihen[name]
        sessions: List[List[Messpunkt]] = []
        for mp in sorted(mr.historie, key=lambda p: p.datum):
            if sessions and mp.datum - sessions[-1][-1].datum <= SESSION_GAP:
                sessions[-1].append(mp)
            else:
                sessions.append([mp])
        rest: List[Messpunkt] = []
        for sess in sessions:
            if len(sess) != n:
                rest.extend(sess)
                continue
            for k, mp in enumerate(sess, start=1):
                label = f"{MESSPOS_PREFIX} {k}"
                ax = achsen.get(label)
                if ax is None:
                    ax = Achse(rs_id=None, rs_bez="", rs_einbaupos=label,
                               einbau=sammel.einbau, ausbau=sammel.ausbau,
                               aktuell=sammel.aktuell, state=sammel.state,
                               kind=KIND_MESSPOSITION)
                    achsen[label] = ax
                r = ax.raeder.get(Side.UNSPECIFIED)
                if r is None:
                    r = Rad(seite=Side.UNSPECIFIED)
                    ax.raeder[Side.UNSPECIFIED] = r
                nmr = r.messreihen.get(name)
                if nmr is None:
                    nmr = Messreihe(messgroesse=mr.messgroesse, einheit=mr.einheit,
                                    direction=mr.direction)
                    r.messreihen[name] = nmr
                nmr.historie.append(mp)
            moved += n
        if rest:
            mr.historie = rest
        else:
            del rad.messreihen[name]
    if not rad.messreihen:
        del sammel.raeder[Side.UNSPECIFIED]
    if not sammel.raeder:
        del achsen[NO_RS_LABEL]
    return moved


def drop_reinstalled_lager(flotte: Flotte) -> int:
    """Entfernt Lager-Komponenten, die inzwischen wieder eingebaut sind.

    Ein Bauteil steht nur an seinem zuletzt benutzten Platz: Gibt es eingebaute
    Zeilen (AUSBAU leer, AKTUELL=1) zur selben DG-ID bzw. Radsatz-ID, ist das
    Bauteil nicht im Lager. Die Messhistorie des frueheren Einbaus wird dabei
    nicht in die eingebaute Reihe uebernommen (Laufleistung und Prognose gelten
    je Einbau).
    """
    inst_dg_ids, inst_dg_bez, inst_rs_ids = set(), set(), set()
    for e in flotte.einheiten.values():
        for dg in e.drehgestelle.values():
            if dg.dg_id is not None:
                inst_dg_ids.add(dg.dg_id)
            elif dg.dg_bez:
                inst_dg_bez.add(dg.dg_bez)
            for a in dg.achsen.values():
                if a.rs_id is not None:
                    inst_rs_ids.add(a.rs_id)

    def reinstalled(c: LagerKomponente) -> bool:
        if c.kind == "drehgestell":
            if c.dg_id is not None:
                return c.dg_id in inst_dg_ids
            return bool(c.dg_bez) and c.dg_bez in inst_dg_bez
        return c.rs_id is not None and c.rs_id in inst_rs_ids

    kept = [c for c in flotte.lager if not reinstalled(c)]
    dropped = len(flotte.lager) - len(kept)
    flotte.lager = kept
    return dropped


def finalize_structure(flotte: Flotte, profile: Profile) -> None:
    """Letzter Schritt nach dem Einlesen (CSV und Oracle gleichermassen).

    1. Wieder eingebaute Bauteile aus der Lager-Liste nehmen.
    2. Profile mit ``wheel_positions``: Sammel-Achse auf Messpositionen verteilen.
    3. Profile mit ``dg_key: id``: Drehgestell-Beschriftungen je Einheit eindeutig
       machen. Die UI identifiziert ein Drehgestell ueber ``dg_einbaupos``. Kommt
       dieselbe Position innerhalb einer Einheit mehrfach vor (Abellio: mehrere
       "Drehgestell"), wird die Bezeichnung angehaengt; eindeutige Positionen
       bleiben kurz.
    """
    dropped = drop_reinstalled_lager(flotte)
    if dropped:
        log.info("Lager (%s): %d wieder eingebaute Komponenten ausgeblendet", profile.name, dropped)
    if profile.wheel_positions:
        n = profile.wheel_positions
        moved = 0
        for e in flotte.einheiten.values():
            for dg in e.drehgestelle.values():
                moved += split_wheel_positions(dg.achsen, n)
        for c in flotte.lager:
            moved += split_wheel_positions(c.achsen, n)
        log.info("Messpositionen (%s): %d Messpunkte auf %d Positionen verteilt",
                 profile.name, moved, n)
    if profile.dg_key != "id":
        return
    for einheit in flotte.einheiten.values():
        pos_count: Dict[str, int] = {}
        for dg in einheit.drehgestelle.values():
            pos_count[dg.dg_einbaupos] = pos_count.get(dg.dg_einbaupos, 0) + 1
        relabeled: Dict[str, Drehgestell] = {}
        for dg in einheit.drehgestelle.values():
            label = dg.dg_einbaupos
            if pos_count[label] > 1:
                label = (f"{label} · {dg.dg_bez}" if dg.dg_bez
                         else f"{label} #{dg.dg_id}")
            base, n = label, 2
            while label in relabeled:
                label = f"{base} #{n}"
                n += 1
            dg.dg_einbaupos = label
            relabeled[label] = dg
        einheit.drehgestelle = relabeled


def add_installed(flotte: Flotte, row, idx, profile: Profile, mdef, side: Side, mp: Messpunkt):
    topeinheit_bez = get_field(row, idx, "topeinheit_bez").strip() or "<unbekannt>"
    einheit = flotte.einheiten.get(topeinheit_bez)
    if einheit is None:
        einheit = Einheit(
            topeinheit_id=parse_int(get_field(row, idx, "topeinheit_id")),
            topeinheit_bez=topeinheit_bez,
        )
        flotte.einheiten[topeinheit_bez] = einheit

    dg_id = parse_int(get_field(row, idx, "dg_id"))
    dg_pos = get_field(row, idx, "dg_einbaupos").strip()
    dg_bez = get_field(row, idx, "dg_bez").strip()
    if profile.dg_key == "id":
        # Position ist nicht eindeutig -> physisches DG ueber seine ID fuehren;
        # die Beschriftung wird in finalize_structure() eindeutig gemacht.
        if dg_id is not None:
            dg_key = f"#{dg_id}"
        elif dg_pos or dg_bez:
            dg_key = f"{dg_pos}|{dg_bez}"
        else:
            dg_key = "<ohne DG>"
        dg_label = dg_pos or (NO_DG_LABEL if dg_key == "<ohne DG>" else dg_bez)
    else:
        dg_key = dg_label = dg_pos or "<DG?>"
    dg = einheit.drehgestelle.get(dg_key)
    if dg is None:
        dg = Drehgestell(dg_id=dg_id, dg_bez=dg_bez, dg_einbaupos=dg_label,
                         synthetic=(dg_key == "<ohne DG>"))
        einheit.drehgestelle[dg_key] = dg

    rs_einbaupos = get_field(row, idx, "rs_einbaupos").strip()
    if profile.hierarchy_depth >= 4 and not rs_einbaupos and profile.fallback_axle:
        rs_einbaupos = NO_RS_LABEL
    if profile.hierarchy_depth >= 4 and rs_einbaupos:
        achse = dg.achsen.get(rs_einbaupos)
        if achse is None:
            achse = Achse(
                rs_id=parse_int(get_field(row, idx, "rs_id")),
                rs_bez=get_field(row, idx, "rs_bez").strip(),
                rs_einbaupos=rs_einbaupos,
                einbau=parse_datetime(get_field(row, idx, "einbau"), profile.date_format),
                ausbau=None,
                aktuell=1,
                state=ComponentState.INSTALLED,
                kind=KIND_SAMMEL if rs_einbaupos == NO_RS_LABEL else KIND_RADSATZ,
            )
            dg.achsen[rs_einbaupos] = achse

        rad = achse.raeder.get(side)
        if rad is None:
            rad = Rad(seite=side)
            achse.raeder[side] = rad
        append_messreihe(rad.messreihen, mdef, mp)
    else:
        # keine Radsatz-Ebene (MOB) -> direkt am DG
        append_messreihe(dg.direkt_messreihen, mdef, mp)


def add_lager(lager_map, row, idx, profile: Profile, mdef, side: Side, mp: Messpunkt,
               ausbau) -> bool:
    """Regel: Hat eine ausgebaute Achse ein zugeordnetes DG, so wurde das
    komplette DG ausgebaut. Dann gruppieren wir alle Achsen desselben DG unter
    einer gemeinsamen Lager-Komponente (kind=drehgestell).

    Gibt ``False`` zurueck, wenn die Zeile weder einem DG noch einem Radsatz
    zugeordnet werden kann (sonst wuerden alle solchen Zeilen zu einer
    Phantom-Komponente verschmelzen)."""
    rs_id = parse_int(get_field(row, idx, "rs_id"))
    rs_bez = get_field(row, idx, "rs_bez").strip()
    dg_bez = get_field(row, idx, "dg_bez").strip()
    dg_id = parse_int(get_field(row, idx, "dg_id"))
    rs_einbaupos = get_field(row, idx, "rs_einbaupos").strip()

    has_dg = (dg_id is not None) or bool(dg_bez)
    if not has_dg and rs_id is None and not rs_bez:
        return False
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
            letzte_einheit=get_field(row, idx, "topeinheit_bez").strip(),
            ausbau=ausbau or datetime(1970, 1, 1),
            einbau=parse_datetime(get_field(row, idx, "einbau"), profile.date_format),
            state=ComponentState.STORED_TO_OVERHAUL,
            kind=kind,
            dg_bez=dg_bez,
            dg_id=dg_id if has_dg else None,
        )
        lager_map[key] = comp
    else:
        # Mehrere Ausbau-Zyklen -> immer das juengste Ausbau-Datum verwenden
        if ausbau and (comp.ausbau is None or ausbau > comp.ausbau):
            comp.ausbau = ausbau
            comp.letzte_einheit = get_field(row, idx, "topeinheit_bez").strip()

    if kind == "drehgestell":
        # Unter dem DG: eine Achse pro rs_id/rs_einbaupos
        axle_key = rs_einbaupos or rs_bez or (
            f"RS-{rs_id}" if rs_id is not None else NO_RS_LABEL)
        achse = comp.achsen.get(axle_key)
        if achse is None:
            achse = Achse(
                rs_id=rs_id, rs_bez=rs_bez,
                rs_einbaupos=rs_einbaupos or axle_key,
                einbau=parse_datetime(get_field(row, idx, "einbau"), profile.date_format),
                ausbau=ausbau,
                aktuell=0,
                state=ComponentState.STORED_TO_OVERHAUL,
                kind=KIND_SAMMEL if axle_key == NO_RS_LABEL else KIND_RADSATZ,
            )
            comp.achsen[axle_key] = achse
        rad = achse.raeder.get(side)
        if rad is None:
            rad = Rad(seite=side)
            achse.raeder[side] = rad
        append_messreihe(rad.messreihen, mdef, mp)
    else:
        rad = comp.raeder.get(side)
        if rad is None:
            rad = Rad(seite=side)
            comp.raeder[side] = rad
        append_messreihe(rad.messreihen, mdef, mp)
    return True


def append_messreihe(container: Dict[str, Messreihe], mdef, mp: Messpunkt):
    key = mdef.name
    mr = container.get(key)
    if mr is None:
        mr = Messreihe(messgroesse=key, einheit=mdef.unit,
                       direction=getattr(mdef, "direction", "decreasing"))
        container[key] = mr
    mr.historie.append(mp)


# ---------- Rohzeilen -> Flotte ----------

def build_flotte(rows: Iterable[Sequence], idx: Dict[str, int], profile: Profile, *,
                 stringify: bool = False, label: str = "Rohdaten") -> Flotte:
    """Baut Flotte und Lager aus Rohzeilen.

    ``rows``: Zeilen als Textlisten (CSV) oder als Datenbankwerte (Oracle,
    dann ``stringify=True``). ``idx``: interner Spaltenname -> Spaltenindex.

    Die Messgroesse wird zuerst klassifiziert: unbekannte Zeilen (z.B.
    Bremsscheiben) werden verworfen, bevor die teure Textkonvertierung aller
    Spalten laeuft.
    """
    flotte = Flotte()
    lager_map: Dict[tuple, LagerKomponente] = {}
    stats = dict(rows=0, kept=0, dropped=0, unknown_zartbez=0, invalid_value=0,
                 lager=0, lager_unassigned=0)
    zi = idx.get("zartbez", -1)

    for raw in rows:
        stats["rows"] += 1
        z = raw[zi] if 0 <= zi < len(raw) else None
        zartbez = ("" if z is None else str(z)).strip()
        if not zartbez:
            stats["dropped"] += 1
            continue
        cls = profile.classify_zartbez(zartbez)
        if cls is None:
            stats["unknown_zartbez"] += 1
            continue
        mdef, side = cls

        row = stringify_row(raw, profile.date_format) if stringify else raw
        datum = parse_datetime(get_field(row, idx, "datum"), profile.date_format)
        stand = parse_float(get_field(row, idx, "stand"), profile.decimal)
        if datum is None or stand is None:
            stats["dropped"] += 1
            continue

        mp = make_messpunkt(lambda k: get_field(row, idx, k), profile, mdef, datum, stand)
        if mp is None:
            stats["invalid_value"] += 1
            continue

        ausbau = parse_datetime(get_field(row, idx, "ausbau"), profile.date_format)
        aktuell = parse_int(get_field(row, idx, "aktuell")) or 0
        if ausbau is None and aktuell == 1:
            add_installed(flotte, row, idx, profile, mdef, side, mp)
            stats["kept"] += 1
        elif add_lager(lager_map, row, idx, profile, mdef, side, mp, ausbau):
            stats["lager"] += 1
        else:
            stats["lager_unassigned"] += 1

    flotte.lager = list(lager_map.values())
    finalize_structure(flotte, profile)
    log.info("%s verarbeitet (%s): %s", label, profile.name, stats)
    return flotte
