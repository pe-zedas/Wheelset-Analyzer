"""Diagnose: warum welche Achse einen Plot bekommt (min_points_fit, Zyklus, Reprof, CV)."""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["MPLBACKEND"] = "Agg"
sys.path.insert(0, SCRIPT_DIR)

from collections import defaultdict

from dates_np import to_datetime64_array
from toolsWheelset import getStartIndexLastCycle
from MeterList import MeterList
from VehicleAxis import VehicleAxis
from radsatz_settings import load_radsatz_config
from radsatz_csv_io import load_bo_radsatz_from_csv
from prognosis_new_core import (
    QUALITY_INSUFFICIENT,
    _calc_prognosis_axis,
    get_prognosis_params,
    prognosis_params_from_radsatz_config,
    set_prognosis_params,
)
from reprof_learning import (
    learn_reprofiling_params,
    learn_reprofiling_params_per_axis,
    reprofiling_params_from_radsatz_config,
    set_reprofiling_params_per_axis,
)

cfg = load_radsatz_config(SCRIPT_DIR)
base = prognosis_params_from_radsatz_config(cfg)
set_prognosis_params(base)
print(f"Config min_points_fit={cfg.progn_new_min_points_fit}, aktiv nach set: {get_prognosis_params().min_points_fit}")

res1, res2 = load_bo_radsatz_from_csv(cfg.csv_bo_radsatzdaten, cfg.dt_start_data)
d: dict = {}
for s in res1:
    d[s[0] + s[1] + s[2]] = VehicleAxis(
        s[0], s[1], s[2],
        MeterList([], [], [], [], [], [], []),
        MeterList([], [], [], [], [], [], []),
    )
for r in res2:
    t = d.get(r[0] + r[1] + r[2])
    if t is None:
        continue
    met = t.getmeterList1() if r[3] == "Rad-Laufkreisdurchmesser-1" else t.getmeterList2()
    met.getstrDates().append(r[4])
    met.getvalues().append(r[5])
    met.getkm().append(r[6])
    met.getmin().append(r[7])
    met.getmax().append(r[8])
    met.getgelb_min().append(r[9])

for t in d.values():
    for met in (t.getmeterList1(), t.getmeterList2()):
        if len(met.getstrDates()) > 1:
            met.setnDates(to_datetime64_array(met.getstrDates()))

_ini = reprofiling_params_from_radsatz_config(cfg)
set_reprofiling_params_per_axis(
    learn_reprofiling_params_per_axis(d, ini_fallback=_ini),
    fleet_fallback=_ini,
)

if cfg.progn_new_cv_tune:
    from radsatz_crossval import tune_prognosis_params_by_cv

    best, score, folds = tune_prognosis_params_by_cv(d, cfg)
    set_prognosis_params(best)
    print(
        f"CV-Tuning: min_points_fit -> {best.min_points_fit}, "
        f"iqr_factor={best.iqr_factor}, score={score:.4f}, folds={folds}"
    )

prm = get_prognosis_params()
diff = cfg.diff_lkd
print(f"Effektiv min_points_fit={prm.min_points_fit}, min_points_quality={prm.min_points_quality}\n")

rows = []
plot_ok = 0
for key, t in sorted(d.items()):
    m1, m2 = t.getmeterList1(), t.getmeterList2()
    if len(m1.getstrDates()) <= 1 or len(m2.getstrDates()) <= 1:
        rows.append((t.getstrVDesc(), t.getstrBogie(), t.getstrPosAxis(), "-", "-", "-", "-", "zu wenig Messungen"))
        continue
    n1 = getStartIndexLastCycle(m1.getkm(), m1.getvalues(), diff)
    n2 = getStartIndexLastCycle(m2.getkm(), m2.getvalues(), diff)
    m1.setindexStartLastCycle(n1)
    m2.setindexStartLastCycle(n2)
    c1 = len(m1.getkm()) - n1
    c2 = len(m2.getkm()) - n2
    try:
        r1 = _calc_prognosis_axis(m1, key + "_LKD1", cfg.n_km)
        r2 = _calc_prognosis_axis(m2, key + "_LKD2", cfg.n_km)
    except Exception as exc:
        rows.append((t.getstrVDesc(), t.getstrBogie(), t.getstrPosAxis(), c1, c2, "ERR", "ERR", str(exc)[:40]))
        continue
    ok = r1.quality != QUALITY_INSUFFICIENT and r2.quality != QUALITY_INSUFFICIENT
    if ok:
        plot_ok += 1
    rows.append((
        t.getstrVDesc(),
        t.getstrBogie(),
        t.getstrPosAxis(),
        c1,
        c2,
        f"{r1.quality} n={r1.n_points_fit}",
        f"{r2.quality} n={r2.n_points_fit}",
        "PLOT" if ok else "kein Plot",
    ))

print(f"{'Fahrzeug':<18} {'DG':<28} {'Achse':<22} {'Zyklus LKD1':>10} {'Zyklus LKD2':>10} {'LKD1':<16} {'LKD2':<16} Ergebnis")
print("-" * 130)
for row in rows:
    print(f"{row[0]:<18} {row[1]:<28} {row[2]:<22} {row[3]:>10} {row[4]:>10} {row[5]:<16} {row[6]:<16} {row[7]}")

print(f"\nAchsen gesamt: {len(d)}, mit Plot: {plot_ok}")

by_reason = defaultdict(int)
for row in rows:
    if row[7] == "PLOT":
        by_reason["plot"] += 1
    elif row[7] == "zu wenig Messungen":
        by_reason["messungen"] += 1
    elif row[7].startswith("ERR"):
        by_reason["exception"] += 1
    else:
        by_reason["insufficient"] += 1
print("Zusammenfassung:", dict(by_reason))
