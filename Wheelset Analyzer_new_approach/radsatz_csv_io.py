"""CSV-Laden für BO_RADSATZDATEN (ohne Oracle-Abhängigkeit)."""

import csv
from datetime import datetime
from typing import Optional


def _parse_csv_datetime(s) -> Optional[datetime]:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_csv_number(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    if not s:
        return None
    return float(s)


def _ausbau_leer(d: dict) -> bool:
    v = d.get("AUSBAU")
    return v is None or str(v).strip() == ""


def _csv_row_to_res2_tuple(d: dict) -> tuple:
    return (
        d["TOPEINHEITBEZEICHNUNG"].strip(),
        d["DGEINBAUPOS"].strip(),
        d["RSEINBAUPOS"].strip(),
        d["ZARTBEZ"].strip(),
        _parse_csv_datetime(d.get("DATUM")),
        _parse_csv_number(d.get("STAND")),
        _parse_csv_number(d.get("LAUFLEISTUNG")),
        _parse_csv_number(d.get("MIN")),
        _parse_csv_number(d.get("MAX")),
        _parse_csv_number(d.get("GELB_MIN")),
        _parse_csv_number(d.get("TOPEINHEITID")),
        _parse_csv_number(d.get("DGEINHEITID")),
        (d.get("DGBEZEICHNUNG") or "").strip(),
        _parse_csv_number(d.get("RSEINHEITID")),
        (d.get("RSBEZEICHNUNG") or "").strip(),
        _parse_csv_datetime(d.get("EINBAU")),
        _parse_csv_datetime(d.get("AUSBAU")),
        int(_parse_csv_number(d.get("AKTUELL")))
        if _parse_csv_number(d.get("AKTUELL")) is not None else None,
        _parse_csv_number(d.get("ZAEHLERARTID")),
    )


def load_bo_radsatz_from_csv(csv_path: str, dt_start_str: str):
    """
    Liest die gleiche CSV-Struktur wie das Hauptprogramm.
    Rückgabe: (res1, res2) mit res1 = Liste (topeinheit, dgpos, rspos), res2 = Messzeilen-Tupel.
    """
    dt_start = datetime.strptime(dt_start_str, "%Y-%m-%d")
    bez_z1 = "Rad-Laufkreisdurchmesser-1"
    bez_z2 = "Rad-Laufkreisdurchmesser-2"
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            zeilen = list(csv.DictReader(f, delimiter=";"))
    except OSError as exc:
        raise SystemExit(f"CSV nicht lesbar: {csv_path}\n{exc}") from exc
    if not zeilen:
        return [], []

    res1_keys, res1 = set(), []
    for d in zeilen:
        if not _ausbau_leer(d):
            continue
        key = (
            d["TOPEINHEITBEZEICHNUNG"].strip(),
            d["DGEINBAUPOS"].strip(),
            d["RSEINBAUPOS"].strip(),
        )
        if key not in res1_keys:
            res1_keys.add(key)
            res1.append(key)

    res2 = []
    for d in zeilen:
        if not _ausbau_leer(d):
            continue
        zb = (d.get("ZARTBEZ") or "").strip()
        if zb not in (bez_z1, bez_z2):
            continue
        dt_mess = _parse_csv_datetime(d.get("DATUM"))
        if dt_mess is None or dt_mess <= dt_start:
            continue
        res2.append(_csv_row_to_res2_tuple(d))

    res2.sort(key=lambda r: r[4] or datetime.min)
    return res1, res2
