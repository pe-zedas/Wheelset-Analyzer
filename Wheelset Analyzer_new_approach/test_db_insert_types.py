"""
Smoke-Test: Simuliert den DB-Insert-Pfad von VehicleAxis.write_Prog_Data() ohne
Oracle-Verbindung. Prüft, ob alle Felder der Insert-Tupel mit Python-nativen
Typen befüllt sind, die oracledb akzeptiert (datetime.datetime, float, int, str, None).

Hintergrund: Nach der Umstellung auf numpy.datetime64 müssen alle DATUM-Felder
am DB-Boundary wieder Python-datetime sein (nicht np.datetime64), sonst
schlägt oracledb beim Binden fehl.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, List

import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

os.environ["MPLBACKEND"] = "Agg"

from MeterList import MeterList
from VehicleAxis import VehicleAxis
from dates_np import to_datetime64_array
from radsatz_csv_io import load_bo_radsatz_from_csv
from radsatz_settings import (
    PROGNOSIS_METHOD_GAUSS,
    PROGNOSIS_METHOD_THEIL_SEN,
    load_radsatz_config,
)
from radsatz_axis_labels import make_axis_key, sync_axis_labels_from_measurement_row
from toolsWheelset import getStartIndexLastCycle
from reprof_learning import (
    learn_reprofiling_params_per_axis,
    reprofiling_params_from_radsatz_config,
    set_reprofiling_params_per_axis,
)
from prognosis_new_core import (
    _calc_prognosis_axis,
    prognosis_params_from_radsatz_config,
    set_prognosis_params,
)
from prognosis_gauss import run_gauss_prognosis_for_vehicle


# Spaltenreihenfolge wie in _PROGNOSE_INSERT_SQL (siehe VehicleAxis.py)
COLUMNS = [
    "TOPEINHEITID", "TOPEINHEITBEZEICHNUNG", "DGEINHEITID", "DGBEZEICHNUNG",
    "DGEINBAUPOS", "RSEINHEITID", "RSBEZEICHNUNG", "RSEINBAUPOS",
    "EINBAU", "AUSBAU", "AKTUELL", "ZAEHLERARTID", "ZARTBEZ",
    "STAND", "DATUM", "LAUFLEISTUNG", "LETZTEAENDZEIT",
    "KM_GRENZWERT", "DATUM_GRENZWERT", "KM_WARNWERT", "DATUM_WARNWERT",
]

# Welche Datumstypen erwarten wir je Spalte? (oracledb akzeptiert Python datetime.datetime)
DATETIME_COLUMNS = {
    "EINBAU", "AUSBAU", "DATUM", "LETZTEAENDZEIT",
    "DATUM_GRENZWERT", "DATUM_WARNWERT",
}


def classify(val: Any) -> str:
    """Kurze Typkennung für den Bericht."""
    if val is None:
        return "None"
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, datetime):
        return "datetime"
    if isinstance(val, np.datetime64):
        return "np.datetime64  <-- UNGUELTIG fuer oracledb!"
    if isinstance(val, np.generic):
        return f"np.{type(val).__name__}  -- Numpy-Skalar (oracledb akzeptiert idR, aber unsauber)"
    if isinstance(val, float):
        return "float"
    if isinstance(val, int):
        return "int"
    if isinstance(val, str):
        return "str"
    return type(val).__name__


class MockCursor:
    """Cursor-Stub: erfasst alle Insert-Aufrufe ohne DB-Verbindung."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    def execute(self, sql: str, params) -> None:
        self.calls.append((sql, list(params)))


class MockConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def build_vehicle_dict(cfg) -> dict:
    res1, res2 = load_bo_radsatz_from_csv(cfg.csv_bo_radsatzdaten, cfg.dt_start_data)
    dict_v: dict = {}
    for sv in sorted(res1, key=lambda t: (str(t[0]), str(t[1]), str(t[2]))):
        dict_v[make_axis_key(sv)] = VehicleAxis(
            sv[0], sv[1], sv[2],
            MeterList([], [], [], [], [], [], []),
            MeterList([], [], [], [], [], [], []),
        )
    for r in res2:
        key = make_axis_key(r)
        v = dict_v.get(key)
        if v is None or None in (r[4], r[5], r[6], r[7], r[8], r[9]):
            continue
        met = v.getmeterList1() if r[3] == "Rad-Laufkreisdurchmesser-1" else v.getmeterList2()
        met.getstrDates().append(r[4])
        met.getvalues().append(r[5])
        met.getkm().append(r[6])
        met.getmin().append(r[7])
        met.getmax().append(r[8])
        met.getgelb_min().append(r[9])
        met.setzaehlerartid(r[18])
        met.setzartbez(r[3])
        sync_axis_labels_from_measurement_row(v, r)
        v.settopeinheitid(r[10])
        v.setdgeinheitid(r[11])
        v.setdgbezeichnung(r[12])
        v.setrseinheitid(r[13])
        v.setrsbezeichnung(r[14])
        v.seteinbau(r[15])
        v.setausbau(r[16])
        v.setaktuell(r[17])
    for v in dict_v.values():
        for met in (v.getmeterList1(), v.getmeterList2()):
            if len(met.getstrDates()) > 1:
                met.setnDates(to_datetime64_array(met.getstrDates()))
    return dict_v


def run_prognosis(dict_v: dict, cfg, method: str) -> None:
    ini_reprof = reprofiling_params_from_radsatz_config(cfg)
    per_axis = learn_reprofiling_params_per_axis(dict_v, ini_fallback=ini_reprof)
    set_reprofiling_params_per_axis(per_axis, fleet_fallback=ini_reprof)
    set_prognosis_params(prognosis_params_from_radsatz_config(cfg))
    for key, v in dict_v.items():
        m1, m2 = v.getmeterList1(), v.getmeterList2()
        if len(m1.getstrDates()) <= 1 or len(m2.getstrDates()) <= 1:
            continue
        try:
            if method == PROGNOSIS_METHOD_GAUSS:
                run_gauss_prognosis_for_vehicle(v, key, cfg)
            else:
                n1 = getStartIndexLastCycle(m1.getkm(), m1.getvalues(), cfg.diff_lkd)
                n2 = getStartIndexLastCycle(m2.getkm(), m2.getvalues(), cfg.diff_lkd)
                m1.setindexStartLastCycle(n1)
                m2.setindexStartLastCycle(n2)
                _calc_prognosis_axis(m1, key + "_LKD1", cfg.n_km)
                _calc_prognosis_axis(m2, key + "_LKD2", cfg.n_km)
        except Exception as exc:
            print(f"  Prognose-Fehler für {key}: {exc}")


def check_tuples(dict_v: dict, method_label: str) -> bool:
    cur = MockCursor()
    con = MockConnection()
    ok_total = 0
    bad_count = 0
    bad_examples: List[str] = []
    for key, v in dict_v.items():
        m1, m2 = v.getmeterList1(), v.getmeterList2()
        if not m1.getvaluesProg() and not m2.getvaluesProg():
            continue
        try:
            v.write_Prog_Data(cur, con)
        except Exception as exc:
            print(f"  write_Prog_Data Exception für {key}: {exc!r}")
            bad_count += 1
            continue
    for sql, params in cur.calls:
        ok_total += 1
        for col_name, val in zip(COLUMNS, params):
            kind = classify(val)
            if "UNGUELTIG" in kind:
                bad_count += 1
                if len(bad_examples) < 5:
                    bad_examples.append(f"    {col_name} = {val!r} ({kind})")
            elif col_name in DATETIME_COLUMNS and val is not None and not isinstance(val, datetime):
                bad_count += 1
                if len(bad_examples) < 5:
                    bad_examples.append(f"    {col_name} = {val!r} ({kind}) - sollte datetime sein")

    print(f"[{method_label}]")
    print(f"  Insert-Tupel: {ok_total}, davon problematisch: {bad_count}")
    if bad_examples:
        print("  Beispiele:")
        for ex in bad_examples:
            print(ex)

    # Eine Beispielzeile vollständig dumpen
    if cur.calls:
        # Suche eine Zeile mit gesetzten DATUM_GRENZWERT/DATUM_WARNWERT
        sample = None
        for sql, params in cur.calls:
            if any(isinstance(p, datetime) for col, p in zip(COLUMNS, params)
                   if col in ("DATUM_GRENZWERT", "DATUM_WARNWERT")):
                sample = params
                break
        if sample is None:
            sample = cur.calls[0][1]
        print("  Beispielzeile (Spalte = Wert : Typ):")
        for col_name, val in zip(COLUMNS, sample):
            print(f"    {col_name:25s} = {val!r}  ({classify(val)})")
    print()
    return bad_count == 0


def main() -> int:
    cfg = load_radsatz_config(SCRIPT_DIR)
    print(f"CSV: {cfg.csv_bo_radsatzdaten}")
    print(f"Startdatum: {cfg.dt_start_data}\n")

    all_ok = True
    for method, label in [
        (PROGNOSIS_METHOD_THEIL_SEN, "Theil-Sen"),
        (PROGNOSIS_METHOD_GAUSS, "Gauss-Newton"),
    ]:
        d = build_vehicle_dict(cfg)
        run_prognosis(d, cfg, method)
        ok = check_tuples(d, label)
        all_ok = all_ok and ok

    print("=" * 60)
    print("ERGEBNIS:", "ALLE TUPEL OK" if all_ok else "FEHLER GEFUNDEN")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
