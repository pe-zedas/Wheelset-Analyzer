"""Laedt Kundenprofile aus YAML und bietet Zugriffs-Helfer."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .models import Side


@dataclass
class MeasurementPattern:
    regex: re.Pattern
    side: Side


@dataclass
class MeasurementDef:
    name: str                     # kanonisch (LKD, SPURKRANZDICKE_SD, ...)
    unit: str
    direction: str                # "decreasing" | "increasing"
    prognosis: bool
    patterns: List[MeasurementPattern]
    # Gueltiger Wertebereich [lo, hi] in der Einheit der Messgroesse. Werte
    # ausserhalb (z.B. 0 als Platzhalter ohne Messung) werden beim Laden
    # verworfen. ``None`` = keine Pruefung (Standard, z.B. VGF).
    valid_range: Optional[Tuple[float, float]] = None


@dataclass
class Profile:
    name: str
    description: str
    delimiter: str
    encoding: str
    date_format: str
    decimal: str
    columns_raw: Dict[str, str]            # CSV-Spalte -> intern
    columns_prognose: Dict[str, str]
    required_base: List[str]
    required_prog_eligible: List[str]
    hierarchy_depth: int
    catalog: List[MeasurementDef]
    # "einbaupos": Drehgestelle einer Einheit werden ueber ihre Einbauposition
    # identifiziert (VGF: eindeutig). "id": ueber die DGEINHEITID, weil die
    # Position nicht eindeutig ist (Abellio: mehrere DG heissen "Drehgestell").
    dg_key: str = "einbaupos"
    # Zeilen ohne Radsatz-Ebene (aber mit Radseite) bekommen eine synthetische
    # Achse, damit sie in der UI wie jede andere Achse darstellbar sind.
    fallback_axle: bool = False
    # MIN_BEREICH/MAX_BEREICH sind Toleranzbereiche (Abellio) und gelten als
    # Grenzwerte, wenn MIN/MAX leer sind.
    bereich_as_limits: bool = False
    # > 0: Messwerte der Sammel-Achse stammen von so vielen Raedern je Messtermin
    # (MOB: 4). Sie werden nach der Messreihenfolge auf "Messposition 1..N"
    # verteilt (siehe structure.split_wheel_positions).
    wheel_positions: int = 0
    # True: das Prognose-Backend kann fuer dieses Schema rechnen ("Prognose neu
    # berechnen" ist freigegeben). Das Backend liest immer die VGF-Datenbank.
    backend_prognosis: bool = False
    _classify_cache: Dict[str, Optional[Tuple[MeasurementDef, Side]]] = field(
        default_factory=dict, repr=False, compare=False)

    def map_raw_header(self, header: List[str]) -> Dict[str, int]:
        """Index je interner Name, aufgeloest ueber columns_raw."""
        out: Dict[str, int] = {}
        for idx, h in enumerate(header):
            internal = self.columns_raw.get(h.strip().lstrip("﻿"))
            if internal:
                out[internal] = idx
        return out

    def map_prognose_header(self, header: List[str]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for idx, h in enumerate(header):
            internal = self.columns_prognose.get(h.strip().lstrip("﻿"))
            if internal:
                out[internal] = idx
        return out

    def classify_zartbez(self, zartbez: str) -> Optional[Tuple[MeasurementDef, Side]]:
        """Ordnet eine ZARTBEZ-Rohbezeichnung einer kanonischen Messgroesse + Seite zu."""
        text = (zartbez or "").strip()
        # Es gibt nur wenige Dutzend verschiedene Bezeichnungen, aber
        # Hunderttausende Zeilen -> Ergebnis je Text merken.
        if text in self._classify_cache:
            return self._classify_cache[text]
        result: Optional[Tuple[MeasurementDef, Side]] = None
        for mdef in self.catalog:
            for pat in mdef.patterns:
                if pat.regex.search(text):
                    result = (mdef, pat.side)
                    break
            if result is not None:
                break
        self._classify_cache[text] = result
        return result


def load_profile(path: Path) -> Profile:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    catalog: List[MeasurementDef] = []
    for name, cfg in (data.get("measurement_catalog") or {}).items():
        patterns = [
            MeasurementPattern(
                regex=re.compile(p["regex"]),
                side=Side(p.get("side", "unspecified")),
            )
            for p in cfg.get("patterns", [])
        ]
        vr = cfg.get("valid_range")
        catalog.append(MeasurementDef(
            name=name,
            unit=cfg.get("unit", "mm"),
            direction=cfg.get("direction", "decreasing"),
            prognosis=bool(cfg.get("prognosis", False)),
            patterns=patterns,
            valid_range=(float(vr[0]), float(vr[1])) if vr else None,
        ))
    csv_cfg = data.get("csv", {})
    req = data.get("required_measurement_fields", {})
    struct = data.get("structure", {}) or {}
    thresholds = data.get("thresholds", {}) or {}
    return Profile(
        name=data["name"],
        description=data.get("description", ""),
        delimiter=csv_cfg.get("delimiter", ";"),
        encoding=csv_cfg.get("encoding", "utf-8-sig"),
        date_format=csv_cfg.get("date_format", "%Y-%m-%d %H:%M:%S"),
        decimal=csv_cfg.get("decimal", "."),
        columns_raw=data.get("columns_raw", {}),
        columns_prognose=data.get("columns_prognose", {}),
        required_base=req.get("base", ["datum", "stand"]),
        required_prog_eligible=req.get("prognosis_eligible", []),
        hierarchy_depth=int(data.get("hierarchy_depth", 4)),
        catalog=catalog,
        dg_key=str(struct.get("dg_key", "einbaupos")),
        fallback_axle=bool(struct.get("fallback_axle", False)),
        bereich_as_limits=bool(thresholds.get("bereich_as_limits", False)),
        wheel_positions=int(struct.get("wheel_positions", 0) or 0),
        backend_prognosis=bool(data.get("backend_prognosis", False)),
    )


PROFILES_DIR = Path(__file__).resolve().parent.parent / "config" / "profiles"


def load_profile_by_name(name: str) -> Profile:
    return load_profile(PROFILES_DIR / f"{name.lower()}.yaml")
