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

    # Eingebaute und ausgebaute (Lager-)Achsen beide durchlassen.
    # res1 bekommt 5 Felder: (TE, DG, RS, RSEINHEITID_oder_None, is_lager).
    # Fuer eingebaute Raeder bleibt der Schluessel (TE, DG, RS) wie bisher;
    # fuer Lagerachsen sichert die RSEINHEITID die Eindeutigkeit.
    res1_keys, res1 = set(), []
    for d in zeilen:
        is_lager = not _ausbau_leer(d)
        rid = (d.get("RSEINHEITID", "") or "").strip() if is_lager else None
        key = (
            d["TOPEINHEITBEZEICHNUNG"].strip(),
            d["DGEINBAUPOS"].strip(),
            d["RSEINBAUPOS"].strip(),
            rid,
            1 if is_lager else 0,
        )
        if key not in res1_keys:
            res1_keys.add(key)
            res1.append(key)

    res2 = []
    for d in zeilen:
        zb = (d.get("ZARTBEZ") or "").strip()
        if zb not in (bez_z1, bez_z2):
            continue
        dt_mess = _parse_csv_datetime(d.get("DATUM"))
        if dt_mess is None:
            continue
        # dt_start-Filter nur fuer EINGEBAUTE Zeilen (schuetzt die Prognose
        # vor uralten Archivdaten). Lagerkomponenten haben oft nur wenige
        # Messungen; die wichtigen Reprof-Doppelmessungen koennen VOR dem
        # Cutoff liegen. Die alte Live-App im Dashboard hat ebenfalls alle
        # verfuegbaren Lager-Messungen verwendet.
        if _ausbau_leer(d) and dt_mess <= dt_start:
            continue
        res2.append(_csv_row_to_res2_tuple(d))

    res2.sort(key=lambda r: r[4] or datetime.min)
    return res1, res2
