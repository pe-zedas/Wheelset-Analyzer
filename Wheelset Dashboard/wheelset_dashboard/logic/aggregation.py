"""UI-unabhaengige Aggregation ueber die Flottenstruktur.

Alles, was aus ``Flotte``/``Einheit``/``Drehgestell``/``Achse``/``LagerKomponente``
Kennzahlen fuer die Ansichten bildet (Donut-Zaehlung, Messgroessen-Spalten,
Faelligkeiten fuer das Gantt, Strukturzahlen) steht hier — ohne Qt, damit es
ohne Oberflaeche testbar ist. Die Ansichten rufen nur noch diese Funktionen auf.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Iterator, List, Optional, Tuple

from ..data.csv_source import MESSPOS_PREFIX, NO_DG_LABEL, is_synthetic_axle
from ..data.models import (
    Achse, Drehgestell, Einheit, Flotte, LagerKomponente, Messreihe, Side,
    StatusAmpel, _worst_messreihe, _worst_status,
)
from .prognose import faelligkeit_shift


# ---------- Strukturzahlen ----------

def n_real_dg(einheit) -> int:
    """Anzahl echter Drehgestelle (ohne das Sammel-Drehgestell fuer Messwerte,
    die keinem Drehgestell zugeordnet sind)."""
    return sum(1 for dg in einheit.drehgestelle.values() if dg.dg_einbaupos != NO_DG_LABEL)


def n_real_achsen(dg) -> int:
    """Anzahl echter Achsen (ohne Sammel-Achse und Messpositionen)."""
    return sum(1 for a in dg.achsen.values() if not is_synthetic_axle(a.rs_einbaupos))


def n_messpositionen(dg) -> int:
    """Anzahl synthetischer Messpositionen ("Messposition 1..N", z.B. MOB)."""
    return sum(1 for a in dg.achsen.values()
               if a.rs_einbaupos.startswith(MESSPOS_PREFIX + " "))


# ---------- Traversierung ----------

def iter_messreihen(obj) -> Iterator[Messreihe]:
    """Alle Messreihen unter einem Flotte-/Einheit-/DG-/Achse-/Lager-Objekt."""
    if isinstance(obj, Flotte):
        for e in obj.einheiten.values():
            yield from iter_messreihen(e)
    elif isinstance(obj, Einheit):
        for dg in obj.drehgestelle.values():
            yield from iter_messreihen(dg)
    elif isinstance(obj, Drehgestell):
        for a in obj.achsen.values():
            yield from iter_messreihen(a)
        yield from obj.direkt_messreihen.values()
    elif isinstance(obj, Achse):
        for r in obj.raeder.values():
            yield from r.messreihen.values()
    elif isinstance(obj, LagerKomponente):
        yield from obj.messreihen.values()
        for r in obj.raeder.values():
            yield from r.messreihen.values()
        for a in obj.achsen.values():
            yield from iter_messreihen(a)


def has_messdaten(obj) -> bool:
    """True, wenn unter ``obj`` (Flotte, Einheit, Drehgestell, Achse oder
    Lager-Komponente) mindestens eine Messreihe mindestens einen Messpunkt hat.
    Eine Ebene hat Messdaten, sobald eine darunterliegende Komponente welche hat."""
    return any(mr.historie for mr in iter_messreihen(obj))


def iter_achsen(obj) -> Iterator[object]:
    """Alle Achsen unter ``obj``; ``obj`` darf auch eine Liste sein.

    Eine Lager-Achse (``kind == "achse"``) ist selbst die Achse (ihre Raeder
    haengen direkt an ihr), ein Lager-Drehgestell liefert seine Achsen.
    """
    if isinstance(obj, (list, tuple)):
        for o in obj:
            yield from iter_achsen(o)
    elif isinstance(obj, Flotte):
        for e in obj.einheiten.values():
            yield from iter_achsen(e)
    elif isinstance(obj, Einheit):
        for dg in obj.drehgestelle.values():
            yield from iter_achsen(dg)
    elif isinstance(obj, Drehgestell):
        yield from obj.achsen.values()
    elif isinstance(obj, LagerKomponente):
        if obj.kind == "achse":
            yield obj
        else:
            yield from obj.achsen.values()
    elif isinstance(obj, Achse):
        yield obj


# ---------- Donut: Status je Rad ----------

def messstellen_stati(achse) -> List[StatusAmpel]:
    """Status je Messstelle (Rad) einer Achse — Grundlage der Donut-Zaehlung.

    * Jedes Rad links/rechts mit Messreihen ist eine Messstelle. Sein Status ist
      der schlechteste aus den eigenen und den achsweiten Messreihen.
    * Achsweite Messreihen (Spurmass/Stichmass) haengen am Pseudo-Rad
      ``unspecified`` und gelten fuer beide Raeder; sonst zeigte die Tabelle rote
      Spur-Punkte, der Donut aber keine roten Raeder.
    * Hat eine Achse **nur** seitenlose Messwerte (Abellio: am Drehgestell
      gemessen; MOB: Messposition), zaehlt dieses Pseudo-Rad als eine Messstelle
      — sonst waere der Donut leer, obwohl Daten vorliegen.
    """
    extra: List[StatusAmpel] = []
    for side, rad in achse.raeder.items():
        if side == Side.UNSPECIFIED:
            extra.extend(m.status for m in rad.messreihen.values())
    stati: List[StatusAmpel] = []
    for side, rad in achse.raeder.items():
        if side == Side.UNSPECIFIED:
            continue
        if not rad.messreihen and not extra:
            continue
        stati.append(_worst_status([m.status for m in rad.messreihen.values()] + extra))
    if not stati and extra:
        stati.append(_worst_status(extra))
    return stati


def status_counts(obj) -> Dict[StatusAmpel, int]:
    """Raeder je Status unter ``obj`` (Flotte, Einheit, Drehgestell, Achse,
    Lager-Komponente oder eine Liste davon)."""
    counts = {s: 0 for s in StatusAmpel}
    for achse in iter_achsen(obj):
        for st in messstellen_stati(achse):
            counts[st] += 1
    return counts


# ---------- Messgroessen-Spalten ----------

def collect_messgroessen_values(obj) -> Dict[str, Tuple[StatusAmpel, Optional[float]]]:
    """Pro Messgroesse: Status und letzter Wert der schlechtesten Messreihe im Objekt."""
    worst: Dict[str, Messreihe] = {}
    for mr in iter_messreihen(obj):
        worst[mr.messgroesse] = _worst_messreihe(worst.get(mr.messgroesse), mr)
    result: Dict[str, Tuple[StatusAmpel, Optional[float]]] = {}
    for name, mr in worst.items():
        letzt = mr.letzter_wert()
        result[name] = (mr.status, letzt.stand if letzt else None)
    return result


# ---------- Faelligkeiten (Gantt) ----------

def collect_gantt_entries(groups, flotte, prog_cfg):
    """Sammelt Reprof-/Warn-/Grenz-Termine pro Gruppe (Einheit oder DG).

    Die Werte werden direkt aus ``mr.prognose`` (Prognose-Tabelle)
    gelesen — keine Live-Berechnung mehr.

    * Warn-/Grenz-Datum stehen als Endpunkte in der Tabelle.
    * Reprofilierungen werden aus ``prog.punkte`` extrahiert: zwei Punkte
      am selben Datum, deren zweiter ``stand`` kleiner ist als der erste,
      markieren eine prognostizierte Reprofilierung an diesem Datum.
      Nur Reprofs in der Zukunft (nach heute) erscheinen im Gantt.

    ``groups`` ist eine Liste ``(label, iterable_of_drehgestelle)``.
    Rueckgabe: Liste von
    ``(label, [(reprof_datum, achse_label), …],
             [(warn_datum, achse_label), …],
             [(grenz_datum, achse_label), …],
             note | None)``.

    Pro Achse wird nur das kritischste Rad eingezeichnet (frueheste
    Grenzueberschreitung; sonst frueheste Warnung). Dessen Reprofs,
    Warn- und Grenz-Marker werden aufgenommen.
    """
    heute = datetime.now()
    out = []
    _side = {"left": "links", "right": "rechts", "unspecified": "–"}
    NOTE_NO_PROGNOSE = "keine Prognosedaten vorhanden"

    def _future_reprofs(prog, mr) -> List[datetime]:
        """Zukuenftige Reprof-Datumswerte aus prog.punkte extrahieren.

        Die Prognose-Treppe ist im Backend an den letzten Messwert geankert
        (damit sie im Diagramm nahtlos an die Historie anknuepft). Fuer die
        Faelligkeits-Kachel muessen die Reprof-Termine aber ab heute gelten
        — eine Lagerachse verschleisst nicht, die Restlebensdauer zaehlt ab
        Wiederinbetriebnahme. Wir verschieben die Reprof-Datumswerte um
        delta = heute − letzter Messwert (nur fuer ruhende Raeder).
        """
        pts = list(getattr(prog, "punkte", []) or [])
        letzt = mr.letzter_wert() if mr is not None else None
        delta = timedelta(0)
        if letzt is not None and letzt.datum < heute:
            delta = heute - letzt.datum
        out_d: List[datetime] = []
        for a, b in zip(pts, pts[1:]):
            # Zwei Punkte am selben Datum und der zweite springt nach
            # unten → prognostizierte Reprofilierung.
            if a.datum == b.datum and b.stand < a.stand:
                shifted = b.datum + delta
                if shifted > heute:
                    out_d.append(shifted)
        return out_d

    for label, dgs in groups:
        reprofs: List[Tuple[datetime, str]] = []
        warns: List[Tuple[datetime, str]] = []
        grenze: List[Tuple[datetime, str]] = []
        has_any_history = False
        has_any_prognose = False
        for dg in dgs:
            for achse in dg.achsen.values():
                rad_marker = []   # (reprofs, warn_d, grenz_d, axis_label)
                for seite, rad in achse.raeder.items():
                    mr = rad.messreihen.get("LKD")
                    if mr is None or not mr.historie:
                        continue
                    has_any_history = True
                    prog = mr.prognose
                    if prog is None:
                        continue
                    # Verschiebung in die Zukunft: NUR fuer Faelligkeits-
                    # Anzeigen (Kachel, KpiCards, Info-Box, Export).
                    # Logik in logic.prognose.faelligkeit_shift.
                    warn_d = faelligkeit_shift(prog.datum_warnwert, mr)
                    grenz_d = faelligkeit_shift(prog.datum_grenzwert, mr)
                    rad_reprofs = _future_reprofs(prog, mr)
                    if (warn_d is None and grenz_d is None and not rad_reprofs):
                        continue
                    has_any_prognose = True
                    axis_label = (
                        f"{dg.dg_einbaupos} · {achse.rs_einbaupos} · "
                        f"Rad {_side.get(seite.value, seite.value)}"
                    )
                    rad_marker.append(
                        ([(d, axis_label) for d in rad_reprofs],
                         warn_d, grenz_d, axis_label)
                    )
                if not rad_marker:
                    continue
                with_grenz = [r for r in rad_marker if r[2] is not None]
                if with_grenz:
                    crit = min(with_grenz, key=lambda r: r[2])
                else:
                    with_warn = [r for r in rad_marker if r[1] is not None]
                    if with_warn:
                        crit = min(with_warn, key=lambda r: r[1])
                    else:
                        crit = rad_marker[0]
                rad_reprofs, warn_d, grenz_d, axis_label = crit
                # Reprofs auf den Zeitraum bis zur Grenzueberschreitung begrenzen
                if grenz_d is not None:
                    rad_reprofs = [r for r in rad_reprofs if r[0] <= grenz_d]
                reprofs.extend(rad_reprofs)
                if warn_d is not None:
                    warns.append((warn_d, axis_label))
                if grenz_d is not None:
                    grenze.append((grenz_d, axis_label))
        reprofs.sort(key=lambda t: t[0])
        warns.sort(key=lambda t: t[0])
        grenze.sort(key=lambda t: t[0])
        # Note nur anzeigen, wenn fuer diese Gruppe wirklich KEINE
        # Prognose-Daten in der Tabelle stehen. Bei vorhandener Prognose,
        # aber ohne Marker im Sichtfenster (alle Fälligkeiten liegen vor
        # heute oder weit in der Zukunft), bleibt die Zeile leer.
        if (reprofs or warns or grenze) or has_any_prognose:
            note = None
        else:
            note = NOTE_NO_PROGNOSE
        out.append((label, reprofs, warns, grenze, note))
    return out
