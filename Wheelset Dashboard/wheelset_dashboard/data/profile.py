"""Laedt Kundenprofile aus YAML und bietet Zugriffs-Helfer."""
from __future__ import annotations

import re
from dataclasses import dataclass
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
        for mdef in self.catalog:
            for pat in mdef.patterns:
                if pat.regex.search(text):
                    return mdef, pat.side
        return None


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
        catalog.append(MeasurementDef(
            name=name,
            unit=cfg.get("unit", "mm"),
            direction=cfg.get("direction", "decreasing"),
            prognosis=bool(cfg.get("prognosis", False)),
            patterns=patterns,
        ))
    csv_cfg = data.get("csv", {})
    req = data.get("required_measurement_fields", {})
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
    )


PROFILES_DIR = Path(__file__).resolve().parent.parent / "config" / "profiles"


def load_profile_by_name(name: str) -> Profile:
    return load_profile(PROFILES_DIR / f"{name.lower()}.yaml")
