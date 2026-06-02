"""Zählt Achsen mit plot-fähiger Prognose (ohne GUI, Backend Agg)."""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ["MPLBACKEND"] = "Agg"
sys.path.insert(0, SCRIPT_DIR)

from radsatz_settings import load_radsatz_config
from radsatz_matplotlib import configure_matplotlib_backend

cfg = load_radsatz_config(SCRIPT_DIR)
print("Backend:", configure_matplotlib_backend("Agg", plot_show_window=False))

from dates_np import to_datetime64_array
from toolsWheelset import getStartIndexLastCycle
from MeterList import MeterList
from VehicleAxis import VehicleAxis
from radsatz_csv_io import load_bo_radsatz_from_csv
from prognosis_new_core import (
    QUALITY_INSUFFICIENT,
    _calc_prognosis_axis,
    prognosis_params_from_radsatz_config,
    set_prognosis_params,
)
from reprof_learning import (
    learn_reprofiling_params_per_axis,
    reprofiling_params_from_radsatz_config,
    set_reprofiling_params_per_axis,
)

set_prognosis_params(prognosis_params_from_radsatz_config(cfg))
res1, res2 = load_bo_radsatz_from_csv(cfg.csv_bo_radsatzdaten, cfg.dt_start_data)
dict_VehicleAxis = {}
for strVehicle in res1:
    dict_VehicleAxis[strVehicle[0] + strVehicle[1] + strVehicle[2]] = VehicleAxis(
        strVehicle[0], strVehicle[1], strVehicle[2],
        MeterList([], [], [], [], [], [], []),
        MeterList([], [], [], [], [], [], []),
    )
for r in res2:
    axis_key = r[0] + r[1] + r[2]
    tVehicle = dict_VehicleAxis.get(axis_key)
    if tVehicle is None:
        continue
    met = tVehicle.getmeterList1() if r[3] == "Rad-Laufkreisdurchmesser-1" else tVehicle.getmeterList2()
    met.getstrDates().append(r[4])
    met.getvalues().append(r[5])
    met.getkm().append(r[6])
    met.getmin().append(r[7])
    met.getmax().append(r[8])
    met.getgelb_min().append(r[9])
for key, tmpVehicle in dict_VehicleAxis.items():
    for met in (tmpVehicle.getmeterList1(), tmpVehicle.getmeterList2()):
        if len(met.getstrDates()) > 1:
            met.setnDates(to_datetime64_array(met.getstrDates()))

_ini_reprof = reprofiling_params_from_radsatz_config(cfg)
set_reprofiling_params_per_axis(
    learn_reprofiling_params_per_axis(dict_VehicleAxis, ini_fallback=_ini_reprof),
    fleet_fallback=_ini_reprof,
)
n_km = cfg.n_km
diff = cfg.diff_lkd
n_plot = 0
for key, tmpVehicle in dict_VehicleAxis.items():
    m1, m2 = tmpVehicle.getmeterList1(), tmpVehicle.getmeterList2()
    if len(m1.getstrDates()) <= 1 or len(m2.getstrDates()) <= 1:
        continue
    m1.setindexStartLastCycle(getStartIndexLastCycle(m1.getkm(), m1.getvalues(), diff))
    m2.setindexStartLastCycle(getStartIndexLastCycle(m2.getkm(), m2.getvalues(), diff))
    r1 = _calc_prognosis_axis(m1, key + "_LKD1", n_km)
    r2 = _calc_prognosis_axis(m2, key + "_LKD2", n_km)
    if r1.quality != QUALITY_INSUFFICIENT and r2.quality != QUALITY_INSUFFICIENT:
        n_plot += 1
        print(f"  plot: {key}")
print(f"Achsen gesamt: {len(dict_VehicleAxis)}, mit Plot: {n_plot}")
