"""
Datums-Hilfen für die Radsatz-Prognosepipeline (numpy.datetime64-basiert).

Konvention für den neuen Ansatz (Radsatz_Bahn_DB_new_Approach.py):
- MeterList.nDates / nDatesProg werden als numpy.ndarray mit dtype 'datetime64[s]' gespeichert.
- MeterList.min_Prog_dt / gelb_min_Prog_dt sind einzelne numpy.datetime64-Werte (Skalar).
- 'NaT' (np.datetime64('NaT')) bedeutet "kein Wert" — ersetzt den bisherigen 0.0-Sentinel.

Damit entfällt die alte Matlab-Datezahl-Konversion (siehe datetime2matlabdn.py — nur noch
für die Legacy-Skripte Radsatz_Bahn_DB_KM_Gauss_Class_All*.py erhalten).
"""

from datetime import datetime
from typing import Iterable, Optional

import numpy as np

# Skalar-Sentinel für "kein Wert" bei min_Prog_dt / gelb_min_Prog_dt
NAT = np.datetime64("NaT", "s")


def to_datetime64_array(seq: Iterable) -> np.ndarray:
    """Liste/Iterable von Python-datetime → np.ndarray mit dtype 'datetime64[s]'."""
    return np.array(list(seq), dtype="datetime64[s]")


def is_nat(dt) -> bool:
    """True für None, NaT, oder einen anderen 'leer'-Marker (z. B. 0.0 aus Legacy)."""
    if dt is None:
        return True
    if isinstance(dt, np.datetime64):
        return bool(np.isnat(dt))
    # Legacy-Kompatibilität: 0 / 0.0 als "kein Wert"
    try:
        return float(dt) == 0.0
    except (TypeError, ValueError):
        return False


def to_python_datetime(dt) -> Optional[datetime]:
    """np.datetime64 / datetime / NaT / None → Python datetime (None für NaT)."""
    if is_nat(dt):
        return None
    if isinstance(dt, datetime):
        return dt
    if isinstance(dt, np.datetime64):
        # Konvertierung über datetime64[us], damit .astype(object) ein Python-datetime liefert
        py = dt.astype("datetime64[us]").astype(object)
        if isinstance(py, datetime):
            return py
        return None
    try:
        return np.datetime64(dt).astype("datetime64[us]").astype(object)
    except Exception:
        return None


def days_to_timedelta64(days) -> np.ndarray:
    """Float (oder Array) in Tagen → np.timedelta64[s] (Sekunden-Auflösung)."""
    secs = np.round(np.asarray(days, dtype=float) * 86400.0).astype("int64")
    return secs.astype("timedelta64[s]")


def add_days(dt64, days: float) -> np.datetime64:
    """Skalares datetime64 + Float-Tage → datetime64. Bei NaT/None → NaT."""
    if is_nat(dt64):
        return NAT
    sec = int(round(float(days) * 86400.0))
    return dt64 + np.timedelta64(sec, "s")


def timedelta64_to_days(td) -> np.ndarray:
    """timedelta64 (Array oder Skalar) → Tage als float."""
    return np.asarray(td) / np.timedelta64(1, "D")
