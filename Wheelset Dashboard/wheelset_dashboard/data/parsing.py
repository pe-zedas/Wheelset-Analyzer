"""Einfache Text -> Wert-Umwandlung fuer Rohzeilen (CSV und Oracle)."""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence


def parse_float(s: Optional[str], decimal: str) -> Optional[float]:
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


def parse_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(float(s.strip()))
    except ValueError:
        return None


def parse_datetime(s: Optional[str], fmt: str) -> Optional[datetime]:
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


def get_field(row: Sequence[str], idx_map: Dict[str, int], key: str) -> str:
    """Wert der internen Spalte ``key`` oder ``""``, wenn die Spalte fehlt."""
    i = idx_map.get(key)
    if i is None or i >= len(row):
        return ""
    return row[i]


def stringify_row(row: Sequence, date_format: str) -> List[str]:
    """Datenbankwerte einer Zeile als Text (None -> "", Datum -> ``date_format``)."""
    return [
        "" if v is None else (v.strftime(date_format) if hasattr(v, "strftime") else str(v))
        for v in row
    ]
