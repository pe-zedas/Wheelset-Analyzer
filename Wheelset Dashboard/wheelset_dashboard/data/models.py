"""Datenmodell fuer das Wheelset Dashboard.

Hierarchie (siehe PRD Abschnitt 5.3):
    Flotte -> Einheit -> Drehgestell -> Achse -> Rad -> Messreihe -> Messpunkt

Lager-Komponenten werden ueber dieselben Klassen abgebildet, aber ueber
ComponentState markiert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class Side(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    UNSPECIFIED = "unspecified"


class ComponentState(str, Enum):
    INSTALLED = "installed"           # eingebaut (AUSBAU leer, AKTUELL=1)
    STORED_TO_OVERHAUL = "to_overhaul"
    STORED_READY = "ready"


class StatusAmpel(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GRAY = "gray"                     # keine Prognose / Schwellen moeglich


class Quality(str, Enum):
    OK = "ok"
    INSUFFICIENT = "insufficient"
    NO_DATA_FOR_PROGNOSIS = "no_data_for_prognosis"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class Messpunkt:
    datum: datetime
    stand: float                       # Messwert [mm]
    laufleistung: Optional[float] = None   # [km]
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    gelb_min: Optional[float] = None
    gelb_max: Optional[float] = None


@dataclass
class Prognose:
    km_warnwert: Optional[float] = None
    datum_warnwert: Optional[datetime] = None
    km_grenzwert: Optional[float] = None
    datum_grenzwert: Optional[datetime] = None
    methode: Optional[str] = None
    qualitaet: Quality = Quality.NOT_APPLICABLE
    # Komplette Treppenkurve aus der Prognose-Tabelle als
    # (datum, lkd_stand, laufleistung_km). Zeitlich aufsteigend sortiert;
    # Reprofilierungen erscheinen als zwei Punkte am selben Datum
    # (erst der hoehere "vor"-Wert, dann der niedrigere "nach"-Wert),
    # sodass ein verbindender Linienzug einen senkrechten Sprung
    # nach unten zeichnet.
    punkte: List["PrognosePunkt"] = field(default_factory=list)


@dataclass
class PrognosePunkt:
    datum: datetime
    stand: float
    laufleistung: Optional[float] = None


@dataclass
class Messreihe:
    messgroesse: str                   # kanonisch, z.B. "LKD", "SPURKRANZDICKE_SD"
    einheit: str = "mm"
    direction: str = "decreasing"      # "decreasing" | "increasing" | "both"
    historie: List[Messpunkt] = field(default_factory=list)
    prognose: Optional[Prognose] = None
    status: StatusAmpel = StatusAmpel.GRAY

    def letzter_wert(self) -> Optional[Messpunkt]:
        """Chronologisch jüngster Messpunkt (robust auch bei unsortierter Historie)."""
        if not self.historie:
            return None
        return max(self.historie, key=lambda mp: mp.datum)


@dataclass
class Rad:
    seite: Side
    messreihen: Dict[str, Messreihe] = field(default_factory=dict)

    def status(self) -> StatusAmpel:
        return _worst_status(m.status for m in self.messreihen.values())


@dataclass
class Achse:
    rs_id: Optional[int]
    rs_bez: str
    rs_einbaupos: str
    einbau: Optional[datetime] = None
    ausbau: Optional[datetime] = None
    aktuell: int = 1
    state: ComponentState = ComponentState.INSTALLED
    raeder: Dict[Side, Rad] = field(default_factory=dict)

    def status(self) -> StatusAmpel:
        return _worst_status(r.status() for r in self.raeder.values())


@dataclass
class Drehgestell:
    dg_id: Optional[int]
    dg_bez: str
    dg_einbaupos: str
    achsen: Dict[str, Achse] = field(default_factory=dict)
    # Falls kein Radsatz vorhanden (MOB-Fall), Messungen direkt am DG:
    direkt_messreihen: Dict[str, Messreihe] = field(default_factory=dict)

    def status(self) -> StatusAmpel:
        stati = [a.status() for a in self.achsen.values()]
        stati += [m.status for m in self.direkt_messreihen.values()]
        return _worst_status(stati)


@dataclass
class Einheit:
    topeinheit_id: Optional[int]
    topeinheit_bez: str
    drehgestelle: Dict[str, Drehgestell] = field(default_factory=dict)

    def status(self) -> StatusAmpel:
        return _worst_status(d.status() for d in self.drehgestelle.values())


@dataclass
class LagerKomponente:
    """Ausgebaute Achse oder komplettes Drehgestell im Lager."""
    rs_id: Optional[int]
    rs_bez: str
    letzte_einheit: str                 # TOPEINHEIT, aus der ausgebaut
    ausbau: datetime
    einbau: Optional[datetime] = None
    state: ComponentState = ComponentState.STORED_TO_OVERHAUL
    kind: str = "achse"                 # "achse" | "drehgestell"
    dg_bez: str = ""                    # fuer DG-Komponenten
    # Historie der Messreihen am Rad (bei Achse: direkt, bei DG: aggregiert ueber die Achsen)
    raeder: Dict[Side, Rad] = field(default_factory=dict)
    messreihen: Dict[str, Messreihe] = field(default_factory=dict)
    # Nur bei kind == "drehgestell": eingebaute Achsen
    achsen: Dict[str, "Achse"] = field(default_factory=dict)
    # Nur bei kind == "drehgestell": DGEINHEITID (zum Abgleich mit eingebauten DG)
    dg_id: Optional[int] = None

    def status(self) -> StatusAmpel:
        stati = [m.status for m in self.messreihen.values()]
        for r in self.raeder.values():
            stati.append(r.status())
        for a in self.achsen.values():
            stati.append(a.status())
        return _worst_status(stati)

    def messgroessen_stati(self) -> Dict[str, StatusAmpel]:
        """Status pro Messgröße, aggregiert über Räder/Achsen/direkte Reihen."""
        return {k: v[0] for k, v in self.messgroessen_data().items()}

    def messgroessen_data(self) -> Dict[str, "tuple[StatusAmpel, Optional[float]]"]:
        """Pro Messgröße: Status + letzter Wert der schlechtesten Messreihe."""
        out_mr: Dict[str, "Messreihe"] = {}
        def consider(mr: "Messreihe"):
            prev = out_mr.get(mr.messgroesse)
            out_mr[mr.messgroesse] = _worst_messreihe(prev, mr)
        for mr in self.messreihen.values():
            consider(mr)
        for r in self.raeder.values():
            for mr in r.messreihen.values():
                consider(mr)
        for a in self.achsen.values():
            for r in a.raeder.values():
                for mr in r.messreihen.values():
                    consider(mr)
        result: Dict[str, tuple] = {}
        for name, mr in out_mr.items():
            letzt = mr.letzter_wert()
            result[name] = (mr.status, letzt.stand if letzt else None)
        return result


@dataclass
class PrognoseConfig:
    """Konfigurierbare Defaults fuer die Prognose-Visualisierung.

    Logik aus dem Backend-Programm ``Radsatz_Bahn_DB_new_Approach.py`` nachgebaut:
    - Reprofilierung ist ein **negativer** LKD-Sprung (Material abgetragen).
    - Zukuenftige Reprof wird im festen km-Intervall ausgeloest (NICHT bei GELB_MIN).
    - Werte werden aus der Historie gelernt, sonst gelten die Fallback-Defaults.
    """
    # Erkennung in der Historie (Seeds)
    reprof_dkm_threshold: float = 5000.0  # max. km-Abstand fuer eine Reprof-Erkennung
    reprof_dlkd_abs_min: float = 3.0      # Mindest-Abtrag (mm) als abs. Betrag
    # Projektions-Fallbacks (wenn Historie zu knapp)
    reprof_typical_interval_km: float = 100000.0  # km-Abstand zwischen zwei Reprof
    reprof_typical_magnitude_mm: float = 8.0      # Standardmaessiger Abtrag pro Reprof
    # Fit-Parameter
    min_points_fit: int = 4
    min_points_quality: int = 8
    iqr_factor: float = 2.0
    ci_level: float = 0.90
    # Verhalten
    auto_from_history: bool = True
    show_reprof_steps: bool = True
    show_ci_band: bool = False


@dataclass
class Flotte:
    einheiten: Dict[str, Einheit] = field(default_factory=dict)
    lager: List[LagerKomponente] = field(default_factory=list)

    def status(self) -> StatusAmpel:
        return _worst_status(e.status() for e in self.einheiten.values())

    def alle_achsen(self):
        for e in self.einheiten.values():
            for dg in e.drehgestelle.values():
                for a in dg.achsen.values():
                    yield e, dg, a


_ORDER = {
    StatusAmpel.RED: 3,
    StatusAmpel.YELLOW: 2,
    StatusAmpel.GREEN: 1,
    StatusAmpel.GRAY: 0,
}


def _worst_status(stati) -> StatusAmpel:
    worst = StatusAmpel.GRAY
    for s in stati:
        if _ORDER[s] > _ORDER[worst]:
            worst = s
    return worst


def _is_worse_value(a_val: float, b_val: float, template_mp: Optional[Messpunkt]) -> bool:
    if template_mp is not None:
        if template_mp.min_val is not None or template_mp.gelb_min is not None:
            return a_val < b_val
        if template_mp.max_val is not None or template_mp.gelb_max is not None:
            return a_val > b_val
    return False


def _worst_messreihe(prev: Optional[Messreihe], cand: Optional[Messreihe]) -> Optional[Messreihe]:
    """Liefert die schlechtere der beiden Messreihen (Status zuerst, dann numerischer Wert)."""
    if prev is None:
        return cand
    if cand is None:
        return prev
    sp = _ORDER.get(prev.status, 0)
    sc = _ORDER.get(cand.status, 0)
    if sc > sp:
        return cand
    if sc < sp:
        return prev
    lp = prev.letzter_wert()
    lc = cand.letzter_wert()
    if lp is None:
        return cand
    if lc is None:
        return prev
    tmpl = lc if (lc.min_val is not None or lc.max_val is not None
                   or lc.gelb_min is not None or lc.gelb_max is not None) else lp
    return cand if _is_worse_value(lc.stand, lp.stand, tmpl) else prev
